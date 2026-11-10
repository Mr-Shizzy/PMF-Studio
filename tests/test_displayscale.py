import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import displayscale  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_the_dpi_is_read_from_the_resource_string(self):
        self.assertEqual(displayscale.parse("Xft.antialias:\t1\nXft.dpi:\t144\nXft.hinting:\t1\n"), 144.0)
        self.assertEqual(displayscale.parse("Xft.dpi: 110.5"), 110.5)

    def test_missing_or_nonsense_settings_leave_things_as_they_are(self):
        for text in ("", None, "Xft.antialias: 1\n", "Xft.dpi: abc\n", "Xft.dpi: 0\n", "Xft.dpi: 9000\n", "Other.Xft.dpi: 144\n", "xft.dpi: 144\n"):
            self.assertIsNone(displayscale.parse(text), text)


class ApplyTests(unittest.TestCase):
    def test_tk_is_told_the_desktops_dpi_in_points(self):
        window = mock.Mock()
        with mock.patch.object(displayscale, "xft_dpi", return_value=144.0):
            self.assertEqual(displayscale.apply(window), 144.0)
        window.tk.call.assert_called_once_with("tk", "scaling", 2.0)         # Tk counts in pixels per point: 144 / 72

    def test_nothing_is_changed_when_the_desktop_sets_no_dpi(self):
        window = mock.Mock()
        with mock.patch.object(displayscale, "xft_dpi", return_value=None):
            self.assertIsNone(displayscale.apply(window))
        window.tk.call.assert_not_called()

    def test_windows_and_a_missing_display_are_left_alone(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            self.assertIsNone(displayscale.xft_dpi())
        if os.name == "nt":
            self.assertIsNone(displayscale.xft_dpi())


if __name__ == "__main__":
    unittest.main()
