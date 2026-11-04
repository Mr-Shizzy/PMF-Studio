"""A movie with several sound tracks (one per language): list them, and keep only the ones you want.
The picture is not touched (the game's own stream goes back in exactly as it was); only the sound tracks change.
What happens to a track you do not keep:
  "delete"  it is gone, the kept tracks are numbered 0, 1, ... again;
  "silent"  it stays in its place but holds silence at the lowest bitrate, as long as the movie;
  "short"   it stays in its place but holds only a moment of silence (the fewest frames).
Whether a game accepts a missing or a shortened track is up to the game: see RESEARCH_NOTES.md (sound tracks)."""
import os

from . import atrac3p, cli, mirror, psmf, umdimage
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
        container.update(style=mir.style, video_kib=mir.video_kib or None, header_kib=mir.header_kib or None, audio_kib=mir.audio_kib or None)
    entry_hint = mirror.entry_hint_for(mir, True) if mir.known and mir.has_map else None
    return mux(video, sound, allow_b=True, strict=False, entry_hint=entry_hint, **container)


def parse_keep(text):
    """track numbers as people say them ("1" or "1,3": counted from 1) -> the list [0] or [0, 2] the code uses; empty or None = keep them all (None)"""
    if text is None or not str(text).strip():
        return None
    try:
        out = sorted({int(x) - 1 for x in str(text).replace(";", ",").split(",") if x.strip()})
    except ValueError:
        raise ValueError("The sound tracks to keep are numbers such as 1 or 1,3.")
    if not out or out[0] < 0:
        raise ValueError("Sound tracks are counted from 1.")
    return out


def _track_count(head):
    """how many sound tracks a movie has, from its first bytes (the PSMF header counts its streams: the picture and then each sound track)"""
    try:
        return max(0, psmf.parse_header(bytes(head[:2048])).streams - 1)
    except (ValueError, IndexError):
        return 0


def multitrack_movies(path, limit=12):
    """the movies in a movie file, a folder or a game image that have several sound tracks, the biggest first for a game
    -> [(name, loader)] where loader() gives the movie's bytes; at most `limit` of them (the headers are read, not the whole movies)"""
    from . import shrink, umdimage
    found = []
    if umdimage.is_image(path):
        img = umdimage.Image(path)
        try:
            for m in sorted(umdimage.find_movies(umdimage.walk(img)), key=lambda m: -m.size):
                if _track_count(img.read(m.extent, 1)) >= 2:
                    found.append((os.path.basename(m.name), lambda e=m.extent, n=m.size: _image_movie(path, e, n)))
                    if len(found) >= limit:
                        break
        finally:
            img.close()
        return found
    for full, rel in shrink.find_movies(path):
        try:
            with open(full, "rb") as f:
                head = f.read(2048)
        except OSError:
            continue
        if _track_count(head) >= 2:
            found.append((rel, lambda p=full: open(p, "rb").read()))
            if len(found) >= limit:
                break
    return found


def _image_movie(path, extent, size):
    img = umdimage.Image(path)
    try:
        return img.read(extent, -(-size // umdimage.SECTOR))[:size]
    finally:
        img.close()


def sample_pcm(raw, track, ffmpeg, seconds=14.0, start=6.0):
    """a few seconds of one sound track, to listen to -> 16-bit stereo 44.1 kHz bytes. It starts `start` seconds in (earlier in a short movie)."""
    import subprocess
    import tempfile
    from . import snd0
    _, _, tr, _ = demux_all(raw)
    if track not in tr:
        raise ValueError("That movie has no sound track %d." % (track + 1))
    st = atrac3p.from_units(tr[track])
    per = atrac3p.SAMPLES_PER_FRAME / atrac3p.SAMPLE_RATE
    want = int(seconds / per)
    first = min(int(start / per), max(0, len(st.frames) - want))
    frames = st.frames[first:first + want]
    if len(frames) < 8:
        raise ValueError("The sound of this movie is too short to listen to.")
    work = tempfile.mkdtemp(prefix="pmftrack_")
    try:
        at3 = os.path.join(work, "t.at3")
        with open(at3, "wb") as f:
            f.write(snd0.build(frames, st.frame_bytes, loop=False))
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", at3, "-vn", "-ac", "2", "-ar", "44100", "-f", "s16le", "-"],
                           capture_output=True, stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0, timeout=120)
        if r.returncode or len(r.stdout) < 4:
            raise ValueError("The sound could not be played.")
        return r.stdout
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
