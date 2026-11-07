"""Make a game's own PMF movies smaller: the same movie, the same picture size, the same length, fewer bytes.

The picture is decoded and encoded again at a lower bitrate (B-frames on: the same trick the game's own composer used, a little less
space for the same look). The sound is kept byte for byte, or encoded again at a lower ATRAC3plus bitrate. Every result is checked
(same number of pictures, same length, same sound) before it is written; a movie that would not get smaller is copied unchanged.

Not seen in a real game yet: only the output's structure is checked (notes: shrinking game movies)."""
import hashlib
import os
import re
import shutil
import tempfile

from . import atrac3p, mirror, snd0
from .demux import demux, demux_all, duration_seconds
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


class Survey:
    """what a folder of movies looks like, read from the biggest few: how many, how big, and the picture and sound bitrates (kbps) they have now"""

    def __init__(self, count=0, total=0, picture_kbps=0, sound_kbps=0, sound_share=0.0, tracks=0):
        self.count, self.total, self.picture_kbps, self.sound_kbps, self.sound_share = count, total, picture_kbps, sound_kbps, sound_share
        self.tracks = tracks                             # the most sound tracks one of the looked-at movies has (one per language)


def survey(path, samples=3):
    """a movie, a folder of movies, or a game's disc image (.cso / .iso) -> Survey"""
    from . import umdimage
    if umdimage.is_image(path):
        return umdimage.survey_image(path, samples)
    movies = find_movies(path)
    if not movies:
        return Survey()
    sizes = [os.path.getsize(p) for p, _ in movies]
    picked = sorted(range(len(movies)), key=lambda i: -sizes[i])[:samples]
    raws = []
    for i in picked:
        try:
            raws.append(load_pmf(movies[i][0]))
        except (ValueError, OSError):
            continue
    return survey_stats(raws, len(movies), sum(sizes))


def survey_stats(raws, count, total):
    """the Survey of `count` movies taking `total` bytes, read from a few of them (their bytes in raws)"""
    vbits = abits = secs = asecs = abytes = weight = most = 0
    for raw in raws:
        try:
            _, video, tracks, _ = demux_all(raw)
        except ValueError:
            continue
        audio = tracks[min(tracks)] if tracks else b""
        seconds = max(duration_seconds(video, audio), 0.1)
        vbits += len(video) * 8
        abits += len(audio) * 8                          # the bitrate is per track; the share of the file counts every track
        asecs += seconds if audio else 0
        secs += seconds
        abytes += sum(len(t) for t in tracks.values())
        weight += len(raw)
        most = max(most, len(tracks))
    if not secs:
        return Survey(count, total)
    return Survey(count, total, vbits / secs / 1000, abits / max(asecs, 0.1) / 1000, abytes / max(weight, 1), most)


def predict(info, ratio, sound_kbps=None, keep_tracks=None):
    """bytes after shrinking, a guess from a Survey: the picture part scales with the ratio, the sound part with the new sound bitrate,
    and with keep_tracks (how many of the movies' sound tracks stay) the sound of the other tracks all but goes"""
    if not info.total:
        return 0
    sound = info.sound_share
    if sound_kbps and info.sound_kbps > sound_kbps + 4:
        sound = sound * sound_kbps / info.sound_kbps
    if keep_tracks and info.tracks > 1 and keep_tracks < info.tracks:
        sound = sound * keep_tracks / info.tracks
    return int(info.total * ((1 - info.sound_share) * min(ratio, 1.0) + sound))


MAX_FORCED_IDRS = 1500        # the pictures to start a GOP with are given to ffmpeg on its command line; a longer list keeps the regular spacing instead


