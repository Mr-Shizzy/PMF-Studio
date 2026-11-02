"""Batch 19: separate SIZE from DURATION for gameboots (the 30 s / 4.3 MB one did not play, 12 s / 1.7 MB did).
S1-S4: 12 s at growing sizes; D1-D4: growing durations at ~1.5-1.7 MB; N1: the 30 s movie with no RCO patch (does the movie start at all?).
Local test builder (patched RCO is Sony content). usage (from the project folder): python tools/analysis/ctf_batch3.py"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import ctf, ptf

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
GOW = "God Of War 660 theme example/GOW Dynamic Theme [660].ctf"
RCO = "CTFtool_GUI_v5_beta_3/CTFtoolGUI/base/661/opening_plugin.rco"
GB = "test_output/gameboot"
OUT = "test_output/ctf3"
FONT = r"fontfile='C\:/Windows/Fonts/arialbd.ttf'"
py = [sys.executable, "-m", "pmfkit"]
tpl = ctf.parse(open(GOW, "rb").read())["ptf"]
base = open(RCO, "rb").read()
assert struct.unpack_from("<f", base, 0x39c8)[0] == 1500.0


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


# sources: clean counter (190 s exists) and a noisy one so high bitrates are really reached
noisy = GB + "/tenths_noisy_15s.mp4"
if not os.path.exists(noisy):
    vf = (r"noise=alls=14,drawtext=%s:text='%%{eif\:trunc(t)\:d}.%%{eif\:mod(trunc(t*10)\,10)\:d}':fontsize=120:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=(h-text_h)/2" % FONT)
    run(FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=480x272:r=30000/1001:d=15", "-vf", vf, "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", noisy)
clean = GB + "/tenths_190s.mp4"


def movie(name, src, secs, kbps):
    d = "%s/bisect/%s" % (GB, name)
    os.makedirs(d, exist_ok=True)
    wav = "%s/hum_%d.wav" % (GB, secs)
    if not os.path.exists(wav):
        e = "if(lt(t,%g),0.35*sin(2*PI*440*t)+0.35*sin(2*PI*880*t),0.85*sin(2*PI*1320*t)*lt(mod(t,0.5),0.25))" % (secs - 2)
        run(FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (e.replace(",", r"\,"), secs), "-ac", "2", "-c:a", "pcm_s16le", wav)
    out = d + "/gameboot.pmf"
    run(*py, "make", src, "-o", out, "-t", str(secs), "--video-kbps", str(kbps), "--audio", wav, "--quiet-audio", "--audio-kbps", "128", "--ffmpeg", FF, "--atracdenc", AD)
    return open(out, "rb").read()


def picture(color, line2, line3):
    vf = ("drawtext=%s:text='GAMEBOOT BISECT':fontsize=20:fontcolor=white@0.85:x=(w-text_w)/2:y=14,"
          "drawtext=%s:text='%s':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=48,"
          "drawtext=%s:text='%s':fontsize=24:fontcolor=yellow:x=(w-text_w)/2:y=118" % (FONT, FONT, line2, FONT, line3))
    r = subprocess.run([FF, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=%s:s=300x170:d=1,format=rgba" % color, "-vf", vf,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == 300 * 170 * 4, r.stderr
    return r.stdout


def icon(rgb, mark):
    pal = bytearray(1024)
    pal[4:8] = bytes(rgb) + b"\xff"
    pal[8:12] = b"\xff\xff\xff\xff"
    idx = bytearray(256)
    for y in range(16):
        for x in range(16):
            edge = x in (0, 15) or y in (0, 15)
            m = {"S": 7 <= y <= 8, "D": 7 <= x <= 8, "N": x == y}[mark]
            idx[y * 16 + x] = 2 if edge or m else 1
    return bytes(idx), bytes(pal)


def ctf_for(name, pmf, secs, patch, color, rgb, mark):
    files = {"/vsh/resource/gameboot.pmf": pmf}
    if patch:
        d = bytearray(base)
        struct.pack_into("<f", d, 0x39c8, float(secs * 1000 - 1000))
        files["/vsh/resource/opening_plugin.rco"] = bytes(d)
    idx, pal = icon(rgb, mark)
    mb = len(pmf) / 1e6
    theme = ptf.with_preview(tpl, idx, pal, picture(color, "%s  %ds" % (name, secs), "%.1f MB%s" % (mb, "" if patch else "  no RCO patch")))
    data = ctf.build(theme, files, "661")
    path = "%s/%s_%ds_%.1fMB_661.ctf" % (OUT, name, secs, mb)
    open(path, "wb").write(data)
    print("%-28s PMF %6.2f MB  CTF %6.2f MB  %s" % (os.path.basename(path), mb, len(data) / 1e6, "patched RCO" if patch else "no patch"))


# size axis, 12 s: (name, target total kbps - 128 audio)
for name, kbps, color, rgb in (("S1", 1340, "0x1f5fbf", (0x1f, 0x5f, 0xbf)), ("S2", 1740, "0x1f8f3f", (0x1f, 0x8f, 0x3f)),
                               ("S3", 2200, "0xbf5f1f", (0xbf, 0x5f, 0x1f)), ("S4", 2740, "0x8f1fbf", (0x8f, 0x1f, 0xbf))):
    ctf_for(name, movie("%s_12s" % name, noisy, 12, kbps), 12, True, color, rgb, "S")
# duration axis, ~1.5-1.7 MB
for name, secs, kbps, color, rgb in (("D1", 20, 410, "0xaf1f4f", (0xaf, 0x1f, 0x4f)), ("D2", 30, 250, "0x1f8f8f", (0x1f, 0x8f, 0x8f)),
                                     ("D3", 45, 150, "0x8f8f1f", (0x8f, 0x8f, 0x1f)), ("D4", 60, 100, "0x4f4f4f", (0x4f, 0x4f, 0x4f))):
    ctf_for(name, movie("%s_%ds" % (name, secs), clean, secs, kbps), secs, True, color, rgb, "D")
# N1: the original 30 s / 4.3 MB movie, no RCO patch
ctf_for("N1", open(GB + "/G6_30s/gameboot.pmf", "rb").read(), 30, False, "0x202020", (0x40, 0x40, 0x40), "N")
