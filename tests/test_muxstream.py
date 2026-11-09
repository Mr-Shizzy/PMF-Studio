import os
import shutil
import subprocess
import tempfile
import unittest

from pmfkit import atrac3p, cli
from pmfkit.h264 import iter_access_units, split_access_units
from pmfkit.mux import mux, mux_file

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc" + (".exe" if os.name == "nt" else "")), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class StreamingMuxTests(unittest.TestCase):
    """mux_file must write exactly the bytes mux() makes, and iter_access_units must find exactly the units split_access_units finds."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmf_stream_")
        run = lambda *a: subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *a], check=True)          # noqa: E731
        cls.clips = {}
        for name, secs, size, gop in (("long", 40, "480x272", 59), ("short", 0.4, "480x272", 59), ("one_gop", 1.5, "480x272", 90), ("icon", 6, "144x80", 30)):
            mp4 = os.path.join(cls.dir, name + ".mp4")
            run("-f", "lavfi", "-i", "testsrc2=size=%s:rate=30000/1001:duration=%s" % (size, secs), "-f", "lavfi", "-i", "sine=f=330:duration=%s:sample_rate=44100" % secs, "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4)
            w, h = (int(x) for x in size.split("x"))
            es = os.path.join(cls.dir, name + ".264")
            cli.encode_video(FFMPEG, mp4, es, None, w, h, 1500 if w > 200 else 100, gop, total=secs)
            oma = os.path.join(cls.dir, name + ".oma")
            cli.encode_audio(FFMPEG, ATRAC, mp4, oma, None, lufs=None, kbps=96, total=secs)
            cls.clips[name] = (es, atrac3p.read_oma(oma), w, h)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_access_units_match_whatever_the_read_size(self):
        for name, (es, _, _, _) in self.clips.items():
            want = split_access_units(open(es, "rb").read())
            for chunk in (1 << 23, 4096, 777):
                got = list(iter_access_units(es, chunk=chunk))
                self.assertEqual(len(got), len(want), (name, chunk))
                self.assertTrue(all(a.data == b.data and a.is_idr == b.is_idr and a.has_sps == b.has_sps for a, b in zip(got, want)), (name, chunk))

    def test_same_bytes_as_the_in_memory_muxer(self):
        cases = []
        for name, (es, audio, w, h) in self.clips.items():
            for with_audio in (True, False):
                for version, style in (("0012", "B"), ("0012", "A"), ("0014", "B")):
                    cases.append((name, es, audio if with_audio else None, w, h, version, style))
        for name, es, audio, w, h, version, style in cases:
            want = mux(open(es, "rb").read(), audio, version=version, style=style, width=w, height=h)
            out = os.path.join(self.dir, "out.pmf")
            size = mux_file(es, out, audio, version=version, style=style, width=w, height=h)
            got = open(out, "rb").read()
            self.assertEqual(size, len(got))
            self.assertEqual(len(got), len(want), (name, audio is not None, version, style))
            self.assertTrue(got == want, (name, audio is not None, version, style))

    def test_a_failed_mux_leaves_no_partial_file(self):
        bad = os.path.join(self.dir, "bad.264")
        open(bad, "wb").write(b"\x00\x00\x00\x01\x65garbage")
        out = os.path.join(self.dir, "never.pmf")
        with self.assertRaises(ValueError):
            mux_file(bad, out, None)
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + ".part"))


if __name__ == "__main__":
    unittest.main()
