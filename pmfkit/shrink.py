"""Make a game's own PMF movies smaller: the same movie, the same picture size, the same length, fewer bytes.

The picture is decoded and encoded again at a lower bitrate (B-frames on: the same trick the game's own composer used, a little less
space for the same look). The sound is kept byte for byte, or encoded again at a lower ATRAC3plus bitrate. Every result is checked
(same number of pictures, same length, same sound) before it is written; a movie that would not get smaller is copied unchanged.

Not seen in a real game yet: only the output's structure is checked (notes: shrinking game movies)."""
import os
import re
import shutil
import tempfile

from . import atrac3p, snd0
from .demux import demux, duration_seconds
from .extract import load_pmf
from .h264 import split_access_units
from .mux import mux, HEADER_KIB
from .toolinfo import passthrough_args

# how much of the picture's bitrate is kept, and the lowest the picture is allowed to go (kbps): below this it turns to mush
RATIOS = {"smaller": 0.75, "much": 0.5, "tiny": 0.3}
FLOOR_KBPS = 60
MIN_GAIN = 0.05                      # a result less than 5% smaller is not worth the loss: the original is copied instead


class ShrinkResult:
    def __init__(self, src, dst, before, after, note=""):
        self.src, self.dst, self.before, self.after, self.note = src, dst, before, after, note

    @property
    def saved(self):
        return self.before - self.after


def find_movies(path):
    """a .pmf file, or every .pmf inside a folder (also in its sub-folders) -> list of (full path, path relative to the chosen folder)"""
    if os.path.isfile(path):
        return [(path, os.path.basename(path))]
    found = []
    for dirpath, _, names in os.walk(path):
        for n in sorted(names):
            if n.lower().endswith(".pmf"):
                full = os.path.join(dirpath, n)
                found.append((full, os.path.relpath(full, path)))
    return sorted(found, key=lambda t: t[1].lower())


def estimate(path, ratio, sound_kbps=None, samples=3):
    """a quick guess before the work starts -> (number of movies, their total bytes, bytes after shrinking).
    Looks inside a few of the movies to see how much of a file is sound (the sound stays the same size unless sound_kbps is given)."""
    movies = find_movies(path)
    sizes = [os.path.getsize(p) for p, _ in movies]
    total = sum(sizes)
    if not movies:
        return 0, 0, 0
    picked = sorted(range(len(movies)), key=lambda i: -sizes[i])[:samples]
    share_sum = weight = 0
    for i in picked:
        try:
            raw = load_pmf(movies[i][0])
            _, video, audio, _ = demux(raw)
            seconds = duration_seconds(video, audio)
            audio_bytes = len(audio)
            if sound_kbps and audio and audio_bytes * 8 / max(seconds, 0.1) / 1000 > sound_kbps + 4:
                audio_bytes = int(audio_bytes * sound_kbps / (audio_bytes * 8 / max(seconds, 0.1) / 1000))
            share_sum += (len(raw) - len(audio)) * ratio + audio_bytes
            weight += len(raw)
        except (ValueError, OSError):
            continue
    if not weight:
        return len(movies), total, int(total * ratio)
    return len(movies), total, int(total * share_sum / weight)


def _reencode(ffmpeg, es_in, es_out, seconds, kbps, gop, bframes, bufsize):
    from . import cli
    refs = 2 if bframes else 1
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "h264", "-r", "30000/1001", "-i", es_in] + passthrough_args(ffmpeg) + [
        "-an", "-c:v", "libx264", "-profile:v", "main", "-level", "2.1", "-bf", str(bframes), "-refs", str(refs),
        "-g", str(gop), "-keyint_min", str(gop), "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.5), "-bufsize", "%dk" % bufsize,
        "-pix_fmt", "yuv420p", "-x264-params", cli.X264_PARAMS + ":weightp=0" + (":b-pyramid=none:b-adapt=0:weightb=0" if bframes else ""),
        "-f", "h264", es_out]
    cli.run(cmd, track=("ffmpeg", seconds))


def _new_sound(ffmpeg, atracdenc, audio_es, work, kbps):
    """the sound encoded again at kbps (decoded to a WAV first, like everywhere else); None when that wouldn't be smaller"""
    from . import cli
    st = atrac3p.from_units(audio_es)
    if st.kbps <= kbps + 4:
        return None
    at3 = os.path.join(work, "old.at3")
    open(at3, "wb").write(snd0.build(st.frames, st.frame_bytes, loop=False))
    oma = os.path.join(work, "new.oma")
    cli.encode_audio(ffmpeg, atracdenc, at3, oma, None, lufs=None, kbps=kbps)
    return atrac3p.read_oma(oma)


