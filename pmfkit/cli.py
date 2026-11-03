"""Command line: python -m pmfkit make|mux|info ..."""
import argparse
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from . import atrac3p
from .demux import demux, duration_seconds
from . import pbp as pbpmod
from . import snd0 as snd0mod
from . import ctf as ctfmod, ptf as ptfmod, rco as rcomod
from .fit import pick_audio_kbps
from .toolinfo import ascii_temp_dir, is_ascii
from .gameboot import STOCK_SECONDS, BUDGET_BYTES, VERIFIED_OK_BYTES, VERIFIED_FAIL_BYTES, movie_ms
from .snd0 import COMBINED_LIMIT
from .mux import mux, mux_file, ICON1,ICON1_GOP, ICON1_VIDEO_KBPS, ICON1_AUDIO_KBPS, ICON1_MAX_BYTES, ICON1_VERIFIED_OK, ICON1_VERIFIED_FAIL

# Sony-composer gameboots use 1 reference frame and no weighted prediction; PPSSPP plays anything, the PSP hardware decoder is stricter
X264_PARAMS = "aud=1:nal-hrd=vbr:pic-struct=1:force-cfr=1:scenecut=0:repeat-headers=1"


class BuildError(Exception):
    """a problem the user can fix (bad input, missing tool, over a limit); the message is meant to be shown as it is"""


def fail(message):
    raise BuildError(message)


NOWND = 0x08000000 if os.name == "nt" else 0          # helper programs run without a console window popping up
PRIORITY = 0                                           # the window sets 0x4000 (below normal) so a long job doesn't make the PC sluggish


class Cancelled(BuildError):
    """the user pressed Stop"""


CANCELLED_TEXT = "Stopped."
CANCEL = threading.Event()
ACTIVE = []                                            # helper programs running right now


def cancel():
    """stop what is running: nothing new starts, and the helper programs that are running are ended"""
    CANCEL.set()
    for p in list(ACTIVE):
        try:
            p.terminate()
        except OSError:
            pass


def check_cancel():
    if CANCEL.is_set():
        raise Cancelled(CANCELLED_TEXT)


def tool(path):
    """Absolute path of an executable given as a path or a name on PATH."""
    found = shutil.which(path) or (os.path.abspath(path) if os.path.exists(path) else None)
    if not found:
        fail("cannot find %r" % path)
    return found


def frame_bytes_for_kbps(kbps):
    """ATRAC3plus frame size (multiple of 8) for a bitrate: 128 -> 744, 96 -> 560, 64 -> 376, as in Sony-made PMFs."""
    known = {32: 192, 48: 280, 64: 376, 96: 560, 128: 744}   # 64/96/128 seen in Sony-made PMFs (64 = Bomberman's ICON1, not plain rounding); 32/48 are the standard ATRAC3plus sizes, both play on a real PSP (notes section 55; 32 needs the tonal-trim atracdenc)
    if kbps in known:
        return known[kbps]
    raw = kbps * 1000 / 8 * 2048 / 44100
    return max(8, int(round(raw / 8.0)) * 8)


class Progress:
    """How far along a job is (0 to 1) and what it is doing. Work is split into stages; each stage fills part of the whole.
    The window shows it; the command line ignores it (nothing is set as the callback)."""

    def __init__(self):
        self.callback = None
        self.lo, self.hi, self.last, self.text = 0.0, 1.0, 0.0, ""

    def reset(self):
        self.lo, self.hi, self.last, self.text = 0.0, 1.0, 0.0, ""

    def window(self, lo, hi):
        self.lo, self.hi = lo, hi

    def report(self, fraction, text=None):
        if text:
            self.text = text
        overall = max(self.last, self.lo + (self.hi - self.lo) * min(max(fraction, 0.0), 1.0))      # never goes backwards
        self.last = overall
        if self.callback:
            self.callback(overall, self.text)

    @contextlib.contextmanager
    def stage(self, a, b, text=None):
        """inside this block, 0..1 means the part from a to b of the current window"""
        lo, hi = self.lo, self.hi
        self.lo, self.hi = lo + (hi - lo) * a, lo + (hi - lo) * b
        self.report(0.0, text)
        try:
            yield
        finally:
            self.report(1.0)
            self.lo, self.hi = lo, hi


PROGRESS = Progress()
_OUT_TIME = re.compile(rb"out_time_(?:us|ms)=(\d+)")
_DONE = re.compile(rb"(\d+)%\s*done")


