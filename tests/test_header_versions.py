"""PSMF header facts from eight more commercial games (notes 91): the version label is only a label (0014 and 0015 have the same layout),
a game movie can have several sound tracks (header stream count), and Shrink keeps the game's own version label."""
import os
import shutil
import subprocess
import tempfile
import unittest

from pmfkit import atrac3p, cli, psmf, shrink
from pmfkit.demux import demux_all
from pmfkit.mux import mux

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)


class HeaderTests(unittest.TestCase):
    def test_stream_count_is_read_from_the_header(self):
        h = bytearray(psmf.build_header(psmf.Params(stream_bytes=2048, last_pts=90000 + 3003, audio=True)))
        self.assertEqual(psmf.parse_header(bytes(h)).streams, 2)
        h[0x80:0x82] = (5).to_bytes(2, "big")                                   # 007 From Russia With Love: one picture + four sound tracks
        p = psmf.parse_header(bytes(h))
        self.assertEqual((p.streams, p.audio), (5, True))

    def test_every_version_label_builds_the_same_layout(self):
        base = psmf.build_header(psmf.Params(stream_bytes=4096, last_pts=180000, version="0014", video_buffer_kib=251, audio=True))
        for v in ("0012", "0013", "0015"):
            other = psmf.build_header(psmf.Params(stream_bytes=4096, last_pts=180000, version=v, video_buffer_kib=251, audio=True))
            self.assertEqual(other[:4] + other[8:], base[:4] + base[8:])
            self.assertEqual(other[4:8], v.encode())


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class ShrinkHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmfhdr_test_")
        mp4 = os.path.join(cls.dir, "src.mp4")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=480x272:rate=30000/1001:duration=3",
                        "-f", "lavfi", "-i", "sine=f=440:duration=3:sample_rate=44100", "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4], check=True)
        cls.pmf = os.path.join(cls.dir, "movie.pmf")
        cli.main(["make", mp4, "-o", cls.pmf, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--video-kbps", "2500", "--audio-kbps", "128", "--quiet-audio"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _patched(self, name, patch):
        data = bytearray(open(self.pmf, "rb").read())
        patch(data)
        path = os.path.join(self.dir, name)
        open(path, "wb").write(data)
        return path

    def test_the_games_own_version_label_is_kept(self):
        for label in ("0014", "0015"):
            src = self._patched("v%s.pmf" % label, lambda d, l=label: d.__setitem__(slice(4, 8), l.encode()))
            out = os.path.join(self.dir, "out%s.pmf" % label)
            r = shrink.shrink(src, out, FFMPEG, ATRAC, ratio=0.5)[0]
            self.assertLess(r.after, r.before, r.note)
            self.assertEqual(open(out, "rb").read(8)[4:8], label.encode())

    def test_copies_of_one_movie_are_shrunk_once_and_stay_identical(self):
        folder = os.path.join(self.dir, "game")
        os.makedirs(folder, exist_ok=True)
        for name in ("CREDITS_ENG.PMF", "CREDITS_FRE.PMF", "CREDITS_GER.PMF"):          # one movie listed under three names, as on a game disc
            shutil.copyfile(self.pmf, os.path.join(folder, name))
        out = os.path.join(self.dir, "game_out")
        results = shrink.shrink(folder, out, FFMPEG, ATRAC, ratio=0.5)
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(1 for r in results if r.note.startswith("same movie as")), 2)
        data = [open(os.path.join(out, n), "rb").read() for n in ("CREDITS_ENG.PMF", "CREDITS_FRE.PMF", "CREDITS_GER.PMF")]
        self.assertTrue(data[0] == data[1] == data[2] and len(data[0]) < os.path.getsize(self.pmf))

    def _two_tracks(self):
        params, video, tracks, _ = demux_all(open(self.pmf, "rb").read())
        a = atrac3p.from_units(tracks[0])
        b = atrac3p.Atrac3pStream([bytes(x ^ 0x5A for x in f) for f in a.frames], a.param)              # a different "language"
        path = os.path.join(self.dir, "two_tracks.pmf")
        open(path, "wb").write(mux(video, [a, b], version="0014", style="B", width=params.width, height=params.height, strict=False))
        return path, tracks[0]

    def test_a_movie_with_two_sound_tracks_keeps_both(self):
        src, first = self._two_tracks()
        p0, v0, t0, _ = demux_all(open(src, "rb").read())
        self.assertEqual((p0.streams, sorted(t0)), (3, [0, 1]))
        self.assertEqual(t0[0], first)
        out = os.path.join(self.dir, "two_out.pmf")
        r = shrink.shrink(src, out, FFMPEG, ATRAC, ratio=0.5, sound_kbps=64)[0]
        self.assertLess(r.after, r.before, r.note)
        p1, v1, t1, _ = demux_all(open(out, "rb").read())
        self.assertEqual((p1.streams, sorted(t1)), (3, [0, 1]))
        self.assertNotEqual(t1[0], t1[1])
        self.assertLess(len(t1[0]), len(t0[0]) * 0.7)
        self.assertEqual(len(t1[0]), len(t1[1]))

    def test_the_tracks_are_kept_when_only_the_picture_shrinks(self):
        src, _ = self._two_tracks()
        out = os.path.join(self.dir, "two_picture_out.pmf")
        shrink.shrink(src, out, FFMPEG, ATRAC, ratio=0.5)
        _, _, t0, _ = demux_all(open(src, "rb").read())
        _, _, t1, _ = demux_all(open(out, "rb").read())
        self.assertEqual(t1, t0)                                                # both tracks byte for byte


RETAIL = os.path.join(HERE, "More PSP Commercial PMFs", "007 From Russia With Love.PMF")


@unittest.skipUnless(os.path.isfile(RETAIL), "needs the retail sample (not in the repository)")
class RetailMultiTrackTests(unittest.TestCase):
    def test_remux_of_007_matches_the_retail_file(self):
        """four sound tracks, one picture: same size, same streams, the sound packs in the same places"""
        raw = open(RETAIL, "rb").read()
        params, video, tracks, _ = demux_all(raw)
        self.assertEqual((params.streams, sorted(tracks)), (5, [0, 1, 2, 3]))
        out = mux(video, [atrac3p.from_units(tracks[t]) for t in sorted(tracks)], version=params.version, style="B",
                  width=params.width, height=params.height, strict=False)
        p2, v2, t2, _ = demux_all(out)
        self.assertEqual((len(out), v2, t2), (len(raw), video, tracks))
        self.assertEqual(out[:0x82 + 16 * 5], raw[:0x82 + 16 * 5][:0x89] + out[0x89:0x8A] + raw[0x8A:0x8D] + out[0x8D:0x8E] + raw[0x8E:0x82 + 16 * 5])


if __name__ == "__main__":
    unittest.main()