def shrink_one(src, dst, ffmpeg, atracdenc=None, ratio=0.5, sound_kbps=None, bframes=1, log=print):
    """src (.pmf) -> dst (.pmf). ratio: the share of the picture's bitrate to keep. sound_kbps: None keeps the sound as it is.
    Raises ValueError with a plain message when the file can't be used. -> ShrinkResult"""
    from .cli import PROGRESS
    raw = load_pmf(src)
    params, video, audio, _ = demux(raw)
    if not video:
        raise ValueError("There is no picture in that movie.")
    aus = split_access_units(video)
    seconds = duration_seconds(video, audio)
    before = len(raw)
    old_kbps = len(video) * 8 / max(seconds, 0.1) / 1000
    kbps = max(FLOOR_KBPS, int(old_kbps * ratio))
    if kbps >= old_kbps * 0.95:
        shutil.copyfile(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
        return ShrinkResult(src, dst, before, before, "already small: copied as it is")
    version = params.version if params.version in HEADER_KIB else "0012"
    style = "A" if params.video_buffer_kib >= 400 else "B"
    work = tempfile.mkdtemp(prefix="pmfshrink_")
    try:
        es_in, es_out = os.path.join(work, "in.264"), os.path.join(work, "out.264")
        open(es_in, "wb").write(video)
        new_audio = None
        if audio and sound_kbps and atracdenc:
            with PROGRESS.stage(0.0, 0.2, "Shrinking the sound…"):
                new_audio = _new_sound(ffmpeg, atracdenc, audio, work, sound_kbps)
        sound = new_audio if new_audio is not None else (atrac3p.from_units(audio) if audio else None)
        gop = 59
        bufsize = int(kbps * 1.5)
        best = None
        for attempt in range(4):
            lo = 0.2 + 0.7 * attempt / 4
            with PROGRESS.stage(lo, lo + 0.7 / 4, "Making the picture smaller…" if attempt == 0 else "Adjusting…"):
                _reencode(ffmpeg, es_in, es_out, seconds, kbps, gop, bframes, bufsize)
            try:
                out = mux(open(es_out, "rb").read(), sound, version=version, style=style, width=params.width, height=params.height,
                          allow_b=bool(bframes), strict=True)
            except ValueError as e:
                if "picture is larger" not in str(e):
                    raise
                bufsize = int(bufsize * 0.6)             # a picture over 65,535 bytes can't be indexed: a smaller buffer caps picture sizes
                continue
            want = before * (ratio if not (sound is not None and new_audio is not None) else min(1.0, ratio + 0.05))
            if best is None or len(out) < len(best):
                best = out
            if len(out) <= want * 1.08 or attempt == 3:
                break
            kbps = max(FLOOR_KBPS, int(kbps * want / len(out) * 0.97))      # too big: lower the bitrate and try again
            bufsize = int(kbps * 1.5)
        if best is None:
            raise ValueError("Couldn't make that movie smaller.")
        problem = _check(raw, best, new_audio is None)
        if problem:
            raise ValueError("The smaller movie did not pass the check (%s), so nothing was written." % problem)
        if len(best) > before * (1 - MIN_GAIN):
            shutil.copyfile(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
            return ShrinkResult(src, dst, before, before, "would not get smaller: copied as it is")
        open(dst, "wb").write(best)
        PROGRESS.report(1.0)
        return ShrinkResult(src, dst, before, len(best), "picture %d -> %d kbps" % (old_kbps, kbps))
    finally:
        shutil.rmtree(work, ignore_errors=True)


_SLICE = re.compile(rb"\x00\x00\x01[\x01\x21\x41\x61\x05\x25\x45\x65]")


def count_pictures(video_es):
    """pictures that really have picture data (a game's movie can end with a stub that has none; ffmpeg skips it)"""
    return sum(1 for a in split_access_units(video_es) if _SLICE.search(a.data))


def _check(original, new, same_sound):
    """None when the new movie matches the old one (same pictures, same length, same sound); otherwise what is different"""
    _, v0, a0, _ = demux(original)
    p1, v1, a1, _ = demux(new)
    n0, n1 = count_pictures(v0), count_pictures(v1)
    if not n0 - 1 <= n1 <= n0:                       # a game's movie can end with a cut-off last picture that nothing can decode
        return "%d pictures instead of %d" % (n1, n0)
    if abs(duration_seconds(v0, a0) - duration_seconds(v1, a1)) > 0.15:
        return "the length changed"
    if same_sound and a0 != a1:
        return "the sound changed"
    if bool(a0) != bool(a1):
        return "the sound is missing"
    return None


def shrink(path, out, ffmpeg, atracdenc=None, ratio=0.5, sound_kbps=None, bframes=1, log=print):
    """a movie or a folder of movies -> out (a file for a movie, a folder for a folder; same file names inside).
    -> list of ShrinkResult. A movie that fails is reported and skipped; the others go on."""
    from .cli import PROGRESS, BuildError
    movies = find_movies(path)
    if not movies:
        raise BuildError("There are no .pmf movies there.")
    single = os.path.isfile(path)
    results = []
    for i, (full, rel) in enumerate(movies):
        dst = out if single else os.path.join(out, rel)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        PROGRESS.window(i / len(movies), (i + 1) / len(movies))
        PROGRESS.report(0.0, "Movie %d of %d: %s" % (i + 1, len(movies), os.path.basename(full)) if len(movies) > 1 else "Reading the movie…")
        try:
            r = shrink_one(full, dst, ffmpeg, atracdenc, ratio, sound_kbps, bframes, log)
        except (ValueError, BuildError, OSError) as e:
            log("%s: %s" % (rel, e))
            r = ShrinkResult(full, dst, os.path.getsize(full), 0, "failed: %s" % e)
            results.append(r)
            continue
        log("%s: %s -> %s KB (%s)" % (rel, r.before // 1000, r.after // 1000, r.note))
        results.append(r)
    PROGRESS.window(0.0, 1.0)
    PROGRESS.report(1.0)
    return results
