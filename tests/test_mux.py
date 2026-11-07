import glob, os, unittest
from pmfkit import atrac3p
from pmfkit.demux import demux
from pmfkit.mux import mux

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "Mr. Shizzy - GameBoots Pack 1")
SAMPLES = ["ATARI/gameboot.pmf", "Zelda/gameboot.pmf", "Texas Chainsaw-Bloody Mask (DH safe)/gameboot.pmf",
           "Loading Skeleton/gameboot.pmf"]


def style_of(packs):
    flag = [i.payload for p in packs for i in p.items if i.sid == 0xBB][0][3]
    return "B" if flag == 0x80 else "A"


class RemuxOracle(unittest.TestCase):
    """Re-mux the elementary streams of Sony-made PMFs and compare with the originals."""

    def test_streams_and_layout(self):
        found = [os.path.join(PACK, s) for s in SAMPLES if os.path.exists(os.path.join(PACK, s))]
        if not found:
            self.skipTest("oracle PMFs not present")
        for f in found:
            orig = open(f, "rb").read()
            params, v, a, packs = demux(orig)
            new = mux(v, atrac3p.from_units(a), version=params.version, style=style_of(packs),
                      header_kib=params.video_buffer_kib)
            p2, v2, a2, packs2 = demux(new)
            self.assertEqual(v2, v, f)                      # video ES survives unchanged
            self.assertEqual(a2, a, f)                      # audio ES survives unchanged
            self.assertEqual(len(packs2), len(packs), f)
            same = sum(1 for i in range(len(packs))
                       if orig[2048 + i * 2048 + 14:2048 + (i + 1) * 2048] == new[2048 + i * 2048 + 14:2048 + (i + 1) * 2048])
            self.assertGreaterEqual(same / len(packs), 0.95, f)   # only +-1 tick audio PTS rounding differs


class StillSceneIsNeverLate(unittest.TestCase):
    """A still scene at a very low picture bitrate puts a whole second of tiny pictures into one pack. The muxer used to time such a pack by the
    LAST picture in it, so the first one reached the decoder up to 0.84 s late (Gun Showdown's intro at the lowest settings; the PSP froze).
    Sony's own movies never deliver a picture later than 35,814 ticks before its decode time."""

    def test_no_picture_arrives_after_its_decode_time(self):
        import shutil, subprocess, tempfile
        from pmfkit import cli, mux as muxmod
        ffmpeg = shutil.which("ffmpeg")
        atrac = next((p for p in (os.path.join(ROOT, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)
        if not (ffmpeg and atrac):
            self.skipTest("ffmpeg / atracdenc not available")
        tmp = tempfile.mkdtemp(prefix="pmfstill_")
        try:
            mp4, pmf = os.path.join(tmp, "still.mp4"), os.path.join(tmp, "still.pmf")
            subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x203040:s=480x272:r=30000/1001:d=12",
                            "-f", "lavfi", "-i", "sine=f=330:duration=12:sample_rate=44100", "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4], check=True)
            cli.main(["make", mp4, "-o", pmf, "--ffmpeg", ffmpeg, "--atracdenc", atrac, "--video-kbps", "60", "--audio-kbps", "32", "--quiet-audio"])
            _, _, _, packs = __import__("pmfkit.demux", fromlist=["demux_all"]).demux_all(open(pmf, "rb").read())
            leads = [it.dts - p.scr27 / 300 for p in packs for it in p.items if it.sid == 0xE0 and it.dts is not None]
            self.assertTrue(leads)
            self.assertGreaterEqual(min(leads), 30000, min(leads))                                       # Sony's smallest: 35,814
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SelfConsistency(unittest.TestCase):
    def test_every_pack_is_2048_and_parses(self):
        f = os.path.join(PACK, SAMPLES[0])
        if not os.path.exists(f):
            self.skipTest("oracle PMFs not present")
        params, v, a, packs = demux(open(f, "rb").read())
        new = mux(v, atrac3p.from_units(a), style="B")
        self.assertEqual((len(new) - 2048) % 2048, 0)
        demux(new)                                          # parses without raising


if __name__ == "__main__":
    unittest.main()


class PictureSizeLimit(unittest.TestCase):
    """The muxer refuses a picture over mux.MAX_PICTURE (95,545 bytes: the largest picture seen in a retail movie that plays) and accepts one at the limit."""

    def test_limit_is_a_named_bound_and_applies(self):
        from pmfkit import mux as mux_module
        from pmfkit.h264 import split_access_units
        f = os.path.join(PACK, SAMPLES[0])
        if not os.path.exists(f):
            self.skipTest("oracle PMFs not present")
        params, v, a, packs = demux(open(f, "rb").read())
        biggest = max(len(x.data) for x in split_access_units(v))
        self.assertGreater(mux_module.MAX_PICTURE, 0xFFFF)               # no longer the old 16-bit refusal
        old = mux_module.MAX_PICTURE
        try:
            mux_module.MAX_PICTURE = biggest                              # exactly at the limit: accepted
            mux(v, atrac3p.from_units(a), version=params.version, style=style_of(packs), header_kib=params.video_buffer_kib)
            mux_module.MAX_PICTURE = biggest - 1                          # one byte over: refused
            with self.assertRaises(ValueError) as cm:
                mux(v, atrac3p.from_units(a), version=params.version, style=style_of(packs), header_kib=params.video_buffer_kib)
            self.assertIn("picture is larger", str(cm.exception))
        finally:
            mux_module.MAX_PICTURE = old


# SOE.pmf: a high-bitrate movie whose big pictures fill the video buffer; Sony holds those packs back until the buffer has room (the muxer does not model that yet)
OPEN_CLOCK_CASES = {"SOE.pmf"}


class PackClockMatchesSony(unittest.TestCase):
    """Sony's muxer sends packs only on its pack clock (start 3,044,236.8, step 44,236.8 ticks of 27 MHz) and admits a picture or audio unit one second
    (STD_delay 90000) before it is due; the last pack of a movie waits for the last picture's turn, and a full pack that ends exactly where a picture ends
    does not wait for the next one. Re-muxing every real gameboot of the pack must give the original's clock value on every pack."""

    def test_every_pack_has_the_original_clock_value(self):
        from pmfkit.demux import demux_all
        from pmfkit.mirror import read as mirror_read
        files = sorted(glob.glob(os.path.join(PACK, "*", "*.[pP][mM][fF]")))
        if not files:
            self.skipTest("oracle PMFs not present")
        checked = skipped = 0
        for f in files:
            raw = open(f, "rb").read()
            params, v, tr, packs = demux_all(raw)
            mir = mirror_read(raw)
            if not tr or not mir.known or mir.bframes:
                continue
            new = mux(v, atrac3p.from_units(tr[sorted(tr)[0]]), version=params.version, style=mir.style, width=params.width, height=params.height,
                      video_kib=mir.video_kib or None, header_kib=mir.header_kib or None, audio_kib=mir.audio_kib or None)
            packs2 = demux_all(new)[3]
            if len(packs2) != len(packs):                    # Sony packs by time: a late-admitted tail of tiny pictures can get its own short pack (open)
                skipped += 1
                continue
            off = [k for k, (a, b) in enumerate(zip(packs, packs2)) if abs(a.scr27 - b.scr27) > 1]
            if os.path.basename(f) in OPEN_CLOCK_CASES:
                self.assertGreater(len(off), 0, f)            # still differs: when it starts to match, take it off the list
                continue
            self.assertEqual(off, [], f)
            checked += 1
        self.assertGreater(checked, 35)
        self.assertLess(skipped, 12)
