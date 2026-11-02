"""Batch 16: real gameboot test files (CTF/CXMB on the user's 6.61 ARK-5). Each folder holds one gameboot.pmf, 480x272,
tenths-of-a-second counter, hum then beeps at the end. Lengths bracket the stock 2.5 s limit; G4 repeats G1 with B-frames.
Local test builder. usage (from the project folder): python tools/analysis/gameboot_batch.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/gameboot"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout + r.stderr


src = OUT + "/tenths_8s.mp4"
if not os.path.exists(src):
    vf = (r"drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='%{eif\:trunc(t)\:d}.%{eif\:mod(trunc(t*10)\,10)\:d}':fontsize=130:"
          r"fontcolor=white:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=(h-text_h)/2")
    run(FF, "-y", "-f", "lavfi", "-i", "testsrc2=s=480x272:r=30000/1001:d=8", "-vf", vf, "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", src)

# name, seconds, B-frames, seconds of beeps at the end
JOBS = [("G1_2.5s", 2.5, 0, 1.0), ("G2_5s", 5.0, 0, 2.0), ("G3_7.4s", 7.4, 0, 2.0), ("G4_2.5s_Bframes", 2.5, 1, 1.0)]
for name, secs, bf, beep in JOBS:
    wav = "%s/hum_%s.wav" % (OUT, secs)
    e = "if(lt(t,%g),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - beep)
    run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%g" % (e.replace(",", r"\,"), secs), "-ac", "2", "-c:a", "pcm_s16le", wav)
    d = "%s/%s" % (OUT, name)
    os.makedirs(d, exist_ok=True)
    out = d + "/gameboot.pmf"
    args = [*py, "make", src, "-o", out, "-t", str(secs), "--video-kbps", "1000", "--audio", wav, "--quiet-audio", "--audio-kbps", "128",
            "--ffmpeg", FF, "--atracdenc", AD]
    if bf:
        args += ["--bframes", str(bf)]
    run(*args)
    P, v, a, packs = demux(open(out, "rb").read())
    n = len(split_access_units(v))
    print("%-16s %5.1f s  %3d frames  %6d bytes  B-frames %d" % (name, secs, n, os.path.getsize(out), bf))
