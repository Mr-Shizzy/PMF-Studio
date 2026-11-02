import hashlib
import io
import os
import shutil
import tempfile
import unittest
import zipfile

from pmfstudio import updater
from pmfstudio.updater import UpdateError


def make_release_zip(path, top="PMF Studio", missing=(), extra=None):
    names = {top + "/PMF Studio.exe": b"MZ" + b"\0" * 100, top + "/_internal/base.dll": b"x", top + "/tools/ffmpeg.exe": b"MZ", top + "/tools/atracdenc.exe": b"MZ",
             top + "/LICENSE": b"GPL", top + "/Output/junk.txt": b"should not be installed", top + "/selftest_result.txt": b"old"}
    names.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for n, data in names.items():
            if not any(m in n for m in missing):
                z.writestr(n, data)


class AssetTests(unittest.TestCase):
    def test_asset_and_checksum_come_from_the_release(self):
        info = {"assets": [{"name": "notes.txt", "browser_download_url": "x"},
                           {"name": "PMF-Studio-0.2-beta-win64.zip", "browser_download_url": updater.PREFIX + "releases/download/v0.2/PMF-Studio-0.2-beta-win64.zip",
                            "size": 52_000_000, "digest": "sha256:" + "AB" * 32}], "body": "SHA-256 " + "cd" * 32}
        a = updater.pick_asset(info)
        self.assertEqual((a["name"], a["size"], a["sha"]), ("PMF-Studio-0.2-beta-win64.zip", 52_000_000, "ab" * 32))      # GitHub's own digest wins
        del info["assets"][1]["digest"]
        self.assertEqual(updater.pick_asset(info)["sha"], "cd" * 32)                                                      # else the release notes
        info["body"] = "no checksum here"
        self.assertEqual(updater.pick_asset(info)["sha"], "")
        self.assertIsNone(updater.pick_asset({"assets": []}))

    def test_versions(self):
        self.assertGreater(updater.ver("v0.2"), updater.ver("0.1"))
        self.assertGreater(updater.ver("0.10.0"), updater.ver("0.9.9"))
        self.assertEqual(updater.ver("v1.2.0"), updater.ver("1.2.0"))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_upd_")
        self.zip = os.path.join(self.d, "src.zip")
        make_release_zip(self.zip)
        self.sha = hashlib.sha256(open(self.zip, "rb").read()).hexdigest()
        self.asset = dict(name="PMF-Studio-9-beta-win64.zip", url=updater.PREFIX + "x.zip", size=os.path.getsize(self.zip), sha=self.sha)
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
        z = os.path.join(self.d, "r.zip")
        make_release_zip(z)
        new = updater.unpack(z, os.path.join(self.d, "stage"))
        self.assertTrue(os.path.isfile(os.path.join(new, "PMF Studio.exe")))
        self.assertFalse(os.path.exists(os.path.join(new, "Output")))                 # things a build left behind are not installed
        self.assertFalse(os.path.exists(os.path.join(new, "selftest_result.txt")))

    def test_an_incomplete_or_odd_release_is_refused(self):
        z = os.path.join(self.d, "r.zip")
        make_release_zip(z, missing=("atracdenc",))
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s1"))
        make_release_zip(z, extra={"PMF Studio/PMF Studio.exe": b"not a program"})
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s2"))
        open(z, "wb").write(b"this is not a zip")
        with self.assertRaises(UpdateError):
            updater.unpack(z, os.path.join(self.d, "s3"))

    def test_entries_that_escape_the_folder_are_refused(self):
        for evil in ("../evil.txt", "PMF Studio/../../evil.txt", "C:/evil.txt", "/evil.txt"):
            z = os.path.join(self.d, "e.zip")
            make_release_zip(z, extra={evil: b"x"})
            with self.assertRaises(UpdateError, msg=evil):
                updater.unpack(z, os.path.join(self.d, "s"))
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil.txt")))


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

    def test_cleanup_removes_only_what_the_update_left_aside(self):
        d = tempfile.mkdtemp(prefix="pmf_clean_")
        try:
            for n in ("_internal.old", "tools.old", "update_staging", "Output"):
                os.makedirs(os.path.join(d, n))
            open(os.path.join(d, "PMF Studio.exe.old"), "wb").write(b"x")
            open(os.path.join(d, "PMF Studio settings.json"), "wb").write(b"{}")
            updater.cleanup_after_update(d)
            self.assertEqual(sorted(os.listdir(d)), ["Output", "PMF Studio settings.json"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
