"""Batch 8 (30 EBOOTs): exact ICON1 line (1), exact SND0 line in 376-byte frame steps (10), ICON1+SND0 mixing line (19).
Local test builder; needs files from earlier batches (steps SND0 D4, icons I3/R5/Z_512000).
usage (from the project folder): python tools/analysis/final_batch.py"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import snd0 as snd0mod

BATCH = "test_output/xmb_batch8"
GAME = BATCH + "/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
SMALL = "test_output/icon1/I3_icon1_video_only.pmf"            # 139,264 B, video only
R5 = "test_output/icon1_size/R5_30s_400K.pmf"                  # 409,600 B, with beeps
Z = "test_output/icon1_line/Z_512000.pmf"                      # 512,000 B, with sound
SRC = "test_output/snd0_len/D4_46s_64k.AT3"                    # 991 frames of 376 B, 164-byte header
FB, HDR = 376, 164
py = [sys.executable, "-m", "pmfkit"]
raw = open(SRC, "rb").read()
frames = [raw[HDR + i * FB:HDR + (i + 1) * FB] for i in range((len(raw) - HDR) // FB)]
assert len(frames) == 991
f3 = open("test_output/snd0_len/F3_45.5s.AT3", "rb").read()
# F3 was encoded to end at 45.5 s, so only its last frame or two differ from the first 980 frames of the 46 s encode
assert snd0mod.build(frames[:980], FB)[:368000] == f3[:368000], "rebuilt SND0 differs from the F3 file that played"


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)


rows = []


def eboot(n, kind, icon, nframes, label):
    snd = None
    if nframes:
        snd = "%s/snd/%02d.AT3" % (BATCH, n)
        os.makedirs(os.path.dirname(snd), exist_ok=True)
        open(snd, "wb").write(snd0mod.build(frames[:nframes], FB))
    d = "%s/T%02d" % (GAME, n)
    os.makedirs(d, exist_ok=True)
    isz, ssz = os.path.getsize(icon), (os.path.getsize(snd) if snd else 0)
    title = "%02d %s %d" % (n, kind, (isz + ssz) if kind == "mix" else (ssz or isz))
    cmd = py + ["pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", icon, "--title", title]
    if snd:
        cmd += ["--snd0", snd]
    run(*cmd)
    rows.append((n, kind, isz, ssz, isz + ssz, title))


n = 1
eboot(n, "icon", Z, 0, "")
for fr in range(981, 991):                                      # 369,020 ... 372,404 B (368,644 plays, 372,780 silent)
    n += 1
    eboot(n, "snd", SMALL, fr, "")
mix = [239, 240, 241] + list(range(266, 279)) + [304, 305, 306]  # around 500,000 / 512,000 / 524,288 combined
for fr in mix:
    n += 1
    eboot(n, "mix", R5, fr, "")
assert n == 30

with open(BATCH + "/ANSWER_SHEET.txt", "w") as f:
    f.write("Number  what it is     ICON1 B   SND0 B  combined  answer\n")
    for r in rows:
        f.write("%02d      %-4s %9d %9d %9d  %s\n" % (r[0], r[1], r[2], r[3], r[4],
                "plays / nothing" if r[1] == "icon" else "hum / silent" if r[1] == "snd" else "hum / both"))
print(open(BATCH + "/ANSWER_SHEET.txt").read())
