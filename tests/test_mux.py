import glob, os, unittest
from pmfkit import atrac3p
from pmfkit.demux import demux
from pmfkit.mux import mux

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "Mr. Shizzy - GameBoots Pack 1")
SAMPLES = ["ATARI/gameboot.pmf", "Zelda/gameboot.pmf", "Texas Chainsaw-Bloody Mask (DH safe)/gameboot.pmf",
           "Loading Skeleton/gameboot.pmf"]


def style_of(packs):
    flag = [i.payload for p in packs for i in p.items if i.sid == 0xBB][0][3]
    return "B" if flag == 0x80 else "A"


class RemuxOracle(unittest.TestCase):
    """Re-mux the elementary streams of Sony-made PMFs and compare with the originals."""

    def test_streams_and_layout(self):
        found = [os.path.join(PACK, s) for s in SAMPLES if os.path.exists(os.path.join(PACK, s))]
        if not found:
            self.skipTest("oracle PMFs not present")
        for f in found:
            orig = open(f, "rb").read()
            params, v, a, packs = demux(orig)
            new = mux(v, atrac3p.from_units(a), version=params.version, style=style_of(packs),
                      header_kib=params.video_buffer_kib)
            p2, v2, a2, packs2 = demux(new)
            self.assertEqual(v2, v, f)                      # video ES survives unchanged
            self.assertEqual(a2, a, f)                      # audio ES survives unchanged
            self.assertEqual(len(packs2), len(packs), f)
            same = sum(1 for i in range(len(packs))
                       if orig[2048 + i * 2048 + 14:2048 + (i + 1) * 2048] == new[2048 + i * 2048 + 14:2048 + (i + 1) * 2048])
            self.assertGreaterEqual(same / len(packs), 0.95, f)   # only +-1 tick audio PTS rounding differs


class SelfConsistency(unittest.TestCase):
    def test_every_pack_is_2048_and_parses(self):
        f = os.path.join(PACK, SAMPLES[0])
        if not os.path.exists(f):
            self.skipTest("oracle PMFs not present")
        params, v, a, packs = demux(open(f, "rb").read())
        new = mux(v, atrac3p.from_units(a), style="B")
        self.assertEqual((len(new) - 2048) % 2048, 0)
        demux(new)                                          # parses without raising


if __name__ == "__main__":
    unittest.main()
