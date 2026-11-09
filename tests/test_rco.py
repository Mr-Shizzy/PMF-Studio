import glob
import os
import struct
import unittest

from pmfkit import rco

BASES = sorted(glob.glob("CTFtool_GUI_v5_beta_3/CTFtoolGUI/base/*/opening_plugin.rco"))


def _fake(last=1500.0):
    d = bytearray(b"\x00PRF" + bytes(2000))
    d[100:100 + 19] = b"anim_gameboot_movie"
    d[500:504] = struct.pack("<f", 300.0)
    d[500 + 116:500 + 120] = struct.pack("<f", 700.0)
    d[500 + 160:500 + 164] = struct.pack("<f", last)
    return bytes(d)


class RcoTests(unittest.TestCase):
    def test_patch_synthetic(self):
        r = _fake()
        self.assertEqual(rco.find_delay(r), 660)
        self.assertEqual(rco.gameboot_ms(r), 2500.0)
        p = rco.patch(r, 12000)
        self.assertEqual(len(p), len(r))
        self.assertEqual(rco.gameboot_ms(p), 12000.0)
        self.assertEqual(rco.gameboot_ms(rco.patch(r, 1000)), 2500.0)       # never shorter than stock

    def test_rejects_encrypted_and_foreign_files(self):
        with self.assertRaises(ValueError):
            rco.load(b"~PSP" + bytes(100))
        with self.assertRaises(ValueError):
            rco.find_delay(b"\x00PRF" + bytes(100))

    @unittest.skipUnless(BASES, "CTFtool base files not present")
    def test_all_firmware_bases(self):
        for path in BASES:
            r = rco.load(open(path, "rb").read())
            self.assertEqual(rco.gameboot_ms(r), 2500.0, path)
            self.assertEqual(rco.gameboot_ms(rco.patch(r, 30000)), 30000.0, path)


    def test_wrong_file_gets_the_plain_message(self):
        with self.assertRaises(ValueError) as c:
            rco.find_delay(b"\x00PRF" + bytes(100))
        self.assertEqual(str(c.exception), "Invalid File. Please choose a decrypted opening_plugin.rco from your specific firmware version")

    def test_names_and_digits(self):
        self.assertEqual(rco.label("661"), "6.61")
        self.assertEqual(rco.digits("6.61"), "661")
        self.assertEqual(rco.names(("660", "661")), "6.60 or 6.61")
        self.assertEqual(rco.names(("620", "635", "639")), "6.20, 6.35 or 6.39")

    @unittest.skipUnless(BASES, "CTFtool base files not present")
    def test_known_files_are_recognised_by_their_firmware(self):
        for path in BASES:
            fw = os.path.basename(os.path.dirname(path))
            r = rco.load(open(path, "rb").read())
            group = rco.identify(r)
            self.assertIsNotNone(group, path)
            self.assertIn(fw, group, path)
        self.assertIsNone(rco.identify(rco.patch(r, 30000)))                  # a file that isn't a known one is not named


if __name__ == "__main__":
    unittest.main()
