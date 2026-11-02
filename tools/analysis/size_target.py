"""Build an ICON1 PMF as close as possible to a target size by adjusting the video bitrate.
usage: python tools/analysis/size_target.py SRC OUT TARGET_BYTES SECONDS [--noaudio]"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
FF = "Things to refrence/pmftools/tools/ffmpeg.exe"
AD = "tools/atracdenc/bin/atracdenc.exe"
src, out, target, secs = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
audio = "--noaudio" not in sys.argv
kbps = max(10, int(target * 8 / float(secs) / 1000 * (0.55 if audio else 0.95)))
for _ in range(6):
    cmd = [sys.executable, "-m", "pmfkit", "make", src, "-o", out, "--icon1", "-t", secs, "--video-kbps", str(kbps), "--ffmpeg", FF]
    if audio:
        cmd += ["--atracdenc", AD]
    subprocess.run(cmd, check=True, capture_output=True)
    size = os.path.getsize(out)
    print("video %d kbps -> %d bytes (target %d)" % (kbps, size, target))
    if abs(size - target) < target * 0.015:
        break
    kbps = max(10, int(kbps * (1 + 0.9 * (target - size) / size)))
