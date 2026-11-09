"""What each button does: builds pmfkit command lines and runs them (the window is a front end for the same code as the command line)."""
import contextlib
import io
import os
import shutil
import tempfile

from pmfkit import cli
from pmfkit.snd0 import COMBINED_LIMIT


class Log(io.TextIOBase):
    def __init__(self, emit):
        self.emit, self.buf = emit, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.emit(line)
        return len(s)


def run(argv, emit, window=(0.0, 1.0)):
    """Runs pmfkit with this command line. Raises cli.BuildError with a readable message on failure.
    window: the part of the whole job's progress bar this command covers."""
    cli.PROGRESS.window(*window)
    with contextlib.redirect_stdout(Log(emit)):
        try:
            cli.main(argv)
        except SystemExit as e:
            raise cli.BuildError(str(e.code).replace("error: ", "", 1) if e.code else "failed")


def _part(v):
    """the part of the movie to use, when the user picked one: --start and -t"""
    if v.get("part_length"):
        return ["--start", "%.3f" % v.get("part_start", 0), "-t", "%.3f" % v["part_length"]]
    return []


def _audio(v):
    """how loud the new sound is made: nothing changed, or a target loudness in dB (LUFS). The default is -12, good for the PSP's small speakers."""
    if v.get("keep"):
        return ["--quiet-audio"]
    if v.get("lufs") is not None:
        return ["--lufs", str(int(v["lufs"]))]
    return []


def gameboot(v, tools, emit):
    argv = ["gameboot", v["movie"], "-o", v["out"], "--ffmpeg", tools["ffmpeg"], "--atracdenc", tools["atracdenc"], "--fit", v.get("fit", "crop")] + _audio(v) + _part(v)
    if v.get("sound"):
        argv += ["--audio", v["sound"]]
    if v["ctf"]:
        if v.get("firmware"):
            argv += ["--firmware", v["firmware"].replace(".", "")]
        if v.get("rco"):
            argv += ["--rco", v["rco"]]
        if v.get("preview"):
            argv += ["--preview", v["preview"]]
    else:
        argv.append("--pmf-only")
    run(argv, emit)


def cintro(v, tools, emit):
    argv = ["make", v["movie"], "-o", v["out"], "--ffmpeg", tools["ffmpeg"], "--atracdenc", tools["atracdenc"], "--video-kbps", "2000", "--fit", v.get("fit", "crop")] + _audio(v) + _part(v)
    run(argv, emit)


def at3(v, tools, emit):
    argv = ["snd0", v["sound"], "-o", v["out"], "--ffmpeg", tools["ffmpeg"], "--atracdenc", tools["atracdenc"], "--kbps", str(v["kbps"])] + _audio(v)
    if not v.get("loop"):
        argv.append("--no-loop")
    run(argv, emit)


