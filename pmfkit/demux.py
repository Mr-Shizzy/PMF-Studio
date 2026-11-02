"""Read a PMF back: packet list and the elementary streams (used by tests and tools)."""
import struct
from dataclasses import dataclass, field

from . import psmf


def _ts(x):
    return (((x[0] >> 1) & 7) << 30) | (x[1] << 22) | ((x[2] >> 1) << 15) | (x[3] << 7) | (x[4] >> 1)


@dataclass
class Item:
    sid: int
    off: int                 # offset inside the pack
    length: int              # PES/packet length field
    flags: int = 0
    hl: int = 0
    pts: int = None
    dts: int = None
    ext: bytes = b""
    payload: bytes = b""     # PES payload, or the body for 0xBB/0xBF/0xBE


@dataclass
class Pack:
    index: int
    scr27: int
    items: list = field(default_factory=list)


def scr27(pack_hdr):
    v = int.from_bytes(pack_hdr[4:10], "big")
    base = ((v >> 43) & 7) << 30 | ((v >> 27) & 0x7FFF) << 15 | ((v >> 11) & 0x7FFF)
    ext = (v >> 1) & 0x1FF
    return base * 300 + ext


def packs(body):
    for k in range(len(body) // 2048):
        s = body[k * 2048:(k + 1) * 2048]
        if s[:4] != b"\x00\x00\x01\xba":
            raise ValueError("pack %d: bad pack header" % k)
        p = 14 + (s[13] & 7)
        pk = Pack(k, scr27(s[:14]))
        while p < 2048:
            if s[p:p + 3] != b"\x00\x00\x01":
                raise ValueError("pack %d: bad start code at %d" % (k, p))
            sid = s[p + 3]
            ln = struct.unpack(">H", s[p + 4:p + 6])[0]
            it = Item(sid, p, ln)
            if sid in (0xE0, 0xBD):
                it.flags, it.hl = s[p + 7], s[p + 8]
                q = p + 9
                if it.flags & 0x80:
                    it.pts = _ts(s[q:q + 5])
                    q += 5
                if it.flags & 0x40:
                    it.dts = _ts(s[q:q + 5])
                    q += 5
                it.ext = s[q:p + 9 + it.hl]
                it.payload = s[p + 9 + it.hl:p + 6 + ln]
            else:
                it.payload = s[p + 6:p + 6 + ln]
            pk.items.append(it)
            p += 6 + ln
        yield pk


def demux(pmf):
    """-> (Params, video_es, audio_bytes, list[Pack]); audio_bytes = the audio ES without the 4-byte PES prefixes."""
    params = psmf.parse_header(pmf[:2048])
    plist = list(packs(pmf[2048:]))
    v, a = bytearray(), bytearray()
    for pk in plist:
        for it in pk.items:
            if it.sid == 0xE0:
                v += it.payload
            elif it.sid == 0xBD:
                a += it.payload[4:]
    return params, bytes(v), bytes(a), plist


def duration_seconds(video_es, audio_es=b""):
    """Real length from the streams themselves: the picture count at 29.97 fps, or the sound if that is longer.
    (The times in the PSMF header are not reliable: a Sony-composer gameboot of 2 s claims 75 s there.)"""
    from . import atrac3p
    from .h264 import split_access_units
    seconds = len(split_access_units(video_es)) * 1001 / 30000
    if audio_es:
        try:
            seconds = max(seconds, len(atrac3p.from_units(audio_es).frames) * 2048 / 44100)
        except ValueError:
            pass
    return seconds
