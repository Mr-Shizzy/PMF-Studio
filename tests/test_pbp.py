import os
import struct
import unittest

from pmfkit.pbp import Pbp, PbpError, NAMES, HEADER


def make_sfo(title=b"My Homebrew"):
    keys = b"BOOTABLE\x00TITLE\x00"
    data_off = 20 + 32 + len(keys)
    data_off += (-data_off) % 4
    tbl = struct.pack("<HHIII", 0, 0x0404, 4, 4, 0) + struct.pack("<HHIII", 9, 0x0204, len(title) + 1, 128, 4)
    body = struct.pack("<I", 1) + title + b"\x00" * (128 - len(title))
    hdr = b"\x00PSF" + struct.pack("<IIII", 0x101, 20 + 32, data_off, 2)
    sfo = hdr + tbl + keys
    return sfo + b"\x00" * (data_off - len(sfo)) + body


def make_pbp(sections=None, version=b"\x00\x00\x01\x00", head=b""):
    secs = sections or [make_sfo(), b"\x89PNG-icon0", b"", b"", b"\x89PNG-pic1", b"", b"~PSP-exe" * 50, b""]
    pos, offs = HEADER + len(head), []
    for s in secs:
        offs.append(pos)
        pos += len(s)
    return b"\x00PBP" + version + struct.pack("<8I", *offs) + head + b"".join(secs)


class PbpTests(unittest.TestCase):
    def test_round_trip_is_exact(self):
        for raw in (make_pbp(), make_pbp(head=b"\x01\x02\x03\x04"), make_pbp(version=b"\x01\x00\x01\x00")):
            self.assertEqual(Pbp.parse(raw).to_bytes(), raw)

    def test_replace_icon1_keeps_everything_else(self):
        raw = make_pbp()
        p = Pbp.parse(raw)
        before = list(p.sections)
        p.replace("ICON1", b"PSMF0012" + b"\x00" * 2040)
        out = Pbp.parse(p.to_bytes())
        self.assertEqual(out.get("ICON1.PMF")[:4], b"PSMF")
        for i, n in enumerate(NAMES):
            if n != "ICON1.PMF":
                self.assertEqual(out.sections[i], before[i], n)
        self.assertEqual(out.version, p.version)

    def test_remove_section(self):
        p = Pbp.parse(make_pbp([make_sfo(), b"i0", b"PSMF", b"", b"", b"snd", b"exe", b""]))
        p.replace("SND0", b"")
        out = Pbp.parse(p.to_bytes())
        self.assertEqual(out.get("SND0.AT3"), b"")
        self.assertEqual(out.get("DATA.PSP"), b"exe")

    def test_title(self):
        p = Pbp.parse(make_pbp())
        self.assertEqual(p.title(), "My Homebrew")
        p.set_title("I3 video only")
        out = Pbp.parse(p.to_bytes())
        self.assertEqual(out.title(), "I3 video only")
        self.assertEqual(len(out.get("PARAM.SFO")), len(p.get("PARAM.SFO")))
        p.set_title("x" * 500)
        self.assertEqual(len(Pbp.parse(p.to_bytes()).title()), 127)
        p.set_title("é" * 100)                       # 2-byte characters must not be cut in half
        self.assertTrue(Pbp.parse(p.to_bytes()).title().startswith("é"))

    def test_rejects_garbage(self):
        with self.assertRaises(PbpError):
            Pbp.parse(b"PSMF" + b"\x00" * 100)
        bad = bytearray(make_pbp())
        bad[8:12] = struct.pack("<I", 0xFFFFFF)
        with self.assertRaises(PbpError):
            Pbp.parse(bytes(bad))

    def test_real_ebootS_round_trip_if_present(self):
        folder = os.path.join(os.path.dirname(__file__), "..", "EBOOT samples")
        if not os.path.isdir(folder):
            self.skipTest("no EBOOT samples folder")
        n = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if f.upper().endswith(".PBP"):
                    raw = open(os.path.join(root, f), "rb").read()
                    self.assertEqual(Pbp.parse(raw).to_bytes(), raw, f)
                    n += 1
        if not n:
            self.skipTest("no .PBP files in EBOOT samples")


if __name__ == "__main__":
    unittest.main()
