"""A movie with several sound tracks (one per language): list them, and keep only the ones you want.
The picture is not touched (the game's own stream goes back in exactly as it was); only the sound tracks change.
What happens to a track you do not keep:
  "delete"  it is gone, the kept tracks are numbered 0, 1, ... again;
  "silent"  it stays in its place but holds silence at the lowest bitrate, as long as the movie;
  "short"   it stays in its place but holds only a moment of silence (the fewest frames).
Whether a game accepts a missing or a shortened track is up to the game: see RESEARCH_NOTES.md (sound tracks)."""
import os

from . import atrac3p, cli, mirror
from .demux import demux_all
from .mux import mux

SILENT_KBPS = 32               # the lowest ATRAC3plus bitrate that plays on a real PSP (notes 55)
OTHERS = ("delete", "silent", "short")


class TrackInfo:
    def __init__(self, index, kbps, frames, seconds):
        self.index, self.kbps, self.frames, self.seconds = index, kbps, frames, seconds

    def __repr__(self):
        return "Track %d: %.0f kbps, %d frames, %.1f s" % (self.index, self.kbps, self.frames, self.seconds)


def read_tracks(raw):
    """-> list of TrackInfo for a movie's sound tracks ([] for no sound)"""
    params, video, tracks, _ = demux_all(raw)
    out = []
    for t in sorted(tracks):
        st = atrac3p.from_units(tracks[t])
        out.append(TrackInfo(t, st.kbps, len(st.frames), len(st.frames) * atrac3p.SAMPLES_PER_FRAME / atrac3p.SAMPLE_RATE))
    return out


def silent_stream(frames, ffmpeg, atracdenc, work, kbps=SILENT_KBPS):
    """`frames` frames of silence at kbps: a short silent clip is encoded once, and its last frame repeated"""
    oma = os.path.join(work, "silence_%d.oma" % kbps)
    if not os.path.exists(oma):
        cli.encode_audio(ffmpeg, atracdenc, None, oma, None, lufs=None, kbps=kbps, silent_seconds=3)
    st = atrac3p.read_oma(oma)
    got = st.frames[:frames]
    got += [st.frames[-1]] * (frames - len(got))
    return atrac3p.Atrac3pStream(got, st.param)


def retrack(raw, keep, others, ffmpeg=None, atracdenc=None, work=None, short_frames=1):
    """a movie (bytes) -> the same movie (bytes) with only the tracks in `keep` playing. keep: track numbers. others: see the top."""
    if others not in OTHERS:
        raise ValueError("unknown way to treat the other tracks: %r" % (others,))
    params, video, tracks, _ = demux_all(raw)
    order = sorted(tracks)
    if len(order) < 2:
        raise ValueError("This movie has only one sound track.")
    if order != list(range(len(order))):
        raise ValueError("The sound tracks in this movie are numbered in an unusual way, so it was left as it is.")
    keep = sorted(set(keep))
    if not keep or any(k not in tracks for k in keep):
        raise ValueError("Keep at least one of the movie's sound tracks.")
    streams = [atrac3p.from_units(tracks[t]) for t in order]
    if others == "delete":
        sound = [streams[k] for k in keep]
    else:
        n = len(streams[keep[0]].frames)
        sound = [streams[t] if t in keep else silent_stream(n if others == "silent" else short_frames, ffmpeg, atracdenc, work)
                 for t in order]
    if len(sound) == 1:
        sound = sound[0]
    mir = mirror.read(raw)
    version = params.version if params.version in ("0012", "0013", "0014", "0015") else "0012"
    container = dict(version=version, style="A" if params.video_buffer_kib >= 400 else "B", width=params.width, height=params.height)
    if mir.known:
        container.update(style=mir.style, video_kib=mir.video_kib or None, header_kib=mir.header_kib or None)
    entry_hint = mirror.entry_hint_for(mir, True) if mir.known and mir.has_map else None
    return mux(video, sound, allow_b=True, strict=False, entry_hint=entry_hint, **container)
