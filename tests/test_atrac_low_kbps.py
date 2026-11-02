import os
import shutil
import subprocess
import tempfile
import unittest

from pmfkit import cli

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = shutil.which("ffmpeg")
ATRAC = next((p for p in (os.path.join(HERE, "tools", "atracdenc", "bin", "atracdenc.exe"), shutil.which("atracdenc") or "") if p and os.path.isfile(p)), None)


@unittest.skipUnless(FFMPEG and ATRAC, "needs ffmpeg and atracdenc")
class LowBitrateSoundTests(unittest.TestCase):
    """The atracdenc build must not abort at 32 and 48 kbps on busy sound (noise, chords, real music). Upstream stops with "TODO" there;
    tools/atracdenc/tonal-trim.patch fixes it. A build without that patch fails these (it did, once: the shipped build had left it out)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmf_lowkbps_")
        cls.wav = os.path.join(cls.dir, "busy.wav")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=44100:a=0.3", "-ac", "2", "-c:a", "pcm_s16le", cls.wav], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_quality_encodes_busy_sound(self):
        for kbps in (32, 48, 64, 96, 128):
            out = os.path.join(self.dir, "s%d.at3" % kbps)
            cli.main(["snd0", self.wav, "-o", out, "--ffmpeg", FFMPEG, "--atracdenc", ATRAC, "--kbps", str(kbps), "--quiet-audio"])
            r = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", out, "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000 if os.name == "nt" else 0)
            self.assertEqual(r.returncode, 0, "%d kbps: %s" % (kbps, r.stdout[-200:]))
            self.assertGreater(os.path.getsize(out), kbps * 100)            # about 6 s of sound


if __name__ == "__main__":
    unittest.main()
