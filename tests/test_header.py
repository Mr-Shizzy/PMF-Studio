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


if __name__ == "__main__":
    unittest.main()
