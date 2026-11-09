import json
import os
import tempfile
import unittest
from unittest import mock

from pmfstudio import settings
from pmfkit import toolinfo


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pmfs_")
        self.app = os.path.join(self.tmp, "PMF Studio")
        os.makedirs(self.app)
        self.patches = [mock.patch.object(settings, "data_dir", lambda: self.app),
                        mock.patch.object(settings, "default_output", lambda: os.path.join(self.app, "Output"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_folder_inside_the_program_is_saved_relative(self):
        self.assertEqual(settings.to_stored(os.path.join(self.app, "My Output")), "My Output")
        outside = os.path.join(self.tmp, "elsewhere")
        self.assertEqual(settings.to_stored(outside), outside)

    def test_relative_choice_follows_a_moved_program(self):
        os.makedirs(os.path.join(self.app, "Mine"))
        s = {"output_dir": "Mine"}
        first = settings.output_dir(s)
        moved = os.path.join(self.tmp, "Renamed Folder")
        os.rename(self.app, moved)
        self.app = moved                                        # the patched app_dir reads self.app
        self.assertEqual(settings.output_dir(s), os.path.join(moved, "Mine"))
        self.assertNotEqual(first, settings.output_dir(s))

    def test_a_vanished_folder_is_dropped_not_recreated(self):
        gone = os.path.join(self.tmp, "old place", "Output")
        s = {"output_dir": gone}
        folder = settings.output_dir(s)
        self.assertFalse(os.path.exists(gone))                  # the old path was not brought back to life
        self.assertEqual(folder, os.path.join(self.app, "Output"))
        self.assertEqual(s["output_dir"], "")
        self.assertIn("isn't available", s["_note"])

    def test_damaged_settings_file_is_ignored(self):
        open(os.path.join(self.app, settings.FILE), "w").write("{ not json")
        self.assertEqual(settings.load()["dark"], True)
        json.dump({"dark": "yes", "output_dir": 5, "auto_update": False, "extra": 1}, open(os.path.join(self.app, settings.FILE), "w"))
        s = settings.load()
        self.assertEqual((s["dark"], s["output_dir"], s["auto_update"]), (True, "", False))
        self.assertNotIn("extra", s)

    def test_notes_are_never_written_to_the_file(self):
        settings.save({"dark": False, "output_dir": "", "_note": "temporary"})
        self.assertNotIn("_note", json.load(open(os.path.join(self.app, settings.FILE))))


class DataDirTests(unittest.TestCase):
    """settings, saved files and working files go beside the program, but beside the .AppImage file for an AppImage (its own folder is read-only)"""

    def test_beside_the_program_normally(self):
        from pmfstudio import paths
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APPIMAGE", None)
            self.assertEqual(paths.data_dir(), paths.app_dir())

    def test_beside_the_appimage_file_when_running_as_one(self):
        import sys
        from pmfstudio import paths
        folder = os.path.join(tempfile.gettempdir(), "My Games")
        with mock.patch.dict(os.environ, {"APPIMAGE": os.path.join(folder, "PMF-Studio.AppImage")}), mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(paths.data_dir(), os.path.abspath(folder))
            self.assertEqual(paths.default_output(), os.path.join(os.path.abspath(folder), "Output"))
            self.assertEqual(paths.restore_missing_tools(), [])                   # a read-only AppImage is never written to

    def test_the_variable_is_ignored_by_a_program_run_from_source(self):
        from pmfstudio import paths
        with mock.patch.dict(os.environ, {"APPIMAGE": "/elsewhere/x.AppImage"}):
            self.assertEqual(paths.data_dir(), paths.app_dir())


class ToolInfoTests(unittest.TestCase):
    def test_ascii_check(self):
        self.assertTrue(toolinfo.is_ascii("C:\\PMF Studio\\temp"))
        self.assertFalse(toolinfo.is_ascii("C:\\Jos\u00e9\\temp"))

    def test_picture_flag_follows_the_ffmpeg_version(self):
        with mock.patch.dict(toolinfo._versions, {"old": (4, 2), "new": (9, 0), "edge": (5, 1)}):
            self.assertEqual(toolinfo.passthrough_args("old"), ["-vsync", "0"])
            self.assertEqual(toolinfo.passthrough_args("new"), ["-fps_mode", "passthrough"])
            self.assertEqual(toolinfo.passthrough_args("edge"), ["-fps_mode", "passthrough"])

    def test_plain_letter_work_folder(self):
        d = toolinfo.ascii_temp_dir()
        try:
            self.assertTrue(toolinfo.is_ascii(d) and os.path.isdir(d))
        finally:
            os.rmdir(d)


if __name__ == "__main__":
    unittest.main()
