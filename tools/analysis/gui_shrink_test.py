"""The Shrink game movies page, run from the window: a folder of movies (with a bad file and a sub-folder), the estimate line, the
protection against saving over the originals, the sound choice, and a real run. Saves screenshots.
usage: python tools/analysis/gui_shrink_test.py FOLDER_WITH_PMF_FILES"""
import os
import sys
import time
import tkinter.messagebox as mb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfstudio import app as A                                                         # noqa: E402
from PIL import ImageGrab                                                              # noqa: E402

src = os.path.abspath(sys.argv[1])
out = os.path.abspath("test_output/shrink/gui_out")
a = A.App()
a.settings["auto_update"] = False
a.settings["open_folder"] = False
A.set_theme(True)
a.build_ui()
shown = []
mb.showinfo = mb.showerror = mb.showwarning = lambda *x, **k: shown.append(x[1] if len(x) > 1 else x[0])


def pump(s):
    t = time.time()
    while time.time() - t < s:
        a.update()
        time.sleep(0.02)


def snap(name):
    a.lift()
    a.attributes("-topmost", True)
    pump(0.4)
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/shrink/shot_%s.png" % name)


a.show("shrink")
pump(0.5)
snap("empty")
a.vars["src"].set(src)
pump(1.5)
print("info:", a.shrink_info.cget("text"))
print("picture:", a.picture_note.cget("text"))
print("sound:", a.sound_note.cget("text"), "|", a.shrink_result.cget("text"))
a.vars["picture"].set("0.3"); a.vars["sound"].set("64"); a.shrink_texts()
print("30% + 64 kbps:", a.picture_note.cget("text")[:70], "|", a.sound_note.cget("text")[:50], "|", a.shrink_result.cget("text"))
a.vars["picture"].set("0.5"); a.vars["sound"].set("96"); a.shrink_draw()
snap("ready")
# saving over the originals is refused
a.vars["out"].set(src)
a.run_shrink(); pump(1)
print("same folder ->", shown[-1][:70] if shown else "NOT REFUSED", "| busy", a.busy)
a.vars["out"].set(os.path.join(src, "inside"))
a.run_shrink(); pump(1)
print("inside folder ->", shown[-1][:70] if shown else "NOT REFUSED", "| busy", a.busy)
# a real run
a.vars["out"].set(out)
a.run_shrink()
t = time.time()
while (a.busy or t == time.time()) and time.time() - t < 240:
    a.update()
    time.sleep(0.05)
pump(0.8)
print("status:", a.status.cget("text"), "|", a.progress_label.cget("text"), a.progress_pct.cget("text"))
print("log:\n" + a.log.get("1.0", "end").strip())
snap("done")
print("made:", sorted(os.path.relpath(os.path.join(d, f), out) for d, _, fs in os.walk(out) for f in fs))
a.quit_app()
