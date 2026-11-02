import glob
import os
import unittest

from pmfkit.demux import demux
from pmfkit.sps import psp_problems

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BISECT = os.path.join(ROOT, "test_output", "bisect")
PACK = os.path.join(ROOT, "Mr. Shizzy - GameBoots Pack 1")


def video_of(path):
    return demux(open(path, "rb").read())[1]


class PspGuard(unittest.TestCase):
    """Real-PSP results (2026-10-30): A, B, C, E played; D (3 reference frames) did not."""

    def test_hardware_bisect_results(self):
        if not os.path.isdir(BISECT):
            self.skipTest("bisect files not present")
        for name in glob.glob(os.path.join(BISECT, "*.pmf")):
            problems = psp_problems(video_of(name))
            if os.path.basename(name).startswith("D_"):
                self.assertTrue(any("reference frames" in p for p in problems), name)
            else:
                self.assertEqual(problems, [], name)

    def test_sony_gameboots_pass(self):
        files = glob.glob(os.path.join(PACK, "**", "*.[pP][mM][fF]"), recursive=True)
        if not files:
            self.skipTest("gameboot pack not present")
        for f in files:
            self.assertEqual(psp_problems(video_of(f)), [], f)


if __name__ == "__main__":
    unittest.main()
