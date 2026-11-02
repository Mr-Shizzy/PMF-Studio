import os
import unittest

from pmfkit.h264 import AccessUnit
from pmfkit.mux import _layout_video
from pmfkit.poc import display_indices, reference_flags

SPS = {"poc_type": 0, "log2_max_frame_num": 4, "log2_max_poc_lsb": 4, "frame_mbs_only": 1}


class _W:
    def __init__(self):
        self.bits = []

    def u(self, n, v):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def ue(self, v):
        v += 1
        n = v.bit_length()
        self.u(n - 1, 0)
        self.u(n, v)

    def bytes(self):
        b = self.bits + [1]
        while len(b) % 8:
            b.append(0)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def au(kind, poc, ref, idr=False):
    """access unit: AUD + one slice header; kind 0 P, 1 B, 2 I; poc = picture order count (2 per frame)"""
    w = _W()
    w.ue(0)
    w.ue({0: 5, 1: 6, 2: 7}[kind])
    w.ue(0)
    w.u(4, 0)
    if idr:
        w.ue(0)
    w.u(4, poc % 16)
    nal = bytes([(ref << 5) | (5 if idr else 1)]) + w.bytes() + b"\x80" * 40
    return AccessUnit(b"\x00\x00\x01\x09\x10" + b"\x00\x00\x01" + nal, idr, idr)


class BFrameTests(unittest.TestCase):
    def test_display_order_ipbpb(self):
        aus = [au(2, 0, 3, True), au(0, 4, 2), au(1, 2, 0), au(0, 8, 2), au(1, 6, 0)]
        self.assertEqual(display_indices(aus, SPS), [0, 2, 1, 4, 3])
        self.assertEqual(reference_flags(aus), [0x80, 0x80, 0, 0x80, 0])

    def test_display_order_closed_gops_and_wrap(self):
        # second GOP starts at decode position 5; POC lsb wraps every 8 frames (4 bits, 2 per frame)
        gop = [au(2, 0, 3, True)]
        for i in range(1, 11):
            gop.append(au(0, (2 * i) % 16, 2))
        aus = gop + [au(2, 0, 3, True), au(0, 4, 2), au(1, 2, 0)]
        disp = display_indices(aus, SPS)
        self.assertEqual(disp[:11], list(range(11)))
        self.assertEqual(disp[11:], [11, 13, 12])

    def test_stamps_follow_decode_and_display_clock(self):
        aus = [au(2, 0, 3, True), au(0, 4, 2), au(1, 2, 0)] + [au(0, 4 + 4 * i, 2) if i % 2 == 0 else au(1, 2 + 4 * i, 0) for i in range(1, 40)]
        disp = display_indices(aus, SPS)
        self.assertEqual(max(k - d for k, d in enumerate(disp)), 1)
        entries, gops, _ = _layout_video(aus, "B", 251, disp=disp)
        self.assertTrue(entries)


@unittest.skipUnless(os.path.exists("Commercial PMF samples/Loco Roco 2/story_10.pmf"), "commercial sample not present")
class OracleTests(unittest.TestCase):
    def test_locoroco_stamps_match(self):
        import bisect
        from pmfkit import atrac3p
        from pmfkit.demux import demux
        from pmfkit.h264 import split_access_units
        from pmfkit.mux import mux
        orig = open("Commercial PMF samples/Loco Roco 2/story_10.pmf", "rb").read()
        P, v, a, packs = demux(orig)
        new = mux(v, atrac3p.from_units(bytes(a)), version="0012", style="B", width=P.width, height=P.height,
                  header_kib=P.video_buffer_kib, allow_b=True)
        P2, v2, a2, packs2 = demux(new)
        self.assertEqual(v2, v)
        self.assertEqual(len(packs2), len(packs))

        def stamps(pks):
            es, raw = bytearray(), []
            for pk in pks:
                for i in pk.items:
                    if i.sid == 0xE0:
                        if i.pts is not None:
                            raw.append((len(es), i.pts, i.dts))
                        es += i.payload
            aus = split_access_units(bytes(es), strip_x264_sei=False)
            starts, o = [], 0
            for x in aus:
                starts.append(o)
                o += len(x.data)
            return {bisect.bisect_left(starts, off): (p, d) for off, p, d in raw}

        so, sn = stamps(packs), stamps(packs2)
        common = set(so) & set(sn)
        self.assertGreater(len(common), 15)
        self.assertTrue(all(so[k] == sn[k] for k in common))


if __name__ == "__main__":
    unittest.main()
