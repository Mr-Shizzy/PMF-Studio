"""Mirror mode for shrinking a game's own movie: change the bitrate and nothing else about how the movie is built.

A game's movie player was tried by its makers with the game's own kind of movie only. So a shrunk movie keeps what the original has:
the same use of B-frames and reference frames, keyframes (IDR pictures that start a GOP) on the same pictures, the same video buffer numbers
in the header, the system headers and the PES packets, the same version label and stream style, and an entry-point map when the original
has one. This reads those facts from the original movie."""
from dataclasses import dataclass, field

from .demux import demux_all
from .h264 import split_access_units
from .sps import stream_info

SYS_HEADER = 0xBB


@dataclass
class Source:
    version: str = "0012"
    style: str = "B"                       # stream style (see mux.PROFILES), read from the system header's flag byte
    video_kib: int = 0                     # the video buffer in the system header (0 = unknown)
    header_kib: int = 0                    # the video buffer in the PSMF header
    audio_kib: int = 0                     # the audio (BD) buffer bound in the system header (0 = unknown; 8 in version 0014 movies, 776 in 0015)
    refs: int = 1
    bframes: int = 0                       # 0 = the movie has no B-frames (picture order count type 2), 1 = it has (type 0)
    idr_frames: list = field(default_factory=list)     # picture numbers (decode order) of the pictures that start a GOP
    hints: dict = field(default_factory=dict)          # PTS of an IDR -> the u16 of its entry-point map entry
    has_map: bool = False
    known: bool = False                    # False: could not be read, the caller keeps its own defaults


def read(raw):
    """a PMF movie's bytes -> Source (known=False when its stream can't be understood)"""
    params, video, _, packs = demux_all(raw)
    src = Source(version=params.version, header_kib=params.video_buffer_kib)
    sysh = next((it.payload for pk in packs for it in pk.items if it.sid == SYS_HEADER), b"")
    if len(sysh) >= 9:
        src.style = "B" if sysh[3] == 0x80 else "A"
        src.video_kib = int.from_bytes(sysh[7:9], "big") & 0x1FFF
    if len(sysh) >= 12 and sysh[9] == 0xBD:
        src.audio_kib = int.from_bytes(sysh[10:12], "big") & 0x1FFF
    try:
        sps, _ = stream_info(video)
        aus = split_access_units(video)
    except ValueError:
        return src
    if sps is None:
        return src
    src.refs = max(1, int(sps["num_ref_frames"]))
    src.bframes = 0 if sps["poc_type"] == 2 else 1
    src.idr_frames = [i for i, a in enumerate(aus) if a.gop_start]
    src.hints = {pts: hint for hint, pts, _ in params.entries}
    src.has_map = bool(params.entries)
    src.known = bool(src.idr_frames)
    return src


def entry_hint_for(src, picture_kept=False):
    """the function mux() uses to fill an entry-point map: the original's own number where the same IDR is listed (when the picture is
    the original's own, or the entry says 0 data), otherwise a guess from the size of the new first pictures with the original's top bits"""
    from .mux import hint_from_size

    def hint(pts, first_bytes):
        old = src.hints.get(pts)
        if old is not None and picture_kept:
            return old
        return hint_from_size(first_bytes, (old & 0xFC00) if old is not None else 0xC000)
    return hint
