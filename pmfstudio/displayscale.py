"""The Linux counterpart of Windows' "this program knows about high-DPI screens" setting.

A Linux desktop publishes the screen's DPI as the X resource Xft.dpi (GNOME, KDE, XFCE and the others fill it in, and it is what a user changes
to make everything bigger). Tk by itself works the DPI out from the screen's size in millimetres, which is often wrong, so on a high-resolution
screen the window comes out tiny. The window asks for Xft.dpi once, before it is drawn, and when the desktop has set one it tells Tk (`tk scaling`);
the rest of the program already measures everything from Tk's scaling. Where nothing is set (or on Windows) nothing changes."""
import ctypes
import os
import re

MIN_DPI, MAX_DPI = 48, 480                       # anything outside this is a broken setting, not a screen


def parse(resources):
    """the DPI in an X resource string ("Xft.dpi:\\t144\\n..."), or None when it holds none that makes sense"""
    m = re.search(r"^Xft\.dpi:\s*([0-9]+(?:\.[0-9]+)?)\s*$", resources or "", re.M)
    if not m:
        return None
    dpi = float(m.group(1))
    return dpi if MIN_DPI <= dpi <= MAX_DPI else None


def xft_dpi():
    """the desktop's own DPI setting, or None (Windows, no X display, nothing set)"""
    if os.name == "nt" or not os.environ.get("DISPLAY"):
        return None
    try:
        x = ctypes.CDLL("libX11.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XResourceManagerString.restype = ctypes.c_char_p
        x.XResourceManagerString.argtypes = [ctypes.c_void_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x.XOpenDisplay(None)
        if not dpy:
            return None
        try:
            raw = x.XResourceManagerString(dpy)
            return parse(raw.decode("utf-8", "replace") if raw else "")
        finally:
            x.XCloseDisplay(dpy)
    except (OSError, AttributeError):
        return None


def apply(window):
    """tells Tk the desktop's DPI when the desktop has set one -> the DPI used, or None when Tk's own guess stays"""
    dpi = xft_dpi()
    if dpi:
        window.tk.call("tk", "scaling", dpi / 72.0)
    return dpi
