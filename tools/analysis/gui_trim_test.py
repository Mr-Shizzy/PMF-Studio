"""Part-of-the-movie picker: a long movie on the Gameboot and EBOOT icon pages. Saves screenshots.
usage: python tools/analysis/gui_trim_test.py long_movie.mp4"""
import sys
import time
sys.path.insert(0, ".")
from pmfstudio import app as A
from PIL import ImageGrab

movie = sys.argv[1]
a = A.App()
a.settings["auto_update"] = False
A.set_theme(False)
a.build_ui()


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        a.update()
        time.sleep(0.02)


def snap(name):
    a.lift()
    a.attributes("-topmost", True)
    pump(0.3)
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/gb_build/shot_%s.png" % name)


a.show("gameboot")
a.vars["movie"].set(movie)
pump(6)
t = a.trim
print("gameboot: movie %.0f s, default block %s, thumbs %d" % (t["dur"], tuple(round(x, 1) for x in a.trim_sel), len(t["bar"].thumbs)))
print("  message:", a.trim_msg.cget("text"))
snap("trim_gameboot")
# drag the block to the middle and make it longer than fits
t["bar"].set_selection(60, 160)
a.trim_changed(60, 160)
print("  100 s block ->", t["bar"].state, "|", a.trim_msg.cget("text"))
print("  Build blocked:", end=" ")
import tkinter.messagebox as mb
mb.showinfo = lambda *x, **k: print("message shown:", x[1][:70])
a.run_gameboot()
a.fit_me()
print("  after Fit it for me:", tuple(round(x, 1) for x in a.trim_sel), t["bar"].state, "|", a.trim_msg.cget("text"))
print("  job arguments:", a.part_args())
snap("trim_gameboot_fit")
# icon page
a.show("icon")
a.vars["movie"].set(movie)
pump(6)
t = a.trim
print("icon: default block", tuple(round(x, 1) for x in a.trim_sel), "|", a.trim_msg.cget("text"))
snap("trim_icon")
# a short movie that fits as a whole
a.show("gameboot")
a.vars["movie"].set("test_output/gb_build/src20.mp4")
pump(4)
print("short movie: block", tuple(round(x, 1) for x in a.trim_sel), "| args", a.part_args(), "|", a.trim_msg.cget("text"))
a.quit_app()
