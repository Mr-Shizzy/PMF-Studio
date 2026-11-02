"""Build a PMF: PSMF header + MPEG-PS in 2048-byte packs (H.264 video, optional ATRAC3plus audio).

Rules reproduced from Sony-composer PMFs (see RESEARCH_NOTES.md):
  * every GOP (IDR with SPS/PPS) starts a new pack: system header + 0xBF GOP index + video PES with PTS/DTS (+P-STD ext)
  * later video PES carry PTS/DTS only when an access unit starts in them >=16 frames after the last stamp
  * the last pack of a stream is filled with a 0xBE padding packet (or PES header stuffing if <6 bytes are left)
  * audio PES payload = 00 00 <ptr> + audio bytes; ptr = distance to the next 8-byte audio unit header (0xFFFF if none)
  * SCR advances 44236.8 (27 MHz) per pack; a video pack is not sent earlier than DTS(AU following it) - 89925,
    an audio pack waits until the 4096-byte audio buffer has room (units leave it at their PTS)
"""
import bisect
from fractions import Fraction

from . import psmf
from .h264 import split_access_units
from .poc import display_indices, reference_flags
from .sps import psp_problems, stream_info

PACK = 2048
FRAME = 3003
FIRST_PTS = 90000
SCR_START = 3044236
SCR_STEP = Fraction(2048 * 27000000, 25000 * 50)          # 44236.8 ticks of 27 MHz per pack
VIDEO_LEAD = 89925          # fitted on Sony PMFs: SCR >= DTS(AU after the pack) - 89925
AUDIO_BUF = 4096            # audio P-STD buffer
AUDIO2_FLOOR = 16046        # Sony files send the 2nd audio pack at SCR 16046 (90 kHz) regardless of content
STAMP_EVERY = 16
MAX_AUDIO_UNIT = PACK - 14 - 9 - 5 - 4        # an audio unit (8-byte header + frame) must fit in one pack
AUDIO_PTS_BASE = Fraction(8506956, 100)                     # first audio unit PTS (fitted: matches Sony to +-1 tick)
AUDIO_UNIT_TICKS = Fraction(2048 * 90000, 44100)            # one ATRAC3plus frame in 90 kHz ticks

# ICON1.PMF as made by the same composer (fitted on two commercial ICON1s, see RESEARCH_NOTES section 26): 144x80,
# older stream style A with a 0012 header, a GOP-index whose last entry is flagged, and slightly different pacing.
ICON1 = dict(width=144, height=80, version="0012", style="A", index_last_flag=0x80,
             video_lead=80930, audio_pts_base=Fraction(858202, 10))
ICON1_GOP = 30              # frames; both samples use 1 s GOPs
ICON1_VIDEO_KBPS = 100      # samples: ~95 kbps (no audio) and ~70 kbps (with audio)
ICON1_AUDIO_KBPS = 64       # Bomberman's built-in audio: ATRAC3plus 64 kbps (376-byte frames)
# ICON1.PMF size, real XMB (notes sections 34-38, 46): 512,000 bytes (500 KiB) plays, 514,048 shows nothing, and no
# PMF size exists in between (files are multiples of 2048). With an SND0.AT3 present the two must total 512,000
# together (notes section 49), so ICON1 + SND0 share this budget.
ICON1_VERIFIED_OK = 512000
ICON1_VERIFIED_FAIL = 514048
ICON1_MAX_BYTES = 512000     # size the tool fits to by default (the largest file verified on hardware)

# Stream styles seen in Sony-composer PMFs. The PSMF header version is independent of the style: the user's shipped
# gameboots are mostly style B streams with a "0012" header.
#   A: older composer (the game's own movies), 495 KiB video buffer     B: newer composer / pspbuild, 251 KiB
PROFILES = {
    "A": dict(sys_flag=0x40, sys_audio_kib=4, audio_ext=b"\x1e\x40\x20", video_kib=495),
    "B": dict(sys_flag=0x80, sys_audio_kib=8, audio_ext=b"\x1e\x60\x04", video_kib=251),
}
HEADER_KIB = {"0012": 495, "0014": 251}                     # P-STD value Sony/MPStoPMF headers carry per version