def _reencode(ffmpeg, es_in, es_out, seconds, kbps, gop, bframes, bufsize, refs=None, idr_frames=None, pictures=0):
    """idr_frames: the numbers of the pictures that must start a GOP (an IDR picture each); None = one every `gop` pictures"""
    from . import cli
    refs = refs or (2 if bframes else 1)
    forced = []
    if idr_frames and 1 < len(idr_frames) <= MAX_FORCED_IDRS:
        # a list of times, each a quarter of a picture before its picture. ffmpeg turns a time into picture units and ROUNDS it, then takes the
        # first picture at or after that: n - 0.5 is a rounding tie (a microsecond of error in the text decided between n and n - 1: about a
        # third of the keyframes came out one picture early), n - 0.25 always rounds to n. An expression with one term per GOP
        # ("eq(n,59)+...") is refused by ffmpeg from about 200 terms on
        times = ",".join("%.6f" % max(0.0, (n - 0.25) * 1001 / 30000) for n in idr_frames)
        forced = ["-force_key_frames", times, "-forced-idr", "1"]
        gaps = [b - a for a, b in zip(idr_frames, idr_frames[1:])] + [pictures - idr_frames[-1]]       # the last GOP counts too
        gop, keymin = max(gaps + [gop]) + 8, 1              # nothing else starts a GOP: the forced pictures do (the encoder's own limit is kept out of the way: with B-frames it fires a picture early)
    else:
        keymin = gop
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "h264", "-r", "30000/1001", "-i", es_in] + passthrough_args(ffmpeg) + [
        "-an", "-c:v", "libx264", "-profile:v", "main", "-level", "2.1", "-bf", str(bframes), "-refs", str(refs),
        "-g", str(gop), "-keyint_min", str(keymin), "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.5), "-bufsize", "%dk" % bufsize,
        "-pix_fmt", "yuv420p"] + forced + ["-x264-params", cli.X264_PARAMS + ":weightp=0" + (":b-pyramid=none:b-adapt=0:weightb=0" if bframes else ""),
        "-f", "h264", es_out]
    cli.run(cmd, track=("ffmpeg", seconds))


def _sound_bytes(sound):
    """the audio bytes a muxed movie holds for one stream, a list of streams, or none"""
    if sound is None:
        return 0
    return sum(len(s.frames) * s.unit_bytes for s in (sound if isinstance(sound, list) else [sound]))


def _equal_length(streams):
    """several sound tracks encoded separately: the same frame size, and cut to the shortest (they differ by a frame at most)"""
    if len({s.frame_bytes for s in streams}) != 1:
        raise ValueError("The sound tracks came out in different qualities.")
    n = min(len(s.frames) for s in streams)
    return [atrac3p.Atrac3pStream(s.frames[:n], s.param) for s in streams]


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


