"""Full-screen player: controls appear on mouse movement and hide again; leaving works and the window keeps playing.
usage: python tools/analysis/gui_fs_test.py movie.pmf"""
import sys
import time
sys.path.insert(0, ".")
from pmfstudio import app as A
from PIL import ImageGrab

a = A.App()
a.settings["auto_update"] = False
A.set_theme(False)
a.build_ui()
a.show("player")
a.update()
pl = a.player


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        a.update()
        time.sleep(0.01)


pl.load(sys.argv[1])
pump(2)
pl.enter_fullscreen()
pump(0.5)
print("entered: bar shown %s (False expected), decode %dx%d x%d, playing %s" % (pl.fs_bar.winfo_viewable(), pl.vw, pl.vh, pl.vz, pl.playing))
pump(3.5)
print("after 3.5 s of rest: bar shown %s (False expected), cursor %r" % (pl.fs_bar.winfo_viewable(), str(pl.fs.cget("cursor"))))
pl.fs.event_generate("<Motion>", x=300, y=300, warp=True)
pump(0.2)
print("pointer just there: bar shown %s (False expected)" % pl.fs_bar.winfo_viewable())
pl.fs.event_generate("<Motion>", x=340, y=330, warp=True)
pump(0.4)
print("mouse moved: bar shown %s (True expected)" % pl.fs_bar.winfo_viewable())
ImageGrab.grab(all_screens=True).save("test_output/gb_build/shot_fs_bar.png")
before = pl.now()
pl.scrub(12.0)
pl.seek_release(12.0)
pump(1.2)
print("seek to 12 s from the full-screen bar: clock %.2f, playing %s" % (pl.now(), pl.playing))
pl.fs_vol.set(25, notify=True)
print("volume from the full-screen bar: main slider %.0f, volume %.2f" % (pl.vol.value, pl.volume))
pl.fs.focus_force()
pl.fs.event_generate("<Escape>")
pump(0.5)
print("after Esc: fullscreen window gone %s, playing %s, decode %dx%d" % (pl.fs is None, pl.playing, pl.vw, pl.vh))
img = pl.image
pump(0.8)
print("main window still painting new pictures:", pl.image is not img, "| clock %.2f" % pl.now())
a.lift()
a.attributes("-topmost", True)
pump(0.3)
x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/gb_build/shot_fs_after.png")
# a short movie ending in full screen: the bar must come up and stay
if len(sys.argv) > 2:
    pl.exit_fullscreen() if pl.fs else None
    pl.load(sys.argv[2])
    pump(0.5)
    pl.enter_fullscreen()
    pump(0.3)
    print("short movie in full screen, before the end: bar shown %s (False expected)" % pl.fs_bar.winfo_viewable())
    t = time.time()
    while pl.playing and time.time() - t < 8:
        a.update(); time.sleep(0.02)
    pump(0.4)
    print("movie ends: playing %s, bar shown %s (True expected)" % (pl.playing, pl.fs_bar.winfo_viewable()))
    pump(4)
    print("4 s later, still shown: %s (True expected)" % pl.fs_bar.winfo_viewable())
    ImageGrab.grab(all_screens=True).save("test_output/gb_build/shot_fs_end.png")
    pl.toggle()
    pump(4)
    print("pressed play again: playing %s, bar shown %s (False expected after the rest)" % (pl.playing, pl.fs_bar.winfo_viewable()))
pl.fs and pl.exit_fullscreen()
a.quit_app()
