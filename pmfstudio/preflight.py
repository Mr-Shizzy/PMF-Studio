"""Checks made before any work starts, so a job that cannot work is refused with a plain sentence instead of failing halfway and leaving
a partial file: a name Windows won't accept, saving over one of the files you picked, a folder that can't be written to, too little
free space (where the file goes and where the working files go), too little memory for a very long movie.

Every check raises cli.BuildError; its message is shown to the user as it is."""
import ctypes
import os
import shutil
import tempfile

from pmfkit import cli
from pmfkit.cli import BuildError

INVALID = set('<>:"|?*')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}
MAX_PATH_TEXT = 240                      # Windows stops at 260 letters; helper programs add a few
INPUT_KEYS = ("movie", "sound", "eboot", "src", "preview", "rco", "icon0", "pic1", "pic0")
MARGIN = 100_000_000                     # always leave this much free
PCM_BYTES_PER_SECOND = 176_400           # a decoded sound: 44.1 kHz, 16 bit, stereo


def fmt(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else ("%.0f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % round(n / 1e3))


def free_ram():
    """bytes of memory free right now (None when it can't be read)"""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong)]
    try:
        m = MemoryStatus()
        m.length = ctypes.sizeof(m)
        return int(m.avail) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else None
    except (AttributeError, OSError):
        return None


def check_name(path):
    """the name or folder names in a path that Windows would refuse, or a path that is too long"""
    full = path if os.path.isabs(path) else os.path.abspath(path)          # (abspath turns a name like "nul" into a device path, which hides it)
    _, rest = os.path.splitdrive(full)
    for part in rest.replace("/", "\\").split("\\"):
        if not part:
            continue
        if any(c in INVALID or ord(c) < 32 for c in part):
            raise BuildError("\"%s\" has a character Windows doesn't allow in names (< > : \" | ? *). Pick another name." % part)
        if part.split(".")[0].upper() in RESERVED:
            raise BuildError("\"%s\" is a name Windows keeps for itself. Pick another name." % part)
        if part != part.rstrip(" ."):
            raise BuildError("\"%s\" ends with a space or a dot, which Windows doesn't allow. Pick another name." % part)
    if len(full) > MAX_PATH_TEXT:
        raise BuildError("That file path is %d letters long, which is more than Windows handles reliably (about %d). Save in a folder closer to the top of the drive."
                         % (len(full), MAX_PATH_TEXT))


def check_not_input(v, out):
    """the file being written is never one of the files you picked: originals stay untouched"""
    target = os.path.normcase(os.path.abspath(out))
    for key in INPUT_KEYS:
        p = v.get(key)
        if p and os.path.isfile(p) and os.path.normcase(os.path.abspath(p)) == target:
            raise BuildError("You are saving over a file you picked (%s). PMF Studio never replaces your originals: save under another name or in another folder." % os.path.basename(p))


def nearest_existing(folder):
    p = os.path.abspath(folder)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    return p


def check_writable(folder):
    """a small test file is made in the folder (or the nearest one that exists) and removed again"""
    anc = nearest_existing(folder)
    if anc is None or not os.path.isdir(anc):
        raise BuildError("PMF Studio can't use the folder %s. Pick another folder to save in." % folder)
    try:
        fd, name = tempfile.mkstemp(prefix=".pmfstudio_", dir=anc)
        os.close(fd)
        os.remove(name)
    except OSError:
        raise BuildError("PMF Studio can't save into %s. It may be read-only or protected. Pick another folder (for example one inside your Documents)." % anc)


def _seconds(v, tools, key):
    if v.get("part_length"):
        return float(v["part_length"])
    try:
        return cli.probe_seconds(tools["ffmpeg"], v[key])
    except Exception:                                    # an odd file: the real job will say what is wrong with it
        return None


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def needs(mode, v, tools, out_folder):
    """[(folder, bytes)]: what the job will occupy, in the folder it saves to and in the temporary folder (rough, on the high side)"""
    out_need = temp_need = 0
    if mode == "gameboot":
        secs = _seconds(v, tools, "movie")
        out_need, temp_need = 4_000_000, int((secs or 0) * 400_000) + 50_000_000
    elif mode == "cintro":
        secs = _seconds(v, tools, "movie")
        out_need, temp_need = int((secs or 0) * 270_000), int((secs or 0) * 430_000)
    elif mode == "icon":
        out_need, temp_need = _size(v.get("eboot", "")) + 2_000_000, 80_000_000
    elif mode == "at3":
        task = v.get("task", "make")
        secs = _seconds(v, tools, "sound")
        if task == "extract":
            if v.get("fmt") == "mp3":
                out_need = int((secs or 0) * int(str(v.get("mp3kbps", "192 kbps")).split()[0]) * 125)
            else:
                out_need = int((secs or 0) * PCM_BYTES_PER_SECOND)
        else:
            out_need = int((secs or 0) * int(str(v.get("kbps", "64 kbps")).split()[0]) * 125) + 100_000
        temp_need = int((secs or 0) * PCM_BYTES_PER_SECOND * 1.1)
    elif mode == "extract":
        size = _size(v.get("src", ""))
        out_need, temp_need = int(size * 1.6) + 20_000_000, int(size * 2.2) + 50_000_000
    elif mode == "shrink":
        from pmfkit import shrink
        info = shrink.survey(v["src"])
        sound = int(v["sound"]) if v.get("sound", "keep") != "keep" else None
        out_need = shrink.predict(info, float(v.get("picture", "0.5")), sound) + 1_000_000
        biggest = max([_size(p) for p, _ in shrink.find_movies(v["src"])] or [0])
        temp_need = biggest * 4
    return [(out_folder, out_need), (tempfile.gettempdir(), temp_need)]


def check_space(items):
    """each drive the job touches must have room for everything it will put there, plus a margin"""
    drives = {}
    for folder, n in items:
        anc = nearest_existing(folder)
        if anc is None or n <= 0:
            continue
        try:
            key = os.stat(anc).st_dev
            free = shutil.disk_usage(anc).free
        except OSError:
            continue
        entry = drives.setdefault(key, [anc, free, 0])
        entry[2] += n
    for anc, free, n in drives.values():
        if free < n * 1.03 + MARGIN:
            raise BuildError("Not enough free space on %s: about %s is needed there, but only %s is free. Free up some room or choose another folder."
                             % (os.path.splitdrive(anc)[0] + "\\" if os.path.splitdrive(anc)[0] else anc, fmt(n), fmt(free)))


def check_memory(mode, v, tools):
    """a C-Intro movie is written piece by piece, so length doesn't matter; the sound (about 16 KB a second, held a few times over) and a
    working margin are what is needed: refuse only when even that can't fit, with advice"""
    if mode != "cintro":
        return
    secs = _seconds(v, tools, "movie")
    avail = free_ram()
    if not secs or not avail:
        return
    need = int(secs * 16_000 * 3) + 250_000_000
    if need > 400_000_000 and need > avail * 0.8:
        raise BuildError("This movie is too long to build with the memory free right now: it needs about %s and %s is free. "
                         "Close other programs, or pick a shorter part with the strip above." % (fmt(need), fmt(avail)))


def run(mode, v, tools):
    """all the checks, in the order the user would want to hear about them"""
    out = v.get("out", "")
    if not out:
        return
    check_name(out)
    check_not_input(v, out)
    folder = out if mode == "shrink" else os.path.dirname(os.path.abspath(out))
    check_writable(folder)
    check_memory(mode, v, tools)
    check_space(needs(mode, v, tools, folder))
