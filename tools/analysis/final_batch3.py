"""Batch 10 (6 EBOOTs): an SND0 and NO ICON1 at all. Is there a size limit, and is it 512,000 on its own?
128 kbps (744-byte frames), loud 440+880 Hz tone. Local test builder; needs test_output/snd0_len/tone330_54s.wav (loud tone,
made by final_batch2.py). usage (from the project folder): python tools/analysis/final_batch3.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import snd0 as snd0mod

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/snd0_len"
BATCH = "test_output/xmb_batch10"
GAME = BATCH + "/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
py = [sys.executable, "-m", "pmfkit"]
HDR, FB = 164, 744


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)


os.makedirs(BATCH + "/snd", exist_ok=True)
long_at3 = OUT + "/tone_54s_128k.AT3"
run(*py, "snd0", OUT + "/tone330_54s.wav", "-o", long_at3, "--ffmpeg", FF, "--atracdenc", AD, "-t", "54", "--kbps", "128", "--quiet-audio")
raw = open(long_at3, "rb").read()
frames = [raw[HDR + i * FB:HDR + (i + 1) * FB] for i in range((len(raw) - HDR) // FB)]
assert all(len(f) == FB for f in frames), "unexpected frame size"
print("%d frames of %d bytes" % (len(frames), FB))
fb = (512000 - HDR) // FB                                  # largest frame count with SND0 <= 512,000
for n, f in enumerate([300, fb, fb + 1, 800, 1000, min(1160, len(frames))], 1):
    snd = "%s/snd/%02d.AT3" % (BATCH, n)
    open(snd, "wb").write(snd0mod.build(frames[:f], FB))
    size = os.path.getsize(snd)
    d = "%s/T%02d" % (GAME, n)
    os.makedirs(d, exist_ok=True)
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--snd0", snd, "--title", "%02d snd alone %d" % (n, size))
    print("%02d  SND0 %7d bytes (%d frames, %.1f s)  %s 512,000" % (n, size, f, f * 2048 / 44100, "over" if size > 512000 else "under"))