def ts(prefix, v):
    return bytes([(prefix << 4) | (((v >> 30) & 7) << 1) | 1, (v >> 22) & 0xFF,
                  (((v >> 15) & 0x7F) << 1) | 1, (v >> 7) & 0xFF, ((v & 0x7F) << 1) | 1])


def pack_header(scr27):
    base, ext = divmod(scr27, 300)
    b = [0x44 | (((base >> 30) & 7) << 3) | ((base >> 28) & 3),
         (base >> 20) & 0xFF,
         (((base >> 15) & 0x1F) << 3) | 4 | ((base >> 13) & 3),
         (base >> 5) & 0xFF,
         ((base & 0x1F) << 3) | 4 | ((ext >> 7) & 3),
         ((ext & 0x7F) << 1) | 1]
    rate = (psmf.MUX_RATE << 2) | 3
    return b"\x00\x00\x01\xba" + bytes(b) + rate.to_bytes(3, "big") + b"\xf8"


def system_header(style, video_kib):
    prof = PROFILES[style]
    return (b"\x00\x00\x01\xbb\x00\x0c\x80\xc3\x51" + bytes([prof["sys_flag"]]) + b"\xf0\x7f"
            + b"\xb9" + (0xE000 | video_kib).to_bytes(2, "big")
            + b"\xbd" + (0xE000 | prof["sys_audio_kib"]).to_bytes(2, "big"))


def pes(sid, flags2, fields, payload, room):
    """One PES packet plus padding so the result is exactly `room` bytes.
    `fields` = PES header data (PTS/DTS/extension). Gaps of 1-5 bytes become header stuffing."""
    rest = room - (6 + 3 + len(fields) + len(payload))
    assert rest >= 0, rest
    pad = b""
    if 0 < rest < 6:
        fields, rest = fields + b"\xff" * rest, 0
    elif rest:
        pad = b"\x00\x00\x01\xbe" + (rest - 6).to_bytes(2, "big") + b"\xff" * (rest - 6)
    body = bytes([0x81, flags2, len(fields)]) + fields + payload
    return b"\x00\x00\x01" + bytes([sid]) + len(body).to_bytes(2, "big") + body + pad


def gop_index(sizes, pack_idx, last_flag=0, flags=None):
    n = len(sizes)
    first4 = pack_idx[:4]
    first4 = first4 + [first4[-1]] * (4 - len(first4))
    b = b"\x01\xe0" + b"".join(i.to_bytes(2, "big") for i in first4) + b"\x00\x00\x00\x00"
    b += (2 + 4 * n).to_bytes(2, "big") + n.to_bytes(2, "big")
    for i, s in enumerate(sizes):
        flag = flags[i] if flags is not None else (0x0080 if i < n - 1 else last_flag)    # B-frame streams: 0x80 = reference picture
        b += flag.to_bytes(2, "big") + s.to_bytes(2, "big")
    return b


def gop_index_len(npics):
    return 18 + 4 * npics


class _Entry:
    """One output pack before SCR assignment."""
    __slots__ = ("kind", "body", "floor", "gop", "cum_end", "gop_start")


