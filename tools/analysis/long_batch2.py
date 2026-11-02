"""Batch 12: 32 kbps sounds (needs the tonal-trim atracdenc), long SND0 + long ICON1 together, and long ICON1 with
48 / 32 kbps sound inside. Same hum-then-8-beeps sound and seconds-counter icon as long_batch.py. Local test builder.
usage (from the project folder): python tools/analysis/long_batch2.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import atrac3p, snd0 as snd0mod
from pmfkit.cli import encode_audio, frame_bytes_for_kbps

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/long_test"
GAME = "test_output/xmb_batch12/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
COUNTER = OUT + "/counter_300s.mp4"                     # made by long_batch.py
py = [sys.executable, "-m", "pmfkit"]
LIMIT = snd0mod.COMBINED_LIMIT
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


def tone(secs):
    wav = "%s/hum_%ds.wav" % (OUT, secs)
    e = "if(lt(t,%d),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - 4)
    run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (e.replace(",", "\\,"), secs), "-ac", "2", "-c:a", "pcm_s16le", wav)
    return wav


def snd0(name, secs, kbps):
    oma = "%s/%s.oma" % (OUT, name)
    encode_audio(FF, AD, tone(secs), oma, secs, lufs=None, kbps=kbps)
    st = atrac3p.read_oma(oma)
    data = snd0mod.build(st.frames, st.frame_bytes, pcm_samples=secs * 44100)
    f = "%s/%s_%ds_%dk.AT3" % (OUT, name, secs, kbps)
    open(f, "wb").write(data)
    return f, len(data), len(st.frames), st.frame_bytes


def secs_for(budget, kbps):
    """longest whole number of seconds whose SND0 stays within budget bytes"""
    fb = frame_bytes_for_kbps(kbps)
    frames = (budget - 164) // fb - 1
    return int((frames * 2048 - 2048 - 368) / 44100)


def icon(name, secs, target):
    out = "%s/%s_%ds.pmf" % (OUT, name, secs)
    run(sys.executable, "tools/analysis/size_target.py", COUNTER, out, str(target), str(secs), "--noaudio")
    return out, os.path.getsize(out)


# ---- B: 32 kbps sounds alone
for name, secs in (("B1", 20), ("B2", 120)):
    f, size, n, fb = snd0(name, secs, 32)
    assert size <= LIMIT and fb == 192, (name, size, fb)
    print("%s  SND0 %d bytes, %d frames of %d, %d s, 32 kbps" % (name, size, n, fb, secs))
    eboot(name, "%s snd %ds 32k" % (name, secs), snd0=f)

# ---- C: long ICON1 (video only) + SND0 together, total just under 512,000
for name, isecs, itarget, kbps in (("C1", 60, 140000, 64), ("C2", 120, 255000, 64), ("C3", 180, 375000, 48)):
    pmf, isize = icon(name, isecs, itarget)
    ssecs = secs_for(LIMIT - isize - 1500, kbps)
    f, ssize, n, fb = snd0(name, ssecs, kbps)
    total = isize + ssize
    assert total <= LIMIT, (name, total)
    print("%s  ICON1 %d B (%d s) + SND0 %d B (%d s, %d kbps) = %d  (limit %d)" % (name, isize, isecs, ssize, ssecs, kbps, total, LIMIT))
    eboot(name, "%s icon %ds + snd %ds" % (name, isecs, ssecs), icon1=pmf, snd0=f)

# ---- D: ICON1 with the sound inside it at 48 / 32 kbps
for name, secs, kbps in (("D1", 40, 48), ("D2", 60, 32)):
    out = "%s/%s_%ds_%dk.pmf" % (OUT, name, secs, kbps)
    print(run(*py, "make", COUNTER, "-o", out, "--icon1", "-t", str(secs), "--video-kbps", "40", "--audio", tone(secs),
              "--audio-kbps", str(kbps), "--quiet-audio", "--ffmpeg", FF, "--atracdenc", AD).strip().splitlines()[-1])
    print("%s  ICON1 %d B, %d s, sound %d kbps inside" % (name, os.path.getsize(out), secs, kbps))
    eboot(name, "%s icon %ds + sound %dk" % (name, secs, kbps), icon1=out)
