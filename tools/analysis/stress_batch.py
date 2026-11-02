"""Batch 14: stress tests for full-size PMFs in the OneLua player: 2 reference frames (is 1 really the limit? B-frames need
at least 2), high video bitrates (2000-6000 kbps), a 480 s file, files over 30 MB. Moving noisy test pattern + seconds
counter; audio = hum, then 8 beeps in the last 4 s. Local test builder. usage (from the project folder):
python tools/analysis/stress_batch.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/stress"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout + r.stderr


src = OUT + "/noisy_480s.mp4"
if not os.path.exists(src):
    vf = (r"noise=alls=14:allf=t,drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='%{eif\:trunc(t)\:d}':fontsize=120:"
          r"fontcolor=white:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=(h-text_h)/2")
    run(FF, "-y", "-f", "lavfi", "-i", "testsrc2=s=480x272:r=30000/1001:d=480", "-vf", vf, "-c:v", "libx264", "-crf", "10",
        "-pix_fmt", "yuv420p", src)

# name, seconds, video kbps, extra make args
JOBS = [("R1_refs2", 60, 1000, ["--refs", "2", "--no-psp-check"]),
        ("H1_2000k", 45, 2000, []),
        ("H2_3500k", 45, 3500, []),
        ("H3_4800k", 55, 4800, []),
        ("H4_6000k", 30, 6000, []),
        ("H5_480s", 480, 800, [])]
for name, secs, kbps, extra in JOBS:
    wav = "%s/hum_%ds.wav" % (OUT, secs)
    if not os.path.exists(wav):
        e = "if(lt(t,%d),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - 4)
        run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (e.replace(",", r"\,"), secs), "-ac", "2", "-c:a", "pcm_s16le", wav)
    out = "%s/%s.pmf" % (OUT, name)
    log = run(*py, "make", src, "-o", out, "-t", str(secs), "--video-kbps", str(kbps), "--audio", wav, "--quiet-audio",
              "--audio-kbps", "128", "--ffmpeg", FF, "--atracdenc", AD, *extra)
    for line in log.strip().splitlines():
        if "retrying" in line:
            print("   ", name, line)
    P, v, a, packs = demux(open(out, "rb").read())
    aus = split_access_units(v)
    big = max(len(x.data) for x in aus)
    print("%-9s %4d s  target %4d kbps  actual video %5.0f kbps  largest picture %6d B  file %7.1f MB  frames %d" % (
        name, secs, kbps, len(v) * 8 / (len(aus) * 1001 / 30000) / 1000, big, os.path.getsize(out) / 1e6, len(aus)))
