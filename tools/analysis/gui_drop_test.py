"""Sends the same Windows message Explorer sends when files are dropped on the window, and checks the right page and box are filled.
Also the command-line route (files given at start). usage: python tools/analysis/gui_drop_test.py FOLDER_WITH_A_PMF"""
import ctypes
import os
import sys
import time
import tkinter.messagebox as mb
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfstudio import app as A                                                          # noqa: E402

folder = os.path.abspath(sys.argv[1])
pmf = next(os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.lower().endswith(".pmf"))
said = []
mb.showinfo = mb.showerror = mb.showwarning = lambda *x, **k: said.append(x[1] if len(x) > 1 else x[0])
a = A.App([pmf])                                      # given on the command line
a.settings["auto_update"] = False


def pump(s):
    t = time.time()
    while time.time() - t < s:
        a.update()
        time.sleep(0.02)


def drop(*files):
    """build an HDROP (DROPFILES header + double-null wide string) and send WM_DROPFILES to the window, as Explorer does"""
    text = "\0".join(files) + "\0\0"
    data = text.encode("utf-16-le")
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    h = k32.GlobalAlloc(0x0042, 20 + len(data))                       # GMEM_MOVEABLE | GMEM_ZEROINIT
    p = k32.GlobalLock(h)
    ctypes.memmove(p, (ctypes.c_uint32 * 5)(20, 0, 0, 0, 1), 20)      # offset of the names, point, not in the non-client area, wide characters
    ctypes.memmove(p + 20, data, len(data))
    k32.GlobalUnlock(h)
    u32.GetParent.restype = wintypes.HWND
    hwnd = u32.GetParent(a.winfo_id()) or a.winfo_id()
    u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
    u32.SendMessageW(hwnd, 0x0233, h, 0)
    pump(0.4)


pump(1.5)
print("command line:", a.mode, "| player has file:", bool(a.player and getattr(a.player, "src", None) or getattr(a.player, "path", None)), "| drop hook problem:", a.drop_problem)
a.show("gameboot")
drop(pmf.replace("movie", "movie"))                                    # a PMF on the Gameboot page -> the player
print("pmf on Gameboot ->", a.mode)
a.show("gameboot")
mp4 = os.path.abspath("test_output/gb_build/src20.mp4")
if os.path.exists(mp4):
    drop(mp4)
    print("mp4 on Gameboot -> page", a.mode, "| movie box:", a.vars["movie"].get() == mp4)
    a.show("cintro")
    drop(mp4)
    print("mp4 on C-Intro  -> page", a.mode, "| movie box:", a.vars["movie"].get() == mp4)
drop(folder)
print("folder -> page", a.mode, "| box:", a.vars["src"].get() == folder, "| info:", a.shrink_info.cget("text")[:40] if hasattr(a, "shrink_info") else "")
drop(os.path.join(folder, "nothing.xyz")) if False else None
a.show("extract")
drop(pmf)
print("pmf on Extract -> page", a.mode, "| src:", a.vars["src"].get() == pmf, "| out:", os.path.basename(a.vars["out"].get()))
a.show("gameboot")
open(os.path.join(os.environ["TEMP"], "notes.txt"), "w").write("x")
said.clear()
drop(os.path.join(os.environ["TEMP"], "notes.txt"))
print("txt ->", said[-1] if said else "no message")
a.quit_app()