def _picture(ffmpeg, src, width, height, out):
    """any picture -> a PNG of exactly this size (cropped to fill)"""
    vf = "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d" % (width, height, width, height)
    run_plain([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-frames:v", "1", "-vf", vf, out])


def run_plain(cmd):
    import subprocess
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode:
        raise cli.BuildError("couldn't read that picture: %s" % r.stdout[-300:])


PICTURES = (("icon0", "--icon0", 144, 80), ("pic1", "--pic1", 480, 272), ("pic0", "--pic0", 310, 180))


def icon(v, tools, emit):
    """Changes a copy of an EBOOT: the icon movie (with its own sound or a different one), the pictures, the title. Anything left empty stays as it is."""
    work = tempfile.mkdtemp(prefix="pmfstudio_")
    try:
        _icon(v, tools, emit, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _icon(v, tools, emit, work):
    final = ["pbp", "set", v["eboot"], "-o", v["out"]]
    changes = 0
    if v.get("sound") and not v.get("movie"):
        raise cli.BuildError("A different sound needs an icon movie too. Pick one, or untick Use a different sound.")
    if v.get("movie"):
        pmf = os.path.join(work, "ICON1.PMF")
        argv = ["make", v["movie"], "--icon1", "-o", pmf, "--ffmpeg", tools["ffmpeg"], "--fit", v.get("fit", "crop")] + _part(v)
        snd = None
        if v.get("sound"):
            snd = os.path.join(work, "SND0.AT3")
            run(["snd0", v["sound"], "-o", snd, "--ffmpeg", tools["ffmpeg"], "--atracdenc", tools["atracdenc"], "--kbps", "64"] + _audio(v), emit, (0.0, 0.25))
            room = COMBINED_LIMIT - os.path.getsize(snd)
            if room < 60000:
                raise cli.BuildError("that sound is too long: it leaves only %d KB for the icon picture. Use a shorter sound." % (max(room, 0) // 1000))
            argv += ["--max-kb", str(room / 1000 - 1)]            # no sound inside the icon: the separate sound replaces it anyway
        else:
            argv += ["--atracdenc", tools["atracdenc"]] + _audio(v)
        run(argv, emit, (0.25, 0.9) if snd else (0.0, 0.9))
        final += ["--icon1", pmf]
        if snd:
            final += ["--snd0", snd]
        changes += 1
    for key, flag, w, h in PICTURES:
        if v.get(key):
            png = os.path.join(work, key + ".png")
            _picture(tools["ffmpeg"], v[key], w, h, png)
            final += [flag, png]
            changes += 1
    title = (v.get("title") or "").strip()
    if title and title != v.get("title0"):
        final += ["--title", title]
        changes += 1
    if not changes:
        raise cli.BuildError("Nothing to change yet. Pick an icon movie, a picture, or type a new title.")
    run(final, emit, (0.9, 1.0))


def extract(v, tools, emit):
    from pmfkit import extract as ex
    stem = os.path.splitext(v["out"])[0]
    mine = [p for p in (v["out"], stem + ".at3", stem + ".wav") if not os.path.exists(p)]       # files this run creates: removed again if it fails
    work = tempfile.mkdtemp(prefix="pmfstudio_")
    try:
        pmf = ex.load_pmf(v["src"])
        cli.PROGRESS.window(0.0, 1.0)
        ex.extract(pmf, tools["ffmpeg"], v["out"], work, bool(v.get("sound_too")), emit)
    except (ValueError, OSError, cli.BuildError) as e:
        for p in mine:
            try:
                os.remove(p)
            except OSError:
                pass
        raise cli.BuildError(str(e))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def shrink(v, tools, emit):
    """Game movies made smaller. v["src"] is a movie or a folder of movies, v["out"] the folder for the new ones (same file names)."""
    src, out = os.path.abspath(v["src"]), os.path.abspath(v["out"])
    from pmfkit import umdimage
    if umdimage.is_image(src):                      # a whole game: v["out"] is the new game file (.cso or .iso)
        if os.path.normcase(out) == os.path.normcase(src):
            raise cli.BuildError("Save the smaller game under another name. PMF Studio never replaces your original.")
        run(_shrink_argv(v, tools, src, out), emit)
        return
    if os.path.isdir(src):
        if out == src or out.startswith(src.rstrip("\\/") + os.sep):
            raise cli.BuildError("Save the smaller movies in a different folder, not in the folder you picked. PMF Studio never replaces your originals.")
        dest = out
    else:
        dest = os.path.join(out, os.path.basename(src))
        if os.path.normcase(dest) == os.path.normcase(src):
            raise cli.BuildError("Save the smaller movie in a different folder. PMF Studio never replaces your originals.")
    run(_shrink_argv(v, tools, src, dest), emit)


def _shrink_argv(v, tools, src, dest):
    """the shrink command for the window's choices: picture amount, sound quality, and the sound tracks to keep (v["keep"], counted from 1)"""
    argv = ["shrink", src, "-o", dest, "--ffmpeg", tools["ffmpeg"], "--amount", str(v.get("picture", "0.5"))]
    recode = v.get("sound", "keep") != "keep"
    keep = str(v.get("keep", "") or "").strip()
    if recode or keep:
        argv += ["--atracdenc", tools["atracdenc"]]
    if recode:
        argv += ["--sound-kbps", str(int(v["sound"]))]
    if keep:
        argv += ["--keep-tracks", keep]
    return argv


def extract_sound(v, tools, emit):
    from pmfkit import extract as ex
    try:
        cli.PROGRESS.window(0.0, 1.0)
        ex.extract_sound(v["sound"], tools["ffmpeg"], v["out"], v.get("fmt", "wav"), int(v.get("mp3kbps", "192 kbps").split()[0]), emit)
    except (ValueError, OSError) as e:
        raise cli.BuildError(str(e))
