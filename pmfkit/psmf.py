"""PSMF 2048-byte header builder.

Layout decoded from Sony-composer / MPStoPMF PMFs (all big-endian, rest of the 2048 bytes is zero):
  0x00 "PSMF"+version  0x08 u32 2048  0x0C u32 stream bytes  0x50 u32 table length
  0x54 first PTS (6)   0x5A last PTS (6)   0x60 u32 mux rate   0x64 u32 90000
  0x68 u8 stream count, u8 1   0x6A u32 sub-table length   0x6E first PTS (6)   0x74 last PTS (6)
  0x7A u16 1   0x7C u32 entries length   0x80 u16 stream count
  0x82 video entry: e0 00 <P-STD u16> 8*00 <W/16> <H/16> 00 00
  0x92 audio entry: bd 00 20 04 10*00 02 02   (audio only)
"""
from dataclasses import dataclass

MUX_RATE = 25000
CLOCK = 90000


@dataclass
class Params:
    stream_bytes: int
    last_pts: int
    width: int = 480
    height: int = 272
    version: str = "0012"
    first_pts: int = 90000
    video_buffer_kib: int = 495     # P-STD buffer: 495 (0012 files) or 251 (0014 files)
    audio: bool = False
    streams: int = 1                # stream entries in the header: 1 video + the sound tracks (007 From Russia With Love: 5 = 4 tracks)
    audio_tracks: int = 1           # sound tracks to write when audio is True (one entry each; fields below grow by 16 bytes per track)


def pstd(kib):
    return 0x2000 | kib


def build_header(p):
    if len(p.version) != 4 or not p.version.isdigit():
        raise ValueError("version must be 4 digits, e.g. '0012'")
    if p.width % 16 or p.height % 16:
        raise ValueError("width/height must be multiples of 16")
    h = bytearray(2048)
    h[0:4] = b"PSMF"
    h[4:8] = p.version.encode()
    h[8:12] = (2048).to_bytes(4, "big")
    h[12:16] = p.stream_bytes.to_bytes(4, "big")
    t = max(1, p.audio_tracks) if p.audio else 0
    a = 16 * t
    h[0x50:0x54] = (0x3E + a).to_bytes(4, "big")
    h[0x54:0x5A] = p.first_pts.to_bytes(6, "big")
    h[0x5A:0x60] = p.last_pts.to_bytes(6, "big")
    h[0x60:0x64] = MUX_RATE.to_bytes(4, "big")
    h[0x64:0x68] = CLOCK.to_bytes(4, "big")
    h[0x68] = 1 + t
    h[0x69] = 1
    h[0x6A:0x6E] = (0x24 + a).to_bytes(4, "big")
    h[0x6E:0x74] = p.first_pts.to_bytes(6, "big")
    h[0x74:0x7A] = p.last_pts.to_bytes(6, "big")
    h[0x7A:0x7C] = (1).to_bytes(2, "big")
    h[0x7C:0x80] = (0x12 + a).to_bytes(4, "big")
    h[0x80:0x82] = (1 + t).to_bytes(2, "big")
    h[0x82:0x84] = b"\xe0\x00"
    h[0x84:0x86] = pstd(p.video_buffer_kib).to_bytes(2, "big")
    h[0x8E] = p.width // 16
    h[0x8F] = p.height // 16
    for j in range(t):                                  # one entry per sound track: bd <track> 20 04, ten zero bytes, 02 02
        o = 0x92 + 16 * j
        h[o:o + 4] = bytes([0xBD, j, 0x20, 0x04])
        h[o + 14:o + 16] = b"\x02\x02"
    return bytes(h)


def parse_header(h):
    """Inverse of build_header for the fields it writes (used by tests and tools)."""
    if h[:4] != b"PSMF":
        raise ValueError("not a PSMF file")
    streams = int.from_bytes(h[0x80:0x82], "big")
    return Params(
        stream_bytes=int.from_bytes(h[12:16], "big"),
        last_pts=int.from_bytes(h[0x5A:0x60], "big"),
        width=h[0x8E] * 16, height=h[0x8F] * 16,
        version=h[4:8].decode("ascii"),
        first_pts=int.from_bytes(h[0x54:0x5A], "big"),
        video_buffer_kib=int.from_bytes(h[0x84:0x86], "big") & 0x1FFF,
        audio=streams >= 2,
        streams=streams,
        audio_tracks=max(1, streams - 1),
    )
