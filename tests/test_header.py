import glob, os, unittest
from pmfkit.psmf import build_header, parse_header

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "Mr. Shizzy - GameBoots Pack 1")
ORIG = os.path.join(ROOT, "reference_from_golf_project", "original_pmfs_DO_NOT_COMMIT")


def files():
    fs = glob.glob(os.path.join(PACK, "**", "*.[pP][mM][fF]"), recursive=True)
    fs += glob.glob(os.path.join(ORIG, "mv0*.pmf"))
    # 3 files (SOE, EVIL DEAD, Lennox) carry composer extras (mark data after 0xA2, header mux rate 6250); we don't generate those
    return [f for f in fs if not any(open(f, "rb").read(2048)[0xA2:])]


class HeaderTest(unittest.TestCase):
    def test_roundtrip_all_oracles(self):
        fs = files()
        if not fs:
            self.skipTest("oracle PMFs not present")
        for f in fs:
            h = open(f, "rb").read(2048)
            self.assertEqual(build_header(parse_header(h)), h, f)


class MapTest(unittest.TestCase):
    def test_a_short_map_fits_the_usual_header_and_a_long_one_grows_it(self):
        from pmfkit.psmf import Params
        entries = tuple((0xC000 + 2 * i, 90000 + 177177 * i, 70 * i) for i in range(43))
        h = build_header(Params(stream_bytes=2048 * 3000, last_pts=6129033, audio=True, entries=entries))
        self.assertEqual((len(h), int.from_bytes(h[8:12], "big")), (2048, 2048))
        self.assertEqual((int.from_bytes(h[0x86:0x8A], "big"), int.from_bytes(h[0x8A:0x8E], "big")), (0xA2, 43))
        self.assertEqual(parse_header(h).entries, entries)
        long = tuple((0xC000, 90000 + 3003 * i, i) for i in range(210))           # Gun Showdown's CREDITS.PMF: 210 entries, a 4096-byte header
        h = build_header(Params(stream_bytes=2048 * 10, last_pts=1, audio=True, entries=long))
        self.assertEqual((len(h), int.from_bytes(h[8:12], "big")), (4096, 4096))
        self.assertEqual(parse_header(h).entries, long)
        plain = build_header(Params(stream_bytes=2048 * 10, last_pts=1, audio=True))
        self.assertEqual((len(plain), parse_header(plain).entries), (2048, ()))


if __name__ == "__main__":
    unittest.main()
