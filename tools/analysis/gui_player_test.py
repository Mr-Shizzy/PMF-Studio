"""Exercises the Player page on a PMF: play, volume, scrubbing, seeking, full screen, end of a short movie. Saves screenshots.
usage: python tools/analysis/gui_player_test.py movie.pmf [short.pmf]"""
import ctypes
import sys
import time
sys.path.insert(0, ".")
from pmfstudio import app as A
from PIL import ImageGrab

a = A.App()
a.settings["auto_update"] = False
A.set_theme(True)
a.build_ui()
a.show("player")
a.update()
pl = a.player


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        a.update()
        time.sleep(0.01)


def snap(name):
    a.lift()
    a.attributes("-topmost", True)
    a.update()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/gb_build/shot_%s.png" % name)


print("sound device:", pl.audio is not None)
pl.load(sys.argv[1])
pump(3)
print("played 3 s -> clock %.2f, playing %s, previews ready %d" % (pl.now(), pl.playing, len(pl.thumbs)))
snap("player_playing")
got = ctypes.wintypes.DWORD()
for level in (100, 30, 0, 80):
    pl.vol.set(level, notify=True)
    pl.audio.lib.waveOutGetVolume(pl.audio.h, ctypes.byref(got))
    print("slider %3d -> device volume left %5.1f%%" % (level, (got.value & 0xFFFF) / 655.35))
pl.toggle_mute()
pl.audio.lib.waveOutGetVolume(pl.audio.h, ctypes.byref(got))
print("muted ->", (got.value & 0xFFFF), "(0 expected)")
pl.toggle_mute()
# dragging the timeline: pictures must follow, playback pauses, release carries on from there
seen = []
for v in (2.0, 5.0, 8.0, 12.0, 16.0):
    pl.scrub(v)
    a.update()
    seen.append((v, pl.image is not None))
print("scrub frames shown:", seen, "paused while dragging:", not pl.playing)
snap("player_scrub")
pl.slider.value = 14.0
pl.seek_release(14.0)
pump(1.5)
print("after release at 14 s, clock %.2f playing %s" % (pl.now(), pl.playing))
# full screen
pl.enter_fullscreen()
pump(2)
print("fullscreen: playing %s, clock %.2f, decode %dx%d zoom %d" % (pl.playing, pl.now(), pl.vw, pl.vh, pl.vz))
x, y = pl.fs.winfo_rootx(), pl.fs.winfo_rooty()
ImageGrab.grab(all_screens=True).save("test_output/gb_build/shot_player_fullscreen.png")
pl.exit_fullscreen()
pump(1)
print("back in the window: playing %s clock %.2f decode %dx%d" % (pl.playing, pl.now(), pl.vw, pl.vh))
snap("player_back")
pl.stop()
if len(sys.argv) > 2:
    pl.load(sys.argv[2])
    t = time.time()
    while pl.playing and time.time() - t < 8:
        a.update()
        time.sleep(0.02)
    print("short movie (%.2f s) ended by itself after %.1f s, playing=%s" % (pl.duration, time.time() - t, pl.playing))
a.quit_app()
