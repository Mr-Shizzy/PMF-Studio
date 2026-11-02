"""Facts about the helper programs and the places they can work in, so odd folders and different ffmpeg versions don't break anything."""
import ctypes
import os
import re
import shutil
import subprocess
import tempfile

NOWND = 0x08000000 if os.name == "nt" else 0
_versions = {}


def is_ascii(path):
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def ffmpeg_version(ffmpeg):
    """(major, minor) of this ffmpeg, (0, 0) when it can't be read; asked once per program"""
    if ffmpeg not in _versions:
        try:
            r = subprocess.run([ffmpeg, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20, creationflags=NOWND)
            m = re.search(r"version\s+n?(\d+)\.(\d+)", r.stdout)
            _versions[ffmpeg] = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        except (OSError, subprocess.SubprocessError):
            _versions[ffmpeg] = (0, 0)
    return _versions[ffmpeg]


def passthrough_args(ffmpeg):
    """'one output picture per input picture': -vsync 0 in older ffmpeg, -fps_mode passthrough from 5.1 on (the old name is going away)"""
    return ["-fps_mode", "passthrough"] if ffmpeg_version(ffmpeg) >= (5, 1) else ["-vsync", "0"]


def _short(path):
    """the old 8.3 form of a Windows path, which is plain letters even when the real name isn't"""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        return buf.value if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) else path
    except (AttributeError, OSError):
        return path


def ascii_temp_dir():
    """a fresh folder whose path is plain ASCII, for programs (atracdenc) that cannot open files in folders with other letters in the name.
    Normally the short form of a folder beside the program; failing that, the shared Public folder. The caller removes it afterwards."""
    for base in (tempfile.gettempdir(), os.environ.get("PUBLIC"), os.environ.get("ProgramData")):
        if not base or not os.path.isdir(base):
            continue
        try:
            d = tempfile.mkdtemp(prefix="pmf_", dir=_short(base))
        except OSError:
            continue
        if is_ascii(d):
            return d
        shutil.rmtree(d, ignore_errors=True)
    raise OSError("PMF Studio couldn't find a folder with a plain-letter name to work in. Move the program to a folder like C:\\PMF Studio.")
