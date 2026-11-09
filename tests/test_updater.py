import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile

from pmfstudio import updater
from pmfstudio.updater import UpdateError

WINDOWS = os.name == "nt"
ARCHIVE = ".zip" if WINDOWS else ".tar.gz"                      # the release file of this system
EXE_NAME = updater.EXE
PROGRAM = (b"MZ" + b"\0" * 100) if WINDOWS else (b"\x7fELF" + b"\0" * 100)
THIS_ASSET = "PMF-Studio-0.2-beta-win64.zip" if WINDOWS else "PMF-Studio-0.2-beta-linux-x64.tar.gz"
OTHER_ASSET = "PMF-Studio-0.2-beta-linux-x64.tar.gz" if WINDOWS else "PMF-Studio-0.2-beta-win64.zip"


def make_release_zip(path, top="PMF Studio", missing=(), extra=None, executable=True):
    """a fake release file of this system (a zip on Windows, a tar.gz on Linux) holding a small fake program"""
    names = {top + "/" + EXE_NAME: PROGRAM, top + "/_internal/base.dll": b"x", top + "/LICENSE": b"GPL",
             top + "/Output/junk.txt": b"should not be installed", top + "/selftest_result.txt": b"old"}
    for h in updater.HELPERS:
        names[top + "/tools/" + h] = PROGRAM
    names.update(extra or {})
    kept = {n: d for n, d in names.items() if not any(m in n for m in missing)}
    if WINDOWS:
        with zipfile.ZipFile(path, "w") as z:
            for n, data in kept.items():
                z.writestr(n, data)
        return
    with tarfile.open(path, "w:gz") as t:
        for n, data in kept.items():
            info = tarfile.TarInfo(n)
            info.size = len(data)
            info.mode = 0o755 if executable and (n.endswith(EXE_NAME) or "/tools/" in n) else 0o644
            t.addfile(info, io.BytesIO(data))


class AssetTests(unittest.TestCase):
    def test_asset_and_checksum_come_from_the_release(self):
        info = {"assets": [{"name": "notes.txt", "browser_download_url": "x"},
                           {"name": OTHER_ASSET, "browser_download_url": updater.PREFIX + "releases/download/v0.2/" + OTHER_ASSET, "size": 1, "digest": "sha256:" + "11" * 32},
                           {"name": THIS_ASSET, "browser_download_url": updater.PREFIX + "releases/download/v0.2/" + THIS_ASSET,
                            "size": 52_000_000, "digest": "sha256:" + "AB" * 32}], "body": "SHA-256 " + "cd" * 32}
        a = updater.pick_asset(info)
        self.assertEqual((a["name"], a["size"], a["sha"]), (THIS_ASSET, 52_000_000, "ab" * 32))      # the file of THIS system; GitHub's own digest wins
        del info["assets"][2]["digest"]
        self.assertEqual(updater.pick_asset(info)["sha"], "cd" * 32)                                  # else the release notes
        info["body"] = "no checksum here"
        self.assertEqual(updater.pick_asset(info)["sha"], "")
        self.assertIsNone(updater.pick_asset({"assets": []}))
        self.assertIsNone(updater.pick_asset({"assets": [info["assets"][1]]}))                        # only the other system's file: nothing to install

    def test_versions(self):
        self.assertGreater(updater.ver("v0.2"), updater.ver("0.1"))
        self.assertGreater(updater.ver("0.10.0"), updater.ver("0.9.9"))
        self.assertEqual(updater.ver("v1.2.0"), updater.ver("1.2.0"))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_upd_")
        self.zip = os.path.join(self.d, "src" + ARCHIVE)
        make_release_zip(self.zip)
        self.sha = hashlib.sha256(open(self.zip, "rb").read()).hexdigest()
        self.asset = dict(name="PMF-Studio-9-beta-x" + ARCHIVE, url=updater.PREFIX + "x.zip", size=os.path.getsize(self.zip), sha=self.sha)
        self.opener = lambda url: open(self.zip, "rb")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_good_download_is_kept(self):
        dest = os.path.join(self.d, "got.zip")
        seen = []
        updater.download(self.asset, dest, lambda got, total: seen.append((got, total)), opener=self.opener)
        self.assertEqual(updater.sha256_of(dest), self.sha)
        self.assertTrue(seen)

    def test_wrong_checksum_is_deleted(self):
        dest = os.path.join(self.d, "got.zip")
        with self.assertRaises(UpdateError):
            updater.download(dict(self.asset, sha="0" * 64), dest, opener=self.opener)
        self.assertFalse(os.path.exists(dest))

    def test_no_checksum_or_foreign_address_is_refused(self):
        with self.assertRaises(UpdateError):
            updater.download(dict(self.asset, sha=""), os.path.join(self.d, "a.zip"), opener=self.opener)
        with self.assertRaises(UpdateError):
            updater.download(dict(self.asset, url="https://example.com/x.zip"), os.path.join(self.d, "b.zip"), opener=self.opener)

    def test_stop_during_download_leaves_nothing(self):
        dest = os.path.join(self.d, "got.zip")
        with self.assertRaises(UpdateError):
            updater.download(self.asset, dest, cancelled=lambda: True, opener=self.opener)
        self.assertFalse(os.path.exists(dest))

    def test_a_broken_connection_is_explained(self):
        def broken(url):
            raise OSError("connection reset")
        with self.assertRaises(UpdateError) as cm:
            updater.download(self.asset, os.path.join(self.d, "c.zip"), opener=broken)
        self.assertIn("Nothing was changed", str(cm.exception))


class UnpackTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_unp_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_a_complete_release_unpacks_and_loses_what_is_not_the_program(self):
        z = os.path.join(self.d, "r" + ARCHIVE)
        make_release_zip(z)
        new = updater.unpack(z, os.path.join(self.d, "stage"))
        self.assertTrue(os.path.isfile(os.path.join(new, EXE_NAME)))
        self.assertFalse(os.path.exists(os.path.join(new, "Output")))                 # things a build left behind are not installed
        self.assertFalse(os.path.exists(os.path.join(new, "selftest_result.txt")))

    def test_an_incomplete_or_odd_release_is_refused(self):
        z = os.path.join(self.d, "r" + ARCHIVE)
        make_release_zip(z, missing=("atracdenc",))
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s1"))
        make_release_zip(z, extra={"PMF Studio/" + EXE_NAME: b"not a program"})
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s2"))
        open(z, "wb").write(b"this is not an archive")
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s3"))

    def test_entries_that_escape_the_folder_are_refused(self):
        for evil in ("../evil.txt", "PMF Studio/../../evil.txt", "C:/evil.txt", "/evil.txt"):
            if not WINDOWS and evil.startswith("C:"):
                continue                                                              # a colon is an ordinary letter in a Linux name
            z = os.path.join(self.d, "e" + ARCHIVE)
            make_release_zip(z, extra={evil: b"x"})
            with self.assertRaises(UpdateError, msg=evil):
                updater.unpack(z, os.path.join(self.d, "s"))
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil.txt")))

    @unittest.skipIf(WINDOWS, "tar.gz files are the Linux release")
    def test_links_and_odd_files_in_a_tar_are_refused(self):
        for kind in ("outside symlink", "hard link", "fifo"):
            z = os.path.join(self.d, "t.tar.gz")
            make_release_zip(z)
            # rebuild with the odd member added (appending to a .gz is not possible, so write the archive again)
            members = {}
            with tarfile.open(z, "r:gz") as t:
                for m in t.getmembers():
                    members[m.name] = (m, t.extractfile(m).read() if m.isfile() else None)
            with tarfile.open(z, "w:gz") as t:
                for name, (m, data) in members.items():
                    t.addfile(m, io.BytesIO(data) if data is not None else None)
                bad = tarfile.TarInfo("PMF Studio/odd")
                if kind == "outside symlink":
                    bad.type, bad.linkname = tarfile.SYMTYPE, "../../etc/passwd"
                elif kind == "hard link":
                    bad.type, bad.linkname = tarfile.LNKTYPE, "PMF Studio/LICENSE"
                else:
                    bad.type = tarfile.FIFOTYPE
                t.addfile(bad)
            with self.assertRaises(UpdateError, msg=kind):
                updater.unpack(z, os.path.join(self.d, "s_" + kind.replace(" ", "_")))

    @unittest.skipIf(WINDOWS, "file permissions matter on Linux")
    def test_a_program_that_cannot_be_started_is_refused(self):
        z = os.path.join(self.d, "r.tar.gz")
        make_release_zip(z, executable=False)
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "stage"))


