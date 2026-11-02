"""The Extract section (PMF -> MP4) and AT3 Tools > Extract (AT3 -> WAV or MP3), run from the window. Saves screenshots."""
import os, subprocess, sys, time
sys.path.insert(0, ".")
from pmfstudio import app as A
from pmfstudio.paths import find_tool
from PIL import ImageGrab

OUT = os.path.abspath("test_output/gb_build/extract_ui"); os.makedirs(OUT, exist_ok=True)
FF = find_tool("ffmpeg")
a = A.App(); a.settings["auto_update"] = False; a.settings["open_folder"] = False
a.build_ui()


def pump(s):
    t = time.time()
    while time.time() - t < s:
        a.update(); time.sleep(0.01)


def finish_job():
    t = time.time()
    while a.busy and time.time() - t < 60:
        a.update(); time.sleep(0.05)
    pump(0.5)
    return a.progress_label.cget("text")


def info(path):
    r = subprocess.run([FF, "-hide_banner", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=0x08000000)
    return [l.strip() for l in r.stdout.splitlines() if "Duration" in l or "Stream" in l]


def snap(name):
    a.lift(); a.attributes("-topmost", True); pump(0.3)
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/gb_build/shot_%s.png" % name)


tag = int(time.time())
# 1. the Extract page
a.show("extract")
pmf = os.path.abspath("test_output/gb_build/inputs/pg.pmf")
a.vars["src"].set(pmf)
a.vars["out"].set(OUT + "/pmf_%d.mp4" % tag)
a.vars["sound_too"].set(True)
snap("extract_page")
a.run_extract()
print("PMF extract:", finish_job(), [os.path.basename(f) for f in sorted(os.listdir(OUT)) if str(tag) in f])
# 2. AT3 -> WAV and MP3
at3 = os.path.abspath("test_output/gb_build/inputs/pa.at3")
for fmt in ("wav", "mp3"):
    a.show("at3")
    a.vars["task"].set("extract"); a.at3_refresh()
    a.vars["sound"].set(at3)
    a.vars["fmt"].set(fmt); a.extract_format_changed()
    if fmt == "mp3":
        a.vars["mp3kbps"].set("256 kbps")
        snap("at3_extract_mp3")
    out = OUT + "/snd_%d.%s" % (tag, fmt)
    a.vars["out"].set(out)
    a.run_at3()
    print("AT3 -> %s:" % fmt.upper(), finish_job(), os.path.getsize(out) if os.path.exists(out) else "missing", info(out)[:2])
a.quit_app()
