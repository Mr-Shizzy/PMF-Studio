"""Where things live. Everything stays beside the program (100% portable: nothing in AppData or the registry)."""
import os
import shutil
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pid_alive(pid):
    """is a program with this process number still running (when that can't be told: yes, so nothing is deleted by mistake)"""
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.windll.kernel32.GetLastError() != 87                   # 87 = no such process
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return not ok or code.value == 259                                       # 259 = still running
    except (AttributeError, OSError, ValueError):
        return True


def sweep_temp(base, me):
    """base\\run<number> folders belong to one running program each. Remove those whose program has ended (a crash, a power cut, a
    killed process) and anything else loose in base that is over a day old. Never touches the folder of a program that is still running."""
    import shutil
    import time
    try:
        names = os.listdir(base)
    except OSError:
        return
    for n in names:
        full = os.path.join(base, n)
        try:
            if n.startswith("run") and n[3:].isdigit():
                if int(n[3:]) != me and not pid_alive(int(n[3:])):
                    shutil.rmtree(full, ignore_errors=True)
            elif time.time() - os.path.getmtime(full) > 86400:
                shutil.rmtree(full, ignore_errors=True) if os.path.isdir(full) else os.remove(full)
        except OSError:
            pass


SPARE_TOOLS = ("atracdenc",)             # small helper programs with a spare copy packed inside the program (ffmpeg is too big for that)


def restore_spare(name, spare_dir, tools_dir):
    """put the spare copy of a helper program back in the tools folder when the file there is gone (an antivirus program can quarantine it).
    -> the path of the restored file, or None when nothing was needed or possible"""
    import shutil
    src, dst = os.path.join(spare_dir, name + ".exe"), os.path.join(tools_dir, name + ".exe")
    if os.path.isfile(dst) or not os.path.isfile(src):
        return None
    try:
        os.makedirs(tools_dir, exist_ok=True)
        shutil.copyfile(src, dst + ".part")                       # copied under another name first: a half-copied program is never left in place
        os.replace(dst + ".part", dst)
        return dst
    except OSError:
        try:
            os.remove(dst + ".part")
        except OSError:
            pass
        return None


def restore_missing_tools():
    """-> names of the helper programs that were missing and are back (only in the packaged program, which carries the spares)"""
    if not getattr(sys, "frozen", False):
        return []
    spare = os.path.join(getattr(sys, "_MEIPASS", os.path.join(app_dir(), "_internal")), "spare")
    return [n for n in SPARE_TOOLS if restore_spare(n, spare, os.path.join(app_dir(), "tools"))]


def asset(name):
    """a picture shipped with the program (pmfstudio/assets; the release packs the same folder), or None if it is missing"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
    return p if os.path.isfile(p) else None


def find_tool(name):
    """ffmpeg / atracdenc: the tools folder beside the program first, then (development) the project's own copies, then PATH."""
    base = app_dir()
    candidates = [os.path.join(base, "tools", name + ".exe"), os.path.join(base, name + ".exe"),
                  os.path.join(base, "tools", name, "bin", name + ".exe"),
                  os.path.join(base, "Things to refrence", "pmftools", "tools", name + ".exe")]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which(name)


def default_output():
    return os.path.join(app_dir(), "Output")


def check_tools():
    """-> {name: (path or None, text)}: where each helper program is and whether it really starts (an antivirus can block it, a
    wrong download can be the wrong kind of file)."""
    import subprocess
    result = {}
    for name, args in (("ffmpeg", ["-version"]), ("atracdenc", [])):
        path = find_tool(name)
        if not path:
            result[name] = (None, "not found")
            continue
        try:
            r = subprocess.run([path] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, creationflags=0x08000000 if os.name == "nt" else 0)
            first = (r.stdout or "").strip().splitlines()
            result[name] = (path, first[0][:70] if name == "ffmpeg" and first else "ready")
        except (OSError, subprocess.SubprocessError) as e:
            result[name] = (path, "found, but it won't start (%s)" % (str(e)[:60]))
    return result