def _layout_video(aus, style, video_kib, video_lead=VIDEO_LEAD, disp=None):
    """Split the access units into video packs. Independent of audio.
    disp = display position of every access unit (given in decode order); default = same order, i.e. no B-frames.
    DTS = decode position - shift (frames), PTS = display position; a PES stamp carries only the PTS when the two are equal."""
    if disp is None:
        disp = list(range(len(aus)))
    shift = max(1, max(k - d for k, d in enumerate(disp)))

    def pts(k):
        return FIRST_PTS + FRAME * disp[k]

    def dts(k):
        return FIRST_PTS + FRAME * (k - shift)

    sysh = system_header(style, video_kib)
    vext = b"\x1e" + (0x6000 | video_kib).to_bytes(2, "big")
    idr = [i for i, a in enumerate(aus) if a.gop_start] + [len(aus)]
    entries, gops = [], []
    for gi in range(len(idr) - 1):
        a0, a1 = idr[gi], idr[gi + 1]
        data = b"".join(a.data for a in aus[a0:a1])
        starts, ends, o = [], [], 0
        for a in aus[a0:a1]:
            starts.append(o)
            o += len(a.data)
            ends.append(o)
        npics = a1 - a0
        last_stamp, pos, first = a0, 0, True
        mine = []
        while pos < len(data):
            fields, flags2 = b"", 0
            if first:
                room = PACK - 14 - len(sysh) - (6 + gop_index_len(npics))
                fields = ts(3, pts(a0)) + ts(1, dts(a0)) + vext
                flags2 = 0xC1
            else:
                room = PACK - 14
                j = bisect.bisect_left(starts, pos)
                # an AU must start inside the payload that is left once the 10 PTS/DTS bytes are added
                if j < npics and starts[j] < pos + room - 9 - 10 and (a0 + j) - last_stamp >= STAMP_EVERY:
                    k = a0 + j
                    if pts(k) == dts(k):
                        fields, flags2 = ts(2, pts(k)), 0x80
                    else:
                        fields, flags2 = ts(3, pts(k)) + ts(1, dts(k)), 0xC0
                    last_stamp = k
            end = min(pos + room - 9 - len(fields), len(data))
            e = _Entry()
            e.kind, e.gop, e.gop_start = "v", gi, first
            if end < len(data):
                kn = a0 + bisect.bisect_right(starts, end) - 1      # AU holding the byte after this pack
            else:
                kn = a1 if a1 < len(aus) else None
            e.floor = None if kn is None else dts(kn) - video_lead
            e.body = pes(0xE0, flags2, fields, data[pos:end], room)
            e.cum_end = end
            mine.append(e)
            entries.append(e)
            pos, first = end, False
        gops.append((a0, a1, mine, ends))
    return entries, gops, sysh


