"""The Linux counterpart of Windows' "this program knows about high-DPI screens" setting.

DPI is how many screen dots make an inch. A normal screen is about 96; a high-resolution laptop or 4K screen is often 144 or 192, and then
everything drawn in fixed dots comes out tiny unless the program scales itself. Windows tells a program that has asked for it. On Linux the
desktop publishes the number, and the window reads it once, before it is drawn, in this order:

  1. the desktop's XSETTINGS (Xft/DPI): what GNOME, KDE, XFCE, Cinnamon and MATE publish and what their "scale" or "font size" settings change;
  2. the X resource Xft.dpi (set with xrdb, and by some simpler desktops and by hand);
  3. the environment: GDK_SCALE (a whole-number scale, times 96) and GDK_DPI_SCALE (a text scale), which people set by hand on a HiDPI screen.

When one of them gives a sensible number the window tells Tk (`tk scaling`); everything else already measures from Tk's scaling. Tk by itself works
the DPI out from the screen's size in millimetres, which is often wrong. Where nothing is set (and on Windows) nothing changes."""
import ctypes
import os
import re
import struct

MIN_DPI, MAX_DPI = 48, 480                       # anything outside this is a broken setting, not a screen


def sane(dpi):
    return float(dpi) if dpi is not None and MIN_DPI <= float(dpi) <= MAX_DPI else None


def parse(resources):
    """the DPI in an X resource string ("Xft.dpi:\\t144\\n..."), or None when it holds none that makes sense"""
    m = re.search(r"^Xft\.dpi:\s*([0-9]+(?:\.[0-9]+)?)\s*$", resources or "", re.M)
    return sane(m.group(1)) if m else None


def parse_xsettings(data):
    """the settings in an XSETTINGS block (the desktop's settings property) -> {name: value}; numbers and strings only; {} when the block is damaged"""
    out = {}
    try:
        order = "<" if data[0] == 0 else ">"                                   # byte 0: 0 = little endian, 1 = big endian
        count = struct.unpack_from(order + "I", data, 8)[0]
        pos = 12
        for _ in range(count):
            kind = data[pos]
            name_len = struct.unpack_from(order + "H", data, pos + 2)[0]
            name = data[pos + 4:pos + 4 + name_len].decode("utf-8", "replace")
            pos += 4 + name_len
            pos += -pos % 4                                                     # names are padded to 4 bytes
            pos += 4                                                            # the serial of the last change
            if kind == 0:                                                       # integer
                out[name] = struct.unpack_from(order + "i", data, pos)[0]
                pos += 4
            elif kind == 1:                                                     # string
                size = struct.unpack_from(order + "I", data, pos)[0]
                out[name] = data[pos + 4:pos + 4 + size].decode("utf-8", "replace")
                pos += 4 + size
                pos += -pos % 4
            elif kind == 2:                                                     # colour: four 16-bit numbers, not needed
                pos += 8
            else:
                break
    except (IndexError, struct.error):
        return out
    return out


def xsettings_dpi(settings):
    """the DPI an XSETTINGS block states (Xft/DPI is stored in 1024ths of a dot per inch), or None"""
    value = settings.get("Xft/DPI")
    return sane(value / 1024.0) if isinstance(value, int) and value > 0 else None


def environment_dpi(env=None):
    """the DPI the user's own environment settings ask for (GDK_SCALE: whole number of times 96; GDK_DPI_SCALE: a text scale), or None"""
    env = os.environ if env is None else env
    try:
        scale = float(env.get("GDK_SCALE", "") or 0)
        text = float(env.get("GDK_DPI_SCALE", "") or 1.0)
    except ValueError:
        return None
    if scale <= 1 and text == 1.0:                                              # nothing asked for (a scale of 1 is "no extra scale")
        return None
    return sane(96.0 * max(scale, 1.0) * text)


def _x11():
    x = ctypes.CDLL("libX11.so.6")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XGetSelectionOwner.restype = ctypes.c_ulong
    x.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x.XResourceManagerString.restype = ctypes.c_char_p
    x.XResourceManagerString.argtypes = [ctypes.c_void_p]
    x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x.XFree.argtypes = [ctypes.c_void_p]
    return x


def read_xsettings(x, dpy):
    """the desktop's XSETTINGS block as bytes (None when no settings manager runs): the manager owns the selection _XSETTINGS_S<screen>
    and keeps the block in the property _XSETTINGS_SETTINGS of the window that owns it"""
    owner = x.XGetSelectionOwner(dpy, x.XInternAtom(dpy, b"_XSETTINGS_S%d" % x.XDefaultScreen(dpy), 0))
    if not owner:
        return None
    prop = x.XInternAtom(dpy, b"_XSETTINGS_SETTINGS", 0)
    kind, fmt, count, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    if x.XGetWindowProperty(dpy, owner, prop, 0, 1 << 16, 0, 0, ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(after),
                            ctypes.byref(data)) != 0 or not data.value or fmt.value != 8:
        return None
    try:
        return ctypes.string_at(data.value, count.value)
    finally:
        x.XFree(data)


def desktop_dpi():
    """the desktop's own DPI setting, from XSETTINGS or the X resources (None: Windows, no X display, nothing set)"""
    if os.name == "nt" or not os.environ.get("DISPLAY"):
        return None
    try:
        x = _x11()
        dpy = x.XOpenDisplay(None)
        if not dpy:
            return None
        try:
            block = read_xsettings(x, dpy)
            dpi = xsettings_dpi(parse_xsettings(block)) if block else None
            if dpi is None:
                raw = x.XResourceManagerString(dpy)                            # (read when the connection opens: this one is new)
                dpi = parse(raw.decode("utf-8", "replace") if raw else "")
            return dpi
        finally:
            x.XCloseDisplay(dpy)
    except (OSError, AttributeError):
        return None


def xft_dpi():
    """the DPI to use: the desktop's setting, else the user's environment settings, else None (Tk's own guess stays)"""
    if os.name == "nt":
        return None
    return desktop_dpi() or environment_dpi()


def apply(window):
    """tells Tk the DPI when one was set -> the DPI used, or None when Tk's own guess stays"""
    dpi = xft_dpi()
    if dpi:
        window.tk.call("tk", "scaling", dpi / 72.0)
    return dpi