class ProgressTests(unittest.TestCase):
    def test_the_bar_moves_during_the_test_and_never_quite_ends(self):
        steps = [updater.test_fraction(s) for s in (0, 5, 30, 60, 300)]
        self.assertEqual(steps, sorted(steps))
        self.assertAlmostEqual(steps[0], updater.UNPACK_DONE)
        self.assertLess(steps[-1], 1.0)
        self.assertGreater(steps[-1], 0.9)


@unittest.skipUnless(WINDOWS, "the batch file is the Windows swap")
class SwapScriptTests(unittest.TestCase):
    def test_script_has_the_steps_and_windows_line_endings(self):
        d = tempfile.mkdtemp(prefix="pmf_swap_")
        try:
            bat = updater.write_swap_script(os.path.join(d, "new", "PMF Studio"), os.path.join(d, "app"), pid=4321)
            raw = open(bat, "rb").read()
            os.remove(bat)
            self.assertNotIn(b"\r\r\n", raw)
            text = raw.decode()
            for needle in ("PID eq 4321", "robocopy", "_internal tools licenses source", ".old", ":restore", "PMF Studio.exe"):
                self.assertIn(needle, text)
            self.assertNotIn("{", text)                                                   # every placeholder was filled in
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_folders_travel_in_the_environment_so_accented_names_survive(self):
        d = tempfile.mkdtemp(prefix="pmf_swap_")
        try:
            new, app = os.path.join(d, "nüw", "PMF Studio"), os.path.join(d, "José äpp")
            script = updater.write_swap_script(new, app, pid=77)
            raw = open(script, "rb").read()
            os.remove(script)
            raw.decode("ascii")                                                           # cmd reads the file in the OEM code page: plain ASCII only
            self.assertNotIn(b"Jos", raw)
            env = updater.swap_environment(script)
            self.assertEqual((env["PMF_NEW"], env["PMF_APP"]), (new, app))
            self.assertIn(b"%PMF_APP%", raw)
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(WINDOWS, "the shell script is the Linux swap")
class LinuxSwapTests(unittest.TestCase):
    """the real swap script, run on a small fake program: a shell script that writes a note when it is started"""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_lswap_")
        self.app, self.new = os.path.join(self.d, "José app"), os.path.join(self.d, "stage", "PMF Studio")
        for folder, version in ((self.app, "old"), (self.new, "new")):
            os.makedirs(os.path.join(folder, "_internal"))
            os.makedirs(os.path.join(folder, "tools"))
            open(os.path.join(folder, "_internal", "marker"), "w").write(version)
            exe = os.path.join(folder, EXE_NAME)
            open(exe, "w").write("#!/bin/sh\necho started-%s >> \"$(dirname \"$0\")/started.txt\"\n" % version)
            os.chmod(exe, 0o755)
        open(os.path.join(self.app, "PMF Studio settings.json"), "w").write("{}")
        os.makedirs(os.path.join(self.app, "Output"))
        open(os.path.join(self.app, "Output", "mine.pmf"), "w").write("keep me")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_script(self, pid=2 ** 22 + 12345):
        script = updater.write_swap_script(self.new, self.app, pid=pid)
        self.assertNotIn(b"\r", open(script, "rb").read())
        updater.run_swap(script)
        for _ in range(100):                                                          # the script ends by deleting itself
            if not os.path.exists(script):
                break
            time.sleep(0.1)
        time.sleep(0.5)                                                               # the started program writes its note a moment later
        return script

    def test_the_new_program_is_put_in_started_and_the_old_one_kept_aside(self):
        self.run_script()
        self.assertEqual(open(os.path.join(self.app, "_internal", "marker")).read(), "new")
        self.assertEqual(open(os.path.join(self.app, "_internal.old", "marker")).read(), "old")
        self.assertIn("started-new", open(os.path.join(self.app, "started.txt")).read())
        self.assertEqual(open(os.path.join(self.app, "PMF Studio settings.json")).read(), "{}")      # settings and saved files are never touched
        self.assertEqual(open(os.path.join(self.app, "Output", "mine.pmf")).read(), "keep me")
        self.assertFalse(os.path.exists(self.new))                                    # the staging copy is removed
        updater.cleanup_after_update(self.app)
        self.assertFalse(os.path.exists(os.path.join(self.app, "_internal.old")))

    def test_the_old_program_is_put_back_when_the_new_one_cannot_start(self):
        os.chmod(os.path.join(self.new, EXE_NAME), 0o644)                              # the copy keeps this: the new program is not startable
        self.run_script()
        self.assertEqual(open(os.path.join(self.app, "_internal", "marker")).read(), "old")
        self.assertFalse(os.path.exists(os.path.join(self.app, "_internal.old")))
        self.assertIn("started-old", open(os.path.join(self.app, "started.txt")).read())
        self.assertIn("the old version was put back", open(os.path.join(self.app, "update_log.txt")).read())

    def test_the_script_waits_for_a_running_program_to_end(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        t0 = time.time()
        try:
            script = updater.write_swap_script(self.new, self.app, pid=sleeper.pid)
            updater.run_swap(script)
            time.sleep(1.0)
            self.assertEqual(open(os.path.join(self.app, "_internal", "marker")).read(), "old")      # still waiting: nothing moved yet
            sleeper.wait()
            for _ in range(100):
                if not os.path.exists(script):
                    break
                time.sleep(0.1)
            self.assertEqual(open(os.path.join(self.app, "_internal", "marker")).read(), "new")
            self.assertGreater(time.time() - t0, 2.5)
        finally:
            sleeper.kill()


class CommonSwapTests(unittest.TestCase):
    def test_the_result_file_of_an_offline_update_is_never_copied_from_an_update(self):
        self.assertIn("update_result.txt", updater.KEEP)

    def test_cleanup_removes_only_what_the_update_left_aside(self):
        d = tempfile.mkdtemp(prefix="pmf_clean_")
        try:
            for n in ("_internal.old", "tools.old", "update_staging", "Output"):
                os.makedirs(os.path.join(d, n))
            open(os.path.join(d, EXE_NAME + ".old"), "wb").write(b"x")
            open(os.path.join(d, "PMF Studio settings.json"), "wb").write(b"{}")
            updater.cleanup_after_update(d)
            self.assertEqual(sorted(os.listdir(d)), ["Output", "PMF Studio settings.json"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_appimage_cannot_replace_itself(self):
        old = os.environ.get("APPIMAGE")
        os.environ["APPIMAGE"] = "/somewhere/PMF-Studio.AppImage"
        try:
            frozen = getattr(sys, "frozen", None)
            sys.frozen = True
            try:
                self.assertIn("AppImage", updater.can_install(tempfile.gettempdir()) or "")
            finally:
                if frozen is None:
                    del sys.frozen
                else:
                    sys.frozen = frozen
        finally:
            if old is None:
                del os.environ["APPIMAGE"]
            else:
                os.environ["APPIMAGE"] = old


if __name__ == "__main__":
    unittest.main()