def run(cmd, env=None, track=None):
    """Runs a helper program. track = ("ffmpeg", seconds of output) or ("atracdenc", None) reports its progress as it goes."""
    cmd = list(cmd)
    check_cancel()
    if track and track[0] == "ffmpeg":
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, creationflags=NOWND | PRIORITY)
    ACTIVE.append(proc)
    if CANCEL.is_set():                                # Stop was pressed while it was starting
        proc.terminate()
    tail = b""
    while True:
        chunk = proc.stdout.read1(4096)
        if not chunk:
            break
        tail = (tail + chunk)[-4000:]
        if track and track[0] == "ffmpeg" and track[1]:
            m = _OUT_TIME.findall(tail[-300:])
            if m:
                PROGRESS.report(int(m[-1]) / 1e6 / track[1])
        elif track and track[0] == "atracdenc":
            m = _DONE.findall(tail[-300:])
            if m:
                PROGRESS.report(int(m[-1]) / 100.0)
    code = proc.wait()
    if proc in ACTIVE:
        ACTIVE.remove(proc)
    check_cancel()
    if code:
        fail("command failed (%d): %s\n%s" % (code, " ".join(cmd), tail.decode("latin1")[-2000:]))


FIT = {
    "crop": "scale=%(w)d:%(h)d:force_original_aspect_ratio=increase:flags=lanczos,crop=%(w)d:%(h)d",
    "pad": "scale=%(w)d:%(h)d:force_original_aspect_ratio=decrease:flags=lanczos,pad=%(w)d:%(h)d:(ow-iw)/2:(oh-ih)/2",
    "stretch": "scale=%(w)d:%(h)d:flags=lanczos",
}


def encode_video(ffmpeg, src, out264, seconds, width, height, kbps, gop, refs=1, weightp=0, fit="crop", bufsize=None, bframes=0, start=0, total=None):
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + (["-ss", "%.3f" % start] if start else []) + ["-i", src]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-an", "-vf", FIT[fit] % dict(w=width, h=height) + ",setsar=1,fps=30000/1001",
            "-c:v", "libx264", "-profile:v", "main", "-level", "2.1", "-bf", str(bframes), "-refs", str(refs),
            "-g", str(gop), "-keyint_min", str(gop), "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.5),
            "-bufsize", "%dk" % (bufsize or int(kbps * 1.5)), "-pix_fmt", "yuv420p", "-x264-params", X264_PARAMS + ":weightp=%d" % weightp + (":b-pyramid=none:b-adapt=0:weightb=0" if bframes else ""),
            "-f", "h264", out264]
    run(cmd, track=("ffmpeg", seconds or total))


# Small PSP speakers need a hot signal: normalise perceived loudness (LUFS) with the peak held at -1 dBFS.
DEFAULT_LUFS = -12


def has_audio(ffmpeg, src):
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", src], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWND)
    return "Audio:" in r.stdout


