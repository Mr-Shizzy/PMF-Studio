"""Take a gameboot (a .pmf, or the gameboot inside a .ctf theme) apart: an MP4 for watching, and optionally the sound on its own."""
import os
import subprocess

from . import atrac3p, ctf, snd0
from .demux import demux, duration_seconds

CTF_PATH = "/vsh/resource/gameboot.pmf"
NOWND = 0x08000000 if os.name == "nt" else 0


def load_pmf(path):
    """the PMF bytes of a .pmf file, or of the gameboot inside a .ctf; ValueError says what is wrong"""
    data = open(path, "rb").read()
    if data[:4] == b"\x00PTF":
        files = ctf.parse(data)["files"]
        if CTF_PATH not in files:
            raise ValueError("That CTF theme has no gameboot in it.")
        return files[CTF_PATH]
    if data[:4] != b"PSMF":
        raise ValueError("That isn't a PMF movie or a CTF theme.")
    return data


def _run(cmd, total=None):
    from . import cli
    try:
        cli.run(cmd, track=("ffmpeg", total) if total else None)
    except cli.BuildError as err:
        raise ValueError(str(err))


def extract(pmf, ffmpeg, out_mp4, workdir, sound_too=False, log=print):
    """pmf bytes -> out_mp4 (picture and sound). With sound_too, the sound is also saved next to it as .at3 and .wav.
    -> list of the files written"""
    from .cli import PROGRESS
    PROGRESS.report(0.0, "Reading the movie\u2026")
    _, video, audio, _ = demux(pmf)
    total = duration_seconds(video, audio)
    if not video:
        raise ValueError("There is no picture in that movie.")
    os.makedirs(workdir, exist_ok=True)
    es = os.path.join(workdir, "extract.264")
    open(es, "wb").write(video)
    at3 = wav = None
    if audio:
        st = atrac3p.from_units(audio)
        at3 = os.path.join(workdir, "extract.at3")
        open(at3, "wb").write(snd0.build(st.frames, st.frame_bytes, loop=False))
        wav = os.path.join(workdir, "extract.wav")
        # the MP4 is made from the decoded sound, not from the AT3 file: ffmpeg gives an AT3 file's packets uneven times,
        # which squeezed the sound into a fraction of the movie's length and made players stall or drop it
        PROGRESS.report(0.1, "Decoding the sound\u2026")
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", at3, "-c:a", "pcm_s16le", wav], total)
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "h264", "-r", "30000/1001", "-i", es] + (["-i", wav] if wav else [])
    tail = (["-c:a", "aac", "-b:a", "192k"] if wav else ["-an"]) + ["-movflags", "+faststart", out_mp4]
    PROGRESS.report(0.4, "Making the MP4\u2026")
    try:
        _run(base + ["-c:v", "copy"] + tail, total)                # the picture is copied as it is, nothing is lost
        log("saved %s" % out_mp4)
    except ValueError:
        log("copying the picture failed; encoding it instead")
        _run(base + ["-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p"] + tail, total)
        log("saved %s" % out_mp4)
    PROGRESS.report(0.95, "Saving the sound\u2026")
    written = [out_mp4]
    if sound_too:
        if not at3:
            log("this gameboot has no sound")
        else:
            stem = os.path.splitext(out_mp4)[0]
            open(stem + ".at3", "wb").write(open(at3, "rb").read())
            open(stem + ".wav", "wb").write(open(wav, "rb").read())
            written += [stem + ".at3", stem + ".wav"]
            log("saved the sound as %s.at3 and %s.wav" % (os.path.basename(stem), os.path.basename(stem)))
    PROGRESS.report(1.0)
    return written


def mp3_available(ffmpeg):
    """whether this ffmpeg can write MP3 (most builds include the LAME encoder; the MP3 patents ran out in 2017)"""
    r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWND)
    return "libmp3lame" in r.stdout


def extract_sound(src, ffmpeg, out, fmt="wav", mp3_kbps=192, log=print):
    """any sound file (an AT3 from a game, say) -> a WAV (16-bit, same rate and channels) or an MP3. Nothing else about it is changed."""
    from .cli import PROGRESS, probe_seconds
    PROGRESS.report(0.0, "Reading the sound\u2026")
    total = probe_seconds(ffmpeg, src)
    if fmt == "mp3":
        if not mp3_available(ffmpeg):
            raise ValueError("This copy of ffmpeg can't make MP3 files. Choose WAV instead.")
        codec = ["-c:a", "libmp3lame", "-b:a", "%dk" % mp3_kbps]
    else:
        codec = ["-c:a", "pcm_s16le"]
    PROGRESS.report(0.05, "Saving the %s\u2026" % fmt.upper())
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn"] + codec + [out], total)
    PROGRESS.report(1.0)
    log("saved %s" % out)
    return out
