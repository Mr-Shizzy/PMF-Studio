"""Build a PMF: PSMF header + MPEG-PS in 2048-byte packs (H.264 video, optional ATRAC3plus audio).

Rules reproduced from Sony-composer PMFs (see RESEARCH_NOTES.md):
  * every GOP (IDR with SPS/PPS) starts a new pack: system header + 0xBF GOP index + video PES with PTS/DTS (+P-STD ext)
  * later video PES carry PTS/DTS only when an access unit starts in them >=16 frames after the last stamp
  * the last pack of a stream is filled with a 0xBE padding packet (or PES header stuffing if <8 bytes are left)
  * audio PES payload = 00 00 <ptr> + audio bytes; ptr = distance to the next 8-byte audio unit header (0xFFFF if none)
  * SCR advances 44236.8 (27 MHz) per pack; a video pack is not sent earlier than DTS(AU following it) - 89925,
    an audio pack waits until the 4096-byte audio buffer has room (units leave it at their PTS)
"""
import bisect
import os
from fractions import Fraction

from . import psmf
from .h264 import split_access_units
from .poc import display_indices, reference_flags
from .sps import psp_problems, stream_info

PACK = 2048
FRAME = 3003
FIRST_PTS = 90000
SCR_START = Fraction(30442368, 10)                         # 3,044,236.8 = 3,000,000 + one step; the written value is the floor (Sony files: 3044236, 3088473, 3132710 ...)
SCR_STEP = Fraction(2048 * 27000000, 25000 * 50)          # 44236.8 ticks of 27 MHz per pack
VIDEO_LEAD = 90000          # fitted on Sony PMFs: SCR >= DTS(AU after the pack) - 89925
MIN_VIDEO_LEAD = 35000      # a picture's first byte is never sent later than DTS - this (Sony movies: smallest lead seen 35,814)
AUDIO_BUF = 4096            # audio P-STD buffer
AUDIO_LOOKAHEAD = 90000     # STD_delay Composer writes (90 kHz ticks)
AUDIO2_FLOOR = 16046        # the old fitted constant for the 2nd audio pack's time (90 kHz); no longer used: pass audio2_floor=AUDIO2_FLOOR to get it back (the formula in _AudioFeeder.next_floor is the default)
STAMP_EVERY = 16
CLOSE_AFTER = 18            # pictures since the last time stamp after which a pending short pack is closed for the next picture (0 = never)
# Largest single picture allowed. The GOP index has a 21-bit size field and the stream's video buffer is 251 KiB (495 KiB in version 0012), so the
# real ceiling is far higher; 95,545 bytes is the largest picture seen in a retail movie that plays on a PSP (Coded Arms sector00.pmf), so it is the proven bound.
MAX_PICTURE = 95545
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


