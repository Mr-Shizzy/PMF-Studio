"""Dragging the timeline hard (200 mouse moves a second) in the window and in full screen: how long does the program stay busy, and is it caught up at the end?
usage: python tools/analysis/gui_scrub_test.py movie.pmf"""
import sys, time, math
sys.path.insert(0, ".")
from pmfstudio import app as A

a = A.App(); a.settings["auto_update"] = False
a.build_ui(); a.show("player"); a.update()
pl = a.player
pl.load(sys.argv[1])
t = time.time()
while time.time() - t < 2.5:
    a.update(); time.sleep(0.01)


def drag(label, seconds=2.5):
    pl.scrub(0.0)
    worst, paints, last = 0.0, 0, None
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        n += 1
        v = (0.5 + 0.5 * math.sin(n / 40.0)) * pl.duration
        pl.scrub(v)                                    # a mouse move
        s = time.perf_counter()
        a.update()                                     # the program handles whatever is waiting
        worst = max(worst, time.perf_counter() - s)
        if pl.last_still != last:
            paints += 1
            last = pl.last_still
        time.sleep(0.005)
    final = pl.duration * 0.37
    pl.scrub(final)
    t1 = time.time()
    while pl.scrub_job is not None and time.time() - t1 < 1:
        a.update(); time.sleep(0.002)
    frames, size, step, zoom = pl.still_set()
    shown = last if pl.last_still is None else pl.last_still
    idx = pl.last_still[1] if pl.last_still else -1
    want = min(int(final / step + 0.5), len(frames) - 1)
    print("%-11s %d mouse moves, %d pictures drawn, longest wait %.0f ms, caught up at the end: %s (set of %d, zoom %d)" %
          (label, n, paints, worst * 1000, idx == want, len(frames), zoom))
    pl.seek_release(final)


drag("in window")
pl.enter_fullscreen()
t = time.time()
while time.time() - t < 6 and not pl.fs_thumbs:
    a.update(); time.sleep(0.02)
print("full-screen previews ready: %d pictures" % len(pl.fs_thumbs))
drag("full screen")
pl.exit_fullscreen()
a.quit_app()
