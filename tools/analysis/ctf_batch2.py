"""Batch 17 (output: test_output/ctf2): gameboot CTFs with a patched opening_plugin.rco so the boot is not cut at 2.5 s. The patch raises the last Delay of
anim_gameboot_movie (float32 1500.0 at 0x39c8 of the 6.61 base RCO). The patched RCO is Sony firmware content: local tests only.
usage (from the project folder): python tools/analysis/ctf_batch2.py"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import ctf, ptf

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
GOW = "God Of War 660 theme example/GOW Dynamic Theme [660].ctf"
RCO = "CTFtool_GUI_v5_beta_3/CTFtoolGUI/base/661/opening_plugin.rco"
OUT = "test_output/ctf2"
tpl = ctf.parse(open(GOW, "rb").read())["ptf"]
base = open(RCO, "rb").read()
EXPECT = {0x3928: 300.0, 0x399c: 700.0, 0x39c8: 1500.0}
for off, val in EXPECT.items():
    assert struct.unpack_from("<f", base, off)[0] == val, hex(off)
FONT = r"fontfile='C\:/Windows/Fonts/arialbd.ttf'"
COLORS = {"H1": ("0xbf1f1f", (0xbf, 0x1f, 0x1f)), "H2": ("0x1f8f8f", (0x1f, 0x8f, 0x8f)), "H3": ("0xaf8f1f", (0xaf, 0x8f, 0x1f)),
          "H4": ("0x3f3fbf", (0x3f, 0x3f, 0xbf)), "H5": ("0x1f9f3f", (0x1f, 0x9f, 0x3f)), "H6": ("0xbf3f9f", (0xbf, 0x3f, 0x9f))}


def picture(code, line2, line3):
    vf = ("drawtext=%s:text='GAMEBOOT + RCO':fontsize=20:fontcolor=white@0.85:x=(w-text_w)/2:y=14,"
          "drawtext=%s:text='%s  %s':fontsize=54:fontcolor=white:x=(w-text_w)/2:y=48,"
          "drawtext=%s:text='%s':fontsize=26:fontcolor=yellow:x=(w-text_w)/2:y=118" % (FONT, FONT, code, line2, FONT, line3))
    r = subprocess.run([FF, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=%s:s=300x170:d=1,format=rgba" % COLORS[code][0], "-vf", vf,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == 300 * 170 * 4, r.stderr
    return r.stdout


def icon(code):
    pal = bytearray(1024)
    pal[4:8] = bytes(COLORS[code][1]) + b"\xff"
    pal[8:12] = b"\xff\xff\xff\xff"
    idx = bytearray(256)
    for y in range(16):
        for x in range(16):
            idx[y * 16 + x] = 2 if (x in (0, 15) or y in (0, 15) or (6 <= x <= 9 and 6 <= y <= 9) or x == y) else 1
    return bytes(idx), bytes(pal)


def patched(delay_ms):
    d = bytearray(base)
    struct.pack_into("<f", d, 0x39c8, float(delay_ms))
    return bytes(d)


for code, src, secs, delay in (("H1", "G2_5s", "5s", 4000), ("H2", "G3_7.4s", "7.4s", 6400), ("H3", "G5_12s", "12s", 11000),
                               ("H4", "G6_30s", "30s", 29000), ("H5", "G7_60s", "60s", 59000), ("H6", "G8_180s", "180s", 179000)):
    pmf = open("test_output/gameboot/%s/gameboot.pmf" % src, "rb").read()
    idx, pal = icon(code)
    theme_ptf = ptf.with_preview(tpl, idx, pal, picture(code, secs, "delay %d ms" % delay))
    files = {"/vsh/resource/gameboot.pmf": pmf, "/vsh/resource/opening_plugin.rco": patched(delay)}
    data = ctf.build(theme_ptf, files, "661")
    q = ctf.parse(data)
    assert q["files"] == files
    path = "%s/%s_%s_rco%d_661.ctf" % (OUT, code, src, delay)
    open(path, "wb").write(data)
    print("%-36s %8d bytes (gameboot %.1f s total %.1f s)" % (os.path.basename(path), len(data), float(secs.rstrip("s")), (300 + 700 + delay) / 1000.0))
