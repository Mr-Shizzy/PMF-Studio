import ctypes
import os
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import displayscale  # noqa: E402


def xsettings_block(settings, order="<", serial=1):
    """an XSETTINGS block the way a desktop's settings manager writes it: {name: int | str}"""
    body = b""
    for name, value in settings.items():
        raw = name.encode()
        entry = struct.pack(order + "BxH", 0 if isinstance(value, int) else 1, len(raw)) + raw
        entry += b"\0" * (-len(entry) % 4) + struct.pack(order + "I", serial)
        if isinstance(value, int):
            entry += struct.pack(order + "i", value)
        else:
            text = value.encode()
            entry += struct.pack(order + "I", len(text)) + text + b"\0" * (-len(text) % 4)
        body += entry
    return struct.pack(order + "BxxxII", 0 if order == "<" else 1, serial, len(settings)) + body


class ParseTests(unittest.TestCase):
    def test_the_dpi_is_read_from_the_resource_string(self):
        self.assertEqual(displayscale.parse("Xft.antialias:\t1\nXft.dpi:\t144\nXft.hinting:\t1\n"), 144.0)
        self.assertEqual(displayscale.parse("Xft.dpi: 110.5"), 110.5)

    def test_missing_or_nonsense_settings_leave_things_as_they_are(self):
        for text in ("", None, "Xft.antialias: 1\n", "Xft.dpi: abc\n", "Xft.dpi: 0\n", "Xft.dpi: 9000\n", "Other.Xft.dpi: 144\n", "xft.dpi: 144\n"):
            self.assertIsNone(displayscale.parse(text), text)


class XSettingsTests(unittest.TestCase):
    def test_a_block_from_a_desktop_is_read_in_either_byte_order(self):
        for order in ("<", ">"):
            block = xsettings_block({"Net/ThemeName": "Adwaita", "Xft/DPI": 144 * 1024, "Gdk/WindowScalingFactor": 2, "Xft/Antialias": 1}, order)
            settings = displayscale.parse_xsettings(block)
            self.assertEqual(settings["Net/ThemeName"], "Adwaita", order)
            self.assertEqual(settings["Gdk/WindowScalingFactor"], 2)
            self.assertEqual(displayscale.xsettings_dpi(settings), 144.0, order)

    def test_names_and_strings_of_every_length_keep_the_following_settings_in_step(self):
        names = {"A": "x", "AB": "xy", "ABC": "xyz", "ABCD": "xyzw", "Xft/DPI": 120 * 1024, "Z": 7}
        settings = displayscale.parse_xsettings(xsettings_block(names))
        self.assertEqual(settings["Z"], 7)
        self.assertEqual(displayscale.xsettings_dpi(settings), 120.0)

    def test_a_damaged_or_empty_block_gives_nothing_and_no_error(self):
        block = xsettings_block({"Xft/DPI": 144 * 1024})
        for bad in (b"", b"\0", block[:10], block[:-3], b"\xff" * 40):
            displayscale.parse_xsettings(bad)                                    # must not raise
        self.assertEqual(displayscale.parse_xsettings(b""), {})
        self.assertIsNone(displayscale.xsettings_dpi({}))
        self.assertIsNone(displayscale.xsettings_dpi({"Xft/DPI": -1}))
        self.assertIsNone(displayscale.xsettings_dpi({"Xft/DPI": 9000 * 1024}))
        self.assertIsNone(displayscale.xsettings_dpi({"Xft/DPI": "144"}))

    def test_a_dpi_that_is_not_a_whole_number_survives(self):
        self.assertAlmostEqual(displayscale.xsettings_dpi({"Xft/DPI": int(110.5 * 1024)}), 110.5, places=2)


class EnvironmentTests(unittest.TestCase):
    def test_gdk_scale_and_gdk_dpi_scale(self):
        self.assertEqual(displayscale.environment_dpi({"GDK_SCALE": "2"}), 192.0)
        self.assertEqual(displayscale.environment_dpi({"GDK_DPI_SCALE": "1.25"}), 120.0)
        self.assertEqual(displayscale.environment_dpi({"GDK_SCALE": "2", "GDK_DPI_SCALE": "1.5"}), 288.0)

    def test_nothing_set_or_nonsense_changes_nothing(self):
        for env in ({}, {"GDK_SCALE": ""}, {"GDK_SCALE": "1"}, {"GDK_SCALE": "abc"}, {"GDK_SCALE": "50"}, {"GDK_DPI_SCALE": "0"}):
            self.assertIsNone(displayscale.environment_dpi(env), env)


