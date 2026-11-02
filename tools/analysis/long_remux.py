"""Remux a long Sony PMF from its own elementary streams with pmfkit and report where the packs start to differ.
usage: python tools/analysis/long_remux.py file.pmf [style]   (style A or B, default B)"""
import sys

sys.path.insert(0, ".")
from pmfkit import atrac3p
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units
from pmfkit.mux import mux

f = sys.argv[1]
style = sys.argv[2] if len(sys.argv) > 2 else "B"
orig = open(f, "rb").read()
P, v, a, packs = demux(orig)
au = atrac3p.from_units(bytes(a)) if P.audio else None
new = mux(v, au, version=P.version, style=style, width=P.width, height=P.height, header_kib=P.video_buffer_kib)
P2, v2, a2, packs2 = demux(new)
nfr = len(split_access_units(v))
print("frames", nfr, " size", len(orig), len(new), " packs", len(packs), len(packs2))
print("video ES identical", v2 == v, " audio ES identical", bytes(a2) == bytes(a))
print("header bytes differing:", [hex(i) for i in range(2048) if orig[i] != new[i]][:20])
bo, bn = orig[2048:], new[2048:]
n = min(len(packs), len(packs2))
bad = [k for k in range(n) if bo[k * 2048 + 10:(k + 1) * 2048] != bn[k * 2048 + 10:(k + 1) * 2048]]
print("packs identical excluding SCR: %d of %d (%.2f%%)" % (n - len(bad), n, 100.0 * (n - len(bad)) / n))
print("first differing packs:", bad[:25])
if bad:
    k = bad[0]
    x, y = bo[k * 2048:(k + 1) * 2048], bn[k * 2048:(k + 1) * 2048]
    d = [i for i in range(10, 2048) if x[i] != y[i]]
    print("pack %d differs at bytes %s..%s (%d bytes)" % (k, d[0], d[-1], len(d)))
scr = [p1.scr27 - p2.scr27 for p1, p2 in zip(packs, packs2)]
print("SCR diff (orig-new): first", scr[0], " min", min(scr), " max", max(scr), " last", scr[-1])
step = max(1, n // 12)
print("SCR diff along the file:", [scr[i] for i in range(0, n, step)])
# where the diffs are, per 10% of the file
for dec in range(10):
    lo, hi = dec * n // 10, (dec + 1) * n // 10
    print("  packs %6d-%6d: %5d differ" % (lo, hi, sum(1 for k in bad if lo <= k < hi)))
