"""How long after a jump does the picture (and then the sound) start, and is it the right picture?
usage: python tools/analysis/gui_seek_test.py movie.pmf"""
import hashlib, subprocess, sys, time
sys.path.insert(0, ".")
from pmfstudio import app as A

a = A.App(); a.settings["auto_update"] = False
a.build_ui(); a.show("player"); a.update()
pl = a.player
pl.load(sys.argv[1])
end = time.time() + 2
while time.time() < end:
    a.update(); time.sleep(0.01)
print("%d keyframes found, duration %.1f s" % (len(pl.keyframes), pl.duration))
FPS = 30000 / 1001
for at in (0.0, 7.3, 15.0, 19.0, pl.duration * 0.9):
    pl.stop()
    t0 = time.perf_counter()
    pl.start(at)
    painted = None
    img0 = pl.image
    while time.perf_counter() - t0 < 5:
        a.update()
        if painted is None and pl.image is not img0:
            painted = time.perf_counter() - t0
        if pl.sound_running and painted is not None:
            break
        time.sleep(0.002)
    sound = (time.perf_counter() - t0) if pl.sound_running else None
    print("jump to %6.1f s: first picture after %4.0f ms, sound started after %s" % (at, (painted or 9) * 1000, "%4.0f ms" % (sound * 1000) if sound else "never"))
# is the first picture the right one? compare with decoding the whole stream and taking that frame
pl.stop()
open("test_output/gb_build/seek.264", "wb").write(pl.es)
vf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (pl.vw, pl.vh, pl.vw, pl.vh)
full = subprocess.run([pl.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "h264", "-r", "30000/1001", "-i", "test_output/gb_build/seek.264", "-an", "-vf", vf, "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                      stdout=subprocess.PIPE, creationflags=0x08000000).stdout
fs = pl.vw * pl.vh * 3
for at in (7.3, 15.0, 19.0):
    pl.start_video(at)
    first = pl.frames.get(timeout=5)
    want = round(at * FPS)
    best = min(range(max(0, want - 3), min(len(full) // fs, want + 4)), key=lambda i: sum(1 for x, y in zip(first[::997], full[i * fs:(i + 1) * fs][::997]) if x != y))
    print("at %.1f s the first picture is frame %d, expected %d" % (at, best, want))
    pl.halt_video()
a.quit_app()
