"""Options, kept in a small file beside the program.

Folders inside the program's own folder are saved as relative names, so the program can be moved or renamed, or carried to another
drive letter, and still find them. A saved folder that no longer exists or can't be written to is dropped, never re-created.
"""
import json
import os

from .paths import app_dir, default_output

FILE = "PMF Studio settings.json"
DEFAULTS = {"auto_update": True, "dark": True, "open_folder": True, "output_dir": "", "low_priority": True}
KINDS = {"auto_update": bool, "dark": bool, "open_folder": bool, "output_dir": str, "low_priority": bool}


def path():
    return os.path.join(app_dir(), FILE)


def load():
    s = dict(DEFAULTS)
    try:
        saved = json.load(open(path(), encoding="utf8"))
        if isinstance(saved, dict):
            s.update({k: v for k, v in saved.items() if k in DEFAULTS and isinstance(v, KINDS[k])})   # a damaged or odd value is ignored
    except (OSError, ValueError):
        pass
    return s


def save(s):
    tmp = path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf8") as f:                # written beside it, then swapped in: a crash can't leave half a file
            json.dump({k: v for k, v in s.items() if k in DEFAULTS}, f, indent=2)
        os.replace(tmp, path())
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def to_stored(folder):
    """how a folder is written to the file: relative to the program when it is inside it, else as it is"""
    if not folder:
        return ""
    try:
        rel = os.path.relpath(folder, app_dir())
    except ValueError:                                         # another drive: no relative form exists
        return folder
    return folder if rel.startswith("..") or os.path.isabs(rel) else rel


def resolve(stored):
    return stored if os.path.isabs(stored) else os.path.join(app_dir(), stored)


def usable(folder):
    """exists (or can be made) and can be written to"""
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_test")
        open(probe, "w").close()
        os.remove(probe)
        return True
    except OSError:
        return False


def output_dir(s):
    """The folder results go to. Order: the one chosen in Options, the Output folder beside the program, then the user's Documents.
    When the chosen folder is gone or locked, s["_note"] says so once, and the choice is cleared."""
    chosen = s.get("output_dir") or ""
    if chosen:
        folder = resolve(chosen)
        if os.path.isdir(folder) and usable(folder):
            return folder
        s["_note"] = "The folder you chose for saving files (%s) isn't available, so PMF Studio is using its own Output folder instead." % folder
        s["output_dir"] = ""
        save(s)
    for folder in (default_output(), os.path.join(os.path.expanduser("~"), "Documents", "PMF Studio"), os.path.expanduser("~")):
        if usable(folder):
            if folder != default_output() and "_note" not in s:
                s["_note"] = "PMF Studio can't write beside itself (the folder may be read-only), so it is saving to %s." % folder
            return folder
    return os.path.expanduser("~")
