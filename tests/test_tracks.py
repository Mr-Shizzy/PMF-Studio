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
from pmfkit.mux import mux, entry_flags, gop_index, reference_pictures  # noqa: E402
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


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class KeepTracksTests(unittest.TestCase):
    """the shrinker's `keep`: the same movie with only the chosen languages playing"""

    @classmethod
    def setUpClass(cls):
        TrackTests.setUpClass()
        cls.t = TrackTests
        cls.src = os.path.join(cls.t.dir, "three.pmf")
        open(cls.src, "wb").write(cls.t.three)

    @classmethod
    def tearDownClass(cls):
        TrackTests.tearDownClass()

    def run_one(self, name, **kw):
        from pmfkit import shrink
        out = os.path.join(self.t.dir, name)
        r = shrink.shrink_one(self.src, out, FFMPEG, ATRAC, log=lambda *a: None, **kw)
        return r, open(out, "rb").read()

    def test_the_picture_stays_and_only_the_chosen_track_is_real(self):
        r, raw = self.run_one("k1.pmf", ratio=1.0, keep=[1])
        _, video, tr, _ = demux_all(raw)
        self.assertEqual(video, self.t.video)
        self.assertEqual(sorted(tr), [0, 1, 2])
        self.assertEqual(tr[1], b"".join(self.t.streams[1].units()))
        self.assertEqual([len(atrac3p.from_units(tr[i]).frames) for i in (0, 2)], [1, 1])
        self.assertLess(r.after, r.before)
        self.assertIn("track 2 kept", r.note)

    def test_picture_and_sound_can_shrink_at_the_same_time(self):
        r, raw = self.run_one("k2.pmf", ratio=0.5, sound_kbps=64, keep=[0])                 # (the other two tracks of this test movie are noise, not sound)
        _, video, tr, _ = demux_all(raw)
        self.assertEqual(sorted(tr), [0, 1, 2])
        self.assertTrue(60 < atrac3p.from_units(tr[0]).kbps < 70)
        self.assertEqual([len(atrac3p.from_units(tr[i]).frames) for i in (1, 2)], [1, 1])
        self.assertLess(len(video), len(self.t.video))

    def test_keeping_everything_or_nothing_that_exists_changes_nothing_about_the_tracks(self):
        for keep in ([0, 1, 2], [7]):
            r, raw = self.run_one("k3.pmf", ratio=1.0, keep=keep)
            self.assertEqual(raw, self.t.three)                                    # nothing to do: copied as it is

    def test_it_asks_for_the_encoder_when_empty_places_are_needed(self):
        from pmfkit import shrink
        with self.assertRaises(ValueError):
            shrink.shrink_one(self.src, os.path.join(self.t.dir, "k4.pmf"), FFMPEG, None, ratio=1.0, keep=[0])

    def test_the_keep_text_is_counted_from_one(self):
        self.assertEqual(tracks.parse_keep("1"), [0])
        self.assertEqual(tracks.parse_keep("3, 1"), [0, 2])
        self.assertIsNone(tracks.parse_keep(""))
        self.assertIsNone(tracks.parse_keep(None))
        for bad in ("0", "x", "-1"):
            with self.assertRaises(ValueError):
                tracks.parse_keep(bad)

    def test_the_size_guess_counts_the_dropped_tracks(self):
        from pmfkit import shrink
        info = shrink.survey(self.src)
        self.assertEqual(info.tracks, 3)
        self.assertLess(shrink.predict(info, 1.0, None, 1), shrink.predict(info, 1.0, None, None))
        self.assertEqual(shrink.predict(info, 1.0, None, 3), shrink.predict(info, 1.0, None, None))

    def test_the_window_command_carries_the_choice(self):
        from pmfstudio import jobs
        tools = {"ffmpeg": "ff.exe", "atracdenc": "at.exe"}
        argv = jobs._shrink_argv({"picture": "0.5", "sound": "keep", "keep": "1,3"}, tools, "a.pmf", "b.pmf")
        self.assertEqual(argv[argv.index("--keep-tracks") + 1], "1,3")
        self.assertIn("--atracdenc", argv)
        self.assertNotIn("--sound-kbps", argv)
        plain = jobs._shrink_argv({"picture": "0.5", "sound": "keep", "keep": ""}, tools, "a.pmf", "b.pmf")
        self.assertNotIn("--keep-tracks", plain)
        self.assertNotIn("--atracdenc", plain)

    def test_the_movies_with_several_tracks_are_found_and_can_be_listened_to(self):
        folder = os.path.join(self.t.dir, "lookfolder")
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(self.src, os.path.join(folder, "A_THREE.PMF"))
        open(os.path.join(folder, "B_ONE.PMF"), "wb").write(self.t.one)
        found = tracks.multitrack_movies(folder)
        self.assertEqual([n for n, _ in found], ["A_THREE.PMF"])
        pcm = tracks.sample_pcm(found[0][1](), 1, FFMPEG, seconds=2.0, start=0.5)
        self.assertGreater(len(pcm), 44100 * 4 * 1)                                # about two seconds of 16-bit stereo
        with self.assertRaises(ValueError):
            tracks.sample_pcm(self.t.three, 5, FFMPEG)

    def test_a_whole_game_keeps_one_language_through_the_shrinker(self):
        files = simple_files()
        files["\\PSP_GAME\\USRDIR\\FMV\\THREE.PMF"] = self.t.three
        root = os.path.join(self.t.dir, "kgame")
        os.makedirs(root, exist_ok=True)
        game, lst = make_game(root, files)
        iso = os.path.join(self.t.dir, "kgame.iso")
        build_umd_iso.build(game, lst, iso, log=lambda *a: None)
        out = os.path.join(self.t.dir, "kgame_out.cso")
        results = umdimage.shrink_image(iso, out, FFMPEG, ATRAC, ratio=1.0, keep=[2], log=lambda *a: None)
        self.assertEqual(results.pop().note, "game image")
        img = umdimage.Image(out)
        try:
            e = {x.path: x for x in umdimage.walk(img)}["\\PSP_GAME\\USRDIR\\FMV\\THREE.PMF"]
            _, _, tr, _ = demux_all(img.read(e.extent, -(-e.size // SECTOR))[:e.size])
            self.assertEqual(tr[2], b"".join(self.t.streams[2].units()))
            self.assertEqual(len(atrac3p.from_units(tr[0]).frames), 1)
        finally:
            img.close()


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class EntryFlagTests(unittest.TestCase):
    """the entry-point map's first two bytes: 0xC0, then twice the 4th number of the GOP's own index (found in the retail movies of three games)"""

    @classmethod
    def setUpClass(cls):
        TrackTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        TrackTests.tearDownClass()

    def test_every_entry_agrees_with_the_index_in_the_pack_it_points_to(self):
        from pmfkit import psmf
        from pmfkit.demux import header_size
        t = TrackTests
        raw = mux(t.video, t.streams[0], version="0014", style="B", header_kib=129, video_kib=129, strict=False, entry_hint=lambda pts, n: 0)
        hs = header_size(raw)
        entries = psmf.parse_header(raw[:hs]).entries
        self.assertGreater(len(entries), 1)
        for hint, pts, pack_no in entries:
            pack = raw[hs + pack_no * SECTOR: hs + (pack_no + 1) * SECTOR]
            i = pack.find(b"\x00\x00\x01\xbf")
            body = pack[i + 6:i + 6 + int.from_bytes(pack[i + 4:i + 6], "big")]
            slots = [int.from_bytes(body[2 + 2 * k:4 + 2 * k], "big") for k in range(4)]
            self.assertEqual(hint, entry_flags(slots))

    def test_the_entry_rule_of_sonys_clip_info_writer(self):
        self.assertEqual(entry_flags([4, 6, 7, 8]), 0xC000 | 2 * 8)                # four slots: number 4, value 8
        self.assertEqual(entry_flags([3, 3, 0xFFFF, 0xFFFF]), 0x4000 | 2 * 3)      # two slots: number 2 (stored 1)
        self.assertEqual(entry_flags([7, 0xFFFF, 0xFFFF, 0xFFFF]), 0x0000 | 2 * 7)
        self.assertEqual(entry_flags([5, 9, 12]), 0x8000 | 2 * 12)                # three slots, the 4th not filled
        self.assertEqual(entry_flags([0xFFFF] * 4), 0x0000 | ((2047 >> 7) << 8) | ((2047 & 0x7F) << 1))
        self.assertEqual(entry_flags([200, 0xFFFF, 0xFFFF, 0xFFFF]) >> 8, 0x00 | (200 >> 7))   # a value over 127 spills into the first byte

    def test_the_gop_index_marks_missing_slots_and_keeps_21_bit_sizes(self):
        flags = [0x80, 0x80, 0, 0x80, 0x80, 0x80]
        sizes = [70000, 1000, 500, 800, 900, 100]
        bf = gop_index(sizes, [0, 1, 3, 4], 0, flags)
        self.assertEqual(bf[:2], b"\x01\xe0")
        self.assertEqual([int.from_bytes(bf[2 + 2 * k:4 + 2 * k], "big") for k in range(4)], [0, 1, 3, 4])
        self.assertEqual(reference_pictures(flags), [0, 1, 3, 4])                    # the B-frame (flag 0) is not a slot
        short = gop_index([100, 200], [2], 0, None)
        self.assertEqual([int.from_bytes(short[2 + 2 * k:4 + 2 * k], "big") for k in range(4)], [2, 0xFFFF, 0xFFFF, 0xFFFF])
        rec = bf[18:22]
        self.assertEqual(int.from_bytes(rec[:2], "big") & 0xFF80, 0x80)
        self.assertEqual(((int.from_bytes(rec[:2], "big") & 0x1F) << 16) | int.from_bytes(rec[2:], "big"), 70000)


class GameFileNameTests(unittest.TestCase):
    def test_a_percent_sign_in_a_name_is_written_as_a_word_for_the_psp(self):
        safe = umdimage.psp_safe_name
        self.assertEqual(safe("007 Picker test (English only, picture 50%, sound 96).cso"), "007 Picker test (English only, picture 50 percent, sound 96).cso")
        self.assertEqual(safe("100%.cso"), "100 percent.cso")
        for good in ("Gun Test 21.cso", "007 TEST 1 - no B-frames, sound 96.cso", "Game - downsampled.cso", "Game (smaller).cso"):
            self.assertEqual(safe(good), good)                                      # a comma, a dash and brackets are fine


class PackFillTests(unittest.TestCase):
    def test_a_gap_of_up_to_7_bytes_is_header_stuffing_and_8_or_more_a_padding_packet(self):
        from pmfkit.mux import pes
        for gap in range(0, 40):
            payload = b"\x11" * 100
            room = 6 + 3 + 5 + len(payload) + gap
            out = pes(0xE0, 0x80, b"\x21\x00\x01\x00\x01", payload, room)
            self.assertEqual(len(out), room, gap)
            has_padding = b"\x00\x00\x01\xbe" in out
            self.assertEqual(has_padding, gap >= 8, gap)                            # Sony's MpsMux.dll: 1-7 bytes are stuffing
            if has_padding:
                self.assertEqual(int.from_bytes(out[-gap + 4:-gap + 6], "big"), gap - 6)    # the padding length field
                self.assertEqual(out[-(gap - 6):], b"\xff" * (gap - 6))
            elif gap:
                self.assertEqual(out[9:9 + 5 + gap][-gap:], b"\xff" * gap)           # the stuffing sits at the end of the PES header


if __name__ == "__main__":
    unittest.main()
