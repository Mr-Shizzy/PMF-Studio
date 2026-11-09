"""`PMF Studio.exe --selftest`: builds and takes apart a few tiny files with the program's own helper programs and writes the result to
selftest_result.txt beside the program. Used to check a freshly built copy (and the bundled ffmpeg) really works."""
import os
import subprocess
import sys
import tempfile
import time

from . import VERSION, STAGE, jobs, paths, settings
from pmfkit import extract, toolinfo
from pmfkit.demux import demux

NOWND = 0x08000000 if os.name == "nt" else 0


def run():
    lines, ok = [], True

    def say(text, good=True):
        nonlocal ok
        ok = ok and good
        lines.append(("ok    " if good else "FAIL  ") + text)

    status = paths.check_tools()
    for name, (path, text) in status.items():
        say("%s: %s" % (name, text if path else "NOT FOUND"), bool(path) and "won't" not in text)
    if all(p for p, _ in status.values()):
        tools = {"ffmpeg": status["ffmpeg"][0], "atracdenc": status["atracdenc"][0]}
        say("ffmpeg version %s.%s, picture flag %s" % (*toolinfo.ffmpeg_version(tools["ffmpeg"]), " ".join(toolinfo.passthrough_args(tools["ffmpeg"]))))
        work = tempfile.mkdtemp(prefix="selftest_", dir=tempfile.gettempdir() if not settings.usable(os.path.join(paths.data_dir(), "temp")) else os.path.join(paths.data_dir(), "temp"))
        src = os.path.join(work, "clip.mp4")
        try:
            r = subprocess.run([tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
                                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWND)
            say("made a test clip", r.returncode == 0 and os.path.exists(src))
            noise = os.path.join(work, "noise.wav")          # busy sound at the lowest quality: a sound encoder build without its fix stops here
            subprocess.run([tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:r=44100:a=0.3", "-ac", "2", noise],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NOWND)
            steps = [
                ("gameboot movie", lambda: jobs.gameboot(dict(movie=src, out=work + "/gb.pmf", ctf=False), tools, lambda l: None), work + "/gb.pmf"),
                ("C-Intro movie", lambda: jobs.cintro(dict(movie=src, out=work + "/ci.pmf"), tools, lambda l: None), work + "/ci.pmf"),
                ("AT3 sound", lambda: jobs.at3(dict(sound=src, out=work + "/s.at3", kbps=64, lufs=-12, keep=False, loop=True), tools, lambda l: None), work + "/s.at3"),
                ("AT3 sound, 32 kbps, busy sound", lambda: jobs.at3(dict(sound=noise, out=work + "/n32.at3", kbps=32, lufs=-12, keep=False, loop=True), tools, lambda l: None), work + "/n32.at3"),
                ("PMF to MP4", lambda: jobs.extract(dict(src=work + "/gb.pmf", out=work + "/gb.mp4", sound_too=True), tools, lambda l: None), work + "/gb.mp4"),
                ("smaller game movie", lambda: jobs.shrink(dict(src=work + "/gb.pmf", out=work + "/shrunk", picture="0.5", sound="64"), tools, lambda l: None), work + "/shrunk/gb.pmf"),
                ("AT3 to WAV", lambda: jobs.extract_sound(dict(sound=work + "/s.at3", out=work + "/s.wav", fmt="wav"), tools, lambda l: None), work + "/s.wav"),
                ("AT3 to MP3", lambda: jobs.extract_sound(dict(sound=work + "/s.at3", out=work + "/s.mp3", fmt="mp3", mp3kbps="192 kbps"), tools, lambda l: None), work + "/s.mp3"),
            ]
            for name, job, out in steps:
                try:
                    job()
                    say("%s (%d bytes)" % (name, os.path.getsize(out)), os.path.getsize(out) > 1000)
                except Exception as e:
                    say("%s: %s" % (name, str(e)[:200]), False)
            try:                                              # a whole game: a small disc is built, its movie shrunk in place, the new disc read back
                import shutil
                from pmfkit import umdbuild, umdimage
                game = os.path.join(work, "game")
                os.makedirs(game + "/PSP_GAME/USRDIR/FMV")
                shutil.copy(work + "/ci.pmf", game + "/PSP_GAME/USRDIR/FMV/MOVIE.PMF")
                shutil.copy(work + "/ci.pmf", game + "/PSP_GAME/USRDIR/FMV/MOVIE_FR.PMF")
                with open(game + "/UMD_DATA.BIN", "wb") as f:
                    f.write(b"ULES-00000|0000000000000000|0001|G".ljust(48, b"\0"))
                with open(game + "/PSP_GAME/PARAM.SFO", "wb") as f:
                    f.write(b"x" * 200)
                umdbuild.build(game, umdbuild.sequential_list(game), work + "/game.iso", log=lambda *a: None)
                jobs.shrink(dict(src=work + "/game.iso", out=work + "/game_small.cso", picture="0.5", sound="64"), tools, lambda l: None)
                sizes = {}
                for name in ("game.iso", "game_small.cso"):
                    img = umdimage.Image(work + "/" + name)
                    try:
                        sizes[name] = {e.path: e.size for e in umdimage.walk(img)}
                    finally:
                        img.close()
                big, small = sizes["game.iso"]["\\PSP_GAME\\USRDIR\\FMV\\MOVIE.PMF"], sizes["game_small.cso"]["\\PSP_GAME\\USRDIR\\FMV\\MOVIE.PMF"]
                say("a whole game made smaller (movie %d -> %d bytes, both names)" % (big, small),
                    small < big and sizes["game_small.cso"]["\\PSP_GAME\\USRDIR\\FMV\\MOVIE_FR.PMF"] == small)
            except Exception as e:
                say("a whole game made smaller: %s" % str(e)[:200], False)
            if os.path.exists(work + "/gb.pmf"):
                pmf = open(work + "/gb.pmf", "rb").read()
                say("the gameboot is a real PMF under 3.03 MB", pmf[:4] == b"PSMF" and len(pmf) <= 3030000)
                es = work + "/v.264"
                open(es, "wb").write(demux(pmf)[1])
                r = subprocess.run([tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-f", "h264", "-r", "30000/1001", "-i", es, "-frames:v", "3"] +
                                   toolinfo.passthrough_args(tools["ffmpeg"]) + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, creationflags=NOWND)
                say("the player's picture command works (%d bytes for 3 pictures)" % len(r.stdout), len(r.stdout) == 3 * 640 * 360 * 3 or len(r.stdout) == 3 * 480 * 272 * 3)
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
    lines.insert(0, "PMF Studio %s %s" % (VERSION, STAGE))
    lines.append("SELFTEST " + ("OK" if ok else "FAILED"))
    text = "\n".join(lines) + "\n"
    try:
        open(os.path.join(paths.data_dir(), "selftest_result.txt"), "w", encoding="utf8").write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text)
    except OSError:
        pass
    if sys.stdout:
        print(text)
    return 0 if ok else 1
