"""Measure what B-frames (+2 reference frames) buy: same footage, same bitrate -> SSIM/PSNR; same CRF -> file size.
Compares our current encode (no B-frames, 1 ref) with 1 and 2 B-frames (2 refs), using pmfkit's x264 settings.
Uses local sample footage only for analysis. usage: python tools/analysis/bframe_gain.py clip.pmf [clip2.pmf ...]"""
import os
import re
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit.cli import FIT, X264_PARAMS

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
OUT = "test_output/bgain"
SETTINGS = (("no B, 1 ref", 0, 1), ("1 B, 2 refs", 1, 2), ("2 B, 2 refs", 2, 2))
VF = FIT["crop"] % dict(w=480, h=272) + ",setsar=1,fps=30000/1001"
START, LEN = "5", "20"


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def encode(src, out, bf, refs, kbps=None, crf=None):
    rate = ["-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.5), "-bufsize", "%dk" % int(kbps * 1.5)] if kbps else ["-crf", str(crf)]
    xp = X264_PARAMS + ":weightp=0" + (":b-pyramid=none:b-adapt=0:weightb=0" if bf else "")
    rc, log = run(FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", START, "-t", LEN, "-i", src, "-an", "-vf", VF, "-c:v", "libx264",
                  "-profile:v", "main", "-level", "2.1", "-bf", str(bf), "-refs", str(refs), "-g", "59", "-keyint_min", "59", *rate,
                  "-pix_fmt", "yuv420p", "-x264-params", xp, "-f", "h264", out)
    assert rc == 0, log
    return os.path.getsize(out)


def quality(src, enc):
    fg = "[0:v]%s,setpts=PTS-STARTPTS[r];[1:v]setpts=PTS-STARTPTS[e];[r]split[r1][r2];[e]split[e1][e2];[e1][r1]ssim;[e2][r2]psnr" % VF
    rc, log = run(FF, "-hide_banner", "-ss", START, "-t", LEN, "-i", src, "-f", "h264", "-framerate", "30000/1001", "-i", enc,
                  "-filter_complex", fg, "-f", "null", "-")
    ssim = re.findall(r"SSIM.*?All:([0-9.]+)", log)
    psnr = re.findall(r"PSNR.*?average:([0-9.]+)", log)
    return float(ssim[-1]), float(psnr[-1])


rows = []
for src in sys.argv[1:]:
    name = os.path.basename(src)
    for kbps in (300, 600, 1200):
        res = []
        for label, bf, refs in SETTINGS:
            enc = "%s/%s_%dk_b%d.264" % (OUT, name, kbps, bf)
            size = encode(src, enc, bf, refs, kbps=kbps)
            s, p = quality(src, enc)
            res.append((label, size, s, p))
        rows.append(("%s @%dk" % (name, kbps), "rate", res))
    res = []
    for label, bf, refs in SETTINGS:
        enc = "%s/%s_crf_b%d.264" % (OUT, name, bf)
        size = encode(src, enc, bf, refs, crf=23)
        s, p = quality(src, enc)
        res.append((label, size, s, p))
    rows.append(("%s crf23" % name, "crf", res))

print("%-28s %-12s %10s %8s %8s" % ("clip", "setting", "bytes", "SSIM", "PSNR"))
for name, kind, res in rows:
    for label, size, s, p in res:
        print("%-28s %-12s %10d %8.4f %8.2f" % (name, label, size, s, p))
    base = res[0]
    for label, size, s, p in res[1:]:
        print("   -> %-10s vs no-B: size %+.1f%%  SSIM %+.4f  PSNR %+.2f dB" % (label, 100.0 * (size - base[1]) / base[1], s - base[2], p - base[3]))
