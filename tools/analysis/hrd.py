"""Print the VUI / HRD fields of the first SPS of PMFs. usage: python tools/analysis/hrd.py a.pmf b.pmf ..."""
import sys
sys.path.insert(0, ".")
from pmfkit import demux, sps


def hrd(r):
    n = r.ue() + 1
    bs, cs = r.u(4), r.u(4)
    out = []
    for _ in range(n):
        out.append(((r.ue() + 1) * 2 ** (6 + bs), (r.ue() + 1) * 2 ** (4 + cs), r.u(1)))
    lens = [r.u(5) + 1 for _ in range(4)]
    return dict(cpb=out, init_delay_len=lens[0], removal_len=lens[1], dpb_len=lens[2], toff_len=lens[3])


def vui(nal):
    d, r = sps.parse_sps(nal)
    if not d["frame_mbs_only"]:
        r.u(1)
    d["direct_8x8"] = r.u(1)
    if r.u(1):
        for _ in range(4): r.ue()
    if not r.u(1):
        return d
    if r.u(1):
        if r.u(8) == 255: r.u(32)
    if r.u(1): r.u(1)
    if r.u(1):
        r.u(3); d["full_range"] = r.u(1)
        if r.u(1): r.u(24)
    if r.u(1): r.ue(); r.ue()
    if r.u(1):
        d["timing"] = (r.u(32), r.u(32), r.u(1))
    nalh = r.u(1)
    if nalh: d["nal_hrd"] = hrd(r)
    vclh = r.u(1)
    if vclh: d["vcl_hrd"] = hrd(r)
    if nalh or vclh: d["low_delay"] = r.u(1)
    d["pic_struct"] = r.u(1)
    return d


for f in sys.argv[1:]:
    P, v, a, _ = demux.demux(open(f, "rb").read())
    nal = next(n for n in sps._nals(v) if n[0] & 0x1F == 7)
    print(f)
    for k, val in vui(nal).items():
        print("   ", k, val)
