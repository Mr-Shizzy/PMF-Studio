"""Fonts on Linux. The window asks for "Segoe UI" (and "Consolas" for the log) everywhere; Windows has them. On Linux the program tells fontconfig,
before the window opens, which fonts to use in their place:

  - Selawik (SIL Open Font License), Microsoft's metric-compatible stand-in for Segoe UI, shipped in tools/fonts/ with the Linux release, so the
    letters are as wide as on Windows and the layout comes out the same;
  - if that can't be loaded, the best installed font in PREFERENCE, closest to Segoe UI first.

Needs a Tk built with Xft (the Linux release has one: see packaging/linux/build_tk_xft.sh); a Tk without it can only draw with the plain X font
"fixed", whatever is asked for. Nothing happens on Windows."""
import ctypes
import glob
import os

from . import paths

SANS = ("Selawik", "Noto Sans", "Liberation Sans", "Ubuntu Sans", "Ubuntu", "Cantarell", "Open Sans", "DejaVu Sans", "sans-serif")
MONO = ("DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono", "Ubuntu Sans Mono", "Ubuntu Mono", "monospace")
ALIASES = (("Segoe UI", SANS), ("Consolas", MONO))
RESULT = {"text": "not set up (Windows)" if os.name == "nt" else "not set up yet"}


def fonts_dir():
    return os.path.join(paths.app_dir(), "tools", "fonts")


def config_xml(aliases=ALIASES):
    """a fontconfig rule per alias: a request for the Windows font is answered by the first of the replacements that is installed"""
    rules = "".join('<match target="pattern"><test name="family" qual="any"><string>%s</string></test>'
                    '<edit name="family" mode="prepend" binding="strong">%s</edit></match>' % (name, "".join("<string>%s</string>" % f for f in replacements))
                    for name, replacements in aliases)
    return '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>%s</fontconfig>' % rules


def setup():
    """tells fontconfig about the shipped fonts and the replacements -> a line for the diagnostics (never raises)"""
    if os.name == "nt":
        return RESULT["text"]
    try:
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigGetCurrent.argtypes = []
        fc.FcConfigGetCurrent.restype = ctypes.c_void_p
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        fc.FcConfigParseAndLoadFromMemory.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        fc.FcConfigParseAndLoadFromMemory.restype = ctypes.c_int
    except (OSError, AttributeError):
        RESULT["text"] = "fontconfig not found: Tk's own font choice"
        return RESULT["text"]
    config = fc.FcConfigGetCurrent()                 # (a NULL config is not accepted by every fontconfig version: one crashed on it)
    if not config:
        RESULT["text"] = "fontconfig has no configuration: Tk's own font choice"
        return RESULT["text"]
    added = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(fonts_dir(), "*.ttf"))) if fc.FcConfigAppFontAddFile(config, f.encode())]
    loaded = bool(fc.FcConfigParseAndLoadFromMemory(config, config_xml().encode(), 1))
    RESULT["text"] = "%s; %s" % ("shipped fonts: " + ", ".join(added) if added else "no shipped fonts", "replacements set" if loaded else "replacements NOT accepted")
    return RESULT["text"]
