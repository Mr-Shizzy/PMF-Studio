"""Build an ICON1 PMF whose size lands inside [LO, HI] bytes by nudging the video bitrate (no size fitting).
usage: python tools/analysis/size_window.py SRC OUT LO HI SECONDS"""
import os
import subprocess
import sys

FF = "Things to refrence/pmftools/tools/ffmpeg.exe"
AD = "tools/atracdenc/bin/atracdenc.exe"
src, out, lo, hi, secs = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
mid = (lo + hi) // 2
kbps = int(mid * 8 / secs / 1000 - 65)
hist = []
for _ in range(14):
    subprocess.run([sys.executable, "-m", "pmfkit", "make", src, "-o", out, "--icon1", "--no-size-fit", "-t", str(secs),
                    "--video-kbps", str(kbps), "--ffmpeg", FF, "--atracdenc", AD], check=True, capture_output=True)
    size = os.path.getsize(out)
    print("video %d kbps -> %d bytes (window %d-%d)" % (kbps, size, lo, hi))
    if lo <= size <= hi:
        break
    hist.append((kbps, size))
    step = (mid - size) * 8 / secs / 1000
    kbps = max(8, kbps + (1 if 0 < step < 1 else -1 if -1 < step < 0 else int(round(step))))
else:
    sys.exit("could not hit the window")