def encode_audio(ffmpeg, atracdenc, src, out_oma, seconds, lufs=DEFAULT_LUFS, kbps=128, silent_seconds=None, start=0, total=None):
    wav = out_oma + ".wav"
    af = "anull"
    if lufs is not None:
        af = "loudnorm=I=%d:TP=-1:LRA=5,aresample=44100,aformat=channel_layouts=stereo,alimiter=limit=0.89:level=disabled" % lufs
    PROGRESS.report(0.0, "Preparing the sound\u2026")
    if silent_seconds:
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % silent_seconds, "-c:a", "pcm_s16le", wav])
    else:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + (["-ss", "%.3f" % start] if start else []) + ["-i", src]
        if seconds:
            cmd += ["-t", str(seconds)]
        with PROGRESS.stage(0.0, 0.25, "Preparing the sound\u2026"):
            run(cmd + ["-vn", "-af", af, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", wav], track=("ffmpeg", seconds or total))
    env = dict(os.environ, AT3P_FRAME=str(frame_bytes_for_kbps(kbps)))     # needs the patched atracdenc (tools/atracdenc)
    with PROGRESS.stage(0.25, 1.0, "Encoding the sound\u2026"):
        src_wav, dst_oma, tmp = wav, out_oma, None
        if not (is_ascii(wav) and is_ascii(out_oma)):            # atracdenc cannot open files in folders with other letters in their names
            tmp = ascii_temp_dir()
            src_wav, dst_oma = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.oma")
            shutil.copyfile(wav, src_wav)
        try:
            run([atracdenc, "-e", "atrac3plus", "--container", "oma", "-i", src_wav, "-o", dst_oma], env, track=("atracdenc", None))
            if tmp:
                shutil.move(dst_oma, out_oma)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    os.remove(wav)


class Streamed:
    """what make_pmf returns when it wrote the movie straight to a.stream_out (a long movie is never held in memory): the size written"""

    def __init__(self, path, size):
        self.path, self.size = path, size

    def __len__(self):
        return self.size


def make_pmf(a):
    """video (+ audio) -> pmf bytes. a.limit_bytes (optional) is a size budget the video bitrate is lowered to fit."""
    own = not a.workdir
    work = a.workdir or tempfile.mkdtemp(prefix="pmfkit_")
    try:
        return _make_pmf(a, work)
    finally:
        if own:                                        # the picture and sound files can be tens of MB each: never leave them behind
            shutil.rmtree(work, ignore_errors=True)


def _make_pmf(a, work):
    a.ffmpeg = tool(a.ffmpeg)
    a.atracdenc = tool(a.atracdenc) if a.atracdenc else None
    os.makedirs(work, exist_ok=True)
    es = os.path.join(work, "video.264")
    opt = dict(ICON1) if a.icon1 else {}
    w, h = (opt["width"], opt["height"]) if a.icon1 else (480, 272)
    video_kbps = a.video_kbps or (ICON1_VIDEO_KBPS if a.icon1 else 1000)
    gop = a.gop or (ICON1_GOP if a.icon1 else 59)
    audio_kbps = a.audio_kbps or (ICON1_AUDIO_KBPS if a.icon1 else 128)
    audio = None
    total = a.seconds or max(0.1, probe_seconds(a.ffmpeg, a.input) - getattr(a, "start", 0))
    if a.atracdenc:
        oma = os.path.join(work, "audio.oma")
        source = a.audio or a.input
        silent = None
        if not has_audio(a.ffmpeg, source):
            print("your movie has no sound, so a silent track is added")
            silent = a.seconds or (probe_seconds(a.ffmpeg, source) - getattr(a, "start", 0))
            audio_kbps = 32                                  # silence needs no room
        with PROGRESS.stage(0.0, 0.15, "Preparing the sound\u2026"):
            encode_audio(a.ffmpeg, a.atracdenc, source, oma, a.seconds, lufs=None if a.quiet_audio else a.lufs, kbps=audio_kbps, silent_seconds=silent,
                         start=0 if a.audio else getattr(a, "start", 0), total=total)
        audio = atrac3p.read_oma(oma)
    if not a.icon1:
        opt = dict(version=a.version or "0012", style=a.style or "B")
    limit = getattr(a, "limit_bytes", None)
    if limit is None and a.icon1 and not a.no_size_fit:
        limit = int(a.max_kb * 1000) if a.max_kb else ICON1_MAX_BYTES
    audio_bytes = len(b"".join(audio.units())) * 2048 // 2024 if audio else 0
    pmf = b""
    bufsize = None
    opt["strict"] = not a.no_psp_check
    refs = a.refs
    if a.bframes:
        refs = max(refs, 2)                        # a B-frame needs a past and a future reference
        opt["allow_b"] = True
    cap = getattr(a, "max_video_kbps", None) or (400 if a.icon1 and limit else None)
    best = None                                              # the biggest result that fits the budget
    shares = [(0.0, 0.6), (0.6, 0.85), (0.85, 0.94), (0.94, 0.98), (0.98, 1.0)]       # each try fills a smaller part of the bar: the number of tries isn't known
    for attempt in range(9):
        lo, hi = shares[min(attempt, 4)]
        with PROGRESS.stage(0.15 + 0.82 * lo, 0.15 + 0.82 * hi, "Encoding the picture\u2026" if attempt == 0 else "Fitting it to the best quality\u2026"):
            encode_video(a.ffmpeg, a.input, es, a.seconds, w, h, video_kbps, gop, refs, a.weightp, a.fit, bufsize, a.bframes, getattr(a, "start", 0), total)
        PROGRESS.report(0.97, "Packaging the movie\u2026")
        try:
            if limit is None and getattr(a, "stream_out", None) and not a.bframes:
                opt_stream = {k: v for k, v in opt.items() if k != "allow_b"}
                pmf = Streamed(a.stream_out, mux_file(es, a.stream_out, audio, **opt_stream))     # no size budget to fit: written piece by piece
            else:
                pmf = mux(open(es, "rb").read(), audio, **opt)
        except ValueError as e:
            if "picture is larger" not in str(e):
                raise
            # a picture over 65,535 bytes cannot be indexed: shrink the VBV buffer so the encoder caps picture sizes
            bufsize = int((bufsize or video_kbps * 1.5) * 0.6)
            print("a picture is over 65,535 bytes; retrying with a %d kbit VBV buffer" % bufsize)
            continue
        if limit is None:
            best = pmf
            break
        if len(pmf) <= limit:
            if best is None or len(pmf) > len(best):
                best = pmf
            if not cap or video_kbps >= cap or len(pmf) >= 0.95 * limit:
                break                                        # full enough
            new_kbps = min(cap, int(video_kbps * 0.985 * (limit - audio_bytes) / max(len(pmf) - audio_bytes, 1)))
            if new_kbps <= video_kbps * 1.03:
                break
            print("%d bytes leaves room in the %d byte budget; video %d -> %d kbps" % (len(pmf), limit, video_kbps, new_kbps))
            video_kbps = new_kbps
            continue
        if limit <= audio_bytes + 4096:
            fail("the sound alone would be about %d KB, more than the %d KB limit. Use a shorter clip." % (audio_bytes // 1000, limit // 1000))
        new_kbps = max(8, int(video_kbps * 0.97 * (limit - audio_bytes) / (len(pmf) - audio_bytes)))
        if new_kbps >= video_kbps:
            new_kbps = int(video_kbps * 0.9)
        print("%d bytes is over the %d byte size budget; video %d -> %d kbps" % (len(pmf), limit, video_kbps, new_kbps))
        if best is not None and new_kbps <= video_kbps * 0.5:
            break
        video_kbps = new_kbps
    if best is None:
        fail("could not make the movie fit its size limit; use a shorter part" if limit else "could not keep every picture under 65,535 bytes; lower --video-kbps")
    PROGRESS.report(1.0, "Movie ready")
    return best


def probe_seconds(ffmpeg, src):
    """length of a media file in seconds (read from ffmpeg's banner)"""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", src], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWND)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stdout)
    if not m:
        fail("cannot read the length of %r" % src)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def grab_rgba(ffmpeg, src, width, height, at=None):
    """one picture (width*height*4 RGBA bytes, cropped to fill) from an image or from a video at `at` seconds"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"] + (["-ss", "%.3f" % at] if at else []) + ["-i", src, "-frames:v", "1",
           "-vf", FIT["crop"] % dict(w=width, h=height) + ",format=rgba", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWND)
    if r.returncode or len(r.stdout) != width * height * 4:
        fail("could not read a %dx%d picture from %r: %s" % (width, height, src, r.stderr.decode("latin1")[-300:]))
    return r.stdout


def cmd_gameboot(a):
    ff = tool(a.ffmpeg)
    start = a.start or 0.0
    seconds = a.seconds or (probe_seconds(ff, a.input) - start)
    budget = int(a.budget_kb * 1000)
    rco_bytes = None
    if a.pmf_only:
        pass
    elif a.rco:
        rco_bytes = rcomod.load(open(a.rco, "rb").read())     # fails early, with an explanation, for an encrypted file
        rcomod.find_delay(rco_bytes)
    elif seconds * 1000 > STOCK_SECONDS * 1000 + 100:
        fail("this movie is %.1f s long but the stock gameboot lasts %.1f s. Give your own decrypted opening_plugin.rco with --rco "
                 "(it is patched, the original is not touched) or trim with -t %.1f" % (seconds, STOCK_SECONDS, STOCK_SECONDS))
    audio_kbps = a.audio_kbps
    if a.atracdenc and not audio_kbps:
        audio_kbps = pick_audio_kbps(seconds, 128, budget)
        if audio_kbps != 128:
            print("sound lowered to %d kbps so that it takes a fair share of the %d byte budget" % (audio_kbps, budget))
    audio_bytes = int(seconds * (audio_kbps or 0) * 125) if a.atracdenc else 0
    video_kbps = a.video_kbps or int(max(50, min(6000, 0.93 * (budget - audio_bytes) * 8 / seconds / 1000)))
    mk = argparse.Namespace(ffmpeg=a.ffmpeg, atracdenc=a.atracdenc, workdir=a.workdir, icon1=False, video_kbps=video_kbps, gop=a.gop,
                            audio_kbps=audio_kbps, audio=a.audio, input=a.input, seconds=a.seconds, quiet_audio=a.quiet_audio,
                            lufs=a.lufs, start=start, version=None, style=None, no_psp_check=False, refs=a.refs, bframes=a.bframes,
                            weightp=0, fit=a.fit, max_kb=None, no_size_fit=False, limit_bytes=budget, max_video_kbps=6000)
    with PROGRESS.stage(0.0, 0.9):
        pmf = make_pmf(mk)
    PROGRESS.report(0.9, "Writing the file")
    if a.pmf_only:
        open(a.output, "wb").write(pmf)
        print("wrote %s (%d bytes, %.1f s)" % (a.output, len(pmf), movie_ms(pmf) / 1000))
        PROGRESS.report(1.0)
        return
    files = {"/vsh/resource/gameboot.pmf": pmf}
    ms = movie_ms(pmf)
    if ms > STOCK_SECONDS * 1000 + 100:
        if rco_bytes is None:
            fail("the finished movie is %.1f s: it needs --rco (see above)" % (ms / 1000))
        files["/vsh/resource/opening_plugin.rco"] = rcomod.patch(rco_bytes, ms)
        print("opening_plugin.rco patched: the gameboot lasts %.1f s (was %.1f s)" % (ms / 1000, rcomod.gameboot_ms(rco_bytes) / 1000))
    shot = a.preview or a.input
    at = None if a.preview else start + min(1.0, seconds / 2)
    image = grab_rgba(ff, shot, ptfmod.IMG_W, ptfmod.IMG_H, at)
    icon = grab_rgba(ff, shot, ptfmod.ICON_W, ptfmod.ICON_H, at)
    title = a.title if a.title is not None else os.path.splitext(os.path.basename(a.input))[0]
    out = ctfmod.build(ptfmod.new(icon, image, title, a.author), files, firmware=a.firmware)
    open(a.output, "wb").write(out)
    print("wrote %s (%d bytes; gameboot.pmf %d bytes, %.1f s)" % (a.output, len(out), len(pmf), ms / 1000))
    if len(pmf) > VERIFIED_OK_BYTES:
        print("warning: gameboot.pmf is larger than any verified to play (%d ok, %d failed)" % (VERIFIED_OK_BYTES, VERIFIED_FAIL_BYTES))
    if a.pmf_out:
        open(a.pmf_out, "wb").write(pmf)
    PROGRESS.report(1.0)


def cmd_make(a):
    a.stream_out = None if a.icon1 else a.output
    pmf = make_pmf(a)
    if not isinstance(pmf, Streamed):
        open(a.output, "wb").write(pmf)
    print("wrote %s (%d bytes)" % (a.output, len(pmf)))
    if a.icon1 and len(pmf) > ICON1_VERIFIED_OK:
        print("warning: %d bytes is larger than any ICON1 verified on a real PSP (%d ok, %d showed nothing)" % (len(pmf), ICON1_VERIFIED_OK, ICON1_VERIFIED_FAIL))


def cmd_mux(a):
    audio = atrac3p.read_oma(a.audio) if a.audio else None
    opt = dict(ICON1) if a.icon1 else dict(version=a.version or "0012", style=a.style or "B")
    pmf = mux(open(a.video, "rb").read(), audio, **opt)
    open(a.output, "wb").write(pmf)
    print("wrote %s (%d bytes)" % (a.output, len(pmf)))


def cmd_shrink(a):
    from . import shrink
    a.ffmpeg = tool(a.ffmpeg)
    a.atracdenc = tool(a.atracdenc) if a.atracdenc else None
    ratio = shrink.RATIOS[a.amount] if a.amount in shrink.RATIOS else float(a.amount)
    from . import umdimage
    if umdimage.is_image(a.input):                 # a game's own disc image (.cso / .iso): the movies inside it are shrunk and a new image is written
        results = umdimage.shrink_image(a.input, a.output, a.ffmpeg, a.atracdenc, ratio, a.sound_kbps, a.bframes)
        image = results.pop()
        moved = [r for r in results if r.after < r.before]
        print("%d of %d movies made smaller: %.1f MB -> %.1f MB" % (len(moved), len(results), sum(r.before for r in results) / 1e6, sum(r.after for r in results) / 1e6))
        print("game image: %.1f MB -> %.1f MB (%s)" % (image.before / 1e6, image.after / 1e6, a.output))
        return
    results = shrink.shrink(a.input, a.output, a.ffmpeg, a.atracdenc, ratio, a.sound_kbps, a.bframes)
    done = [r for r in results if not r.note.startswith("failed")]
    failed = len(results) - len(done)
    before, after = sum(r.before for r in done), sum(r.after for r in done)
    print("%d movie%s: %.1f MB -> %.1f MB%s" % (len(done), "" if len(done) == 1 else "s", before / 1e6, after / 1e6,
                                               ", %d could not be used" % failed if failed else ""))
    if not done:
        fail("none of the movies could be made smaller")


def cmd_info(a):
    P, v, au, packs = demux(open(a.pmf, "rb").read())
    frames = (P.last_pts - P.first_pts) / 3003
    print("version %s  %dx%d  stream %d bytes (%d packs)  header duration %.2fs  real length %.2fs" %
          (P.version, P.width, P.height, P.stream_bytes, len(packs), frames * 1001 / 30000, duration_seconds(v, au)))
    print("audio:", "yes" if P.audio else "no", "(%d bytes of audio ES)" % len(au))


def cmd_snd0(a):
    own = not a.workdir
    work = a.workdir or tempfile.mkdtemp(prefix="pmfkit_")
    try:
        _cmd_snd0(a, work)
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def _cmd_snd0(a, work):
    ffmpeg, ad = tool(a.ffmpeg), tool(a.atracdenc)
    os.makedirs(work, exist_ok=True)
    seconds = a.seconds                                   # no length cap: only the 512,000-byte budget matters (notes section 53)
    oma = os.path.join(work, "snd0.oma")
    total = seconds or probe_seconds(ffmpeg, a.input)
    with PROGRESS.stage(0.0, 0.95):
        encode_audio(ffmpeg, ad, a.input, oma, seconds, lufs=None if a.quiet_audio else a.lufs, kbps=a.kbps, total=total)
    PROGRESS.report(0.95, "Writing the sound\u2026")
    st = atrac3p.read_oma(oma)
    data = snd0mod.build(st.frames, st.frame_bytes, pcm_samples=int(seconds * 44100) if seconds else None, loop=not a.no_loop)
    open(a.output, "wb").write(data)
    PROGRESS.report(1.0)
    print("wrote %s (%d bytes, %d frames of %d bytes, %.0f kbps)" % (a.output, len(data), len(st.frames), st.frame_bytes, st.kbps))
    if len(data) > COMBINED_LIMIT:
        print("warning: the XMB does not play an SND0.AT3 over %d bytes, with or without an ICON1" % COMBINED_LIMIT)
    else:
        print("note: ICON1.PMF + SND0.AT3 must total at most %d bytes; this SND0 leaves %d bytes for the ICON1"
              % (COMBINED_LIMIT, COMBINED_LIMIT - len(data)))


def cmd_pbp_info(a):
    print(pbpmod.Pbp.read(a.pbp).describe())


def cmd_pbp_set(a):
    PROGRESS.report(0.1, "Changing the EBOOT\u2026")
    p = pbpmod.Pbp.read(a.pbp)
    if os.path.abspath(a.output) == os.path.abspath(a.pbp):
        fail("refusing to overwrite the input; give a different -o name")
    for opt, name in (("icon1", "ICON1.PMF"), ("icon0", "ICON0.PNG"), ("pic0", "PIC0.PNG"), ("pic1", "PIC1.PNG"), ("snd0", "SND0.AT3")):
        path = getattr(a, opt)
        if path:
            data = open(path, "rb").read()
            if name == "ICON1.PMF" and (data[:4] != b"PSMF" or len(data) % 2048):
                fail("%s does not look like a PMF (no PSMF header / size not a multiple of 2048)" % path)
            p.replace(name, data)
    for name in a.remove or []:
        p.replace(name, b"")
    if a.title is not None:
        p.set_title(a.title)
    pad = p.realign()
    if pad:
        print("note: padded DATA.PSP by %d zero bytes so DATA.PSAR keeps its original alignment" % pad)
    out = p.to_bytes()
    open(a.output, "wb").write(out)
    PROGRESS.report(1.0)
    print("wrote %s (%d bytes)" % (a.output, len(out)))
    for n in p.alignment_notes():
        print("note:", n)
    icon1, snd0 = len(p.get("ICON1.PMF")), len(p.get("SND0.AT3"))
    if icon1 > ICON1_VERIFIED_OK:
        print("warning: ICON1 is %d bytes; sizes up to %d played in the XMB, %d showed nothing" % (icon1, ICON1_VERIFIED_OK, ICON1_VERIFIED_FAIL))
    if snd0 and not icon1 and snd0 > COMBINED_LIMIT:
        print("warning: SND0 is %d bytes, over the %d the XMB accepts: it will NOT be played (notes section 51)" % (snd0, COMBINED_LIMIT))
    elif snd0 and icon1 + snd0 > COMBINED_LIMIT:
        print("warning: ICON1 (%d) + SND0 (%d) = %d bytes, over the %d the XMB accepts together: it will NOT play the SND0 "
              "and will play the sound inside ICON1 instead (notes section 49)" % (icon1, snd0, icon1 + snd0, COMBINED_LIMIT))
    elif snd0 and icon1:
        print("note: ICON1 + SND0 = %d bytes (limit %d); the SND0 plays and replaces any sound inside ICON1"
              % (icon1 + snd0, COMBINED_LIMIT))


def main(argv=None):
    p = argparse.ArgumentParser(prog="pmfkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--version", choices=["0012", "0014"], help="PSMF header version (default 0012)")
    common.add_argument("--style", choices=["A", "B"], help="stream style (default B, see mux.PROFILES)")
    common.add_argument("--icon1", action="store_true", help="make an ICON1.PMF: 144x80, GOP 30, style A (overrides size/style/version)")
    m = sub.add_parser("make", parents=[common], help="video file -> pmf (needs ffmpeg with libx264)")
    m.add_argument("input")
    m.add_argument("-o", "--output", required=True)
    m.add_argument("--ffmpeg", default="ffmpeg")
    m.add_argument("--atracdenc", help="path to atracdenc; enables audio")
    m.add_argument("--audio", help="separate audio source (default: the input's own audio)")
    m.add_argument("--start", type=float, default=0.0, help="start this many seconds into the movie")
    m.add_argument("-t", "--seconds", type=float, help="trim to this length")
    m.add_argument("--video-kbps", type=int, help="default 1000 (ICON1: 100)")
    m.add_argument("--gop", type=int, help="default 59 (ICON1: 30)")
    m.add_argument("--fit", default="crop", choices=sorted(FIT), help="how to fit the picture into 480x272")
    m.add_argument("--audio-kbps", type=int, help="ATRAC3plus bitrate (<=320; default 128 as in Sony-made gameboots, ICON1: 64)")
    m.add_argument("--lufs", type=int, default=DEFAULT_LUFS, help="target loudness, higher = louder (default -12)")
    m.add_argument("--quiet-audio", action="store_true", help="skip the loudness boost")
    m.add_argument("--refs", type=int, default=1)
    m.add_argument("--bframes", type=int, default=0, help="B-frames between P-frames (0 = none, the only setting Sony composers used; "
                   "1 matches LocoRoco 2). Needs 2 reference frames; our own B-frame files are untested on hardware")
    m.add_argument("--weightp", type=int, default=0, choices=[0, 1, 2])
    m.add_argument("--workdir")
    m.add_argument("--max-kb", type=float, help="ICON1 size budget in KB (default 500); the video bitrate is lowered until it fits")
    m.add_argument("--no-psp-check", action="store_true", help="experiments only: skip the check that the video uses settings the PSP played (1 ref frame, Main L2.1, no B-frames)")
    m.add_argument("--no-size-fit", action="store_true", help="ICON1: do not shrink the video to fit the size budget")
    m.set_defaults(fn=cmd_make)
    g = sub.add_parser("gameboot", help="video -> gameboot-only CTF theme (CXMB); lengthens the boot if you give your own opening_plugin.rco")
    g.add_argument("input")
    g.add_argument("-o", "--output", required=True, help="the .ctf to write (copy it to PSP/THEME)")
    g.add_argument("--rco", help="your own DECRYPTED opening_plugin.rco (needed for movies over 2.5 s); it is patched in the CTF, never in place")
    g.add_argument("--title", help="theme title stored in the PTF (default: the input's file name)")
    g.add_argument("--author", default="")
    g.add_argument("--firmware", default="661", help="firmware digits for the CTF marker (661 = 6.61, 660 = 6.60)")
    g.add_argument("--preview", help="picture for the theme preview (default: a frame of the video)")
    g.add_argument("--ffmpeg", default="ffmpeg")
    g.add_argument("--atracdenc", help="path to atracdenc; enables sound")
    g.add_argument("--audio", help="separate audio source (default: the input's own audio)")
    g.add_argument("--audio-kbps", type=int, help="ATRAC3plus bitrate (default: 128, lowered for long clips)")
    g.add_argument("--start", type=float, default=0.0, help="start this many seconds into the movie")
    g.add_argument("-t", "--seconds", type=float, help="trim to this length")
    g.add_argument("--video-kbps", type=int, help="start bitrate (default: fitted to the size budget)")
    g.add_argument("--budget-kb", type=float, default=BUDGET_BYTES / 1000, help="size budget of gameboot.pmf in KB (default %d)" % (BUDGET_BYTES // 1000))
    g.add_argument("--gop", type=int, default=59)
    g.add_argument("--fit", default="crop", choices=sorted(FIT))
    g.add_argument("--lufs", type=int, default=DEFAULT_LUFS)
    g.add_argument("--quiet-audio", action="store_true")
    g.add_argument("--refs", type=int, default=1)
    g.add_argument("--bframes", type=int, default=0)
    g.add_argument("--workdir")
    g.add_argument("--pmf-only", action="store_true", help="write just the gameboot.pmf (no CTF, no RCO needed)")
    g.add_argument("--pmf-out", help="also write the gameboot.pmf on its own")
    g.set_defaults(fn=cmd_gameboot)
    x = sub.add_parser("mux", parents=[common], help="H.264 Annex B (+ OMA ATRAC3plus) -> pmf")
    x.add_argument("video")
    x.add_argument("-a", "--audio")
    x.add_argument("-o", "--output", required=True)
    x.set_defaults(fn=cmd_mux)
    sn = sub.add_parser("snd0", help="audio file -> SND0.AT3 (EXPERIMENTAL, see pmfkit/snd0.py)")
    sn.add_argument("input")
    sn.add_argument("-o", "--output", required=True)
    sn.add_argument("--ffmpeg", default="ffmpeg")
    sn.add_argument("--atracdenc", required=True)
    sn.add_argument("-t", "--seconds", type=float, help="trim to this length (default: the whole input)")
    sn.add_argument("--kbps", type=int, default=64)
    sn.add_argument("--lufs", type=int, default=DEFAULT_LUFS)
    sn.add_argument("--quiet-audio", action="store_true")
    sn.add_argument("--no-loop", action="store_true", help="omit the smpl loop chunk")
    sn.add_argument("--workdir")
    sn.set_defaults(fn=cmd_snd0)
    b = sub.add_parser("pbp", help="inspect / edit an EBOOT.PBP (never overwrites the input)")
    bs = b.add_subparsers(dest="pbp_cmd", required=True)
    bi = bs.add_parser("info", help="list the sections of an EBOOT.PBP")
    bi.add_argument("pbp")
    bi.set_defaults(fn=cmd_pbp_info)
    bt = bs.add_parser("set", help="swap sections / title into a copy of an EBOOT.PBP")
    bt.add_argument("pbp")
    bt.add_argument("-o", "--output", required=True)
    for opt in ("icon1", "icon0", "pic0", "pic1", "snd0"):
        bt.add_argument("--" + opt, help="file to put into the %s section" % opt.upper())
    bt.add_argument("--remove", nargs="+", metavar="SECTION", help="empty these sections, e.g. SND0")
    bt.add_argument("--title", help="XMB title (PARAM.SFO TITLE)")
    bt.set_defaults(fn=cmd_pbp_set)
    sh = sub.add_parser("shrink", help="make a game's PMF movies smaller (a .pmf, or a folder of them; same names inside the output folder)")
    sh.add_argument("input", help="a .pmf file, or a folder with .pmf files")
    sh.add_argument("-o", "--output", required=True, help="the new .pmf, or the folder for the new movies")
    sh.add_argument("--ffmpeg", default="ffmpeg")
    sh.add_argument("--atracdenc", help="path to atracdenc (only needed with --sound-kbps)")
    sh.add_argument("--amount", default="much", help="the share of the picture bitrate to keep: a number such as 0.5 (1.0 leaves the picture as it is and only changes the sound with --sound-kbps), or the words smaller (0.75), much (0.5), tiny (0.3)")
    sh.add_argument("--sound-kbps", type=int, help="encode the sound again at this ATRAC3plus bitrate (default: keep the sound as it is)")
    sh.add_argument("--bframes", type=int, default=None, help="B-frames in the new picture. Default: copy what the original movie does (mirror mode: B-frames, reference frames, GOP starts, buffer numbers and entry-point map stay as they are, only the bitrate changes); a number forces that many")
    sh.set_defaults(fn=cmd_shrink)
    i = sub.add_parser("info", help="show header info of a pmf")
    i.add_argument("pmf")
    i.set_defaults(fn=cmd_info)
    a = p.parse_args(argv)
    try:
        a.fn(a)
    except BuildError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
