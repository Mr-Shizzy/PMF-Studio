"""Batch 6: SND0 size-vs-length decider (D1-D5) + ICON1 size vs SND0 sound mixing (R4-R6). Local test builder.
usage (from the project folder): python tools/analysis/snd0_batch2.py SRC30BUSY_MP4"""
import os
import subprocess
import sys

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/snd0_len"
BATCH = "test_output/xmb_batch6/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
SRC = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
py = [sys.executable, "-m", "pmfkit"]


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


def eboot(folder, icon, snd0, title):
    d = "%s/%s" % (BATCH, folder)
    os.makedirs(d, exist_ok=True)
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", icon, "--snd0", snd0, "--title", title)


src = OUT + "/steps_50s.wav"                      # from batch 5: pitch steps up every 10 s
for name, secs, kbps in [("D1", 30, 128), ("D2", 42, 64), ("D3", 44, 64), ("D4", 46, 64), ("D5", 48, 64)]:
    f = "%s/%s_%ds_%dk.AT3" % (OUT, name, secs, kbps)
    run(*py, "snd0", src, "-o", f, "--ffmpeg", FF, "--atracdenc", AD, "-t", str(secs), "--kbps", str(kbps), "--quiet-audio")
    size = os.path.getsize(f)
    print(name, secs, "s", kbps, "k", size, "bytes")
    eboot("SND0_" + name, "test_output/icon1/I3_icon1_video_only.pmf", f, "%s SND0 %ds %dk %dKB" % (name, secs, kbps, size // 1000))

hum = "test_output/icon1_limits/SND0_test_330Hz.AT3"
for name, target in [("R4", 300000), ("R5", 400000), ("R6", 445000)]:
    pmf = "test_output/icon1_size/%s_30s_%dK.pmf" % (name, target // 1000)
    run(sys.executable, "tools/analysis/size_target.py", SRC, pmf, str(target), "30")
    size = os.path.getsize(pmf)
    print(name, "ICON1", size, "bytes")
    eboot("ICON1_" + name, pmf, hum, "%s %dK icon + SND0 hum" % (name, size // 1000))
