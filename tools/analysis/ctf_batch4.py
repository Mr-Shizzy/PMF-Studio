"""Batch 20: where exactly is the gameboot size limit? 12 s movies sized just below/above the candidate limits
2,000,000 and 2,097,152 (2 MiB) bytes; patched RCO delay 11000 like H3. Local test builder (patched RCO = Sony content).
usage (from the project folder): python tools/analysis/ctf_batch4.py"""
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
OUT = "test_output/ctf4"
FONT = r"fontfile='C\:/Windows/Fonts/arialbd.ttf'"
py = [sys.executable, "-m", "pmfkit"]
os.makedirs(OUT, exist_ok=True)
os.makedirs(GB + "/fine", exist_ok=True)
tpl = ctf.parse(open(GOW, "rb").read())["ptf"]
base = open(RCO, "rb").read()
noisy = GB + "/tenths_noisy_15s.mp4"
wav = GB + "/hum_12.wav"


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)


def build(name, target, secs=12):
    kbps = int(target * 8 / secs / 1000 - 128)
    for _ in range(8):
        out = "%s/fine/%s.pmf" % (GB, name)
        run(*py, "make", noisy, "-o", out, "-t", str(secs), "--video-kbps", str(kbps), "--audio", wav, "--quiet-audio", "--audio-kbps", "128", "--ffmpeg", FF, "--atracdenc", AD)
        size = os.path.getsize(out)
        if abs(size - target) < target * 0.006:
            break
        kbps = max(50, int(kbps * (1 + 0.95 * (target - size) / (size - secs * 16000))))
    return open(out, "rb").read()


def picture(color, line2, line3):
    vf = ("drawtext=%s:text='GAMEBOOT SIZE':fontsize=20:fontcolor=white@0.85:x=(w-text_w)/2:y=14,"
          "drawtext=%s:text='%s':fontsize=44:fontcolor=white:x=(w-text_w)/2:y=48,"
          "drawtext=%s:text='%s':fontsize=24:fontcolor=yellow:x=(w-text_w)/2:y=118" % (FONT, FONT, line2, FONT, line3))
    r = subprocess.run([FF, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=%s:s=300x170:d=1,format=rgba" % color, "-vf", vf,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == 300 * 170 * 4, r.stderr
    return r.stdout


def icon(rgb):
    pal = bytearray(1024)
    pal[4:8] = bytes(rgb) + b"\xff"
    pal[8:12] = b"\xff\xff\xff\xff"
    idx = bytearray(256)
    for y in range(16):
        for x in range(16):
            idx[y * 16 + x] = 2 if (x in (0, 15) or y in (0, 15) or x + y == 15) else 1
    return bytes(idx), bytes(pal)


JOBS = (("F1", 1950000, "0x1f5fbf", (0x1f, 0x5f, 0xbf)), ("F2", 2050000, "0x1f8f3f", (0x1f, 0x8f, 0x3f)),
        ("F3", 2140000, "0xbf5f1f", (0xbf, 0x5f, 0x1f)), ("F4", 3060000, "0x9f1f1f", (0x9f, 0x1f, 0x1f)))   # F4: above 3,000,000, below 3 MiB
for name, target, color, rgb in [j for j in JOBS if len(sys.argv) < 2 or j[0] in sys.argv[1:]]:
    pmf = build(name, target)
    d = bytearray(base)
    struct.pack_into("<f", d, 0x39c8, 11000.0)
    files = {"/vsh/resource/gameboot.pmf": pmf, "/vsh/resource/opening_plugin.rco": bytes(d)}
    idx, pal = icon(rgb)
    theme = ptf.with_preview(tpl, idx, pal, picture(color, "%s  12s" % name, "%d bytes" % len(pmf)))
    data = ctf.build(theme, files, "661")
    path = "%s/%s_%d_bytes_661.ctf" % (OUT, name, len(pmf))
    open(path, "wb").write(data)
    print("%-28s PMF %d bytes (%.3f MiB)  CTF %d bytes" % (os.path.basename(path), len(pmf), len(pmf) / 1048576, len(data)))
