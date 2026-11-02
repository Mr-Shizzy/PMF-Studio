"""Dump the structure of an ICON1.PMF: pack layout, SPS, AUs, audio units. usage: python tools/analysis/icon1.py file.pmf"""
import sys
sys.path.insert(0, ".")
from pmfkit import demux as D, sps, h264, atrac3p

pmf = open(sys.argv[1], "rb").read()
P, v, a, packs = D.demux(pmf)
print("params:", P)
print("file", len(pmf), "packs", len(packs), "video ES", len(v), "audio ES", len(a))
print("stream info:", sps.stream_info(v))
print("psp problems:", sps.psp_problems(v))
aus = h264.split_access_units(v, strip_x264_sei=False)
print("AUs", len(aus), "IDR at", [i for i, x in enumerate(aus) if x.is_idr], "SPS at", [i for i, x in enumerate(aus) if x.has_sps])
print("AU sizes first 12:", [len(x.data) for x in aus[:12]], " max", max(len(x.data) for x in aus), " total", sum(len(x.data) for x in aus))
for pk in packs:
    desc = []
    for it in pk.items:
        n = {0xE0: "V", 0xBD: "A", 0xBB: "SYS", 0xBF: "IDX", 0xBE: "PAD"}.get(it.sid, hex(it.sid))
        s = "%s(%d" % (n, it.length)
        if it.pts is not None: s += " pts=%d" % it.pts
        if it.dts is not None: s += " dts=%d" % it.dts
        if it.ext: s += " ext=" + it.ext.hex()
        if it.sid == 0xBB: s += " " + it.payload.hex()
        if it.sid == 0xBD: s += " ptr=%d" % int.from_bytes(it.payload[2:4], "big")
        desc.append(s + ")")
    print(pk.index, pk.scr27, " ".join(desc))
