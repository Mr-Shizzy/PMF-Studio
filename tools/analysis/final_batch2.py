"""Batch 9 (10 EBOOTs): does the SND0 limit move with the ICON1 size (combined 512,000 rule) or stay fixed (~372.5 KB)?
01-04: video-only ICON1 P (~100 KB) + SND0 straddling 512,000 - P. 05-08: same with Q (~250 KB).
09-10: ICON1 with a beeps-only soundtrack (no carrier tone) + the 330 Hz SND0: 09 combined over 512,000, 10 under.
Local test builder. usage (from the project folder): python tools/analysis/final_batch2.py SRC10BUSY SRC30BUSY"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from pmfkit import snd0 as snd0mod

FF = os.path.abspath("Things to refrence/pmftools/tools/ffmpeg.exe")
AD = os.path.abspath("tools/atracdenc/bin/atracdenc.exe")
S10, S30 = sys.argv[1], sys.argv[2]
OUT = "test_output/snd0_len"
BATCH = "test_output/xmb_batch9"
GAME = BATCH + "/PSP/GAME"
BASE = "EBOOT samples/HOMEBREW.PBP"
HUM81 = BATCH + "/snd/hum_81380.AT3"                         # 216 frames = 81,380 B, built below
py = [sys.executable, "-m", "pmfkit"]
FB, HDR = 376, 164


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


os.makedirs(OUT, exist_ok=True)
os.makedirs(BATCH + "/snd", exist_ok=True)

# long steady 440+880 Hz SND0 source (54 s) -> frames
tone = OUT + "/tone330_54s.wav"
run(FF, "-y", "-f", "lavfi", "-i", "aevalsrc=0.45*sin(2*PI*440*t)+0.45*sin(2*PI*880*t):s=44100:d=54", tone)   # loud: peak ~ -1 dB
long_at3 = OUT + "/tone330_54s.AT3"
run(*py, "snd0", tone, "-o", long_at3, "--ffmpeg", FF, "--atracdenc", AD, "-t", "54", "--kbps", "64", "--quiet-audio")
raw = open(long_at3, "rb").read()
frames = [raw[HDR + i * FB:HDR + (i + 1) * FB] for i in range((len(raw) - HDR) // FB)]
print("long SND0 source: %d frames" % len(frames))
open(HUM81, "wb").write(snd0mod.build(frames[:216], FB))
assert os.path.getsize(HUM81) == 81380

# video-only icons P and Q
P, Q = OUT + "/P_video_only.pmf", OUT + "/Q_video_only.pmf"
if not os.path.exists(P):
    run(sys.executable, "tools/analysis/size_target.py", S10, P, "100000", "10", "--noaudio")
if not os.path.exists(Q):
    run(sys.executable, "tools/analysis/size_target.py", S30, Q, "250000", "30", "--noaudio")

# beeps-only soundtrack (1 kHz beep, 0.15 s each second, silence between) and icons that carry it
beeps = OUT + "/beeps_only_30s.wav"
run(FF, "-y", "-f", "lavfi", "-i", r"aevalsrc=0.5*sin(2*PI*1000*t)*lt(mod(t\,1)\,0.15):s=44100:d=30", beeps)


def beep_icon(out, target, lo, hi):
    kbps = max(10, int(target * 8 / 30 / 1000 * 0.55))
    for _ in range(8):
        run(*py, "make", S30, "-o", out, "--icon1", "--no-size-fit", "-t", "30", "--video-kbps", str(kbps),
            "--ffmpeg", FF, "--atracdenc", AD, "--audio", beeps)
        size = os.path.getsize(out)
        if lo <= size <= hi:
            return size
        kbps = max(10, int(kbps * (1 + 0.9 * (target - size) / size)))
    sys.exit("could not reach %d for %s" % (target, out))


C1, C2 = OUT + "/C1_beeps_450K.pmf", OUT + "/C2_beeps_300K.pmf"
if not os.path.exists(C1):
    beep_icon(C1, 455000, 440000, 490000)
if not os.path.exists(C2):
    beep_icon(C2, 300000, 250000, 400000)
assert os.path.getsize(C1) + os.path.getsize(HUM81) > 515000 and os.path.getsize(C2) + os.path.getsize(HUM81) < 500000

rows = []


def eboot(n, icon, snd_path, tag):
    d = "%s/T%02d" % (GAME, n)
    os.makedirs(d, exist_ok=True)
    isz, ssz = os.path.getsize(icon), os.path.getsize(snd_path)
    title = "%02d %s" % (n, tag)
    run(*py, "pbp", "set", BASE, "-o", d + "/EBOOT.PBP", "--icon1", icon, "--snd0", snd_path, "--title", title)
    rows.append((n, tag, isz, ssz, isz + ssz))


n = 0
for icon in (P, Q):
    isz = os.path.getsize(icon)
    fb = (512000 - isz - HDR) // FB                  # largest frame count with icon + SND0 <= 512,000
    assert fb + 5 <= len(frames), (fb, len(frames))
    for k in (-4, 0, 1, 5):
        n += 1
        f = "%s/snd/%02d.AT3" % (BATCH, n)
        open(f, "wb").write(snd0mod.build(frames[:fb + k], FB))
        eboot(n, icon, f, "snd")
for icon, tag in ((C1, "beep+snd"), (C2, "beep+snd")):
    n += 1
    eboot(n, icon, HUM81, tag)

for r in rows:
    print("%02d %-9s icon %7d + SND0 %7d = %7d  (%s 512,000)" % (r[0], r[1], r[2], r[3], r[4], "over" if r[4] > 512000 else "under"))