@unittest.skipIf(os.name == "nt", "X11 only")
class OrderTests(unittest.TestCase):
    def test_the_desktop_wins_over_the_environment_and_xsettings_over_the_resources(self):
        with mock.patch.object(displayscale, "desktop_dpi", return_value=144.0), mock.patch.object(displayscale, "environment_dpi", return_value=192.0):
            self.assertEqual(displayscale.xft_dpi(), 144.0)
        with mock.patch.object(displayscale, "desktop_dpi", return_value=None), mock.patch.object(displayscale, "environment_dpi", return_value=192.0):
            self.assertEqual(displayscale.xft_dpi(), 192.0)
        with mock.patch.object(displayscale, "desktop_dpi", return_value=None), mock.patch.object(displayscale, "environment_dpi", return_value=None):
            self.assertIsNone(displayscale.xft_dpi())

    def test_no_display_means_no_desktop_dpi(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DISPLAY", None)
            self.assertIsNone(displayscale.desktop_dpi())


class ApplyTests(unittest.TestCase):
    def test_tk_is_told_the_dpi_in_points(self):
        window = mock.Mock()
        with mock.patch.object(displayscale, "xft_dpi", return_value=144.0):
            self.assertEqual(displayscale.apply(window), 144.0)
        window.tk.call.assert_called_once_with("tk", "scaling", 2.0)         # Tk counts in pixels per point: 144 / 72

    def test_nothing_is_changed_when_no_dpi_is_set(self):
        window = mock.Mock()
        with mock.patch.object(displayscale, "xft_dpi", return_value=None):
            self.assertIsNone(displayscale.apply(window))
        window.tk.call.assert_not_called()

    def test_windows_is_left_alone(self):
        if os.name == "nt":
            self.assertIsNone(displayscale.xft_dpi())


def have_display():
    if os.name == "nt" or not os.environ.get("DISPLAY"):
        return False
    try:
        displayscale._x11()
        return bool(displayscale._x11().XOpenDisplay(None))
    except Exception:
        return False


@unittest.skipUnless(have_display(), "needs an X display")
class RealDesktopTests(unittest.TestCase):
    """a stand-in for a desktop's settings manager: owns the selection and keeps the block in the property, as GNOME, KDE and the others do"""

    def run_manager(self, block, then):
        x = displayscale._x11()
        x.XCreateSimpleWindow.restype = ctypes.c_ulong
        x.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 2 + [ctypes.c_uint] * 3 + [ctypes.c_ulong] * 2
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XSetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        dpy = x.XOpenDisplay(None)
        try:
            if x.XGetSelectionOwner(dpy, x.XInternAtom(dpy, b"_XSETTINGS_S0", 0)):
                self.skipTest("this display already has a settings manager")
            window = x.XCreateSimpleWindow(dpy, x.XDefaultRootWindow(dpy), 0, 0, 1, 1, 0, 0, 0)
            x.XChangeProperty(dpy, window, x.XInternAtom(dpy, b"_XSETTINGS_SETTINGS", 0), x.XInternAtom(dpy, b"_XSETTINGS_SETTINGS", 0), 8, 0, block, len(block))
            x.XSetSelectionOwner(dpy, x.XInternAtom(dpy, b"_XSETTINGS_S0", 0), window, 0)
            x.XSync(dpy, 0)
            return then()
        finally:
            x.XCloseDisplay(dpy)                                                 # the selection goes with the connection

    def test_the_dpi_a_settings_manager_publishes_is_what_the_program_gets(self):
        block = xsettings_block({"Net/ThemeName": "Adwaita", "Xft/DPI": 168 * 1024})
        self.assertEqual(self.run_manager(block, displayscale.desktop_dpi), 168.0)

    def test_a_settings_manager_without_a_dpi_leaves_the_resources_to_decide(self):
        block = xsettings_block({"Net/ThemeName": "Adwaita"})
        with mock.patch.object(displayscale, "parse", return_value=None):
            self.assertIsNone(self.run_manager(block, displayscale.desktop_dpi))

    def test_without_a_manager_the_resource_string_is_read(self):
        with mock.patch.object(displayscale, "parse", return_value=133.0) as parse:
            self.assertEqual(displayscale.desktop_dpi(), 133.0)
            parse.assert_called()


if __name__ == "__main__":
    unittest.main()
