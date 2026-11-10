import hashlib
import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import fonts  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


class ConfigTests(unittest.TestCase):
    def test_the_fontconfig_rules_are_well_formed_and_name_the_windows_fonts(self):
        root = ET.fromstring(fonts.config_xml())
        asked = [m.find("test/string").text for m in root.findall("match")]
        self.assertEqual(asked, ["Segoe UI", "Consolas"])
        sans = [s.text for s in root.findall("match")[0].find("edit").findall("string")]
        self.assertEqual(sans[0], "Selawik")                                    # the shipped font first, installed ones after it
        self.assertEqual(sans, list(fonts.SANS))
        for match in root.findall("match"):
            self.assertEqual(match.find("edit").get("mode"), "prepend")

    def test_setup_never_raises_and_says_what_it_did(self):
        self.assertIsInstance(fonts.setup(), str)

    @unittest.skipIf(os.name == "nt", "Linux only")
    def test_setup_with_the_real_fontconfig_and_the_shipped_fonts_when_present(self):
        text = fonts.setup()
        self.assertTrue("replacements set" in text or "fontconfig not found" in text, text)


class PinTests(unittest.TestCase):
    def test_the_font_pin_and_its_licence_text_agree(self):
        pin = json.load(open(os.path.join(ROOT, "packaging", "linux", "font_pin.json"), encoding="utf8"))["selawik"]
        for key in ("sha256", "licence_sha256"):
            self.assertRegex(pin[key], r"^[0-9a-f]{64}$")
        self.assertEqual(sorted(pin["files"]), ["selawk.ttf", "selawkb.ttf"])        # Regular and Bold: all the program asks for
        self.assertTrue(pin["url"].startswith("https://github.com/microsoft/Selawik/"))
        with open(os.path.join(ROOT, "packaging", "licenses", "Selawik-OFL-1.1.txt"), "rb") as f:
            text = f.read()
        self.assertEqual(hashlib.sha256(text).hexdigest(), pin["licence_sha256"])
        self.assertIn(b"SIL OPEN FONT LICENSE Version 1.1", text)

    def test_the_program_asks_for_no_font_weight_the_pin_does_not_cover(self):
        """Selawik is shipped in Regular and Bold; a request for another weight (semibold, light) would silently fall back to something else"""
        import re
        weights = set()
        for name in ("app.py", "widgets.py", "trackdialog.py", "player.py"):
            path = os.path.join(ROOT, "pmfstudio", name)
            if os.path.exists(path):
                weights |= set(re.findall(r"\(FONT, \d+, \"(\w+)\"", open(path, encoding="utf-8").read()))
        self.assertLessEqual(weights, {"bold", "normal"}, weights)


if __name__ == "__main__":
    unittest.main()
