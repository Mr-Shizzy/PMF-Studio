import struct
import unittest

from pmfkit import cli, ctf, ptf
from pmfkit.gameboot import BUDGET_BYTES


class NewPtfTests(unittest.TestCase):
    def setUp(self):
        self.icon = bytes((i * 7) % 256 for i in range(16 * 16 * 4))
        self.img = bytes((i * 3) % 256 for i in range(300 * 170 * 4))
        self.ptf = ptf.new(self.icon, self.img, "My boot", "me")

    def test_blocks_are_padded_and_decode(self):
        bl = ptf.blocks(self.ptf)
        self.assertEqual([len(raw) for _, raw in bl], [1488, 211328, 4])
        for h, _ in bl:
            self.assertEqual(struct.unpack_from("<I", h, 8)[0] % 4, 0)       # missing padding = "corrupted theme"
        self.assertEqual(struct.unpack_from("<I", self.ptf, 0x124)[0], len(self.ptf) - ptf.HEADER)
        self.assertEqual(self.ptf[0x140 + 0x20:][:1], b"\x78")

    def test_pictures_round_trip(self):
        bl = ptf.blocks(self.ptf)
        self.assertEqual(ptf.unswizzle_rgba(bl[1][1][128:], 300, 170), self.img)
        self.assertEqual(bl[0][1][464:464 + 1024], self.icon)
        self.assertEqual(bl[0][1][128:384], bytes(range(256)))

    def test_title_in_header_and_ctf_wrap(self):
        self.assertEqual(self.ptf[0x20:0x27], b"My boot")
        c = ctf.parse(ctf.build(self.ptf, {"/vsh/resource/gameboot.pmf": b"PSMFx"}, "661"))
        self.assertEqual((c["marker"], c["count"], c["ptf_size"]), (0xDEAD0661, 1, len(self.ptf)))
        self.assertEqual(c["files"]["/vsh/resource/gameboot.pmf"], b"PSMFx")

    def test_rejects_bad_sizes(self):
        with self.assertRaises(ValueError):
            ptf.new(b"x", self.img)
        with self.assertRaises(ValueError):
            ptf.new(self.icon, self.img, "t" * 200)


class AudioChoiceTests(unittest.TestCase):
    def test_short_clip_keeps_128(self):
        self.assertEqual(cli.pick_audio_kbps(12, 128, BUDGET_BYTES), 128)

    def test_long_clip_gets_lower_bitrate(self):
        self.assertEqual(cli.pick_audio_kbps(60, 128, BUDGET_BYTES), 128)
        self.assertLessEqual(cli.pick_audio_kbps(180, 128, BUDGET_BYTES), 48)
        self.assertEqual(cli.pick_audio_kbps(1000, 128, BUDGET_BYTES), 32)


if __name__ == "__main__":
    unittest.main()
