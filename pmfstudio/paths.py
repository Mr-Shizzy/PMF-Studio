"""Where things live. Everything stays beside the program (100% portable: nothing in AppData or the registry)."""
import os
import shutil
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
