"""Batch 16b: gameboot-only CTF test files with their own preview picture/icon so each one is recognisable in the XMB.
PTF part = header/colour block of the local God of War 660 example (never commit it) with our own preview pictures; data = one
gameboot.pmf from batch 16; marker 0xDEAD0660 (as in the working example) or 0xDEAD0661.
usage (from the project folder): python tools/analysis/ctf_batch.py"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import ctf, ptf

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
GOW = "God Of War 660 theme example/GOW Dynamic Theme [660].ctf"
OUT = "test_output/ctf"
tpl = ctf.parse(open(GOW, "rb").read())["ptf"]
for old in ("660", "661"):
    shutil.rmtree("%s/%s" % (OUT, old), ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
COLORS = {"G1": ("0x1f5fbf", (0x1f, 0x5f, 0xbf)), "G2": ("0x1f8f3f", (0x1f, 0x8f, 0x3f)),
          "G3": ("0xbf5f1f", (0xbf, 0x5f, 0x1f)), "G4": ("0x8f1fbf", (0x8f, 0x1f, 0xbf))}
FONT = r"fontfile='C\:/Windows/Fonts/arialbd.ttf'"


def picture(code, secs, fw, extra):
    vf = ("drawtext=%s:text='GAMEBOOT TEST':fontsize=20:fontcolor=white@0.85:x=(w-text_w)/2:y=14,"
          "drawtext=%s:text='%s  %s':fontsize=54:fontcolor=white:x=(w-text_w)/2:y=48,"
          "drawtext=%s:text='%s':fontsize=%d:fontcolor=yellow:x=(w-text_w)/2:y=118" % (FONT, FONT, code, secs, FONT, "marker %s%s" % (fw, extra), 23 if extra else 30))
    r = subprocess.run([FF, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=%s:s=300x170:d=1,format=rgba" % COLORS[code][0], "-vf", vf,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == 300 * 170 * 4, r.stderr
    return r.stdout


def icon(code, fw):
    pal = bytearray(1024)
    pal[0:4] = bytes([0, 0, 0, 0])
    pal[4:8] = bytes(COLORS[code][1]) + b"\xff"
    pal[8:12] = b"\xff\xff\xff\xff"
    idx = bytearray(256)
    for y in range(16):
        for x in range(16):
            edge = x in (0, 15) or y in (0, 15)
            dot = fw == "661" and 6 <= x <= 9 and 6 <= y <= 9
            idx[y * 16 + x] = 2 if edge or dot else 1
    return bytes(idx), bytes(pal)


# control file: the untouched GoW PTF (its own preview picture and icon) + G1; if this one shows GoW's preview in the XMB
# but the others show nothing, the problem is in the pictures we generate, not in the container
pmf = open("test_output/gameboot/G1_2.5s/gameboot.pmf", "rb").read()
data = ctf.build(tpl, {"/vsh/resource/gameboot.pmf": pmf}, "660")
open("%s/CONTROL_GoW_preview_G1_2.5s_660.ctf" % OUT, "wb").write(data)
print("CONTROL_GoW_preview_G1_2.5s_660.ctf  %d bytes" % len(data))
for fw in ("660", "661"):
    for code, name, secs, extra in (("G1", "G1_2.5s", "2.5s", ""), ("G2", "G2_5s", "5s", ""), ("G3", "G3_7.4s", "7.4s", ""),
                                    ("G4", "G4_2.5s_Bframes", "2.5s", "  B-frames")):
        pmf = open("test_output/gameboot/%s/gameboot.pmf" % name, "rb").read()
        idx, pal = icon(code, fw)
        theme_ptf = ptf.with_preview(tpl, idx, pal, picture(code, secs, fw, extra))
        data = ctf.build(theme_ptf, {"/vsh/resource/gameboot.pmf": pmf}, fw)
        path = "%s/%s_%s.ctf" % (OUT, name, fw)
        open(path, "wb").write(data)
        q = ctf.parse(data)
        assert q["files"]["/vsh/resource/gameboot.pmf"] == pmf and q["count"] == 1 and q["ptf"][:0x10] + q["ptf"][0x20:] == theme_ptf[:0x10] + theme_ptf[0x20:]
        print("%-26s %8d bytes  marker %#x" % (os.path.basename(path), len(data), q["marker"]))
