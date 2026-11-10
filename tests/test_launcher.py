import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import launcher  # noqa: E402


class TextTests(unittest.TestCase):
    def test_the_file_starts_the_program_with_the_dropped_files(self):
        t = launcher.text("/opt/PMF Studio/PMF Studio", "/opt/PMF Studio/icon.png")
        self.assertIn('Exec="/opt/PMF Studio/PMF Studio" %F\n', t)
        self.assertIn("Icon=/opt/PMF Studio/icon.png\n", t)
        self.assertTrue(t.startswith("[Desktop Entry]\n"))
        self.assertNotIn("\r", t)
        self.assertIn("StartupWMClass=Pmfstudio\n", t)                       # the window's class: a dock groups the window under this launcher

    def test_the_appimages_own_entry_names_the_same_class(self):
        import re
        build = open(os.path.join(os.path.dirname(__file__), "..", "packaging", "build_release.py"), encoding="utf-8").read()
        self.assertEqual(re.findall(r"StartupWMClass=(\w+)", build), [launcher.WINDOW_CLASS])

    def test_the_window_really_gets_the_class_the_launchers_name(self):
        """Tk changes the capitals of the name it is given; what it makes of ours must be what the launchers say"""
        try:
            import tkinter
            root = tkinter.Tk(className=launcher.TK_CLASS_NAME)
        except Exception:
            self.skipTest("needs a display")
        try:
            self.assertEqual(root.winfo_class(), launcher.WINDOW_CLASS)
        finally:
            root.destroy()

    def test_characters_that_are_special_in_a_launcher_line_are_escaped(self):
        self.assertEqual(launcher.quote("/a b/c"), '"/a b/c"')
        self.assertEqual(launcher.quote('/x"y'), '"/x\\\\"y"')             # backslash before the quote, and that backslash doubled for the file
        self.assertEqual(launcher.quote("/x$y`z"), '"/x\\\\$y\\\\`z"')
        self.assertEqual(launcher.quote("/100%/p"), '"/100%%/p"')            # %% is a literal percent sign
        self.assertEqual(launcher.quote("/a\\b"), '"/a\\\\\\\\b"')

    def test_a_path_with_a_line_break_is_not_written(self):
        self.assertIsNone(launcher.text("/a\nb/PMF Studio"))

    def test_nothing_is_written_for_a_windows_or_source_or_appimage_run(self):
        d = tempfile.mkdtemp(prefix="pmf_launch_")
        try:
            self.assertIsNone(launcher.refresh(d))                           # not a packaged program (the tests run from source)
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(os.environ, {"APPIMAGE": "/x.AppImage"}):
                self.assertIsNone(launcher.refresh(d))
            self.assertEqual(os.listdir(d), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(os.name == "nt", "launchers are a Linux thing")
class FileTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf José launch ")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_it_is_written_marked_startable_and_left_alone_when_already_right(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(os.environ):
            os.environ.pop("APPIMAGE", None)
            path = launcher.refresh(self.d, "/some/icon.png")
        self.assertEqual(path, os.path.join(self.d, "PMF Studio.desktop"))
        self.assertTrue(os.access(path, os.X_OK))
        self.assertIn('Exec="%s" %%F' % os.path.join(self.d, "PMF Studio"), open(path).read())
        before = os.stat(path).st_mtime_ns
        time.sleep(0.05)
        launcher.write(self.d, os.path.join(self.d, "PMF Studio"), "/some/icon.png")
        self.assertEqual(os.stat(path).st_mtime_ns, before)                  # unchanged: not rewritten
        launcher.write(self.d, "/moved/PMF Studio", None)                    # the folder was moved: the file follows
        self.assertIn('"/moved/PMF Studio"', open(path).read())

    def test_a_folder_that_cannot_be_written_is_no_problem(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root can write anywhere")
        os.chmod(self.d, 0o555)
        try:
            self.assertIsNone(launcher.write(self.d, "/x/PMF Studio"))
        finally:
            os.chmod(self.d, 0o755)

    @unittest.skipUnless(shutil.which("gio"), "needs gio (GLib's own launcher code)")
    def test_glib_starts_the_program_with_the_dropped_files_whatever_the_names(self):
        folder = os.path.join(self.d, "my folder (1)")
        os.makedirs(folder)
        note = os.path.join(self.d, "note.txt")
        program = os.path.join(folder, "PMF Studio")
        open(program, "w").write('#!/bin/sh\n{ for a in "$@"; do echo "arg:$a"; done; } > "%s"\n' % note)
        os.chmod(program, 0o755)
        desktop = launcher.write(folder, program)
        files = [os.path.join(self.d, "a movie (1).pmf"), os.path.join(self.d, "100% sure & more $HOME `x`.mp4"), os.path.join(self.d, 'say "hi".wav')]
        for f in files:
            open(f, "w").write("x")
        subprocess.run(["gio", "launch", desktop] + files, cwd="/", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        for _ in range(50):
            if os.path.exists(note) and os.path.getsize(note):
                break
            time.sleep(0.1)
        self.assertEqual(open(note).read().splitlines(), ["arg:" + f for f in files])
        os.remove(note)
        subprocess.run(["gio", "launch", desktop], cwd="/", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)    # double-click: no files
        for _ in range(50):
            if os.path.exists(note):
                break
            time.sleep(0.1)
        self.assertEqual(open(note).read(), "")


if __name__ == "__main__":
    unittest.main()
