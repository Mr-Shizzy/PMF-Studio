"""Display order of H.264 access units (picture order count type 0), needed to give B-frame streams correct PTS/DTS."""
import re

from .sps import _Bits, stream_info


def _slice_header(au, sps):
    """(is_idr, nal_ref_idc, pic_order_cnt_lsb) of the first slice of an access unit."""
    for m in re.finditer(rb"\x00\x00\x01", au):
        nal_type = au[m.end()] & 0x1F
        if nal_type in (1, 5):
            r = _Bits(au[m.end() + 1:m.end() + 24])
            r.ue()                                          # first_mb_in_slice
            r.ue()                                          # slice_type
            r.ue()                                          # pps id
            r.u(sps["log2_max_frame_num"])
            if not sps["frame_mbs_only"]:
                raise ValueError("interlaced streams are not supported")
            if nal_type == 5:
                r.ue()                                      # idr_pic_id
            return nal_type == 5, (au[m.end()] >> 5) & 3, r.u(sps["log2_max_poc_lsb"])
    raise ValueError("access unit without a slice")


def display_indices(aus, sps):
    """Display position (in frames, counted from the start of the stream) of every access unit, given in decode order.
    Pictures are grouped per IDR (closed GOPs): the display positions of a GOP are the decode positions of the same set."""
    if sps["poc_type"] == 2:
        return list(range(len(aus)))
    if sps["poc_type"] != 0:
        raise ValueError("picture order count type %d is not supported" % sps["poc_type"])
    max_lsb = 1 << sps["log2_max_poc_lsb"]
    prev_msb, prev_lsb = 0, 0
    pocs = []
    for a in aus:
        idr, ref_idc, lsb = _slice_header(a.data, sps)
        if idr:
            prev_msb = prev_lsb = 0
        if lsb < prev_lsb and prev_lsb - lsb >= max_lsb // 2:
            msb = prev_msb + max_lsb
        elif lsb > prev_lsb and lsb - prev_lsb > max_lsb // 2:
            msb = prev_msb - max_lsb
        else:
            msb = prev_msb
        pocs.append((idr, msb + lsb))
        if ref_idc:
            prev_msb, prev_lsb = msb, lsb
    out, base, start = [], 0, 0
    for i in range(len(pocs) + 1):
        if i == len(pocs) or (pocs[i][0] and i > start):
            order = sorted(range(start, i), key=lambda k: pocs[k][1])
            disp = [0] * (i - start)
            for rank, k in enumerate(order):
                disp[k - start] = base + rank
            out += disp
            base += i - start
            start = i
    return out


def reference_flags(aus):
    """GOP index flag per access unit: 0x80 for a reference picture, 0 for a B-frame nobody references."""
    out = []
    for a in aus:
        for m in re.finditer(rb"\x00\x00\x01", a.data):
            if a.data[m.end()] & 0x1F in (1, 5):
                out.append(0x80 if (a.data[m.end()] >> 5) & 3 else 0)
                break
        else:
            raise ValueError("access unit without a slice")
    return out
