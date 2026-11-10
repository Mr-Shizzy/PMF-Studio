"""Keeping the computer awake while a long job runs (a shrink can take an hour: a PC that goes to sleep in the middle of it would lose the job).

Windows: SetThreadExecutionState, which belongs to the thread that calls it, so start() and stop() must be called from the same thread.
Linux: a lock taken with systemd-inhibit (the standard way; desktops and the login manager honour it). The lock lives as long as the little
program it runs, and that program ends by itself when PMF Studio does, even if PMF Studio is killed. A system without systemd-inhibit is
told so (status()) and simply goes on without the lock."""
import os
import shutil
import subprocess

WHAT = ("sleep:idle", "idle", "sleep")                            # what to keep from happening, strongest first (a login manager may refuse some to some users)
WATCH = 'while kill -0 "$1" 2>/dev/null; do sleep 2; done'        # holds the lock until the process whose number it is given has ended
LAST = {"how": "", "problem": ""}                                 # what the last start() did, for the diagnostics


class KeepAwake:
    def __init__(self):
        self.proc = None

    def start(self):
        """True when the computer is now being kept awake"""
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)       # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            self.proc = "windows"
            LAST.update(how="SetThreadExecutionState", problem="")
            return True
        tool = shutil.which("systemd-inhibit")
        if not tool:
            LAST.update(how="", problem="systemd-inhibit was not found")
            return False
        err = ""
        for what in WHAT:                                    # the strongest lock the system allows this user to take
            try:
                proc = subprocess.Popen([tool, "--what=" + what, "--who=PMF Studio", "--why=Making a file", "--mode=block",
                                         "sh", "-c", WATCH, "sh", str(os.getpid())],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, close_fds=True)
            except OSError as e:
                LAST.update(how="", problem="systemd-inhibit could not be started (%s)" % str(e)[:60])
                return False
            try:
                proc.wait(timeout=0.4)                       # a lock that could not be taken (no login manager, no permission) ends at once
            except subprocess.TimeoutExpired:
                self.proc = proc
                LAST.update(how="systemd-inhibit, %s" % what.replace(":", " and "), problem="")
                return True
            lines = (proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
            proc.stderr.close()
            err = lines[-1][:80] if lines else "no message"
        LAST.update(how="", problem="systemd-inhibit could not take the lock (%s)" % err)
        return False

    def stop(self):
        if self.proc == "windows":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)       # ES_CONTINUOUS alone: back to normal
        elif self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    self.proc.kill()
                except OSError:
                    pass
            if self.proc.stderr:
                self.proc.stderr.close()
        self.proc = None


def status():
    """one line for the diagnostics: whether the computer can be kept awake during a job"""
    if os.name == "nt":
        return "yes (Windows)"
    if LAST["how"]:
        return "works (%s)" % LAST["how"]
    if LAST["problem"]:
        return "not available (%s)" % LAST["problem"]
    return "ready (systemd-inhibit found)" if shutil.which("systemd-inhibit") else "not available (systemd-inhibit was not found)"
