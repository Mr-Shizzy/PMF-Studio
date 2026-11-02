"""Batch 15: B-frame PMFs made by pmfkit (--bframes) for the OneLua player, and B-frame ICON1s in EBOOTs for the real XMB.
Needs the sources/audio from long_full.py, stress_batch.py and long_batch.py. Local test builder.
usage (from the project folder): python tools/analysis/bframe_batch.py"""
import collections
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units
from pmfkit.poc import display_indices
from pmfkit.sps import stream_info

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
OUT = "test_output/bframes"
GAME = OUT + "/xmb/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)
os.makedirs(GAME, exist_ok=True)


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout + r.stderr


def info(path):
    P, v, a, packs = demux(open(path, "rb").read())
    aus = split_access_units(v, strip_x264_sei=False)
    sps, _ = stream_info(v)
    disp = display_indices(aus, sps)
    import tools.analysis.commercial_survey as cs
    t = collections.Counter(cs.slice_type(x.data) for x in aus)
    return "%dx%d  P%d B%d I%d  refs %d  poc %d  frames %d  (%.1f s)  %.1f MB  reorder shift %d" % (
        P.width, P.height, t.get(0, 0), t.get(1, 0), t.get(2, 0), sps["num_ref_frames"], sps["poc_type"], len(aus),
        len(aus) * 1001 / 30000, os.path.getsize(path) / 1e6, max(k - d for k, d in enumerate(disp)))


# ---- 480x272 for the OneLua player
CLEAN, NOISY = "test_output/long_full/pattern_200s.mp4", "test_output/stress/noisy_480s.mp4"
for name, src, secs, kbps, bf in (("B1_bf1_1000k", CLEAN, 60, 1000, 1), ("B2_bf2_1000k", CLEAN, 60, 1000, 2), ("B3_bf1_3000k", NOISY, 45, 3000, 1)):
    wav = "test_output/stress/hum_%ds.wav" % secs
    out = "%s/%s_%ds.pmf" % (OUT, name, secs)
    run(*py, "make", src, "-o", out, "-t", str(secs), "--video-kbps", str(kbps), "--bframes", str(bf), "--audio", wav, "--quiet-audio",
        "--audio-kbps", "128", "--ffmpeg", FF, "--atracdenc", AD)
    print(name, info(out))

# ---- ICON1 with B-frames in EBOOTs (real XMB)
COUNTER = "test_output/long_test/counter_300s.mp4"
for name, secs, audio in (("X1", 20, None), ("X2", 20, "test_output/long_test/hum_20s.wav")):
    out = "%s/%s_icon1_bf1_%ds.pmf" % (OUT, name, secs)
    args = [*py, "make", COUNTER, "-o", out, "--icon1", "-t", str(secs), "--bframes", "1", "--ffmpeg", FF]
    if audio:
        args += ["--audio", audio, "--quiet-audio", "--atracdenc", AD]
    run(*args)
    print(name, info(out), "  ICON1 bytes", os.path.getsize(out))
    d = "%s/ICON1_%s" % (GAME, name)
    os.makedirs(d, exist_ok=True)
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", out, "--title", "%s icon B-frames%s" % (name, " + sound" if audio else ""))
