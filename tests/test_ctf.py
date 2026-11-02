import os
import unittest

from pmfkit import ctf

GOW = "God Of War 660 theme example/GOW Dynamic Theme [660].ctf"


class CtfTests(unittest.TestCase):
    def test_marker(self):
        self.assertEqual(ctf.marker("660"), 0xDEAD0660)
        self.assertEqual(ctf.marker("661"), 0xDEAD0661)

    @unittest.skipUnless(os.path.exists(GOW), "GoW example not present")
    def test_parse_example_and_rebuild_gameboot_only(self):
        c = open(GOW, "rb").read()
        p = ctf.parse(c)
        self.assertEqual(p["count"], 22)
        self.assertEqual(p["marker"], 0xDEAD0660)
        self.assertEqual(p["ptf_size"], len(p["ptf"]))
        self.assertTrue(p["files"]["/vsh/resource/gameboot.pmf"].startswith(b"PSMF"))
        pmf = p["files"]["/vsh/resource/gameboot.pmf"]
        new = ctf.build(p["ptf"], {"/vsh/resource/gameboot.pmf": pmf}, "661")
        q = ctf.parse(new)
        self.assertEqual((q["marker"], q["count"], q["key2"]), (0xDEAD0661, 1, p["key2"]))
        self.assertEqual(q["files"], {"/vsh/resource/gameboot.pmf": pmf})
        self.assertEqual(len(new), len(p["ptf"]) + len(pmf) + 72)
        # everything in the PTF part except the four rewritten dwords is untouched
        self.assertEqual(new[:0x10] + new[0x20:len(p["ptf"])], c[:0x10] + c[0x20:len(p["ptf"])])


class PtfTests(unittest.TestCase):
    def test_blocks_are_four_byte_aligned(self):
        import struct
        from pmfkit import ptf
        raw = b"MIG.00.1PSP" + bytes(range(256)) * 3 + b"x"
        for extra in range(4):
            blk = ptf._pack(0, raw + b"y" * extra)
            csize = struct.unpack_from("<I", blk, 8)[0]
            self.assertEqual(csize % 4, 0)
            self.assertEqual(len(blk), 0x20 + csize)
            self.assertEqual(blk[0x20:0x22], bytes([0x78, 0x9C]))


if __name__ == "__main__":
    unittest.main()
