"""Game disc images: the ISO builder (tools/build_umd_iso.py), CSO files, reading a disc's file system, and shrinking the movies of a whole game
in place (pmfkit/umdimage.py). A small invented game stands in for a real one."""
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import build_umd_iso  # noqa: E402

from pmfkit import atrac3p, cli, umdimage  # noqa: E402
from pmfkit.cso import Cso, compress  # noqa: E402
from pmfkit.demux import demux_all  # noqa: E402
from pmfkit.mux import mux  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)
SECTOR = 2048


def make_game(root, files, shared=()):
    """files: {path inside the game (with backslashes): bytes}. shared: pairs (name, other) listed at the same sector. -> path of the file list.
    Every file starts at the next free sector from 50 on, as on a real disc."""
    game = os.path.join(root, "game")
    lines, lba, where = [], 50, {}
    for path, data in files.items():
        full = game + path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(data)
        where[path] = lba
        lines.append((lba, path))
        lba += max(1, -(-len(data) // SECTOR)) if data else 0
    for name, other in shared:
        full = game + name
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(files[other])
        lines.append((where[other], name))
    lines.sort()
    lst = os.path.join(root, "list.txt")
    open(lst, "w").write("\n".join("%07d , %s" % (a, p) for a, p in lines) + "\n")
    return game, lst


def simple_files():
    rnd = random.Random(7)
    return {"\\UMD_DATA.BIN": b"ULES-00000|0123456789ABCDEF|0001|G".ljust(48, b"\0"),
            "\\PSP_GAME\\PARAM.SFO": bytes(rnd.randrange(256) for _ in range(300)),
            "\\PSP_GAME\\SYSDIR\\EBOOT.BIN": bytes(rnd.randrange(256) for _ in range(5000)),
            "\\PSP_GAME\\USRDIR\\DATA.BIN": bytes(rnd.randrange(256) for _ in range(30000)),
            "\\PSP_GAME\\USRDIR\\EMPTY.TXT": b"",
            "\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF": b"PSMF" + bytes(rnd.randrange(256) for _ in range(9000))}


class BuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmfiso_test_")
        cls.files = simple_files()
        cls.game, cls.list = make_game(cls.dir, cls.files, shared=[("\\PSP_GAME\\USRDIR\\FMV\\TWO.PMF", "\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF")])
        cls.iso = os.path.join(cls.dir, "game.iso")
        build_umd_iso.build(cls.game, cls.list, cls.iso, log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def sector(self, n, count=1):
        with open(self.iso, "rb") as f:
            f.seek(n * SECTOR)
            return f.read(count * SECTOR)

    def test_layout_follows_a_real_umd(self):
        pvd = self.sector(16)
        self.assertEqual((pvd[0], pvd[1:6]), (1, b"CD001"))
        self.assertEqual(self.sector(17)[:6], b"\xffCD001")
        self.assertEqual(set(self.sector(14) + self.sector(15)), {0x20})              # two sectors of spaces before the volume descriptor
        self.assertEqual(self.sector(18), self.sector(19))                           # two copies of each path table
        self.assertEqual(self.sector(20), self.sector(21))
        self.assertNotEqual(self.sector(18), self.sector(20))                        # little endian and big endian
        self.assertEqual(struct.unpack("<I", pvd[158:162])[0], 22)                   # the root directory
        self.assertEqual(pvd[881], 2)
        self.assertEqual(self.sector(50)[:10], b"ULES-00000")

    def test_names_have_no_version_and_records_carry_the_xa_area(self):
        data = self.sector(22)
        o, seen = 0, []
        while data[o]:
            n = data[o]
            rec = data[o:o + n]
            ident = rec[33:33 + rec[32]]
            pad = 33 + rec[32] + (0 if rec[32] % 2 else 1)
            self.assertNotIn(b";", ident)
            self.assertEqual(rec[pad:], (build_umd_iso.XA_DIR if rec[25] & 2 else build_umd_iso.XA_FILE))
            seen.append(ident)
            o += n
        self.assertEqual(seen, [b"\x00", b"\x01", b"PSP_GAME", b"UMD_DATA.BIN"])

    def test_every_file_sits_where_the_list_says_with_its_own_bytes(self):
        img = umdimage.Image(self.iso)
        try:
            found = {e.path: e for e in umdimage.walk(img)}
            listed = {p: int(l) for l, p in (line.split(" , ") for line in open(self.list).read().split("\n") if line)}
            self.assertEqual(set(found), set(listed))
            for path, e in found.items():
                self.assertEqual(e.extent, listed[path], path)
                data = self.files[path] if path in self.files else self.files["\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF"]          # TWO.PMF is a second name for ONE.PMF
                self.assertEqual(img.read(e.extent, -(-e.size // SECTOR))[:e.size], data, path)
        finally:
            img.close()

    def test_names_that_share_a_sector_share_the_movie(self):
        img = umdimage.Image(self.iso)
        try:
            movies = umdimage.find_movies(umdimage.walk(img))
            self.assertEqual(len(movies), 1)
            self.assertEqual([os.path.basename(e.path) for e in movies[0].entries], ["ONE.PMF", "TWO.PMF"])
        finally:
            img.close()

    def test_a_replacement_bigger_than_the_original_is_refused(self):
        rep = os.path.join(self.dir, "rep")
        os.makedirs(rep, exist_ok=True)
        open(os.path.join(rep, "ONE.PMF"), "wb").write(b"PSMF" + b"x" * 20000)
        with self.assertRaises(SystemExit):
            build_umd_iso.build(self.game, self.list, os.path.join(self.dir, "bad.iso"), replace=[rep], log=lambda *a: None)

    def test_files_that_share_a_sector_must_hold_the_same_bytes(self):
        game, lst = make_game(tempfile.mkdtemp(dir=self.dir), simple_files(), shared=[("\\PSP_GAME\\USRDIR\\FMV\\TWO.PMF", "\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF")])
        open(game + "\\PSP_GAME\\USRDIR\\FMV\\TWO.PMF", "wb").write(b"PSMF" + b"different" * 1000)
        with self.assertRaises(SystemExit):
            build_umd_iso.build(game, lst, os.path.join(self.dir, "bad2.iso"), log=lambda *a: None)

    def test_the_template_disc_supplies_the_identity(self):
        pvd = bytearray(self.sector(16))
        pvd[40:72] = b"FRWL".ljust(32)
        pvd[318:446] = b"ELECTRONIC ARTS".ljust(128)
        tpl = os.path.join(self.dir, "template.iso")
        data = bytearray(self.sector(0, 17))
        data[16 * SECTOR:17 * SECTOR] = pvd
        data[14 * SECTOR:15 * SECTOR] = b"\x20" * SECTOR
        open(tpl, "wb").write(bytes(data))
        out = os.path.join(self.dir, "with_template.iso")
        build_umd_iso.build(self.game, self.list, out, template=tpl, log=lambda *a: None)
        new = open(out, "rb").read(17 * SECTOR)[16 * SECTOR:]
        self.assertEqual(new[40:72].rstrip(), b"FRWL")
        self.assertEqual(new[318:446].rstrip(), b"ELECTRONIC ARTS")


class CsoTests(unittest.TestCase):
    def test_round_trip_with_compressible_and_incompressible_blocks(self):
        rnd = random.Random(3)
        with tempfile.TemporaryDirectory() as d:
            iso = os.path.join(d, "x.iso")
            body = b"\0" * (5 * SECTOR) + bytes(rnd.randrange(256) for _ in range(3 * SECTOR)) + b"abc" * 2000 + b"\x01" * 100       # the last block is short
            open(iso, "wb").write(body)
            cso = os.path.join(d, "x.cso")
            size = compress(iso, cso)
            self.assertLess(size, len(body))
            head = open(cso, "rb").read(24)
            self.assertEqual(head[:4], b"CISO")
            self.assertEqual(struct.unpack("<IQIBB", head[4:22]), (24, len(body), SECTOR, 1, 0))
            c = Cso(cso)
            try:
                raw_blocks = sum(1 for i in range(c.blocks) if c.index[i] & 0x80000000)
                self.assertGreaterEqual(raw_blocks, 3)                                    # random data is stored as it is
                self.assertEqual(c.read(0, c.blocks)[:len(body)], body)
                self.assertEqual(c.index[-1], os.path.getsize(cso))                       # the last index entry is the end of the data
            finally:
                c.close()

    def test_a_cso_with_header_size_zero_and_an_index_shift_reads(self):
        """some writers leave the header size at 0 and align blocks with an index shift"""
        data = [bytes([i]) * SECTOR for i in range(3)]
        shift, blob, index = 2, bytearray(), []
        head_len = 24 + 4 * 4
        blob += b"\0" * head_len
        for blk in data:
            while len(blob) % (1 << shift):
                blob += b"\0"
            index.append(len(blob) >> shift)
            blob += blk
        while len(blob) % (1 << shift):
            blob += b"\0"
        index = [i | 0x80000000 for i in index] + [len(blob) >> shift]
        blob[0:24] = b"CISO" + struct.pack("<IQIBB", 0, 3 * SECTOR, SECTOR, 1, shift) + b"\0\0"
        blob[24:head_len] = struct.pack("<4I", *index)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.cso")
            open(p, "wb").write(bytes(blob))
            c = Cso(p)
            try:
                self.assertEqual(c.read(0, 3), b"".join(data))
            finally:
                c.close()

    def test_a_file_that_is_not_a_cso_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.cso")
            open(p, "wb").write(b"NOPE" * 100)
            with self.assertRaises(ValueError):
                Cso(p)


class ImageReadTests(unittest.TestCase):
    def test_a_cso_and_its_iso_have_the_same_file_system(self):
        with tempfile.TemporaryDirectory() as d:
            game, lst = make_game(d, simple_files())
            iso = os.path.join(d, "g.iso")
            build_umd_iso.build(game, lst, iso, log=lambda *a: None)
            cso = os.path.join(d, "g.cso")
            compress(iso, cso)
            a, b = umdimage.Image(iso), umdimage.Image(cso)
            try:
                ea = sorted((e.path, e.extent, e.size, e.rec_sector, e.rec_offset) for e in umdimage.walk(a))
                eb = sorted((e.path, e.extent, e.size, e.rec_sector, e.rec_offset) for e in umdimage.walk(b))
                self.assertEqual(ea, eb)
                self.assertEqual(a.sectors, b.sectors)
            finally:
                a.close()
                b.close()

    def test_something_that_is_not_a_disc_is_refused_plainly(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "no.iso")
            open(p, "wb").write(b"\0" * (40 * SECTOR))
            img = umdimage.Image(p)
            try:
                with self.assertRaises(ValueError) as ctx:
                    umdimage.walk(img)
                self.assertIn("isn't a game disc", str(ctx.exception))
            finally:
                img.close()


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class ShrinkGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmfgame_test_")
        mp4 = os.path.join(cls.dir, "src.mp4")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=480x272:rate=30000/1001:duration=3",
                        "-f", "lavfi", "-i", "sine=f=440:duration=3:sample_rate=44100", "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4], check=True)
        pmf = os.path.join(cls.dir, "one.pmf")
        cli.main(["make", mp4, "-o", pmf, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--video-kbps", "2500", "--audio-kbps", "128", "--quiet-audio"])
        one = open(pmf, "rb").read()
        params, video, tracks, _ = demux_all(one)
        a = atrac3p.from_units(tracks[0])
        b = atrac3p.Atrac3pStream([bytes(x ^ 0x5A for x in f) for f in a.frames], a.param)
        two = mux(video, [a, b], version="0014", style="B", width=params.width, height=params.height, strict=False)
        files = simple_files()
        files["\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF"] = one
        files["\\PSP_GAME\\USRDIR\\FMV\\TWO_TRACKS.PMF"] = two
        files["\\PSP_GAME\\USRDIR\\LAST.BIN"] = bytes(random.Random(1).randrange(256) for _ in range(20000))             # a file after the movies
        cls.one, cls.two = one, two
        cls.game, cls.list = make_game(cls.dir, files, shared=[("\\PSP_GAME\\USRDIR\\FMV\\ONE_FR.PMF", "\\PSP_GAME\\USRDIR\\FMV\\ONE.PMF")])
        cls.iso = os.path.join(cls.dir, "game.iso")
        build_umd_iso.build(cls.game, cls.list, cls.iso, log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def entries(self, path):
        img = umdimage.Image(path)
        try:
            return {e.path: e for e in umdimage.walk(img)}, img.sectors
        finally:
            img.close()

    def check_shrunk(self, out):
        old, old_sectors = self.entries(self.iso)
        new, new_sectors = self.entries(out)
        self.assertEqual(set(old), set(new))
        self.assertEqual(old_sectors, new_sectors)                                  # same length: every file stays where it was
        for path, e in old.items():
            self.assertEqual(e.extent, new[path].extent, path)
        fmv = "\\PSP_GAME\\USRDIR\\FMV\\"
        self.assertLess(new[fmv + "ONE.PMF"].size, old[fmv + "ONE.PMF"].size)
        self.assertLess(new[fmv + "TWO_TRACKS.PMF"].size, old[fmv + "TWO_TRACKS.PMF"].size)
        self.assertEqual(new[fmv + "ONE_FR.PMF"].size, new[fmv + "ONE.PMF"].size)  # a second name for the same movie follows it
        self.assertEqual(new[fmv + "ONE_FR.PMF"].extent, new[fmv + "ONE.PMF"].extent)
        other = [p for p in old if "FMV" not in p]
        for p in other:                                                              # every other file has its bytes and its size
            self.assertEqual(old[p].size, new[p].size, p)
        return new

    def test_a_whole_game_to_a_cso_and_to_an_iso(self):
        for ext in (".cso", ".iso"):
            out = os.path.join(self.dir, "small" + ext)
            results = umdimage.shrink_image(self.iso, out, FFMPEG, ATRAC, ratio=0.5, sound_kbps=64, bframes=0, log=lambda *a: None)
            image = results.pop()
            self.assertEqual(image.note, "game image")
            self.assertLess(image.after, image.before if ext == ".cso" else image.before + 1)
            self.assertEqual(len(results), 2)                                        # two movies on the disc (three names)
            new = self.check_shrunk(out)
            img = umdimage.Image(out)
            try:
                e = new["\\PSP_GAME\\USRDIR\\FMV\\TWO_TRACKS.PMF"]
                _, video, tracks, _ = demux_all(img.read(e.extent, -(-e.size // SECTOR))[:e.size])
                self.assertEqual(sorted(tracks), [0, 1])                             # both languages are still there
                self.assertNotEqual(tracks[0], tracks[1])
                last = new["\\PSP_GAME\\USRDIR\\LAST.BIN"]
                self.assertEqual(img.read(last.extent, -(-last.size // SECTOR))[:last.size], bytes(random.Random(1).randrange(256) for _ in range(20000)))
            finally:
                img.close()

    def test_the_source_image_is_never_overwritten(self):
        with self.assertRaises(cli.BuildError):
            umdimage.shrink_image(self.iso, self.iso, FFMPEG, ATRAC, log=lambda *a: None)

    def test_a_game_without_movies_says_so(self):
        game, lst = make_game(tempfile.mkdtemp(dir=self.dir), {k: v for k, v in simple_files().items() if not k.endswith(".PMF")})
        iso = os.path.join(self.dir, "nomovies.iso")
        build_umd_iso.build(game, lst, iso, log=lambda *a: None)
        with self.assertRaises(cli.BuildError) as ctx:
            umdimage.shrink_image(iso, os.path.join(self.dir, "x.cso"), FFMPEG, ATRAC, log=lambda *a: None)
        self.assertIn("no .pmf movies", str(ctx.exception))

    def test_survey_of_a_game_counts_each_movie_once(self):
        from pmfkit import shrink
        info = shrink.survey(self.iso)
        self.assertEqual(info.count, 2)
        self.assertGreater(info.picture_kbps, 500)

    def test_a_cancelled_job_leaves_no_half_written_game(self):
        out = os.path.join(self.dir, "cancelled.cso")
        cli.CANCEL.set()
        try:
            with self.assertRaises(cli.Cancelled):
                umdimage.shrink_image(self.iso, out, FFMPEG, ATRAC, bframes=0, log=lambda *a: None)
        finally:
            cli.CANCEL.clear()
        self.assertFalse(os.path.exists(out) or os.path.exists(out + ".part"))


if __name__ == "__main__":
    unittest.main()
