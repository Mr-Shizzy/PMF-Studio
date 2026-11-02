"""Batch 13: long FULL-SIZE (480x272) PMFs for the user's OneLua PMF Player: one under 3,770 frames, one between, one over
5,000 (the frame counts where pmftools-plus changes its muxing rules). Moving test pattern + seconds counter; audio is a hum
with 8 beeps in the last 4 s. Local test builder. usage (from the project folder): python tools/analysis/long_full.py"""
import os
import subprocess
import sys

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/long_full"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout + r.stderr


src = OUT + "/pattern_200s.mp4"
if not os.path.exists(src):
    vf = (r"drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='%{eif\:trunc(t)\:d}':fontsize=120:fontcolor=white:"
          "box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=(h-text_h)/2")
    run(FF, "-y", "-f", "lavfi", "-i", "testsrc2=s=480x272:r=30000/1001:d=200", "-vf", vf, "-c:v", "libx264", "-crf", "16",
        "-pix_fmt", "yuv420p", src)

for name, secs in (("L1", 100), ("L2", 140), ("L3", 200)):
    wav = "%s/hum_%ds.wav" % (OUT, secs)
    e = "if(lt(t,%d),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - 4)
    run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (e.replace(",", r"\,"), secs), "-ac", "2", "-c:a", "pcm_s16le", wav)
    out = "%s/%s_%ds.pmf" % (OUT, name, secs)
    print(run(*py, "make", src, "-o", out, "-t", str(secs), "--audio", wav, "--quiet-audio", "--audio-kbps", "128",
              "--ffmpeg", FF, "--atracdenc", AD).strip().splitlines()[-1])
