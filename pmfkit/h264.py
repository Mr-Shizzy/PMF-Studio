"""Annex B H.264 elementary stream -> access units."""
import re
from dataclasses import dataclass

_START = re.compile(rb"\x00\x00\x01")


@dataclass
class AccessUnit:
    data: bytes
    is_idr: bool
    has_sps: bool = False

    @property
    def gop_start(self):
        """Random access point that carries its own parameter sets (starts a new GOP pack in the PMF)."""
        return self.is_idr and self.has_sps


def _nal_spans(es):
    """[(begin_of_start_code, nal_type)] for every NAL; begin includes a leading zero byte."""
    out = []
    for m in _START.finditer(es):
        s = m.start()
        if s + 3 >= len(es):
            continue
        beg = s - 1 if s > 0 and es[s - 1] == 0 else s
        out.append((beg, es[s + 3] & 0x1F))
    return out


def _is_x264_version_sei(es, beg):
    """SEI NAL whose first message is user_data_unregistered (payload type 5): x264's version string."""
    s = es.find(b"\x00\x00\x01", beg) + 3
    return (es[s] & 0x1F) == 6 and es[s + 1] == 5


def _unit_from_segment(seg, strip_x264_sei=True):
    """one access unit from the bytes between two access unit delimiters (the first NAL of seg is the delimiter)"""
    cur, idr, sps = [], False, False
    nals = _nal_spans(seg)
    ends = [n[0] for n in nals[1:]] + [len(seg)]
    for (beg, typ), end in zip(nals, ends):
        if strip_x264_sei and typ == 6 and _is_x264_version_sei(seg, beg):
            continue
        cur.append(seg[beg:end])
        idr = idr or typ == 5
        sps = sps or typ == 7
    return AccessUnit(b"".join(cur), idr, sps)


def iter_access_units(path, strip_x264_sei=True, chunk=1 << 23):
    """The same access units as split_access_units, read from a file a piece at a time (memory use: one picture and a read buffer,
    however long the stream is)."""
    buf = b""
    first = True
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            buf += block
            at_end = not block
            nals = _nal_spans(buf)
            if first and nals and nals[0][1] != 9:
                raise ValueError("stream must start with an access unit delimiter (encode with x264 aud=1)")
            starts = [beg for beg, typ in nals if typ == 9]
            if not at_end:
                starts = starts[:-1] if len(starts) > 1 else []              # the last delimiter's unit may continue in the next piece
            if len(starts) >= 1 or at_end:
                bounds = starts + ([len(buf)] if at_end else [])
                if not at_end:
                    cut = [beg for beg, typ in nals if typ == 9][-1]
                    bounds = starts + [cut]
                for a, b in zip(bounds, bounds[1:]):
                    unit = _unit_from_segment(buf[a:b], strip_x264_sei)
                    if first and not unit.gop_start:
                        raise ValueError("first access unit must be an IDR picture with SPS/PPS")
                    first = False
                    yield unit
                buf = buf[bounds[-1]:] if not at_end else b""
            if at_end:
                break
    if first:
        raise ValueError("stream must start with an access unit delimiter (encode with x264 aud=1)")


def split_access_units(es, strip_x264_sei=True):
    """Split into access units; each starts with an AUD (NAL 9). x264 must be run with aud=1."""
    nals = _nal_spans(es)
    if not nals or nals[0][1] != 9:
        raise ValueError("stream must start with an access unit delimiter (encode with x264 aud=1)")
    ends = [n[0] for n in nals[1:]] + [len(es)]
    aus, cur, idr, sps = [], [], False, False
    for (beg, typ), end in zip(nals, ends):
        if typ == 9 and cur:
            aus.append(AccessUnit(b"".join(cur), idr, sps))
            cur, idr, sps = [], False, False
        if strip_x264_sei and typ == 6 and _is_x264_version_sei(es, beg):
            continue
        cur.append(es[beg:end])
        idr = idr or typ == 5
        sps = sps or typ == 7
    aus.append(AccessUnit(b"".join(cur), idr, sps))
    if not aus[0].gop_start:
        raise ValueError("first access unit must be an IDR picture with SPS/PPS")
    return aus
