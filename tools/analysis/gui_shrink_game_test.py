"""Shrink a whole game from the window: pick a game image (A game / dropped on the window), the 'save to' row turns into a game file, the numbers
are the movies inside, a real run writes a new game, saving over the original is refused. Uses the small invented game of tests/test_umdimage.py.
usage: python tools/analysis/gui_shrink_game_test.py"""
import os
import sys
import time
import tkinter.messagebox as mb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tests import test_umdimage as T                                                   # noqa: E402
from pmfkit import umdimage                                                            # noqa: E402
from pmfstudio import app as A                                                         # noqa: E402
from PIL import ImageGrab                                                              # noqa: E402

T.ShrinkGameTests.setUpClass()
iso = T.ShrinkGameTests.iso
out = os.path.abspath("test_output/shrink/gui_game/smaller game.cso")
os.makedirs(os.path.dirname(out), exist_ok=True)
if os.path.exists(out):
    os.remove(out)
a = A.App()
a.settings["auto_update"] = False
a.settings["open_folder"] = False
A.set_theme(True)
a.build_ui()
shown, asked = [], []
mb.showinfo = mb.showerror = mb.showwarning = lambda *x, **k: shown.append(x[1] if len(x) > 1 else x[0])
mb.askyesno = lambda *x, **k: asked.append(x[1]) or True


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
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/shrink/shot_game_%s.png" % name)


a.show("icon")
pump(0.4)
a.on_drop([iso])                                          # a game image dropped on any page goes to Shrink
pump(1.5)
print("mode after the drop:", a.mode, "| src box:", os.path.basename(a.vars["src"].get()))
print("info:", a.shrink_info.cget("text"))
print("save row:", a.shrink_out_label.cget("text"), "->", os.path.basename(a.vars["out"].get()))
print("note:", a.shrink_note.cget("text")[:90])
print("result line:", a.shrink_result.cget("text"))
a.vars["picture"].set("0.5"); a.vars["sound"].set("64"); a.shrink_draw()
snap("ready")

a.vars["out"].set(iso)
a.run_shrink(); pump(1)
print("saving over the game ->", shown[-1][:80] if shown else "NOT REFUSED", "| busy", a.busy)

a.vars["out"].set(out[:-4])                               # no extension typed: .cso is added
a.run_shrink()
t = time.time()
while (a.busy or t == time.time()) and time.time() - t < 240:
    a.update()
    time.sleep(0.05)
pump(0.8)
print("out box now:", os.path.basename(a.vars["out"].get()))
print("status:", a.status.cget("text"), "|", a.progress_label.cget("text"), a.progress_pct.cget("text"))
print("log:\n" + a.log.get("1.0", "end").strip())
snap("done")
if os.path.exists(out):
    img = umdimage.Image(out)
    new = {e.path: e.size for e in umdimage.walk(img)}
    img.close()
    img = umdimage.Image(iso)
    old = {e.path: e.size for e in umdimage.walk(img)}
    img.close()
    fmv = [p for p in old if p.endswith(".PMF")]
    print("new game: %d bytes (original %d); movies %s" % (os.path.getsize(out), os.path.getsize(iso), {os.path.basename(p): (old[p], new[p]) for p in fmv}))
else:
    print("NO OUTPUT")
# a second run over the same file asks before replacing (while a job runs its output goes to the window's log, not to this console)
a.vars["out"].set(out)
a.run_shrink()
t = time.time()
while (a.busy or t == time.time()) and time.time() - t < 240:
    a.update()
    time.sleep(0.05)
pump(0.5)
print("asked before replacing:", asked[-1][:60] if asked else "NO QUESTION", "| second run:", a.status.cget("text"))
a.quit_app()
T.ShrinkGameTests.tearDownClass()