def shrink_one(src, dst, ffmpeg, atracdenc=None, ratio=0.5, sound_kbps=None, bframes=None, log=print, keep=None):
    """src (.pmf) -> dst (.pmf). ratio: the share of the picture's bitrate to keep. sound_kbps: None keeps the sound as it is.
    bframes: None = MIRROR the original (only the bitrate changes: the same B-frame use, reference frames, GOP starts, buffer numbers and
    entry-point map as the movie has now); a number forces that many B-frames and the plain layout of earlier versions.
    keep: the sound tracks (numbers, 0 first) to keep in a movie with several of them; every other track stays in its place but holds one
    frame of silence (007 From Russia With Love plays such a movie silent under the PSP language of a removed track, and fine under a kept one).
    None keeps them all; a movie that has none of the tracks in `keep` is left with all of its own.
    Raises ValueError with a plain message when the file can't be used. -> ShrinkResult"""
    from .cli import PROGRESS
    raw = load_pmf(src)
    params, video, tracks, _ = demux_all(raw)
    if not video:
        raise ValueError("There is no picture in that movie.")
    order = sorted(tracks)                                   # a movie can carry several sound tracks (one per language)
    audio = tracks[order[0]] if order else b""
    if order and order != list(range(len(order))):
        raise ValueError("The sound tracks in this movie are numbered in an unusual way, so it was left as it is.")
    kept = order
    if keep is not None and len(order) > 1:
        picked = [t for t in order if t in keep]
        if picked and len(picked) < len(order):
            kept = picked
    dropping = kept != order
    if dropping and not (ffmpeg and atracdenc):
        raise ValueError("Choosing sound tracks needs the sound encoder (atracdenc), which makes the empty places.")
    if len(kept) > 1:
        shapes = set()
        for t in kept:
            try:
                st = atrac3p.from_units(tracks[t])
            except ValueError:
                raise ValueError("One of the sound tracks in this movie can't be read, so it was left as it is.")
            shapes.add((st.frame_bytes, len(st.frames)))
        if len(shapes) != 1:
            raise ValueError("The sound tracks in this movie differ in quality or length, so it was left as it is.")
    aus = split_access_units(video)
    seconds = duration_seconds(video, audio)
    before = len(raw)
    old_kbps = len(video) * 8 / max(seconds, 0.1) / 1000
    kbps = max(FLOOR_KBPS, int(old_kbps * ratio))
    keep_picture = ratio >= 0.999 or kbps >= old_kbps * 0.95              # nothing to take from the picture: only the sound can change
    if keep_picture and not (audio and sound_kbps and atracdenc) and not dropping:
        shutil.copyfile(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
        return ShrinkResult(src, dst, before, before, "nothing to change: copied as it is")
    version = params.version if params.version in ("0012", "0013", "0014", "0015") else "0012"        # the game's own version label is kept (the layout is the same in all of them)
    style = "A" if params.video_buffer_kib >= 400 else "B"
    mir = mirror.read(raw) if bframes is None else None
    if mir is not None and not mir.known:
        mir = None
    container = dict(version=version, style=style, width=params.width, height=params.height)
    refs = idr_frames = None
    if mir is not None:
        bframes, refs, idr_frames = mir.bframes, (max(2, mir.refs) if mir.bframes else mir.refs), mir.idr_frames
        container.update(style=mir.style, video_kib=mir.video_kib or None, header_kib=mir.header_kib or None, audio_kib=mir.audio_kib or None)
    elif bframes is None:
        bframes = 1
    work = tempfile.mkdtemp(prefix="pmfshrink_")
    try:
        es_in, es_out = os.path.join(work, "in.264"), os.path.join(work, "out.264")
        open(es_in, "wb").write(video)
        new_audio = kept_streams = None                      # the sound tracks as they are written when they are not the original ones: a list
        resound = False                                      # the kept tracks were encoded again
        if audio and sound_kbps and atracdenc:
            with PROGRESS.stage(0.0, 0.2, "Shrinking the sound…"):
                redone = [_new_sound(ffmpeg, atracdenc, tracks[t], work, sound_kbps) for t in kept]
            if any(r is not None for r in redone):
                new_audio = kept_streams = _equal_length([r if r is not None else atrac3p.from_units(tracks[t]) for r, t in zip(redone, kept)])
                resound = True
        if dropping:
            from . import tracks as track_tools
            stand_in = track_tools.silent_stream(1, ffmpeg, atracdenc, work)
            live = dict(zip(kept, new_audio if resound else [atrac3p.from_units(tracks[t]) for t in kept]))
            new_audio = [live.get(t, stand_in) for t in order]
        if new_audio is not None:
            sound = new_audio
        else:
            sound = [atrac3p.from_units(tracks[t]) for t in order] if len(order) > 1 else (atrac3p.from_units(audio) if audio else None)

        gop = 59
        bufsize = int(kbps * 1.5)
        best = None
        if keep_picture:
            if new_audio is None:
                shutil.copyfile(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
                return ShrinkResult(src, dst, before, before, "the sound is already that low: copied as it is")
            # the picture goes back in exactly as it was (the game's own stream: no PSP check needed), only the sound is new
            with PROGRESS.stage(0.2, 0.95, "Putting the movie together…"):
                best = mux(video, sound, allow_b=True, strict=False, entry_hint=mirror.entry_hint_for(mir, True) if mir is not None and mir.has_map else None, **container)
            kbps = old_kbps
        for attempt in range(0 if keep_picture else 4):
            lo = 0.2 + 0.7 * attempt / 4
            with PROGRESS.stage(lo, lo + 0.7 / 4, "Making the picture smaller…" if attempt == 0 else "Adjusting…"):
                _reencode(ffmpeg, es_in, es_out, seconds, kbps, gop, bframes, bufsize, refs, idr_frames, len(aus))
            try:
                out = mux(open(es_out, "rb").read(), sound, allow_b=bool(bframes), strict=True,
                          entry_hint=mirror.entry_hint_for(mir) if mir is not None and mir.has_map else None, **container)
            except ValueError as e:
                if "picture is larger" not in str(e):
                    raise
                bufsize = int(bufsize * 0.6)             # a picture over mux.MAX_PICTURE is refused: a smaller buffer caps picture sizes
                continue
            # the picture is asked to keep `ratio` of its size; the sound (all tracks) and the container stay as they are, or as the new sound is
            fixed = before - len(video) - sum(len(t) for t in tracks.values()) + _sound_bytes(sound)
            want = fixed + len(video) * ratio
            if best is None or len(out) < len(best):
                best = out
            if len(out) <= want * 1.08 or attempt == 3:
                break
            kbps = max(FLOOR_KBPS, int(kbps * (len(video) * ratio) / max(len(out) - fixed, 1) * 0.97))      # too big: lower the bitrate and try again
            bufsize = int(kbps * 1.5)
        if best is None:
            raise ValueError("Couldn't make that movie smaller.")
        problem = _check(raw, best, not resound, kept if dropping else None)
        if problem:
            raise ValueError("The smaller movie did not pass the check (%s), so nothing was written." % problem)
        if len(best) > before * (1 - (0.0 if keep_picture else MIN_GAIN)) or len(best) >= before:           # a sound asked for by name is kept if it saves anything
            shutil.copyfile(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
            return ShrinkResult(src, dst, before, before, "would not get smaller: copied as it is")
        open(dst, "wb").write(best)
        PROGRESS.report(1.0)
        note = "picture kept" if keep_picture else "picture %d -> %d kbps" % (old_kbps, kbps)
        if resound:
            note += ", sound %d -> %d kbps" % (atrac3p.from_units(audio).kbps, kept_streams[0].kbps)
        if dropping:
            note += " (sound track%s %s kept, the other%s empty)" % ("s" if len(kept) > 1 else "", ", ".join(str(t + 1) for t in kept), "s" if len(order) - len(kept) > 1 else "")
        elif len(order) > 1:
            note += " (%d sound tracks kept)" % len(order)
        return ShrinkResult(src, dst, before, len(best), note)
    finally:
        shutil.rmtree(work, ignore_errors=True)


_SLICE = re.compile(rb"\x00\x00\x01[\x01\x21\x41\x61\x05\x25\x45\x65]")


def count_pictures(video_es):
    """pictures that really have picture data (a game's movie can end with a stub that has none; ffmpeg skips it)"""
    return sum(1 for a in split_access_units(video_es) if _SLICE.search(a.data))


def _check(original, new, same_sound, kept=None):
    """None when the new movie matches the old one (same pictures, same length, same sound); otherwise what is different.
    kept: the tracks that are really there (the others may have been made empty); only those are compared"""
    _, v0, t0, _ = demux_all(original)
    _, v1, t1, _ = demux_all(new)
    if sorted(t0) != sorted(t1):
        return "the number of sound tracks changed"
    live = [t for t in sorted(t0) if kept is None or t in kept]
    a0, a1 = (t0[live[0]] if live else b""), (t1[live[0]] if live else b"")
    if same_sound and any(t0[t] != t1[t] for t in live):
        return "the sound changed"
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


def _digest(path):
    """a fingerprint of a file's whole content (size included), to tell copies of one movie apart from different movies"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return (os.path.getsize(path), h.hexdigest())


def shrink(path, out, ffmpeg, atracdenc=None, ratio=0.5, sound_kbps=None, bframes=None, log=print, keep=None):
    """a movie or a folder of movies -> out (a file for a movie, a folder for a folder; same file names inside).
    -> list of ShrinkResult. A movie that fails is reported and skipped; the others go on."""
    from .cli import PROGRESS, BuildError, Cancelled
    movies = find_movies(path)
    if not movies:
        raise BuildError("There are no .pmf movies there.")
    single = os.path.isfile(path)
    results, seen = [], {}
    for i, (full, rel) in enumerate(movies):
        from .cli import check_cancel
        check_cancel()
        dst = out if single else os.path.join(out, rel)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        PROGRESS.window(i / len(movies), (i + 1) / len(movies))
        PROGRESS.report(0.0, "Movie %d of %d: %s" % (i + 1, len(movies), os.path.basename(full)) if len(movies) > 1 else "Reading the movie…")
        key = _digest(full) if len(movies) > 1 else None
        if key in seen:
            # a game often lists one movie under several names (one per language) that all point at the same data on the disc:
            # the copies are shrunk once and the result is copied, so they stay identical
            lead = seen[key]
            if lead.after and os.path.exists(lead.dst):
                shutil.copyfile(lead.dst, dst)
                r = ShrinkResult(full, dst, lead.before, lead.after, "same movie as %s: %s" % (os.path.basename(lead.src), lead.note))
                log("%s: %s -> %s KB (same movie as %s)" % (rel, r.before // 1000, r.after // 1000, os.path.basename(lead.src)))
            else:
                r = ShrinkResult(full, dst, lead.before, 0, "failed: same movie as %s, which could not be used" % os.path.basename(lead.src))
                log("%s: same movie as %s, which could not be used" % (rel, os.path.basename(lead.src)))
            results.append(r)
            continue
        try:
            r = shrink_one(full, dst, ffmpeg, atracdenc, ratio, sound_kbps, bframes, log, keep)
        except Cancelled:
            raise
        except (ValueError, BuildError, OSError) as e:
            log("%s: %s" % (rel, e))
            r = ShrinkResult(full, dst, os.path.getsize(full), 0, "failed: %s" % e)
            results.append(r)
            if key is not None:
                seen[key] = r
            continue
        log("%s: %s -> %s KB (%s)" % (rel, r.before // 1000, r.after // 1000, r.note))
        results.append(r)
        if key is not None:
            seen[key] = r
    PROGRESS.window(0.0, 1.0)
    PROGRESS.report(1.0)
    return results
