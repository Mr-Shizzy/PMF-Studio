"""Dragging files onto the window (or onto the program's icon, or giving them on the command line): which page and which box each one
belongs in, and the Windows hook that receives the drop (no extra library: the shell's own drag-and-drop calls)."""
import ctypes
import os
from ctypes import wintypes

VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".gif", ".ts", ".m2ts", ".3gp"}
AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".oma", ".wma"}
IMAGES = {".png", ".jpg", ".jpeg", ".bmp"}


def classify(path):
    """folder | pbp | pmf | ctf | at3 | disc | video | audio | image | rco | other"""
    if os.path.isdir(path):
        return "folder"
    ext = os.path.splitext(path)[1].lower()
    for kind, group in (("pbp", {".pbp"}), ("pmf", {".pmf"}), ("ctf", {".ctf"}), ("at3", {".at3"}), ("rco", {".rco"}), ("disc", {".cso", ".iso"}),
                        ("video", VIDEO), ("audio", AUDIO), ("image", IMAGES)):
        if ext in group:
            return kind
    return "other"


def route(paths, mode):
    """-> (page, box, path, sentence): where the first dropped file goes, given the page that is open.
    box is the name of the entry box (None: the Player opens it). page None means the file can't be used, and the sentence says why."""
    if not paths:
        return None, None, None, ""
    first, kind = paths[0], classify(paths[0])
    name = os.path.basename(first.rstrip("\\/")) or first
    if mode == "player" and kind not in ("folder", "pbp", "other", "disc"):
        return "player", None, first, "Opened %s in the player." % name
    if kind == "folder":
        return "shrink", "src", first, "%s: the folder to shrink." % name
    if kind == "pmf":
        many = sum(classify(p) == "pmf" for p in paths) > 1
        if many or mode == "shrink":
            return "shrink", "src", first, "%s: the movie to shrink." % name + (" Several were dropped: drop the folder they are in to shrink them all." if many else "")
        if mode == "extract":
            return "extract", "src", first, "%s: the movie to take apart." % name
        return "player", None, first, "Opened %s in the player." % name
    if kind == "disc":
        return "shrink", "src", first, "%s: the game to shrink." % name
    if kind == "ctf":
        return "extract", "src", first, "%s: the theme to take the gameboot out of." % name
    if kind == "pbp":
        return "icon", "eboot", first, "%s: the game file to change." % name
    if kind in ("video",):
        if mode in ("gameboot", "cintro", "icon"):
            return mode, "movie", first, "%s: your movie." % name
        if mode == "at3":
            return "at3", "sound", first, "%s: the sound source." % name
        return "gameboot", "movie", first, "%s: your movie." % name
    if kind in ("audio", "at3"):
        return "at3", "sound", first, "%s: the sound." % name
    if kind == "rco":
        return "gameboot", "rco", first, "%s: your decrypted opening_plugin.rco." % name
    if kind == "image":
        if mode == "gameboot":
            return "gameboot", "preview", first, "%s: the theme preview picture." % name
        return None, None, None, "Pictures go in a box on the Gameboot page (CTF preview) or the EBOOT icon page: use that box's Browse button."
    return None, None, None, "PMF Studio can't use %s here." % name


def enable(window, on_drop):
    """Lets files be dragged from Explorer onto the window; on_drop(list of paths) is called on the window's own thread.
    Returns None, or a sentence saying why it isn't available (the program works without it)."""
    if os.name != "nt":
        return "not on this system"
    try:
        window.update_idletasks()
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        WM_DROPFILES, GWLP_WNDPROC = 0x0233, -4
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        old_proc = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                found = []
                try:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    for i in range(count):
                        n = shell32.DragQueryFileW(wparam, i, None, 0)
                        buf = ctypes.create_unicode_buffer(n + 1)
                        shell32.DragQueryFileW(wparam, i, buf, n + 1)
                        found.append(buf.value)
                finally:
                    shell32.DragFinish(wparam)
                if found:
                    window.after(10, lambda: on_drop(found))
                return 0
            return user32.CallWindowProcW(old_proc, h, msg, wparam, lparam)

        window._drop_proc = WNDPROC(proc)                       # kept, or Python frees the callback and the program crashes on the next drop
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(window._drop_proc, ctypes.c_void_p).value)
        shell32.DragAcceptFiles(hwnd, True)
        for msg in (WM_DROPFILES, 0x0049, 0x004A):               # also when the file comes from a program running at another privilege level
            user32.ChangeWindowMessageFilterEx(hwnd, msg, 1, None)
        return None
    except Exception as e:                                       # noqa: BLE001
        return str(e)
