import os
import unittest

from pmfkit import atrac3p
from pmfkit.cli import frame_bytes_for_kbps
from pmfkit.demux import demux
from pmfkit.mux import mux

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "test_output", "bisect", "B_ref1_noWP_video.pmf")


class AudioGuard(unittest.TestCase):
    """Real PSP (2026-10-30): 352 kbps (2056-byte units) silent even when loud; 128 and 96 kbps play."""

    def test_frame_sizes_match_sony_files(self):
        self.assertEqual(frame_bytes_for_kbps(128), 744)
        self.assertEqual(frame_bytes_for_kbps(96), 560)

    def test_oversized_audio_is_rejected(self):
        if not os.path.exists(VIDEO):
            self.skipTest("test video not present")
        v = demux(open(VIDEO, "rb").read())[1]
        big = atrac3p.Atrac3pStream([b"\0" * 2048] * 60, atrac3p.param_for(2048))
        with self.assertRaises(ValueError):
            mux(v, big)
        ok = atrac3p.Atrac3pStream([b"\0" * 744] * 60, atrac3p.param_for(744))
        mux(v, ok)


if __name__ == "__main__":
    unittest.main()
