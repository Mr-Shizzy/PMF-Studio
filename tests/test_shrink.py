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

    def big_header_copy(self):
        """the same movie with a 4096-byte header (what Gun Showdown's CREDITS.PMF has): the header's own size field says so"""
        raw = open(self.pmf, "rb").read()
        head = bytearray(raw[:2048] + b"\0" * 2048)
        head[8:12] = (4096).to_bytes(4, "big")
        path = os.path.join(self.dir, "big_header.pmf")
        open(path, "wb").write(bytes(head) + raw[2048:])
        return path, raw

    def test_a_header_of_4096_bytes_is_read(self):
        from pmfkit.demux import demux_all, header_size
        path, raw = self.big_header_copy()
        big = open(path, "rb").read()
        self.assertEqual((header_size(raw), header_size(big)), (2048, 4096))
        _, v0, t0, p0 = demux_all(raw)
        _, v1, t1, p1 = demux_all(big)
        self.assertEqual((v1, t1, len(p1)), (v0, t0, len(p0)))

    def test_a_movie_with_a_big_header_can_be_shrunk(self):
        path, _ = self.big_header_copy()
        out = os.path.join(self.dir, "big_out.pmf")
        r = shrink.shrink(path, out, FFMPEG, ATRAC, ratio=0.5)[0]
        self.assertLess(r.after, r.before)
        _, v0, a0, _ = demux(open(path, "rb").read())
        _, v1, a1, _ = demux(open(out, "rb").read())
        self.assertEqual(a1, a0)

    def structure(self, pmf_bytes):
        """what the game's player could care about: SPS facts, the pictures that start a GOP, buffer numbers, the map"""
        from pmfkit import mirror
        from pmfkit.sps import stream_info
        src = mirror.read(pmf_bytes)
        sps, _ = stream_info(demux(pmf_bytes)[1])
        return src, sps

    def test_mirror_mode_keeps_the_structure_of_the_original(self):
        """a movie with GOPs of 30 pictures, no B-frames, 1 reference frame comes out the same way (earlier versions made B-frames, 2 refs, GOP 59)"""
        from pmfkit.demux import demux_all
        with tempfile.TemporaryDirectory() as d:
            mp4 = os.path.join(self.dir, "src.mp4")
            src = os.path.join(d, "gop30.pmf")
            cli.main(["make", mp4, "-o", src, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--video-kbps", "2500", "--audio-kbps", "128", "--quiet-audio", "--gop", "30"])
            out = os.path.join(d, "small.pmf")
            r = shrink.shrink(src, out, FFMPEG, ATRAC, ratio=0.5)[0]
            self.assertLess(r.after, r.before)
            a, sa = self.structure(open(src, "rb").read())
            b, sb = self.structure(open(out, "rb").read())
            self.assertEqual(a.idr_frames, [0, 30, 60, 90])
            self.assertEqual(b.idr_frames, a.idr_frames)                          # the same pictures start a GOP
            self.assertEqual((sb["poc_type"], sb["num_ref_frames"]), (sa["poc_type"], sa["num_ref_frames"]))      # no B-frames, one reference frame
            self.assertEqual((b.style, b.version, b.video_kib, b.header_kib), (a.style, a.version, a.video_kib, a.header_kib))
            self.assertEqual(b.has_map, a.has_map)

    def test_mirror_mode_copies_buffer_numbers_and_the_entry_point_map(self):
        from pmfkit import atrac3p, mirror
        from pmfkit.demux import demux_all
        from pmfkit.mux import mux, hint_from_size
        with tempfile.TemporaryDirectory() as d:
            _, v, a, _ = demux(open(self.pmf, "rb").read())
            # the original: a game-style movie with a 129 KiB buffer and an entry-point map
            game = mux(v, atrac3p.from_units(a), version="0014", style="B", header_kib=129, video_kib=129, entry_hint=lambda pts, n: hint_from_size(n))
            src = os.path.join(d, "game.pmf")
            open(src, "wb").write(game)
            before = mirror.read(game)
            self.assertTrue(before.has_map and before.video_kib == 129 and before.header_kib == 129)
            out = os.path.join(d, "small.pmf")
            r = shrink.shrink(src, out, FFMPEG, ATRAC, ratio=0.5)[0]
            self.assertLess(r.after, r.before)
            raw = open(out, "rb").read()
            after = mirror.read(raw)
            self.assertEqual((after.video_kib, after.header_kib, after.version, after.style), (129, 129, "0014", "B"))
            params, _, _, packs = demux_all(raw)
            self.assertEqual(len(params.entries), len(after.idr_frames))
            self.assertEqual([pts for _, pts, _ in params.entries], [pts for _, pts, _ in demux_all(game)[0].entries])        # the same IDRs are listed
            for hint, pts, pack in params.entries:                                 # each entry points at a pack that starts the GOP whose first picture has that time stamp
                items = packs[pack].items
                self.assertIn(0xBB, [it.sid for it in items])
                first = next(it for it in items if it.sid == 0xE0)
                self.assertEqual(first.pts, pts)
                self.assertEqual(hint >> 12, 0xC)

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
