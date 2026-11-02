"""Batch 7: ICON1-size vs combined-size for the sound mixing (E1, E2), the SND0 line (F1-F3), and whether a big ICON1
shrinks the SND0 room (G1). Local test builder; needs the files from snd0_batch.py / snd0_batch2.py.
usage (from the project folder): python tools/analysis/snd0_batch3.py"""
import os
import subprocess
import sys

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/snd0_len"
BATCH = "test_output/xmb_batch7/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
SRC = OUT + "/steps_50s.wav"                      # pitch steps up every 10 s
SMALL = "test_output/icon1/I3_icon1_video_only.pmf"          # 139,264 B, video only
R5 = "test_output/icon1_size/R5_30s_400K.pmf"                # 409,600 B, beeps
R6 = "test_output/icon1_size/R6_30s_445K.pmf"                # 446,464 B, beeps
py = [sys.executable, "-m", "pmfkit"]


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


def snd0(name, secs):
    f = "%s/%s_%gs.AT3" % (OUT, name, secs)
    run(*py, "snd0", SRC, "-o", f, "--ffmpeg", FF, "--atracdenc", AD, "-t", str(secs), "--kbps", "64", "--quiet-audio")
    return f


def eboot(folder, icon, snd, label):
    d = "%s/%s" % (BATCH, folder)
    os.makedirs(d, exist_ok=True)
    i, s = os.path.getsize(icon), os.path.getsize(snd)
    title = "%s icon %dK + SND0 %dK" % (label, i // 1000, s // 1000)
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", icon, "--snd0", snd, "--title", title)
    print("%-10s icon %7d + SND0 %7d = %7d   %s" % (folder, i, s, i + s, title))


eboot("ICON1_E1", R6, snd0("E1", 3), "E1")
eboot("ICON1_E2", R5, snd0("E2", 16), "E2")
for name, secs in (("F1", 44.5), ("F2", 45), ("F3", 45.5)):
    eboot("SND0_" + name, SMALL, snd0(name, secs), name)
eboot("ICON1_G1", R5, snd0("G1", 44), "G1")
