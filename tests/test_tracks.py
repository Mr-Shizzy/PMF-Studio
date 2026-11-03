"""A movie with several sound tracks (one per language): keep some of them, delete the others or leave silent stand-ins (pmfkit/tracks.py),
the muxer's own schedule for a track of another frame size or length, and the same for a whole game image."""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import build_umd_iso  # noqa: E402

from pmfkit import atrac3p, cli, tracks, umdimage  # noqa: E402
from pmfkit.demux import demux_all  # noqa: E402
from pmfkit.mux import mux  # noqa: E402
from tests.test_umdimage import make_game, simple_files  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)
SECTOR = 2048


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class TrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmftracks_test_")
        mp4 = os.path.join(cls.dir, "src.mp4")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=480x272:rate=30000/1001:duration=4",
                        "-f", "lavfi", "-i", "sine=f=440:duration=4:sample_rate=44100", "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4], check=True)
        pmf = os.path.join(cls.dir, "one.pmf")
        cli.main(["make", mp4, "-o", pmf, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--video-kbps", "2500", "--audio-kbps", "128", "--quiet-audio"])
        cls.one = open(pmf, "rb").read()
        params, cls.video, t, _ = demux_all(cls.one)
        a = atrac3p.from_units(t[0])
        cls.streams = [a] + [atrac3p.Atrac3pStream([bytes(x ^ k for x in f) for f in a.frames], a.param) for k in (0x5A, 0x33)]    # three "languages"
        cls.three = mux(cls.video, cls.streams, version="0014", style="B", width=params.width, height=params.height, strict=False)
        cls.work = os.path.join(cls.dir, "work")
        os.makedirs(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def parts(self, raw):
        _, video, t, _ = demux_all(raw)
        return video, t

    def test_the_tracks_are_listed(self):
        info = tracks.read_tracks(self.three)
        self.assertEqual([t.index for t in info], [0, 1, 2])
        self.assertTrue(all(round(t.kbps) == 128 and t.frames == len(self.streams[0].frames) for t in info))
        self.assertEqual(tracks.read_tracks(self.one)[0].index, 0)

    def test_deleting_the_others_keeps_the_picture_and_the_chosen_track(self):
        out = tracks.retrack(self.three, [1], "delete")
        video, t = self.parts(out)
        self.assertEqual(video, self.video)
        self.assertEqual(sorted(t), [0])                                          # numbered from 0 again
        self.assertEqual(t[0], b"".join(self.streams[1].units()))
        one_track = len(b"".join(self.streams[0].units()))
        self.assertGreater(len(self.three) - len(out), 1.8 * one_track)             # two tracks' worth of bytes are gone
        out2 = tracks.retrack(self.three, [0, 2], "delete")
        _, t2 = self.parts(out2)
        self.assertEqual([t2[0], t2[1]], [b"".join(self.streams[0].units()), b"".join(self.streams[2].units())])

    def test_keeping_everything_gives_the_same_streams(self):
        video, t = self.parts(tracks.retrack(self.three, [0, 1, 2], "delete"))
        self.assertEqual((video, t), (self.video, {i: b"".join(s.units()) for i, s in enumerate(self.streams)}))

    def test_silent_stand_ins_hold_silence_at_the_lowest_rate(self):
        out = tracks.retrack(self.three, [0], "silent", FFMPEG, ATRAC, self.work)
        video, t = self.parts(out)
        self.assertEqual((video, sorted(t)), (self.video, [0, 1, 2]))
        self.assertEqual(t[0], b"".join(self.streams[0].units()))                    # the kept track, untouched
        n = len(self.streams[0].frames)
        for i in (1, 2):
            st = atrac3p.from_units(t[i])
            self.assertEqual((len(st.frames), st.frame_bytes), (n, 192))             # 32 kbps, as long as the movie
            self.assertEqual(len(set(st.frames)), 1)
        one_track = len(b"".join(self.streams[0].units()))
        self.assertGreater(len(self.three) - len(out), 2 * 0.7 * one_track)         # each stand-in is about a quarter of a track
        self.assertGreater(len(out), len(tracks.retrack(self.three, [0], "delete")))

    def test_the_shortest_stand_in_is_one_frame(self):
        out = tracks.retrack(self.three, [1], "short", FFMPEG, ATRAC, self.work)
        video, t = self.parts(out)
        self.assertEqual((video, sorted(t)), (self.video, [0, 1, 2]))
        self.assertEqual(t[1], b"".join(self.streams[1].units()))
        for i in (0, 2):
            self.assertEqual(len(atrac3p.from_units(t[i]).frames), 1)
        self.assertLessEqual(len(out), len(tracks.retrack(self.three, [1], "delete")) + 4 * SECTOR)

    def test_every_audio_pack_of_every_track_is_in_time_order(self):
        for mode in ("silent", "short"):
            _, _, _, packs = demux_all(tracks.retrack(self.three, [0], mode, FFMPEG, ATRAC, self.work))
            last = {}
            scr = -1
            for pk in packs:
                self.assertGreaterEqual(pk.scr27, scr)
                scr = pk.scr27
                for it in pk.items:
                    if it.sid == 0xBD and it.pts is not None:
                        tr = it.payload[0]
                        self.assertGreaterEqual(it.pts, last.get(tr, 0))
                        last[tr] = it.pts
                        self.assertGreater(it.pts - pk.scr27 / 300, 0)                # never delivered late
            self.assertEqual(sorted(last), [0, 1, 2])

    def test_things_that_cannot_be_done_are_refused(self):
        with self.assertRaises(ValueError):
            tracks.retrack(self.three, [], "delete")
        with self.assertRaises(ValueError):
            tracks.retrack(self.three, [5], "delete")
        with self.assertRaises(ValueError):
            tracks.retrack(self.one, [0], "delete")                                  # only one track: nothing to choose
        with self.assertRaises(ValueError):
            tracks.retrack(self.three, [0], "vanish")


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class TrackGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = TrackTests
        cls.t.setUpClass()
        files = simple_files()
        files["\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF"] = cls.t.one
        files["\\PSP_GAME\\USRDIR\\FMV\\THREE.PMF"] = cls.t.three
        files["\\PSP_GAME\\ICON0.PNG"] = bytes(random.Random(3).randrange(256) for _ in range(3000))
        files["\\PSP_GAME\\USRDIR\\LAST.BIN"] = bytes(random.Random(1).randrange(256) for _ in range(20000))
        cls.game, cls.list = make_game(cls.t.dir, files)
        cls.iso = os.path.join(cls.t.dir, "game.iso")
        build_umd_iso.build(cls.game, cls.list, cls.iso, log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        cls.t.tearDownClass()

    def test_a_whole_game_keeps_one_language(self):
        for mode in ("delete", "silent", "short"):
            out = os.path.join(self.t.dir, "kept_%s.cso" % mode)
            png = b"\x89PNG small test picture"
            results = umdimage.retrack_image(self.iso, out, [1], mode, FFMPEG, ATRAC, log=lambda *a: None, files=[("\\PSP_GAME\\ICON0.PNG", png)])
            self.assertEqual(results.pop().note, "game image")
            self.assertEqual(len(results), 2)
            self.assertEqual(sum(1 for r in results if r.after < r.before), 1)         # only the three-language movie changed
            img = umdimage.Image(out)
            try:
                found = {e.path: e for e in umdimage.walk(img)}
                e = found["\\PSP_GAME\\USRDIR\\FMV\\THREE.PMF"]
                raw = img.read(e.extent, -(-e.size // SECTOR))[:e.size]
                _, video, tr, _ = demux_all(raw)
                self.assertEqual(video, self.t.video)
                self.assertEqual(tr[0 if mode == "delete" else 1], b"".join(self.t.streams[1].units()))
                one = found["\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF"]
                self.assertEqual(img.read(one.extent, -(-one.size // SECTOR))[:one.size], self.t.one)       # a one-track movie is left alone
                icon = found["\\PSP_GAME\\ICON0.PNG"]
                self.assertEqual((icon.size, img.read(icon.extent, 1)[:icon.size]), (len(png), png))
                last = found["\\PSP_GAME\\USRDIR\\LAST.BIN"]
                self.assertEqual(img.read(last.extent, -(-last.size // SECTOR))[:last.size], bytes(random.Random(1).randrange(256) for _ in range(20000)))
            finally:
                img.close()

    def test_a_picture_too_big_for_its_place_is_refused(self):
        out = os.path.join(self.t.dir, "refused.cso")
        with self.assertRaises(ValueError):
            umdimage.retrack_image(self.iso, out, [0], "delete", FFMPEG, ATRAC, log=lambda *a: None, files=[("\\PSP_GAME\\ICON0.PNG", b"x" * 9000)])
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
