"""Takes the screenshots for the README from the real window, with sample files made on the spot (nothing personal, nothing copyrighted).

    python tools/screenshots.py <folder for the pictures>

Run it from a copy of the program that sits at a neutral path (the pictures show file paths): the window shows where the files are.
It needs Pillow (only for the pictures), ffmpeg.exe and atracdenc.exe in tools\\ beside the program, and the screen must be free
(the window is brought to the front and the screen is photographed). It builds the gameboot and a sound for real, so what the
pictures show is what the program did.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import ImageGrab                                                     # noqa: E402

from pmfstudio import app as A                                                # noqa: E402
from pmfstudio.paths import app_dir, find_tool                                # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(app_dir(), "screenshots")
SAMPLES = os.path.join(app_dir(), "Sample files")
os.makedirs(OUT, exist_ok=True)
os.makedirs(SAMPLES, exist_ok=True)
FF = find_tool("ffmpeg")


def make_samples():
    """a moving gradient picture with a soft chord: made up, so nothing here belongs to anyone"""
    def ff(*args):
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", *args], check=True, creationflags=0x08000000)
    movie = os.path.join(SAMPLES, "sample movie.mp4")
    longer = os.path.join(SAMPLES, "long sample movie.mp4")
    sound = os.path.join(SAMPLES, "sample sound.wav")
    for path, secs in ((movie, 12), (longer, 150)):
        if not os.path.exists(path):
            ff("-f", "lavfi", "-i", "gradients=size=1280x720:rate=30:duration=%d:speed=0.03:nb_colors=4" % secs,
               "-f", "lavfi", "-i", "sine=f=220:duration=%d:sample_rate=44100" % secs,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-c:a", "aac", "-shortest", path)
    if not os.path.exists(sound):
        ff("-f", "lavfi", "-i", "sine=f=330:duration=8:sample_rate=44100", "-ac", "2", sound)
    return movie, longer, sound


a = A.App()
a.settings["auto_update"] = False
a.settings["open_folder"] = False
a.settings["dark"] = True
A.set_theme(True)
a.build_ui()
movie, longer, sound = make_samples()


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        a.update()
        time.sleep(0.02)


def pick_part(start, length):
    """a gameboot is about 2.5 seconds: drag the block on the strip to a part of that length (the same call the mouse makes)"""
    a.trim["bar"].set_selection(start, start + length)
    a.trim_changed(start, start + length)
    pump(0.5)


def finish_job(limit=120):
    t = time.time()
    while a.busy and time.time() - t < limit:
        a.update()
        time.sleep(0.05)
    pump(0.6)


def snap(name):
    a.lift()
    a.attributes("-topmost", True)
    pump(0.4)
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    img = ImageGrab.grab((x, y, x + w, y + h), all_screens=True)
    if img.width > 1500:                                                      # keep the files small
        img = img.resize((1500, round(img.height * 1500 / img.width)))
    img.save(os.path.join(OUT, name + ".png"), optimize=True)
    print("saved", name, img.size)


# 1. Gameboot with a long movie: the strip for choosing the part that fits
a.show("gameboot")
a.vars["movie"].set(longer)
pump(9)
pick_part(14.0, 2.4)
snap("gameboot-long-movie")

# 2. Gameboot, built for real from the short movie
a.show("gameboot")
a.vars["movie"].set(movie)
a.vars["out"].set(os.path.join(SAMPLES, "sample gameboot.pmf"))
pump(4)
pick_part(3.0, 2.4)
a.run_gameboot()
finish_job()
snap("gameboot-built")
pmf = a.vars["out"].get()

# 2b. Shrink game movies: the gameboot just built, made smaller for real
a.show("shrink")
a.vars["src"].set(pmf)
a.vars["out"].set(os.path.join(SAMPLES, "Shrunk movies"))
pump(1.5)
a.run_shrink()
finish_job()
snap("shrink")

# 3. EBOOT icon page (nothing chosen yet)
a.show("icon")
pump(0.5)
snap("eboot-icon")

# 4. AT3 Tools, making an AT3 for real
a.show("at3")
a.vars["sound"].set(sound)
a.vars["out"].set(os.path.join(SAMPLES, "sample sound.at3"))
pump(0.5)
a.run_at3()
finish_job()
snap("at3-tools")

# 5. Extract: the PMF built in step 2, taken apart
a.show("extract")
a.vars["src"].set(pmf)
a.vars["out"].set(os.path.join(SAMPLES, "sample extracted.mp4"))
a.vars["sound_too"].set(True)
pump(0.5)
a.run_extract()
finish_job()
snap("extract")

# 6. Player: the PMF paused in the middle
a.show("player")
a.update()
pl = a.player
pl.load(pmf)
pump(2.0)
pl.scrub(5.0)
pump(0.4)
pl.seek_release(5.0)
pump(0.3)
pl.pause()
pump(0.5)
snap("player")
pl.stop()

# 7. Options and Help, and the light theme
a.show("options")
pump(1.0)
snap("options")
a.show("help")
pump(0.5)
snap("help")
A.set_theme(False)
a.settings["dark"] = False
a.build_ui()
a.show("gameboot")
a.vars["movie"].set(longer)
pump(9)
pick_part(14.0, 2.4)
snap("gameboot-light")
a.quit_app()
print("done ->", OUT)
