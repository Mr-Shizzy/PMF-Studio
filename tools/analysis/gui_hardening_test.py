"""Stop button, quitting while a job runs, the checks before a job, leftover working files and the diagnostics text, run through the window.
usage: python tools/analysis/gui_hardening_test.py FOLDER_WITH_A_FEW_BIG_PMF_FILES   (a job that takes several seconds is needed)"""
import os
import subprocess
import sys
import tempfile
import time
import tkinter.messagebox as mb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit import cli                                                                  # noqa: E402
from pmfstudio import app as A                                                          # noqa: E402

src = os.path.abspath(sys.argv[1])
out = os.path.abspath("test_output/shrink/hard_out")
base = os.path.abspath("test_output/shrink/hard_temp")
os.makedirs(base, exist_ok=True)
tempfile.tempdir = base                                                                 # so leftovers can be counted
a = A.App()
a.settings["auto_update"] = False
a.settings["open_folder"] = False
a.build_ui()
said = []
mb.showinfo = mb.showerror = mb.showwarning = lambda *x, **k: said.append(x[1] if len(x) > 1 else x[0])
mb.askyesno = lambda *x, **k: (said.append("ASK: " + x[1]), True)[1]


def pump(s):
    t = time.time()
    while time.time() - t < s:
        a.update()
        time.sleep(0.02)


def ffmpeg_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/NH"], stdout=subprocess.PIPE, text=True, creationflags=0x08000000)
    return r.stdout.lower().count("ffmpeg.exe")


def leftovers():
    return [n for n in os.listdir(base)]


# 1. the checks before a job
a.show("gameboot")
a.vars["movie"].set(os.path.join(src, os.listdir(src)[0]))
for bad in (os.path.join(base, "nul.pmf"), os.path.join(base, 'a?b.pmf'), a.vars["movie"].get()):
    a.vars["out"].set(bad)
    said.clear()
    a.run_gameboot()
    print("out=%-40s -> %s | busy %s" % (os.path.basename(bad), (said[-1][:80] if said else "no message"), a.busy))

# 2. Stop in the middle of a folder job
a.show("shrink")
a.vars["src"].set(src)
a.vars["out"].set(out)
pump(1.0)
said.clear()
a.run_shrink()
pump(2.0)
print("running:", a.busy, "| Stop button shown:", a.stop_btn.winfo_ismapped(), "| ffmpeg processes:", ffmpeg_running())
a.stop_job()
t = time.time()
while a.busy and time.time() - t < 15:
    a.update()
    time.sleep(0.02)
pump(0.5)
print("after Stop: busy %s | status: %s | label: %s | error dialogs: %s" % (a.busy, a.status.cget("text"), a.progress_label.cget("text"), [s for s in said if not s.startswith("ASK")]))
print("ffmpeg processes left:", ffmpeg_running(), "| helper list:", cli.ACTIVE)
print("outputs:", sorted((f, os.path.getsize(os.path.join(out, f))) for f in os.listdir(out)) if os.path.isdir(out) else "no folder")
print("working files left over:", leftovers())

# 3. a full run afterwards still works (the Stop flag is cleared)
said.clear()
a.run_shrink()
t = time.time()
while (a.busy or t == time.time()) and time.time() - t < 240:
    a.update()
    time.sleep(0.05)
pump(0.5)
print("full run after a stop:", a.status.cget("text"), "|", len(os.listdir(out)), "movies | left over:", leftovers())

# 4. diagnostics
b = a
b.last_trace = "Traceback (most recent call last):\n  File \"%s\\x.py\", line 1\nValueError: test" % os.path.expanduser("~")
text = b.diagnostics_text()
print("---- diagnostics\n" + text + "\n----")
assert os.environ.get("USERNAME", "zzz").lower() not in text.lower(), "user name leaked"

# 5. quitting while a job runs
a.run_shrink()
pump(1.5)
print("quit while busy ->", end=" ")
a.quit_app()
print("asked:", [s for s in said if s.startswith("ASK")][-1][:60], "| ffmpeg processes left:", ffmpeg_running())

