"""Batch 5: SND0 length/size bisect (T1-T5) + ICON1-with-sound vs SND0 recheck (R1-R3). Local test builder.
usage (from the project folder): python tools/analysis/snd0_batch.py"""
import os
import subprocess
import sys

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/snd0_len"
BATCH = "test_output/xmb_batch5/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
os.makedirs(OUT, exist_ok=True)
py = [sys.executable, "-m", "pmfkit"]


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


# 50 s source: the pitch steps up every 10 s (300, 400, 500, 600, 700 Hz), so the user can tell how far it played
src = OUT + "/steps_50s.wav"
run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=0.3*sin(2*PI*t*(300+100*floor(t/10))):s=44100:d=50", src)

jobs = [("T1", 20, 64), ("T2", 30, 64), ("T3", 40, 64), ("T4", 50, 64), ("T5", 20, 128)]
for name, secs, kbps in jobs:
    f = "%s/%s_%ds_%dk.AT3" % (OUT, name, secs, kbps)
    run(*py, "snd0", src, "-o", f, "--ffmpeg", FF, "--atracdenc", AD, "-t", str(secs), "--kbps", str(kbps), "--quiet-audio")
    size = os.path.getsize(f)
    title = "%s SND0 %ds %dk %dKB" % (name, secs, kbps, size // 1000)
    d = "%s/SND0_%s" % (BATCH, name)
    os.makedirs(d, exist_ok=True)
    print(run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", "test_output/icon1/I3_icon1_video_only.pmf",
              "--snd0", f, "--title", title).strip())

snd = "test_output/icon1_limits/SND0_test_330Hz.AT3"
for name, icon, title in [("R1", "test_output/icon1/I4_icon1_audio64.pmf", "R1 10s beep icon + SND0 hum"),
                          ("R2", "test_output/icon1_limits/L2_30s.pmf", "R2 30s beep icon + SND0 hum"),
                          ("R3", "test_output/icon1_size/M2_30s_480KB.pmf", "R3 485K icon + SND0 hum")]:
    d = "%s/ICON1_%s" % (BATCH, name)
    os.makedirs(d, exist_ok=True)
    print(run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", icon, "--snd0", snd, "--title", title).strip())
