"""Remux an ICON1.PMF from its own elementary streams with pmfkit and compare. usage: icon1_remux.py file.pmf [style] [version]"""
import sys
sys.path.insert(0, ".")
from pmfkit.demux import demux
from pmfkit import atrac3p
from pmfkit.mux import mux

f = sys.argv[1]
style = sys.argv[2] if len(sys.argv) > 2 else "A"
import json
KW = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
orig = open(f, "rb").read()
P, v, a, packs = demux(orig)
au = atrac3p.from_units(bytes(a)) if P.audio else None
new = mux(v, au, version=P.version, style=style, width=P.width, height=P.height, header_kib=P.video_buffer_kib, index_last_flag=0x80, **KW)
P2, v2, a2, packs2 = demux(new)
print("size", len(orig), len(new), "packs", len(packs), len(packs2))
print("video ES identical", v2 == v, " audio ES identical", bytes(a2) == bytes(a))
hdr_diff = [i for i in range(2048) if orig[i] != new[i]]
print("header bytes differing:", len(hdr_diff), [hex(i) for i in hdr_diff[:20]])
body_o, body_n = orig[2048:], new[2048:]
same = 0
bad = []
for k in range(min(len(packs), len(packs2))):
    x, y = body_o[k * 2048:(k + 1) * 2048], body_n[k * 2048:(k + 1) * 2048]
    if x[10:] == y[10:]:
        same += 1
    else:
        bad.append(k)
print("packs identical excluding SCR:", same, "of", min(len(packs), len(packs2)), " differing:", bad[:20])
scr = [(p1.scr27 - p2.scr27) for p1, p2 in zip(packs, packs2)]
print("SCR diff (orig-new) min/max:", min(scr), max(scr), " first:", scr[:6])
