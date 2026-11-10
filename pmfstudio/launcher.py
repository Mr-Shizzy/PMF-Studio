"""The Linux counterpart of dropping files on the program's icon: a launcher file ("PMF Studio.desktop") beside the program.

Double-click it to start PMF Studio; drop files on it (file managers pass them on as arguments) or choose it under "Open with" and the program starts
with those files, as `PMF Studio movie.pmf` does. A launcher needs the program's full path, which isn't known until the program is somewhere, so the
program writes it itself, in its own folder (nothing is saved anywhere else), and rewrites it when the folder has been moved. Not for an AppImage
(its own launcher entry is inside it) and not for a program running from source files."""
import os
import sys

NAME = "PMF Studio.desktop"


def quote(path):
    """a path as one word of a desktop file's Exec line: inside double quotes, with a backslash before each character that stays special there
    (and % doubled), then every backslash doubled again because the file itself reads backslash escapes"""
    word = "".join("\\" + c if c in '"`$\\' else c for c in path).replace("%", "%%")
    return '"' + word.replace("\\", "\\\\") + '"'


def text(program, icon=None):
    """the launcher file's text, or None when the paths hold something a launcher can't carry (a line break)"""
    if any(ord(c) < 32 for c in program + (icon or "")):
        return None
    return ("[Desktop Entry]\nType=Application\nName=PMF Studio\n"
            "Comment=Make PSP movies, boot movies and AT3 sounds (drop files on this to open them)\n"
            "Exec=%s %%F\n%sTerminal=false\nCategories=AudioVideo;Video;\n" % (quote(program), "Icon=%s\n" % icon.replace("\\", "\\\\") if icon else ""))


def write(folder, program, icon=None):
    """writes (or refreshes) the launcher in `folder` -> the file's path, or None when it can't or needn't be written"""
    want = text(program, icon)
    path = os.path.join(folder, NAME)
    if want is None:
        return None
    try:
        if os.path.exists(path) and open(path, encoding="utf8").read() == want:
            return path                                                  # already right: nothing is touched
        with open(path, "w", encoding="utf8", newline="\n") as f:
            f.write(want)
        os.chmod(path, 0o755)                                            # a file manager starts only a launcher marked as one
        return path
    except (OSError, UnicodeError):
        return None                                                      # a read-only folder: the program works without it


def refresh(app_dir, icon=None):
    """called when the program starts: keeps the launcher beside a packaged Linux program up to date"""
    if os.name == "nt" or not getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"):
        return None
    return write(app_dir, os.path.join(app_dir, "PMF Studio"), icon)
