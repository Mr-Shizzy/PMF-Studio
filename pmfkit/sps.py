"""Minimal H.264 SPS/PPS parser and PSP compatibility check.

Hardware finding (real PSP, 2026-10-30): a stream with num_ref_frames=3 does not play, num_ref_frames=1 does,
weighted prediction on or off both play. PPSSPP plays everything, so it cannot be used to validate a stream.
"""
import re

HIGH_PROFILES = (100, 110, 122, 244, 44, 83, 86, 118, 128)


class _Bits:
    def __init__(self, nal):
        self.b = re.sub(rb"\x00\x00\x03", b"\x00\x00", nal)     # drop emulation prevention bytes
        self.p = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.b[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.u(1) == 0:
            z += 1
        return (1 << z) - 1 + (self.u(z) if z else 0)


def parse_sps(nal):
    """nal = SPS NAL bytes starting with the NAL header byte."""
    r = _Bits(nal[1:])
    d = {"profile": r.u(8), "constraints": r.u(8), "level": r.u(8), "sps_id": r.ue()}
    if d["profile"] in HIGH_PROFILES:
        raise ValueError("High-profile SPS not supported (PSP needs Main/Baseline)")
    d["log2_max_frame_num"] = r.ue() + 4
    d["poc_type"] = r.ue()
    if d["poc_type"] == 0:
        d["log2_max_poc_lsb"] = r.ue() + 4
    d["num_ref_frames"] = r.ue()
    r.u(1)
    d["width"] = (r.ue() + 1) * 16
    r.ue()                                      # pic_height_in_map_units_minus1
    d["frame_mbs_only"] = r.u(1)
    return d, r


def parse_pps(nal):
    r = _Bits(nal[1:])
    r.ue()
    r.ue()
    cabac = r.u(1)
    r.u(1)
    r.ue()
    r.ue()
    r.ue()
    return {"cabac": cabac, "weighted_pred": r.u(1)}


def _nals(es):
    idx = [m.start() for m in re.finditer(rb"\x00\x00\x01", es)]
    for i, s in enumerate(idx):
        e = idx[i + 1] if i + 1 < len(idx) else len(es)
        yield es[s + 3:e].rstrip(b"\x00")


def stream_info(es):
    """First SPS/PPS of an Annex B stream as dicts (None if absent)."""
    sps = pps = None
    for n in _nals(es):
        t = n[0] & 0x1F
        if t == 7 and sps is None:
            sps = n
        elif t == 8 and pps is None:
            pps = n
        if sps and pps:
            break
    return (parse_sps(sps)[0] if sps else None), (parse_pps(pps) if pps else None)


def psp_problems(es, allow_b=False):
    """List of reasons this H.264 stream will not play on a real PSP (empty = looks fine).
    allow_b: accept B-frames (picture order count type 0), as commercial PSP movies have (LocoRoco 2: Main L2.1, 2 refs)."""
    sps, pps = stream_info(es)
    if sps is None:
        return ["no SPS found (encode with repeat-headers so every IDR carries SPS/PPS)"]
    out = []
    if sps["profile"] != 77:
        out.append("profile_idc is %d; use Main (77)" % sps["profile"])
    if sps["level"] > 21:
        out.append("level %.1f; use 2.1 or lower" % (sps["level"] / 10))
    if sps["num_ref_frames"] not in (1, 2):
        out.append("%d reference frames; the PSP played streams with 1 or 2 but not 3 (use x264 --ref 1)" % sps["num_ref_frames"])
    if sps["poc_type"] != 2 and not (allow_b and sps["poc_type"] == 0):
        out.append("picture order count type %d means B-frames; encode with --bframes 0 (or ask for B-frame support)" % sps["poc_type"])
    if not sps["frame_mbs_only"]:
        out.append("interlaced stream; use progressive")
    return out