def _on_clock(t, earliest):
    """the first pack time at or after `earliest` on the pack clock that starts at t (Sony's muxer only sends packs on its clock grid)"""
    if earliest <= t:
        return t
    return t + -((t - earliest) // SCR_STEP) * SCR_STEP


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


def system_header(style, video_kib, audio_kib=None):
    """audio_kib: the BD (audio) buffer bound; default the style's own (8). Movies of version 0015 (Hammerin Hero, Ice Road Truckers, Hot Shots
    Shorties) carry 776 there."""
    prof = PROFILES[style]
    return (b"\x00\x00\x01\xbb\x00\x0c\x80\xc3\x51" + bytes([prof["sys_flag"]]) + b"\xf0\x7f"
            + b"\xb9" + (0xE000 | video_kib).to_bytes(2, "big")
            + b"\xbd" + (0xE000 | (audio_kib or prof["sys_audio_kib"])).to_bytes(2, "big"))


def pes(sid, flags2, fields, payload, room):
    """One PES packet plus padding so the result is exactly `room` bytes.
    `fields` = PES header data (PTS/DTS/extension). Gaps of 1-7 bytes become header stuffing, 8 or more a padding packet
    (the rule in Sony's MpsMux.dll; retail movies hold no padding packet with a payload of 0 or 1 byte)."""
    rest = room - (6 + 3 + len(fields) + len(payload))
    assert rest >= 0, rest
    pad = b""
    if 0 < rest < 8:
        fields, rest = fields + b"\xff" * rest, 0
    elif rest:
        pad = b"\x00\x00\x01\xbe" + (rest - 6).to_bytes(2, "big") + b"\xff" * (rest - 6)
    body = bytes([0x81, flags2, len(fields)]) + fields + payload
    return b"\x00\x00\x01" + bytes([sid]) + len(body).to_bytes(2, "big") + body + pad


def index_flags(npics, last_flag=0, flags=None):
    """The flag of every picture in a GOP index: 0x80 = reference picture (a picture nobody references has 0)."""
    return list(flags) if flags is not None else [0x0080] * (npics - 1) + [last_flag]


def reference_pictures(flags):
    """The first four reference pictures of a GOP (positions in decode order): the pictures whose last pack the GOP index lists."""
    return [i for i, f in enumerate(flags) if f & 0x80 or i == 0][:4]      # the GOP's first picture is an IDR picture, always a reference


def gop_index(sizes, slots, last_flag=0, flags=None):
    """The private-stream-2 payload at the start of a GOP. `slots` = for the first (up to four) reference pictures, the pack where the picture ends,
    counted from the GOP's first pack; a missing slot is 0xFFFF. Per picture: 4 bytes = the flag byte(s) and the size (21 bits; the top 5 sit in
    the flag's low bits). Read from Sony's MpsMux.dll and checked on retail movies (notes 130, 131)."""
    n = len(sizes)
    flags = index_flags(n, last_flag, flags)
    first4 = list(slots[:4]) + [0xFFFF] * (4 - len(slots[:4]))
    b = b"\x01\xe0" + b"".join(i.to_bytes(2, "big") for i in first4) + b"\x00\x00\x00\x00"
    b += (2 + 4 * n).to_bytes(2, "big") + n.to_bytes(2, "big")
    for flag, s in zip(flags, sizes):
        b += (flag | (s >> 16)).to_bytes(2, "big") + (s & 0xFFFF).to_bytes(2, "big")
    return b


def gop_index_len(npics):
    return 18 + 4 * npics


class _Entry:
    """One output pack before SCR assignment."""
    __slots__ = ("kind", "body", "floor", "gop", "cum_end", "gop_start", "pos")


def _layout_video(aus, style, video_kib, video_lead=VIDEO_LEAD, disp=None, audio_kib=None):
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

    sysh = system_header(style, video_kib, audio_kib)
    vext = b"\x1e" + (0x6000 | video_kib).to_bytes(2, "big")
    idr = [i for i, a in enumerate(aus) if a.gop_start] + [len(aus)]
    entries, gops = [], []
    for gi in range(len(idr) - 1):
        a0, a1 = idr[gi], idr[gi + 1]
        mine, ends = _layout_gop(gi, a0, aus[a0:a1], a1 < len(aus), pts, dts, sysh, vext, video_lead)
        entries.extend(mine)
        gops.append((a0, a1, mine, ends))
    return entries, gops, sysh


def _layout_gop(gi, a0, gop_aus, has_next, pts, dts, sysh, vext, video_lead):
    """The video packs of one GOP (a0 = index of its first access unit, has_next = another GOP follows) -> (entries, cumulative end of every AU)"""
    a1 = a0 + len(gop_aus)
    data = b"".join(a.data for a in gop_aus)
    starts, ends, o = [], [], 0
    for a in gop_aus:
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
        closed = False
        if not first and CLOSE_AFTER:
            # time-based packing: a pack that already holds the start of a picture is closed short when a later picture arrives that is long
            # overdue for a time stamp; that picture then starts a new pack (and a new stamped PES). Retail: 22 of 22 mid-GOP padded packs.
            for q in range(bisect.bisect_left(starts, pos) + 1, npics):
                if starts[q] >= end:
                    break
                if (a0 + q) - last_stamp >= CLOSE_AFTER:
                    end = starts[q]
                    closed = True
                    break
        e = _Entry()
        e.kind, e.gop, e.gop_start, e.pos = "v", gi, first, None
        if end < len(data):
            kn = a0 + bisect.bisect_right(starts, end) - 1      # AU holding the byte after this pack
            if starts[kn - a0] == end and not closed:
                kn -= 1                                          # a full pack that ends exactly where a picture ends does not wait for the next one (retail: 6 of 6; padded packs always wait)
        else:
            kn = a1 if has_next else None
        e.floor = dts(a1 - 1) - video_lead if kn is None else dts(kn) - video_lead      # the last pack of the movie waits for the last picture's own turn
        if kn is not None:
            # A pack that holds many tiny pictures (a still scene at a very low bitrate) must not wait for the LAST of them: the picture it
            # starts in would reach the decoder late (up to 0.84 s in a 67 s Gun Showdown intro shrunk to the lowest picture quality, and the
            # PSP froze there). Sony's own movies never deliver a picture later than MIN_VIDEO_LEAD before its decode time (smallest lead over
            # 38 movies: 35,814 ticks); ordinary packs end in the picture they start in or the next one and are not touched by this.
            e.floor = min(e.floor, dts(a0 + bisect.bisect_right(starts, pos) - 1) - MIN_VIDEO_LEAD)
        e.body = pes(0xE0, flags2, fields, data[pos:end], room)
        e.cum_end = end
        mine.append(e)
        pos, first = end, False
    return mine, ends


class _AudioFeeder:
    def __init__(self, audio, style, pts_base=AUDIO_PTS_BASE, second_floor=None):
        """audio: one Atrac3pStream, or a list of them for a movie with several sound tracks (languages). Retail files (007 From Russia With
        Love) send each audio pack once per track, one after the other with the same time stamp, the track number as first byte of the
        payload: tracks of the same frame size and length are sent that way. A track of another frame size or length (a silent stand-in
        for a language, at a lower bitrate or just a few frames long) gets its own schedule instead: a pack whenever it has fallen behind
        the track the packing follows (the one with the most data), and none once it has run out."""
        self.pts_base, self.second_floor = pts_base, second_floor
        tracks = list(audio) if isinstance(audio, (list, tuple)) else [audio]
        self.ntracks = len(tracks)
        self.ess = [b"".join(t.units()) for t in tracks]
        self.Us = [t.unit_bytes for t in tracks]
        self.lead = max(range(len(tracks)), key=lambda i: (len(self.ess[i]), -i))
        shape = (self.Us[self.lead], len(self.ess[self.lead]))
        self.slow = [(self.Us[i], len(self.ess[i])) != shape for i in range(len(tracks))]
        self.gs = [0] * len(tracks)                      # where each slow track is
        self.es = self.ess[self.lead]
        self.U = self.Us[self.lead]
        self.ext = PROFILES[style]["audio_ext"]
        self.g = 0
        self.count = 0

    def done(self):
        return self.g >= len(self.es) and all(self.gs[i] >= len(self.ess[i]) for i in range(self.ntracks) if self.slow[i])

    def next_floor(self):
        """90 kHz time at which the audio buffer has room for the next pack; None = right away."""
        if self.g >= len(self.es):
            return None
        if self.count == 1:
            if self.second_floor is not None:
                return self.second_floor
            # Sony's muxer admits an access unit when its time stamp lies within STD_delay (90000 = 1 s) of the clock: the second audio pack
            # (2016 media bytes after the first pack's 2013) is available that long before the last audio unit it touches is due
            last = min(self.g + PACK - 14 - 9 - 5 - 4, len(self.es)) - 1
            return int(self.pts_base + (last // self.U) * AUDIO_UNIT_TICKS) - AUDIO_LOOKAHEAD
        need = self.g + min(PACK - 14 - 9 - 5 - 4, len(self.es) - self.g) - AUDIO_BUF      # the last pack only holds what is left
        if need <= 0:
            return None
        i = -(-need // self.U) - 1                      # last unit that must have been decoded
        return int(self.pts_base + i * AUDIO_UNIT_TICKS)

    def _pack(self, track, g, take, U, with_ext):
        es = self.ess[track]
        hl = 8 if with_ext else 5
        e = _Entry()
        e.kind, e.gop, e.gop_start, e.cum_end, e.floor, e.pos = "a", None, False, 0, None, None
        ptr = (-g) % U
        if ptr < take:
            payload = bytes([track, 0]) + ptr.to_bytes(2, "big") + es[g:g + take]
            pts = int(self.pts_base + ((g + ptr) // U) * AUDIO_UNIT_TICKS)
            fields = ts(2, pts) + (self.ext if with_ext else b"")
            e.body = pes(0xBD, 0x81 if with_ext else 0x80, fields, payload, PACK - 14)
        else:                                        # no unit header starts in this pack (stream tail): no PTS, ptr 0xFFFF
            payload = bytes([track, 0]) + b"\xff\xff" + es[g:g + take]
            e.body = pes(0xBD, 0x00, b"", payload, PACK - 14)
        return e

    def build_group(self, with_ext):
        """the next audio packs: one per sound track, same position in the sound and same time stamp -> list of entries.
        A track on its own schedule only appears when it is due."""
        room = PACK - 14 - 9 - (8 if with_ext else 5) - 4
        lead_done = self.g >= len(self.es)
        take = min(len(self.es) - self.g, room)
        sent = self.g // self.U
        group = []
        for track in range(self.ntracks):
            if self.slow[track]:
                g, U = self.gs[track], self.Us[track]
                if g >= len(self.ess[track]) or (not lead_done and g // U > sent):
                    continue
                t = min(len(self.ess[track]) - g, room)
                group.append(self._pack(track, g, t, U, with_ext))
                self.gs[track] += t
            elif not lead_done:
                group.append(self._pack(track, self.g, take, self.U, with_ext))
        if not lead_done:
            self.g += take
        self.count += 1
        return group

    def build(self, with_ext):
        """one track only (the streaming muxer)"""
        if self.ntracks != 1:
            raise ValueError("the streaming muxer writes one sound track")
        return self.build_group(with_ext)[0]


def mux(video_es, audio=None, version="0012", style="B", width=480, height=272, header_kib=None, strict=True,
        index_last_flag=0, video_lead=VIDEO_LEAD, audio_pts_base=AUDIO_PTS_BASE, audio2_floor=None, allow_b=False,
        video_kib=None, entry_hint=None, audio_kib=None):
    """video_es: Annex B H.264 (AUD, SPS/PPS on every IDR). No B-frames unless allow_b=True (picture order count type 0,
    2 reference frames, as in LocoRoco 2; untested for our own output on hardware). audio: Atrac3pStream or None. -> PMF bytes.
    version = PSMF header version ("0012" gameboot-safe); style = stream style "A"/"B" (see PROFILES).
    video_kib: the video buffer written into the system headers and the PES extensions (default: the style's own number; a game's own
    movies say 129, 251 or 495). audio_kib: the audio bound in the system headers (default 8; version 0015 movies say 776). entry_hint: a function (PTS of the IDR, bytes of its first three pictures) -> the u16 hint of an entry-point
    map entry; when given, the header gets a map with one entry per GOP (what the game's own movies carry)."""
    if style not in PROFILES:
        raise ValueError("unknown stream style %r (use A or B)" % style)
    n_tracks = len(audio) if isinstance(audio, (list, tuple)) else (0 if audio is None else 1)
    if isinstance(audio, (list, tuple)) and not audio:
        audio = None
    first = audio[0] if isinstance(audio, (list, tuple)) else audio
    if first is not None and first.unit_bytes > MAX_AUDIO_UNIT and strict:
        raise ValueError("audio frames are %d bytes (%.0f kbps): too big to fit one pack, the PSP plays no sound "
                         "(hardware test: 352 kbps silent, 128/96 kbps fine); use 320 kbps or lower"
                         % (first.frame_bytes, first.kbps))
    problems = psp_problems(video_es, allow_b)
    if problems and strict:
        raise ValueError("this video will not play on a real PSP:\n  - " + "\n  - ".join(problems))
    if header_kib is None:
        header_kib = HEADER_KIB.get(version, PROFILES[style]["video_kib"])        # 0013/0015: the header carries the same number as the stream's own system header
    video_kib = video_kib or PROFILES[style]["video_kib"]
    aus = split_access_units(video_es)
    for a in aus:
        if len(a.data) > MAX_PICTURE:
            raise ValueError("a picture is larger than %d bytes; lower the bitrate/quality" % MAX_PICTURE)
    disp = ref_flags = None
    if allow_b:
        sps, _ = stream_info(video_es)
        disp = display_indices(aus, sps)
        ref_flags = reference_flags(aus)
    ventries, gops, sysh = _layout_video(aus, style, video_kib, video_lead, disp, audio_kib)

    # ---- merge video and audio packs, assigning SCR as we go (audio wins ties: it is "due")
    feeder = _AudioFeeder(audio, style, audio_pts_base, audio2_floor) if audio is not None else None
    order, scrs, vi, ext_pending = [], [], 0, True
    cur = None

    def when(floor):
        t = SCR_START if cur is None else cur + SCR_STEP
        return t if floor is None else _on_clock(t, Fraction(floor * 300))

    while vi < len(ventries) or (feeder and not feeder.done()):
        have_a = feeder is not None and not feeder.done()
        tv = when(ventries[vi].floor) if vi < len(ventries) else None
        ta = when(feeder.next_floor()) if have_a and cur is not None else None
        if tv is not None and (not have_a or cur is None or tv < ta):
            e, t = ventries[vi], tv
            ext_pending = ext_pending or e.gop_start
            vi += 1
        else:
            group = feeder.build_group(ext_pending)
            ext_pending = False
            for e in group[:-1]:                                     # sound tracks 2, 3...: the packs right after the first, in track order
                order.append(e)
                scrs.append(int(ta))
                ta = ta + SCR_STEP
            e, t = group[-1], ta
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
            gflags = index_flags(a1 - a0, index_last_flag, None if ref_flags is None else ref_flags[a0:a1])
            idx = _slots(pos_of, mine, ends, gflags)
            bf = gop_index([len(a.data) for a in aus[a0:a1]], idx, index_last_flag, gflags)
            assert len(bf) == gop_index_len(a1 - a0)
            body = sysh + b"\x00\x00\x01\xbf" + len(bf).to_bytes(2, "big") + bf + body
        bodies.append(body)

    stream = bytearray()
    for scr, body in zip(scrs, bodies):
        pk = pack_header(scr) + body
        assert len(pk) == PACK, len(pk)
        stream += pk
    entries = ()
    if entry_hint is not None:                                       # one entry per GOP: the IDR's time stamp and the pack it starts in
        entries = tuple((entry_flags(_slots(pos_of, mine, ends, index_flags(a1 - a0, index_last_flag, None if ref_flags is None else ref_flags[a0:a1]))),
                         FIRST_PTS + FRAME * (disp[a0] if disp else a0), pos_of[id(mine[0])])
                        for a0, a1, mine, ends in gops)
    hdr = psmf.build_header(psmf.Params(
        stream_bytes=len(stream), last_pts=FIRST_PTS + FRAME * len(aus), width=width, height=height,
        version=version, first_pts=FIRST_PTS, video_buffer_kib=header_kib, audio=audio is not None, audio_tracks=max(1, n_tracks),
        entries=entries))
    return hdr + bytes(stream)


def _slots(pos_of, mine, ends, flags):
    """For the first four reference pictures of a GOP: the pack (counted from the GOP's first pack) where the picture ends."""
    p = pos_of[id(mine[0])]
    cum = [m.cum_end for m in mine]
    return [pos_of[id(mine[bisect.bisect_left(cum, ends[i])])] - p for i in reference_pictures(flags)]


def entry_flags(slots):
    """The first two bytes of an entry-point entry (EPIndex and EPPicOffset, as PPSSPP names them) from the GOP index's four slots: the LAST slot that
    is not 0xFFFF gives its number (1-4, written as number - 1 in the top two bits) and its value (11 bits, half of it in the first byte and the
    rest, doubled, in the second); none -> number 1, value 2047. This is the rule of Sony's own clip-info writer (found by Codex in
    ClipInfoComposer, notes 131) and it matches all 3,946 entries of Gun Showdown, LocoRoco 2 (the 44 odd ones too) and 007 From Russia With Love."""
    number, value = 1, 2047
    for i, v in enumerate(list(slots[:4]) + [0xFFFF] * (4 - len(slots[:4]))):
        if v != 0xFFFF:
            number, value = i + 1, v
    return (((number - 1) << 14) | (((value >> 7) & 0x0F) << 8)) | ((value & 0x7F) << 1)


def hint_from_size(first_bytes, top=0xC000):
    """OLD GUESS, no longer used by mux (see entry_flags for the exact rule): the u16 of an entry-point map entry as 0xC000 plus an even number
    that follows the amount of data in the first pictures of the GOP."""
    if first_bytes < 1000:
        return top
    n = int(first_bytes / 1000 * 1.1 + 1)
    return top | min(0x3FE, n + (n & 1))


def _gops_from(units):
    """access units in -> (index of its first unit, its units, whether another GOP follows) for each GOP, one GOP at a time"""
    cur, a0, n, sizes = [], 0, 0, 0
    for au in units:
        if au.gop_start and cur:
            yield a0, cur, True
            a0, cur = n, []
        cur.append(au)
        n += 1
    if cur:
        yield a0, cur, False


def mux_file(es_path, out_path, audio=None, version="0012", style="B", width=480, height=272, header_kib=None, strict=True,
             index_last_flag=0, video_lead=VIDEO_LEAD, audio_pts_base=AUDIO_PTS_BASE, audio2_floor=None):
    """The same file mux() makes (no B-frames), but read from a file and written to a file a piece at a time: the memory used is one GOP
    and the sound, however long the movie is (mux() holds the picture data about six times over). -> the size written."""
    from .h264 import iter_access_units
    if style not in PROFILES:
        raise ValueError("unknown stream style %r (use A or B)" % style)
    if isinstance(audio, (list, tuple)):
        if len(audio) > 1:
            raise ValueError("the streaming muxer writes one sound track")
        audio = audio[0] if audio else None
    if audio is not None and audio.unit_bytes > MAX_AUDIO_UNIT and strict:
        raise ValueError("audio frames are %d bytes (%.0f kbps): too big to fit one pack, the PSP plays no sound; use 320 kbps or lower" % (audio.frame_bytes, audio.kbps))
    with open(es_path, "rb") as f:
        head = f.read(1 << 20)
    problems = psp_problems(head, False)
    if problems and strict:
        raise ValueError("this video will not play on a real PSP:\n  - " + "\n  - ".join(problems))
    if header_kib is None:
        header_kib = HEADER_KIB.get(version, PROFILES[style]["video_kib"])
    video_kib = PROFILES[style]["video_kib"]
    sysh = system_header(style, video_kib)
    vext = b"\x1e" + (0x6000 | video_kib).to_bytes(2, "big")
    shift = 1                                                       # no B-frames: DTS = decode position - 1, PTS = decode position
    pts = lambda k: FIRST_PTS + FRAME * k                           # noqa: E731
    dts = lambda k: FIRST_PTS + FRAME * (k - shift)                 # noqa: E731

    counted = [0]

    def counting(units):
        for au in units:
            if len(au.data) > MAX_PICTURE:
                raise ValueError("a picture is larger than %d bytes; lower the bitrate/quality" % MAX_PICTURE)
            counted[0] += 1
            yield au

    def video_entries():
        for gi, (a0, gop_aus, has_next) in enumerate(_gops_from(counting(iter_access_units(es_path)))):
            mine, ends = _layout_gop(gi, a0, gop_aus, has_next, pts, dts, sysh, vext, video_lead)
            yield mine, ends, [len(a.data) for a in gop_aus]

    feeder = _AudioFeeder(audio, style, audio_pts_base, audio2_floor) if audio is not None else None
    gops = video_entries()
    queue, ends_of, sizes_of = [], None, None                       # video packs of the GOP being merged, waiting to be placed

    def next_video():
        nonlocal queue, ends_of, sizes_of
        if not queue:
            try:
                mine, ends_of, sizes_of = next(gops)
            except StopIteration:
                return None
            queue = list(mine)
            for e in queue:
                e.pos = None
            next_video.mine = list(mine)
        return queue[0]
    next_video.mine = []

    tmp = out_path + ".part"
    packs, cur, ext_pending = 0, None, True
    pending = []                                                    # (scr, entry) from an unresolved GOP start onward
    unresolved = None                                               # (start entry, GOP packs, ends, sizes)

    def when(floor):
        t = SCR_START if cur is None else cur + SCR_STEP
        return t if floor is None else _on_clock(t, Fraction(floor * 300))

    def resolve(out):
        nonlocal pending, unresolved
        g, mine, ends, sizes, needed = unresolved
        idx = [t.pos - g.pos for t in needed]
        bf = gop_index(sizes, idx, index_last_flag, None)
        assert len(bf) == gop_index_len(len(sizes))
        g.body = sysh + b"\x00\x00\x01\xbf" + len(bf).to_bytes(2, "big") + bf + g.body
        for scr, e in pending:
            pk = pack_header(scr) + e.body
            assert len(pk) == PACK, len(pk)
            out.write(pk)
        pending, unresolved = [], None

    try:
        with open(tmp, "wb") as out:
            out.write(b"\0" * PACK)                                 # the header goes here at the end, when the size is known
            while True:
                ventry = next_video()
                have_a = feeder is not None and not feeder.done()
                if ventry is None and not have_a:
                    break
                tv = when(ventry.floor) if ventry is not None else None
                ta = when(feeder.next_floor()) if have_a and cur is not None else None
                if tv is not None and (not have_a or cur is None or tv < ta):
                    e, t = queue.pop(0), tv
                    ext_pending = ext_pending or e.gop_start
                else:
                    e, t = feeder.build(ext_pending), ta
                    ext_pending = False
                scr = int(t)
                cur = t
                e.pos = packs
                packs += 1
                if unresolved is None and e.kind == "v" and e.gop_start:
                    mine_now = next_video.mine
                    refs = reference_pictures(index_flags(len(sizes_of), index_last_flag))
                    unresolved = (e, mine_now, ends_of, sizes_of, [next(m for m in mine_now if m.cum_end >= ends_of[i]) for i in refs])
                if unresolved is not None:
                    pending.append((scr, e))
                    if all(m.pos is not None for m in unresolved[4]):
                        resolve(out)
                else:
                    pk = pack_header(scr) + e.body
                    assert len(pk) == PACK, len(pk)
                    out.write(pk)
            if unresolved is not None:
                resolve(out)
            if counted[0] == 0:
                raise ValueError("there is no picture in that stream")
            out.seek(0)
            out.write(psmf.build_header(psmf.Params(
                stream_bytes=packs * PACK, last_pts=FIRST_PTS + FRAME * counted[0], width=width, height=height,
                version=version, first_pts=FIRST_PTS, video_buffer_kib=header_kib, audio=audio is not None)))
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return packs * PACK + PACK
