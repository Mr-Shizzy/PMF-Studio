import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from collections import namedtuple
from unittest import mock

from pmfkit import cli
from pmfkit.cli import BuildError
from pmfstudio import paths, preflight, settings


class NameTests(unittest.TestCase):
    def test_good_names_pass(self):
        preflight.check_name(os.path.join(tempfile.gettempdir(), "My Movie (2).pmf"))

    def test_bad_names_are_explained(self):
        for bad in ('a<b.pmf', 'what?.pmf', 'CON.pmf', 'nul', 'movie. ', 'x|y.pmf'):
            with self.assertRaises(BuildError, msg=bad):
                preflight.check_name(os.path.join(tempfile.gettempdir(), bad))

    def test_a_very_long_path_is_refused(self):
        with self.assertRaises(BuildError):
            preflight.check_name(os.path.join(tempfile.gettempdir(), "x" * 120, "y" * 120, "movie.pmf"))


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pmf_pre_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_saving_over_an_input_is_refused(self):
        p = os.path.join(self.dir, "game.pbp")
        open(p, "wb").write(b"x")
        with self.assertRaises(BuildError):
            preflight.check_not_input({"eboot": p}, p)
        with self.assertRaises(BuildError):
            preflight.check_not_input({"eboot": p}, p.upper())          # Windows names don't care about capitals
        preflight.check_not_input({"eboot": p}, os.path.join(self.dir, "copy.pbp"))

    def test_a_writable_folder_passes_and_leaves_nothing_behind(self):
        preflight.check_writable(os.path.join(self.dir, "not", "made", "yet"))
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_file_where_a_folder_is_needed_is_refused(self):
        p = os.path.join(self.dir, "a_file")
        open(p, "wb").write(b"x")
        with self.assertRaises(BuildError):
            preflight.check_writable(os.path.join(p, "sub"))

    def test_too_little_space_is_refused_and_enough_passes(self):
        Usage = namedtuple("Usage", "total used free")
        with mock.patch("shutil.disk_usage", return_value=Usage(10**12, 10**12 - 5 * 10**8, 5 * 10**8)):
            with self.assertRaises(BuildError) as cm:
                preflight.check_space([(self.dir, 10**9)])
            self.assertIn("Not enough free space", str(cm.exception))
            preflight.check_space([(self.dir, 10**7)])                            # 10 MB fits in 500 MB
        with mock.patch("shutil.disk_usage", return_value=Usage(10**12, 0, 10**12)):
            preflight.check_space([(self.dir, 10**9), (tempfile.gettempdir(), 10**9)])

    def test_two_folders_on_one_drive_add_up(self):
        Usage = namedtuple("Usage", "total used free")
        with mock.patch("shutil.disk_usage", return_value=Usage(10**12, 0, 10**9)):       # 1 GB free
            with self.assertRaises(BuildError):
                preflight.check_space([(self.dir, 5 * 10**8), (self.dir, 5 * 10**8)])


class SettingsTests(unittest.TestCase):
    def test_save_leaves_no_temporary_file_and_reads_back(self):
        d = tempfile.mkdtemp(prefix="pmf_set_")
        try:
            with mock.patch.object(settings, "path", lambda: os.path.join(d, "s.json")):
                settings.save(dict(settings.DEFAULTS, dark=False))
                self.assertEqual(os.listdir(d), ["s.json"])
                self.assertFalse(settings.load()["dark"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TempSweepTests(unittest.TestCase):
    def test_only_folders_of_ended_programs_are_removed(self):
        base = tempfile.mkdtemp(prefix="pmf_sweep_")
        try:
            mine, dead, other = "run%d" % os.getpid(), "run4000000", "notes"
            for n in (mine, dead, other):
                os.makedirs(os.path.join(base, n))
            paths.sweep_temp(base, os.getpid())
            self.assertEqual(sorted(os.listdir(base)), sorted([mine, other]))      # a running program's folder and unrelated recent things stay
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_this_program_counts_as_running(self):
        self.assertTrue(paths.pid_alive(os.getpid()))
        self.assertFalse(paths.pid_alive(4000000))


class CancelTests(unittest.TestCase):
    def tearDown(self):
        cli.CANCEL.clear()

    def test_stop_ends_the_helper_program_quickly(self):
        cli.CANCEL.clear()
        result = []

        def job():
            try:
                cli.run([sys.executable, "-c", "import time; time.sleep(60)"])
                result.append("finished")
            except cli.Cancelled:
                result.append("cancelled")

        t = threading.Thread(target=job)
        t.start()
        time.sleep(1.0)
        started = time.time()
        cli.cancel()
        t.join(10)
        self.assertEqual(result, ["cancelled"])
        self.assertLess(time.time() - started, 5)
        self.assertEqual(cli.ACTIVE, [])

    def test_nothing_starts_after_stop(self):
        cli.cancel()
        with self.assertRaises(cli.Cancelled):
            cli.run([sys.executable, "-c", "pass"])


if __name__ == "__main__":
    unittest.main()
