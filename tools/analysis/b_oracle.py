"""Remux a B-frame PMF (LocoRoco 2) from its own streams with pmfkit (allow_b=True) and compare with the original.
usage: python tools/analysis/b_oracle.py file.pmf [style]"""
import bisect
import collections
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
new = mux(v, au, version="0012", style=style, width=P.width, height=P.height, header_kib=P.video_buffer_kib, allow_b=True)
P2, v2, a2, packs2 = demux(new)
print("size", len(orig), len(new), "packs", len(packs), len(packs2), " video ES identical", v2 == v, " audio ES identical", bytes(a2) == bytes(a))


def stamps(pks):
    """(AU index, flags, pts, dts) of every stamped video PES"""
    es, out, raw = bytearray(), [], []
    for k, pk in enumerate(pks):
        for i in pk.items:
            if i.sid == 0xE0:
                if i.pts is not None:
                    raw.append((len(es), i.flags, i.pts, i.dts))
                es += i.payload
    aus = split_access_units(bytes(es), strip_x264_sei=False)
    starts, o = [], 0
    for x in aus:
        starts.append(o)
        o += len(x.data)
    return [(bisect.bisect_left(starts, off), fl, p, d) for off, fl, p, d in raw]


so, sn = stamps(packs), stamps(packs2)
print("stamped PES: original %d, ours %d" % (len(so), len(sn)))
mo = {x[0]: x for x in so}
mn = {x[0]: x for x in sn}
common = sorted(set(mo) & set(mn))
same = sum(1 for k in common if mo[k][2:] == mn[k][2:])
print("stamped on the same AU: %d; of those identical PTS/DTS: %d" % (len(common), same))
print("PTS/DTS wrong on any of OUR stamps vs the original's values for the same AU:", [k for k in common if mo[k][2:] != mn[k][2:]][:10])
print("first stamped AUs  orig:", [x[0] for x in so[:20]])
print("                   ours:", [x[0] for x in sn[:20]])
bo, bn = orig[2048:], new[2048:]
n = min(len(packs), len(packs2))
same_p = sum(1 for k in range(n) if bo[k * 2048 + 10:(k + 1) * 2048] == bn[k * 2048 + 10:(k + 1) * 2048])
print("packs identical excluding SCR: %d of %d" % (same_p, n))
# GOP index packs
def gop_idx(pks):
    return [bytes(i.payload) for pk in pks for i in pk.items if i.sid == 0xBF]
go, gn = gop_idx(packs), gop_idx(packs2)
print("GOP index blocks: %d vs %d; identical: %d" % (len(go), len(gn), sum(1 for x, y in zip(go, gn) if x == y)))
print("first differing GOP index (flags/sizes only):", next(((i, x[:18].hex(' '), y[:18].hex(' ')) for i, (x, y) in enumerate(zip(go, gn)) if x != y), None))
