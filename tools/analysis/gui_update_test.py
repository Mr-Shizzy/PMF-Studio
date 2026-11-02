"""The update dialogs and the install steps driven through the window, with the release zip taken from a file instead of GitHub and the swap
not started (it is recorded). usage: python tools/analysis/gui_update_test.py RELEASE.zip
Takes a minute: the new program's own self-test really runs."""
import hashlib
import os
import shutil
import sys
import tempfile
import time
import tkinter.messagebox as mb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfstudio import app as A, updater                                              # noqa: E402

zip_path = os.path.abspath(sys.argv[1])
sha = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
fake_app = tempfile.mkdtemp(prefix="pmf_fakeapp_")
A.app_dir = lambda: fake_app                                                         # the "installed program" is an empty folder
updater.can_install = lambda d: None
real_install = updater.install
updater.install = lambda asset, tag, d, work, progress, cancelled, opener=None: real_install(asset, tag, d, work, progress, cancelled, opener=lambda u: open(zip_path, "rb"))
swaps = []
updater.run_swap = lambda script: swaps.append(script)
said = []
mb.showinfo = mb.showerror = mb.showwarning = lambda *x, **k: said.append(x[1] if len(x) > 1 else x[0])
a = A.App()
a.settings["auto_update"] = False
shown = []
orig_progress = a.update_progress
a.update_progress = lambda text, f: (shown.append((text, round(f, 2))), orig_progress(text, f))
info = dict(tag="9.9", url="https://github.com/x/y", notes="Adds things.\n\nMore.", asset=dict(name=os.path.basename(zip_path), url=updater.PREFIX + "x.zip", size=os.path.getsize(zip_path), sha=sha))


def pump(s):
    t = time.time()
    while time.time() - t < s:
        a.update()
        time.sleep(0.05)


# 1. "Skip this version" is remembered, and a startup check then stays quiet about that version
a.ask_update_choice = lambda msg: (said.append("DIALOG: " + msg), "skip")[1]
a.offer_update(info)
print("skip ->", a.settings["skip_version"], "| dialog text:", said[-1][:90].replace("\n", " "))
# 2. "Remind me" changes nothing
a.ask_update_choice = lambda msg: "later"
a.offer_update(info)
print("later -> skip_version still", a.settings["skip_version"])
# 3. a wrong checksum is refused and the window says so
a.ask_update_choice = lambda msg: "now"
bad = dict(info, asset=dict(info["asset"], sha="0" * 64))
said.clear()
a.offer_update(bad)
t = time.time()
while not any("did not go through" in s for s in said) and time.time() - t < 120:
    pump(0.2)
print("bad checksum ->", [s for s in said if "did not go" in s][0].replace("\n", " ")[:140], "| swap started:", bool(swaps), "| staging left:", os.path.exists(os.path.join(fake_app, "update_staging")))
# 4. announced as 9.9 but the zip really holds 0.1: the version check refuses it
said.clear()
a.offer_update(info)
t = time.time()
while not any("did not go through" in s for s in said) and not swaps and time.time() - t < 400:
    pump(0.2)
print("wrong version ->", [s for s in said if "did not go" in s][0].replace("\n", " ")[:170] if any("did not go" in s for s in said) else "NOT REFUSED", "| swap started:", bool(swaps))
# 5. announced correctly: the real thing
said.clear()
a.settings["skip_version"] = "0.1"
a.offer_update(dict(info, tag="0.1"))
t = time.time()
while not swaps and time.time() - t < 400:
    try:
        pump(0.2)
    except Exception:
        break
print("errors shown:", [s for s in said if "did not go" in s])
print("install -> swap script recorded:", bool(swaps) and os.path.exists(swaps[0]), "| progress steps seen:", sorted({s for s, _ in shown})[:6])
print("skip_version cleared after an install:", repr(a.settings["skip_version"]))
if swaps:
    os.remove(swaps[0])
shutil.rmtree(fake_app, ignore_errors=True)
