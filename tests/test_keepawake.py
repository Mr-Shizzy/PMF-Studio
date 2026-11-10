import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfkit import cli  # noqa: E402
from pmfstudio import keepawake  # noqa: E402

LINUX = os.name != "nt"


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@unittest.skipUnless(LINUX, "systemd-inhibit is the Linux way")
class LinuxKeepAwakeTests(unittest.TestCase):
    """with a stand-in systemd-inhibit (a shell script that notes what it was asked and then runs the command, as the real one does)"""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_awake_")
        self.note = os.path.join(self.d, "asked.txt")
        self.fake = os.path.join(self.d, "systemd-inhibit")
        open(self.fake, "w").write('#!/bin/sh\necho "$@" > "%s"\nwhile [ "$1" != sh ]; do shift; done      # (the real one takes its own options first)\nexec "$@"\n' % self.note)
        os.chmod(self.fake, 0o755)
        keepawake.LAST.update(how="", problem="")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def path(self):
        return mock.patch.dict(os.environ, {"PATH": self.d + os.pathsep + os.environ.get("PATH", "")})

    def test_it_takes_a_lock_while_a_job_runs_and_lets_go_afterwards(self):
        with self.path():
            keep = keepawake.KeepAwake()
            self.assertTrue(keep.start())
            pid = keep.proc.pid
            asked = open(self.note).read()
            for needle in ("--what=sleep:idle", "--who=PMF Studio", "--mode=block", str(os.getpid())):
                self.assertIn(needle, asked)
            self.assertTrue(alive(pid))
            self.assertIn("works", keepawake.status())
            self.assertIn("sleep and idle", keepawake.status())
            keep.stop()
            for _ in range(50):
                if not alive(pid):
                    break
                time.sleep(0.1)
            self.assertFalse(alive(pid))
            keep.stop()                                                        # stopping twice is harmless

    def test_the_lock_ends_by_itself_when_the_program_that_asked_is_gone(self):
        gone = subprocess.Popen(["sleep", "0.3"])
        holder = subprocess.Popen(["sh", "-c", keepawake.WATCH, "sh", str(gone.pid)])
        gone.wait()
        for _ in range(100):
            if holder.poll() is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(holder.poll(), "the lock would stay forever after a crash")

    def test_without_the_tool_the_job_just_runs_and_the_report_says_why(self):
        with mock.patch.object(shutil, "which", return_value=None):
            keep = keepawake.KeepAwake()
            self.assertFalse(keep.start())
            keep.stop()
            self.assertIn("not available", keepawake.status())
            self.assertIn("systemd-inhibit", keepawake.status())

    def test_a_weaker_lock_is_taken_when_the_strongest_is_refused(self):
        open(self.fake, "w").write('#!/bin/sh\necho "$1" >> "%s"\n[ "$1" = "--what=sleep:idle" ] && { echo "Failed to inhibit: Access denied" >&2; exit 1; }\n'
                                   'while [ "$1" != sh ]; do shift; done\nexec "$@"\n' % self.note)
        with self.path():
            keep = keepawake.KeepAwake()
            try:
                self.assertTrue(keep.start())
                self.assertEqual(open(self.note).read().split(), ["--what=sleep:idle", "--what=idle"])
                self.assertIn("idle", keepawake.status())
                self.assertNotIn("sleep", keepawake.status())
            finally:
                keep.stop()

    def test_a_lock_that_cannot_be_taken_is_reported_not_raised(self):
        open(self.fake, "w").write('#!/bin/sh\necho "Failed to connect to bus" >&2\nexit 1\n')
        with self.path():
            keep = keepawake.KeepAwake()
            self.assertFalse(keep.start())
            self.assertIn("could not take the lock", keepawake.status())
            self.assertIn("Failed to connect to bus", keepawake.status())


@unittest.skipIf(LINUX, "Windows only")
class WindowsKeepAwakeTests(unittest.TestCase):
    def test_the_state_is_set_and_cleared(self):
        import ctypes
        calls = []
        fake = mock.Mock(side_effect=lambda flags: calls.append(flags) or 1)
        with mock.patch.object(ctypes, "windll", create=True) as w:
            w.kernel32.SetThreadExecutionState = fake
            keep = keepawake.KeepAwake()
            self.assertTrue(keep.start())
            keep.stop()
        self.assertEqual(calls, [0x80000001, 0x80000000])


class LowerPriorityTests(unittest.TestCase):
    def tearDown(self):
        cli.NICE = 0

    @unittest.skipUnless(LINUX, "nice is the Linux way")
    def test_a_helper_program_is_started_behind_nice_when_asked(self):
        cli.NICE = 10
        cmd = cli.niced(["ffmpeg", "-i", "a b.mp4"])
        self.assertEqual(cmd[1:], ["-n", "10", "ffmpeg", "-i", "a b.mp4"])
        self.assertTrue(cmd[0].endswith("nice"))
        cli.NICE = 0
        self.assertEqual(cli.niced(["ffmpeg"]), ["ffmpeg"])
        cli.NICE = 10
        with mock.patch.object(shutil, "which", return_value=None):
            self.assertEqual(cli.niced(["ffmpeg"]), ["ffmpeg"])                  # no nice on this system: normal priority, no failure

    @unittest.skipUnless(LINUX, "nice is the Linux way")
    def test_the_helper_really_runs_at_the_lower_priority_and_its_output_still_arrives(self):
        probe = [sys.executable, "-c", "import os, sys; sys.exit(0 if os.nice(0) == 10 else 7)"]       # fails unless it runs at nice 10
        cli.NICE = 10
        cli.run(probe)
        if os.nice(0) == 0:                                                                            # (a test run that is itself niced proves nothing here)
            cli.NICE = 0
            with self.assertRaises(cli.BuildError):
                cli.run(probe)

    def test_without_a_request_nothing_changes_anywhere(self):
        cli.NICE = 0
        self.assertEqual(cli.niced(["x", "y"]), ["x", "y"])


if __name__ == "__main__":
    unittest.main()
