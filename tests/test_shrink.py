import os
import shutil
import subprocess
import tempfile
import unittest

from pmfkit import cli, shrink
from pmfkit.demux import demux, duration_seconds

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)


class FindMoviesTests(unittest.TestCase):
    def test_folder_walk_keeps_sub_folders_and_skips_other_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"))
            for rel in ("b.pmf", "A.PMF", os.path.join("sub", "c.pmf"), "notes.txt"):
                open(os.path.join(d, rel), "wb").write(b"x")
            self.assertEqual([r for _, r in shrink.find_movies(d)], ["A.PMF", "b.pmf", os.path.join("sub", "c.pmf")])
            self.assertEqual(shrink.find_movies(os.path.join(d, "b.pmf")), [(os.path.join(d, "b.pmf"), "b.pmf")])

    def test_count_pictures_ignores_a_stub_without_picture_data(self):
        picture = (b"\x00\x00\x00\x01\x09\x10\x00\x00\x00\x01\x67\x4d\x40\x15\x00\x00\x00\x01\x68\xee\x3c\x80"
                   b"\x00\x00\x00\x01\x65\x88\x80")
        stub = b"\x00\x00\x00\x01\x09\x30\x00\x00\x00\x01\x06\x01\x08"
        self.assertEqual(shrink.count_pictures(picture + stub), 1)


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class ShrinkMovieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmfshrink_test_")
        mp4 = os.path.join(cls.dir, "src.mp4")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=480x272:rate=30000/1001:duration=4",
                        "-f", "lavfi", "-i", "sine=f=440:duration=4:sample_rate=44100", "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4], check=True)
        cls.pmf = os.path.join(cls.dir, "movie.pmf")
        cli.main(["make", mp4, "-o", cls.pmf, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--video-kbps", "2500", "--audio-kbps", "128", "--quiet-audio"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_half_size_same_length_same_sound(self):
        out = os.path.join(self.dir, "small.pmf")
        r = shrink.shrink(self.pmf, out, FFMPEG, ATRAC, ratio=0.5)[0]
        self.assertLess(r.after, r.before * 0.8)
        p0, v0, a0, _ = demux(open(self.pmf, "rb").read())
        p1, v1, a1, _ = demux(open(out, "rb").read())
        self.assertEqual((p1.width, p1.height), (p0.width, p0.height))
        self.assertEqual(a1, a0)                                              # the sound is untouched
        self.assertAlmostEqual(duration_seconds(v1, a1), duration_seconds(v0, a0), delta=0.1)

    def test_a_smaller_sound_when_asked(self):
        out = os.path.join(self.dir, "small_sound.pmf")
        r = shrink.shrink(self.pmf, out, FFMPEG, ATRAC, ratio=0.5, sound_kbps=64)[0]
        _, _, a0, _ = demux(open(self.pmf, "rb").read())
        _, _, a1, _ = demux(open(out, "rb").read())
        self.assertLess(len(a1), len(a0) * 0.7)
        self.assertLess(r.after, r.before)

    def test_keep_the_picture_and_change_only_the_sound(self):
        out = os.path.join(self.dir, "sound_only.pmf")
        r = shrink.shrink(self.pmf, out, FFMPEG, ATRAC, ratio=1.0, sound_kbps=32)[0]
        _, v0, a0, _ = demux(open(self.pmf, "rb").read())
        _, v1, a1, _ = demux(open(out, "rb").read())
        self.assertEqual(v1, v0)                                              # the picture data is untouched
        self.assertLess(len(a1), len(a0) * 0.4)
        self.assertLess(r.after, r.before)
        self.assertIn("picture kept", r.note)

    def test_survey_and_prediction(self):
        info = shrink.survey(self.pmf)
        self.assertEqual(info.count, 1)
        self.assertGreater(info.picture_kbps, 500)
        self.assertAlmostEqual(info.sound_kbps, 128, delta=15)
        self.assertLess(shrink.predict(info, 0.5), info.total * 0.7)
        self.assertLess(shrink.predict(info, 0.5, 32), shrink.predict(info, 0.5))
        self.assertEqual(shrink.predict(info, 1.0), info.total)

    def test_a_movie_that_cannot_get_smaller_is_copied_and_a_bad_file_is_reported(self):
        tiny = os.path.join(self.dir, "tiny_in")
        os.makedirs(tiny)
        shutil.copy(self.pmf, os.path.join(tiny, "movie.pmf"))
        open(os.path.join(tiny, "bad.pmf"), "wb").write(b"not a movie")
        out = os.path.join(self.dir, "tiny_out")
        results = shrink.shrink(tiny, out, FFMPEG, ATRAC, ratio=0.99)
        by_name = {os.path.basename(r.src): r for r in results}
        self.assertTrue(by_name["bad.pmf"].note.startswith("failed"))
        self.assertEqual(open(os.path.join(out, "movie.pmf"), "rb").read(), open(self.pmf, "rb").read())
        self.assertFalse(os.path.exists(os.path.join(out, "bad.pmf")))


if __name__ == "__main__":
    unittest.main()
