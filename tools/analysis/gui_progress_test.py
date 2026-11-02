"""Runs real jobs from the window and watches the progress bar. usage: python tools/analysis/gui_progress_test.py"""
import os
import sys
import time
sys.path.insert(0, ".")
from pmfstudio import app as A
from PIL import ImageGrab

SRC = "test_output/gb_build/src20.mp4"
OUT = "test_output/gb_build/progress_ui"
os.makedirs(OUT, exist_ok=True)
a = A.App()
a.settings["auto_update"] = False
a.settings["open_folder"] = False
a.build_ui()


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


def watch(name, shot_at=0.45):
    seen, shot = [], False
    t0 = time.time()
    while a.busy and time.time() - t0 < 120:
        a.update()
        v = a.progress.value
        seen.append((round(v, 2), a.progress_label.cget("text")))
        if not shot and v >= shot_at:
            snap("progress_" + name)
            shot = True
        time.sleep(0.05)
    pump(0.4)
    vals = [v for v, _ in seen]
    labels = []
    for _, l in seen:
        if not labels or labels[-1] != l:
            labels.append(l)
    print("%-9s %.1f s, bar only rises: %s, started %.2f, final %.2f %s (%s)" % (name, time.time() - t0, vals == sorted(vals), vals[0] if vals else -1,
          a.progress.value, a.progress_label.cget("text"), a.progress_pct.cget("text")))
    print("   stages shown:", labels)


# gameboot
a.show("gameboot")
a.vars["movie"].set(SRC)
a.vars["out"].set(os.path.abspath(OUT + "/gb_%d.pmf" % time.time()))
pump(0.8)
a.run_gameboot()
watch("gameboot")
# extract
a.show("extract")
a.vars["src"].set(os.path.abspath([os.path.join(OUT, f) for f in sorted(os.listdir(OUT)) if f.endswith(".pmf")][-1]))
a.vars["out"].set(os.path.abspath(OUT + "/ex_%d.mp4" % time.time()))
a.vars["sound_too"].set(True)
a.run_extract()
watch("extract", 0.5)
# AT3
a.show("at3")
a.vars["sound"].set(SRC)
a.vars["out"].set(os.path.abspath(OUT + "/s_%d.at3" % time.time()))
a.run_at3()
watch("at3")
# opening a big file in the player
a.show("player")
shown = []
orig = a.player.set_busy
a.player.set_busy = lambda f, t=None: (shown.append(round(f, 2)), orig(f, t))
t = time.time()
a.player.load("test_output/gb_build/inputs/l180ci.pmf")
print("player opened a 3-minute PMF in %.1f s; progress steps %d, from %.2f to %.2f" % (time.time() - t, len(shown), min(shown), max(shown)))
a.player.stop()
a.quit_app()