class _AudioFeeder:
    def __init__(self, audio, style, pts_base=AUDIO_PTS_BASE, second_floor=AUDIO2_FLOOR):
        self.pts_base, self.second_floor = pts_base, second_floor
        self.es = b"".join(audio.units())
        self.U = audio.unit_bytes
        self.ext = PROFILES[style]["audio_ext"]
        self.g = 0
        self.count = 0

    def done(self):
        return self.g >= len(self.es)

    def next_floor(self):
        """90 kHz time at which the audio buffer has room for the next pack; None = right away."""
        if self.count == 1:
            return self.second_floor
        need = self.g + PACK - 14 - 9 - 5 - 4 - AUDIO_BUF
        if need <= 0:
            return None
        i = -(-need // self.U) - 1                      # last unit that must have been decoded
        return int(self.pts_base + i * AUDIO_UNIT_TICKS)

    def build(self, with_ext):
        hl = 8 if with_ext else 5
        take = min(len(self.es) - self.g, PACK - 14 - 9 - hl - 4)
        ptr = (-self.g) % self.U
        e = _Entry()
        e.kind, e.gop, e.gop_start, e.cum_end, e.floor = "a", None, False, 0, None
        if ptr < take:
            payload = b"\x00\x00" + ptr.to_bytes(2, "big") + self.es[self.g:self.g + take]
            pts = int(self.pts_base + ((self.g + ptr) // self.U) * AUDIO_UNIT_TICKS)
            fields = ts(2, pts) + (self.ext if with_ext else b"")
            e.body = pes(0xBD, 0x81 if with_ext else 0x80, fields, payload, PACK - 14)
        else:                                    # no unit header starts in this pack (stream tail): no PTS, ptr 0xFFFF
            payload = b"\x00\x00\xff\xff" + self.es[self.g:self.g + take]
            e.body = pes(0xBD, 0x00, b"", payload, PACK - 14)
        self.g += take
        self.count += 1
        return e


def mux(video_es, audio=None, version="0012", style="B", width=480, height=272, header_kib=None, strict=True,
        index_last_flag=0, video_lead=VIDEO_LEAD, audio_pts_base=AUDIO_PTS_BASE, audio2_floor=AUDIO2_FLOOR, allow_b=False):
    """video_es: Annex B H.264 (AUD, SPS/PPS on every IDR). No B-frames unless allow_b=True (picture order count type 0,
    2 reference frames, as in LocoRoco 2; untested for our own output on hardware). audio: Atrac3pStream or None. -> PMF bytes.
    version = PSMF header version ("0012" gameboot-safe); style = stream style "A"/"B" (see PROFILES)."""
    if style not in PROFILES:
        raise ValueError("unknown stream style %r (use A or B)" % style)
    if audio is not None and audio.unit_bytes > MAX_AUDIO_UNIT and strict:
        raise ValueError("audio frames are %d bytes (%.0f kbps): too big to fit one pack, the PSP plays no sound "
                         "(hardware test: 352 kbps silent, 128/96 kbps fine); use 320 kbps or lower"
                         % (audio.frame_bytes, audio.kbps))
    problems = psp_problems(video_es, allow_b)
    if problems and strict:
        raise ValueError("this video will not play on a real PSP:\n  - " + "\n  - ".join(problems))
    if header_kib is None:
        header_kib = HEADER_KIB[version]
    video_kib = PROFILES[style]["video_kib"]
    aus = split_access_units(video_es)
    for a in aus:
        if len(a.data) > 0xFFFF:
            raise ValueError("a picture is larger than 65535 bytes; lower the bitrate/quality")
    disp = ref_flags = None
    if allow_b:
        sps, _ = stream_info(video_es)
        disp = display_indices(aus, sps)
        ref_flags = reference_flags(aus)
    ventries, gops, sysh = _layout_video(aus, style, video_kib, video_lead, disp)

    # ---- merge video and audio packs, assigning SCR as we go (audio wins ties: it is "due")
    feeder = _AudioFeeder(audio, style, audio_pts_base, audio2_floor) if audio is not None else None
    order, scrs, vi, ext_pending = [], [], 0, True
    cur = None

    def when(floor):
        t = SCR_START if cur is None else cur + SCR_STEP
        return t if floor is None else max(t, Fraction(floor * 300))

    while vi < len(ventries) or (feeder and not feeder.done()):
        have_a = feeder is not None and not feeder.done()
        tv = when(ventries[vi].floor) if vi < len(ventries) else None
        ta = when(feeder.next_floor()) if have_a and cur is not None else None
        if tv is not None and (not have_a or cur is None or tv < ta):
            e, t = ventries[vi], tv
            ext_pending = ext_pending or e.gop_start
            vi += 1
        else:
            e, t = feeder.build(ext_pending), ta
            ext_pending = False
        order.append(e)
        scrs.append(int(t))
        cur = t

    # ---- GOP index needs final pack positions
    pos_of = {id(e): p for p, e in enumerate(order)}
    bodies = []
    for p, e in enumerate(order):
        body = e.body
        if e.kind == "v" and e.gop_start:
            a0, a1, mine, ends = gops[e.gop]
            idx = []
            for end in ends[:4]:
                t = next(m for m in mine if m.cum_end >= end)
                idx.append(pos_of[id(t)] - p)
            bf = gop_index([len(a.data) for a in aus[a0:a1]], idx, index_last_flag, None if ref_flags is None else ref_flags[a0:a1])
            assert len(bf) == gop_index_len(a1 - a0)
            body = sysh + b"\x00\x00\x01\xbf" + len(bf).to_bytes(2, "big") + bf + body
        bodies.append(body)

    stream = bytearray()
    for scr, body in zip(scrs, bodies):
        pk = pack_header(scr) + body
        assert len(pk) == PACK, len(pk)
        stream += pk
    hdr = psmf.build_header(psmf.Params(
        stream_bytes=len(stream), last_pts=FIRST_PTS + FRAME * len(aus), width=width, height=height,
        version=version, first_pts=FIRST_PTS, video_buffer_kib=header_kib, audio=audio is not None))
    return hdr + bytes(stream)
