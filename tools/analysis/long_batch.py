"""Batch 11: how long can an SND0 / ICON1 be? Sounds are hum, then 8 beeps in the last 4 s (so the user can tell the whole
file played); icons are a seconds counter. Local test builder.
usage (from the project folder): python tools/analysis/long_batch.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import atrac3p, snd0 as snd0mod
from pmfkit.cli import encode_audio

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/long_test"
GAME = "test_output/xmb_batch11/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)
os.makedirs(GAME, exist_ok=True)


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout + r.stderr


def eboot(folder, title, **sections):
    d = "%s/%s" % (GAME, folder)
    os.makedirs(d, exist_ok=True)
    args = []
    for k, v in sections.items():
        args += ["--" + k, v]
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", *args, "--title", title)


# ---- sounds: 440+880 Hz hum, then 8 beeps (1320 Hz) in the last 4 s
def tone(secs):
    wav = "%s/hum_%ds.wav" % (OUT, secs)
    e = "if(lt(t,%d),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - 4)
    run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (e.replace(",", "\\,"), secs), wav)
    return wav


def sound(name, secs, kbps):
    oma = "%s/%s.oma" % (OUT, name)
    encode_audio(FF, AD, tone(secs), oma, secs, lufs=None, kbps=kbps)
    st = atrac3p.read_oma(oma)
    data = snd0mod.build(st.frames, st.frame_bytes, pcm_samples=secs * 44100)
    f = "%s/%s_%ds_%dk.AT3" % (OUT, name, secs, kbps)
    open(f, "wb").write(data)
    assert len(data) <= snd0mod.COMBINED_LIMIT, (name, len(data))
    print("%s  SND0 %d bytes  %d frames of %d  (%d kbps nominal, %.1f s)" % (name, len(data), len(st.frames), st.frame_bytes, kbps, secs))
    eboot(name, "%s snd %ds %dk" % (name, secs, kbps), snd0=f)


# (32 kbps / 192-byte frames was tried: atracdenc prints TODO and stops early, so it is not offered)
for name, secs, kbps in (("A1", 63, 64), ("A2", 84, 48), ("A3", 20, 48)):
    sound(name, secs, kbps)

# ---- icons: seconds counter, video only, sized to just under 512,000 bytes
src = OUT + "/counter_300s.mp4"
if not os.path.exists(src):
    vf = ("drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='%{eif\\:trunc(t)\\:d}':fontsize=44:fontcolor=white:"
          "x=(w-text_w)/2:y=(h-text_h)/2")
    run(FF, "-y", "-f", "lavfi", "-i", "color=c=0x1030a0:s=144x80:r=30:d=300", "-vf", vf, "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", src)
for name, secs in (("V1", 90), ("V2", 120), ("V3", 180), ("V4", 240)):
    out = "%s/%s_%ds.pmf" % (OUT, name, secs)
    print(run(sys.executable, "tools/analysis/size_target.py", src, out, "500000", str(secs), "--noaudio").strip().splitlines()[-1])
    print("%s  ICON1 %d bytes (%d s)" % (name, os.path.getsize(out), secs))
    eboot(name, "%s icon %ds" % (name, secs), icon1=out)
