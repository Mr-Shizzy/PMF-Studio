"""The PMF Studio window (tkinter, ships with Python, so the program stays portable)."""
import ctypes
import math
import os
import platform
import queue
import shutil
import sys
import tempfile
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import VERSION, STAGE, REPO, jobs, settings, updater
from . import dropfiles, paths, preflight
from .paths import app_dir, find_tool
from .theme import T, S, set_scale, set_theme, mix
from .widgets import Check, FitPicker, ProgressBar, ScrollArea, Segmented, Slider, TrimBar, STATE_COLORS, clock
from pmfkit import fit
from pmfkit import cli
from pmfkit import rco as rcomod
from pmfkit.cli import BuildError, probe_seconds
from pmfkit.gameboot import STOCK_SECONDS

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)         # sharp text on high-DPI screens
except (AttributeError, OSError):
    pass
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MrShizzy.PMFStudio")   # own taskbar icon, also when run from source
except (AttributeError, OSError):
    pass

FONT = "Segoe UI"
OK, BAD = "#2e7d32", "#b3261e"

VIDEO = [("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.gif"), ("All files", "*.*")]
AUDIO = [("Sound files", "*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.at3 *.oma"), ("All files", "*.*")]
IMAGES = [("Pictures", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")]
KBPS = ["32 kbps", "48 kbps", "64 kbps", "96 kbps", "128 kbps"]


class Spinner(tk.Canvas):
    """Two arrows chasing each other in a circle; they turn while `running`."""

    def __init__(self, parent, size=18):
        super().__init__(parent, width=size, height=size, bg=T.bg, highlightthickness=0)
        self.size, self.angle, self.running = size, 0, False
        self.draw()

    def draw(self):
        self.delete("all")
        c, r = self.size / 2, self.size / 2 - 3
        for k in (0, 180):
            s = self.angle + k
            self.create_arc(c - r, c - r, c + r, c + r, start=s, extent=120, style=tk.ARC, width=2, outline=T.accent)
            e = math.radians(s + 120)
            x, y = c + r * math.cos(e), c - r * math.sin(e)
            tx, ty, nx, ny = -math.sin(e), -math.cos(e), math.cos(e), -math.sin(e)
            self.create_polygon(x + tx * 4, y + ty * 4, x + nx * 3, y + ny * 3, x - nx * 3, y - ny * 3, fill=T.accent, outline=T.accent)

    def start(self):
        if not self.running:
            self.running = True
            self.tick()

    def stop(self):
        self.running = False
        self.angle = 0
        self.draw()

    def tick(self):
        if self.running:
            self.angle = (self.angle + 14) % 360
            self.draw()
            self.after(30, self.tick)


class Ring(tk.Canvas):
    """The busy ring beside the build button."""

    def __init__(self, parent):
        super().__init__(parent, width=22, height=22, bg=T.bg, highlightthickness=0)
        self.angle, self.running = 0, False

    def start(self):
        self.running = True
        self.tick()

    def stop(self):
        self.running = False
        self.delete("all")

    def tick(self):
        if not self.running:
            return
        self.delete("all")
        self.create_oval(3, 3, 19, 19, outline=T.line, width=3)
        self.create_arc(3, 3, 19, 19, start=self.angle, extent=90, style=tk.ARC, outline=T.accent, width=3)
        self.angle = (self.angle + 18) % 360
        self.after(30, self.tick)


class Banner(tk.Canvas):
    """The big title with a light that slowly sweeps across it."""

    def __init__(self, parent):
        super().__init__(parent, height=S(70), bg=T.side, highlightthickness=0)
        self.font = tkfont.Font(family=FONT, size=30, weight="bold")
        self.letters, x = [], S(24)
        for ch in "PMF Studio":
            item = self.create_text(x, S(35), text=ch, anchor="w", font=self.font, fill=T.ink)
            self.letters.append((item, x + self.font.measure(ch) / 2))
            x += self.font.measure(ch)
        self.width_text = x
        self.create_text(x + S(14), S(44), text="%s %s" % (VERSION, STAGE), anchor="w", font=(FONT, 11), fill=T.muted)
        self.phase = 0
        self.job = self.after(40, self.tick)

    def tick(self):
        pos = (self.phase % (self.width_text + S(350))) - S(130)           # a pause once the light has passed
        for item, cx in self.letters:
            d = abs(cx - pos) / S(70)
            self.itemconfigure(item, fill=mix(T.ink, T.shine, max(0.0, 1 - d * d)))
        self.phase += S(5)
        self.job = self.after(40, self.tick)


class HeaderButton(tk.Frame):
    def __init__(self, parent, text, command, with_spinner=False):
        super().__init__(parent, bg=T.bg, highlightbackground=T.line, highlightthickness=1, cursor="hand2")
        self.icon = Spinner(self) if with_spinner else None
        if self.icon:
            self.icon.pack(side="left", padx=(10, 2), pady=6)
        self.label = tk.Label(self, text=text, bg=T.bg, fg=T.ink, font=(FONT, 10))
        self.label.pack(side="left", padx=(4 if with_spinner else 12, 12), pady=6)
        for w in [self, self.label] + ([self.icon] if self.icon else []):
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.paint(T.hover))
            w.bind("<Leave>", lambda e: self.paint(T.bg))

    def paint(self, c):
        self.configure(bg=c)
        self.label.configure(bg=c)
        if self.icon:
            self.icon.configure(bg=c)

    def set_text(self, t, color=None):
        self.label.configure(text=t, fg=color or T.ink)


class App(tk.Tk):
    def set_icon(self):
        """the window and taskbar icon; a missing or unreadable picture just leaves the default icon"""
        try:
            ico, png = paths.asset("icon.ico"), paths.asset("icon.png")
            if ico:
                self.iconbitmap(default=ico)
            elif png:
                self._icon_img = tk.PhotoImage(file=png)
                self.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    def __init__(self, files=None):
        super().__init__()
        set_scale(self.winfo_fpixels("1i") / 96)
        self.settings = settings.load()
        set_theme(self.settings["dark"])
        self.title("PMF Studio %s %s" % (VERSION, STAGE))
        self.set_icon()
        self.place_window()
        self.q = queue.Queue()
        self.busy = self.checking = False
        self.vars = {}
        self.player = None
        self.mode = "gameboot"
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.build_ui()
        self.after(100, self.pump)
        self.after(400, self.startup_checks)
        self.updating = False
        self.after(8000, self.clean_after_update)                                # the new version has run for a while: the old files kept aside can go
        self.drop_problem = dropfiles.enable(self, self.on_drop)                 # files can be dragged onto the window
        if files:
            self.after(800, lambda: self.on_drop(list(files)))                    # files given on the command line or dropped on the program's icon
        if self.settings["auto_update"]:
            self.after(900, lambda: self.check_updates(manual=False))

    def place_window(self):
        """Open at a size that suits this screen, in the middle of it."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = int(min(max(sw * 0.62, S(940)), sw * 0.94, S(1180)))
        h = int(min(max(sh * 0.78, S(700)), sh * 0.92, S(900)))
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(0, (sh - h) // 2 - S(10))))
        self.minsize(min(S(820), int(sw * 0.9)), min(S(620), int(sh * 0.9)))

    def startup_checks(self):
        """a few things that can be wrong when the program is moved, copied or unpacked half-way: say so plainly, once"""
        settings.output_dir(self.settings)
        note = self.settings.pop("_note", None)
        if note:
            messagebox.showinfo("PMF Studio", note)
        back = paths.restore_missing_tools()
        if back:
            messagebox.showinfo("PMF Studio", "%s was missing from the tools folder (an antivirus program may have removed it), so the spare copy inside PMF Studio was put back. "
                                "If it keeps disappearing, allow it in your antivirus program." % ", ".join(n + ".exe" for n in back))
        threading.Thread(target=lambda: self.q.put(("tools", paths.check_tools())), daemon=True).start()

    def tools_checked(self, status):
        self.tool_status = status
        problems = [(n, t) for n, (p, t) in status.items() if not p or "won't start" in t]
        if problems:
            lines = "\n".join("  \u2022 %s: %s" % (n, t) for n, t in problems)
            messagebox.showwarning("PMF Studio", "PMF Studio can't use some of its helper programs:\n\n%s\n\n"
                                   "They should sit in the \"tools\" folder next to PMF Studio:\n%s\n\n"
                                   "Start PMF Studio from the folder you unzipped, with everything in it left together (don't copy just the .exe somewhere else). "
                                   "If your antivirus blocked a file, allow it and restart."
                                   % (lines, os.path.join(app_dir(), "tools")))

    def quit_app(self):
        if self.busy:
            if not messagebox.askyesno("PMF Studio", "PMF Studio is still working. Stop and quit?"):
                return
            cli.cancel()                                           # the helper programs are ended, not left running in the background
            if getattr(self, "worker", None):
                self.worker.join(8)
        if self.player:
            self.player.close()
        self.destroy()

    def stop_job(self):
        if self.busy:
            cli.cancel()
            self.stop_btn.configure(state="disabled")
            self.status.configure(text="Stopping\u2026", fg=T.muted)

    # ---------- window ----------
    def style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=T.bg, foreground=T.ink, font=(FONT, 10))
        st.configure("TButton", font=(FONT, 10), padding=(10, 4), background=T.btn, foreground=T.ink, bordercolor=T.line, lightcolor=T.btn, darkcolor=T.btn, focuscolor=T.btn)
        st.map("TButton", background=[("active", T.hover), ("disabled", T.side)], foreground=[("disabled", T.muted)])
        st.configure("Go.TButton", font=(FONT, 10, "bold"), padding=(20, 7), background=T.go, foreground=T.go_ink, bordercolor=T.go, lightcolor=T.go, darkcolor=T.go)
        st.map("Go.TButton", background=[("active", T.go_hover), ("disabled", T.muted)], foreground=[("disabled", T.bg)])
        st.configure("TCheckbutton", background=T.bg, foreground=T.ink, font=(FONT, 10), focuscolor=T.bg, bordercolor=T.muted, indicatorrelief="flat")
        st.map("TCheckbutton", background=[("active", T.bg)], indicatorcolor=[("selected", T.accent), ("!selected", T.bg)], indicatorbackground=[("selected", T.accent), ("!selected", T.bg)])
        st.configure("TRadiobutton", background=T.bg, foreground=T.ink, font=(FONT, 10), focuscolor=T.bg, bordercolor=T.muted, indicatorrelief="flat")
        st.map("TRadiobutton", background=[("active", T.bg)], indicatorcolor=[("selected", T.accent), ("!selected", T.bg)], indicatorbackground=[("selected", T.accent), ("!selected", T.bg)])
        st.configure("TEntry", fieldbackground=T.bg, foreground=T.ink, bordercolor=T.line, lightcolor=T.line, darkcolor=T.line, insertcolor=T.ink, padding=4)
        st.map("TEntry", fieldbackground=[("disabled", T.side)], foreground=[("disabled", T.muted)])
        st.configure("TCombobox", fieldbackground=T.bg, background=T.btn, foreground=T.ink, arrowcolor=T.ink, bordercolor=T.line, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", T.bg)], foreground=[("readonly", T.ink)])
        self.option_add("*TCombobox*Listbox.background", T.bg)
        self.option_add("*TCombobox*Listbox.foreground", T.ink)
        st.configure("Horizontal.TProgressbar", troughcolor=T.side, background=T.accent, bordercolor=T.line, lightcolor=T.accent, darkcolor=T.accent)
        st.configure("Horizontal.TScale", background=T.bg, troughcolor=T.side, bordercolor=T.line)

    def build_ui(self):
        if self.player:
            self.player.close()
            self.player = None
        for w in self.winfo_children():
            w.destroy()
        self.configure(bg=T.bg)
        self.style()
        top = tk.Frame(self, bg=T.side, highlightbackground=T.line, highlightthickness=1)
        top.pack(fill="x")
        Banner(top).pack(side="left", fill="x", expand=True)
        bar = tk.Frame(top, bg=T.side)
        bar.pack(side="right", padx=14)
        self.upbtn = HeaderButton(bar, "Check for updates", self.check_updates, with_spinner=True)
        self.upbtn.pack(side="left", padx=4)
        HeaderButton(bar, "Options", lambda: self.show("options")).pack(side="left", padx=4)
        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True)
        self.side = tk.Frame(body, bg=T.side, width=S(200), highlightbackground=T.line, highlightthickness=1)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        self.holder = tk.Frame(body, bg=T.bg)
        self.holder.pack(side="left", fill="both", expand=True, padx=S(24), pady=S(16))
        self.main = self.foot = None
        self.items = {}
        for key, name in (("gameboot", "Gameboot"), ("cintro", "C-Intro"), ("icon", "EBOOT icon"), ("shrink", "Shrink game movies"),
                          ("at3", "AT3 Tools"), ("extract", "Extract"), ("player", "Player"), (None, None), ("help", "Help"), ("about", "About")):
            if key is None:
                tk.Frame(self.side, bg=T.line, height=1).pack(fill="x", padx=12, pady=8)
                continue
            lab = tk.Label(self.side, text=name, anchor="w", bg=T.side, fg=T.ink, font=(FONT, 11), padx=16, pady=8, cursor="hand2")
            lab.pack(fill="x", padx=6, pady=1)
            lab.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.items[key] = lab
        self.show(self.mode)

    def show(self, key):
        if self.player:
            self.player.close()
            self.player = None
        self.mode = key
        for k, lab in self.items.items():
            lab.configure(bg=T.sel if k == key else T.side, font=(FONT, 11, "bold") if k == key else (FONT, 11))
        for w in self.holder.winfo_children():
            w.destroy()
        self.foot = tk.Frame(self.holder, bg=T.bg)
        self.foot.pack(side="bottom", fill="x")
        area = ScrollArea(self.holder)
        area.pack(fill="both", expand=True)
        self.main = area.inner
        self.vars = {}
        self.trim = None
        self.trim_token = getattr(self, "trim_token", 0) + 1
        getattr(self, "page_" + key)()

    # ---------- building blocks ----------
    def heading(self, title, sub=""):
        tk.Label(self.main, text=title, bg=T.bg, fg=T.ink, font=(FONT, 16, "bold"), anchor="w").pack(fill="x")
        if sub:
            tk.Label(self.main, text=sub, bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w", justify="left", wraplength=S(700)).pack(fill="x", pady=(2, 12))
        else:
            tk.Frame(self.main, bg=T.bg, height=S(10)).pack()

    def label_cell(self, f, label, hint="", enabled=True):
        """the name on the left of a row; with a hint, the real file name in bold and a plain description under it"""
        if not hint:
            tk.Label(f, text=label, width=14, anchor="w", bg=T.bg, fg=T.ink if enabled else T.muted, font=(FONT, 10)).pack(side="left")
            return
        cell = tk.Frame(f, bg=T.bg, width=S(250), height=S(44))
        cell.pack(side="left")
        cell.pack_propagate(False)
        tk.Label(cell, text=label, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(fill="x")
        tk.Label(cell, text=hint, anchor="w", bg=T.bg, fg=T.muted, font=(FONT, 9)).pack(fill="x")

    def row(self, key, label, kind="open", types=None, initial="", enabled=True, parent=None, hint=""):
        f = tk.Frame(parent or self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        self.label_cell(f, label, hint, enabled)
        var = self.vars.setdefault(key, tk.StringVar(value=initial))
        ttk.Entry(f, textvariable=var, state="normal" if enabled else "disabled").pack(side="left", fill="x", expand=True, padx=(0, 8))
        text = {"open": "Browse", "save": "Save as", "dir": "Browse"}[kind]
        ttk.Button(f, text=text, command=lambda: self.pick(key, kind, types), state="normal" if enabled else "disabled").pack(side="left")
        return f

    def choice(self, key, label, values, initial, parent=None):
        f = tk.Frame(parent or self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text=label, width=14, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10)).pack(side="left")
        self.vars[key] = tk.StringVar(value=initial)
        Segmented(f, [(v, v) for v in values], self.vars[key]).pack(side="left")

    def fit_row(self, parent=None):
        """how a movie that isn't the PSP's shape is made to fit"""
        f = tk.Frame(parent or self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text="Picture shape", width=14, anchor="nw", bg=T.bg, fg=T.ink, font=(FONT, 10)).pack(side="left", anchor="n", pady=(S(8), 0))
        self.vars["fit"] = tk.StringVar(value="crop")
        col = tk.Frame(f, bg=T.bg)
        col.pack(side="left", fill="x", expand=True)
        FitPicker(col, self.vars["fit"]).pack(anchor="w")
        tk.Label(col, text="The PSP screen is wide. Fill crops the edges. Black bars keep the whole picture. Stretch squeezes it to fit.", bg=T.bg, fg=T.muted,
                 font=(FONT, 9), justify="left", anchor="w", wraplength=S(620)).pack(anchor="w", pady=(S(4), 0))

    # ---------- choosing the part of a long movie ----------
    def trim_panel(self, target, parent=None):
        """under the movie row: once a movie is chosen, a strip showing it with a block to drag over the part to use"""
        self.trim_target = target
        self.trim = None
        self.trim_sel = (0.0, 0.0)
        self.trim_job = None
        self.trim_holder = tk.Frame(parent or self.main, bg=T.bg)
        self.trim_holder.pack(fill="x")
        self.vars["movie"].trace_add("write", lambda *a: self.movie_typed())

    def movie_typed(self):
        if self.trim_job:
            self.after_cancel(self.trim_job)
        self.trim_job = self.after(600, self.movie_changed)

    def movie_changed(self):
        self.trim_job = None
        if not self.alive(getattr(self, "trim_holder", None)):
            return
        path = self.vars["movie"].get().strip()
        for w in self.trim_holder.winfo_children():
            w.destroy()
        self.trim = None
        self.trim_token = getattr(self, "trim_token", 0) + 1
        token = self.trim_token
        if not (path and os.path.isfile(path)):
            return
        ff = find_tool("ffmpeg")
        if not ff:
            return
        tk.Label(self.trim_holder, text="Reading the movie\u2026", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w").pack(fill="x", pady=(6, 2))
        self.trim_wait = ProgressBar(self.trim_holder, height=6)
        self.trim_wait.pack(fill="x", pady=(0, 6))
        self.trim_wait.indeterminate()

        def work():
            try:
                dur = probe_seconds(ff, path)
            except Exception as e:
                self.q.put(("trim", (token, None, str(e))))
                return
            self.q.put(("trim", (token, dur, "")))
            frames = []
            for i in range(10):
                frames.append(self.grab_small(ff, path, dur * (i + 0.5) / 10))
                if token != self.trim_token:
                    return
                self.q.put(("trim_progress", (token, (i + 1) / 10)))
            self.q.put(("trim_thumbs", (token, frames)))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def grab_small(ff, path, at):
        import subprocess
        r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-ss", "%.2f" % at, "-i", path, "-frames:v", "1", "-vf",
                            "scale=96:54:force_original_aspect_ratio=decrease,pad=96:54:(ow-iw)/2:(oh-ih)/2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        return r.stdout if len(r.stdout) == 96 * 54 * 3 else bytes(96 * 54 * 3)

    def trim_arrived(self, token, dur, error):
        if token != getattr(self, "trim_token", 0) or not self.alive(getattr(self, "trim_holder", None)):
            return
        for w in self.trim_holder.winfo_children():
            w.destroy()
        h = self.trim_holder
        if dur is None:
            tk.Label(h, text="Couldn't read the length of that movie. You can still build it.", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w").pack(fill="x", pady=6)
            return
        target = self.trim_target
        good, most = fit.limits(target, self.icon_sound_bytes())
        whole_ok = fit.verdict(target, dur, self.icon_sound_bytes()) != "toolong"
        start, end = (0.0, dur) if whole_ok else (0.0, min(dur, good if good >= 5 else most))
        head = tk.Frame(h, bg=T.bg)
        head.pack(fill="x", pady=(10, 2))
        tk.Label(head, text="Part to use", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(side="left")
        self.trim_info = tk.Label(head, text="", bg=T.bg, fg=T.muted, font=(FONT, 10))
        self.trim_info.pack(side="left", padx=12)
        bar = TrimBar(h, dur, self.trim_changed)
        bar.pack(fill="x")
        foot = tk.Frame(h, bg=T.bg)
        foot.pack(fill="x", pady=(2, 4))
        self.trim_msg = tk.Label(foot, text="", bg=T.bg, font=(FONT, 10), anchor="w", justify="left", wraplength=S(520))
        self.trim_msg.pack(side="left")
        self.trim_fit = ttk.Button(foot, text="Fit it for me", command=self.fit_me)
        self.trim = dict(dur=dur, bar=bar)
        self.trim_sel = (start, end)
        bar.set_selection(start, end)
        self.trim_changed(start, end)

    def trim_wait_update(self, token, fraction):
        if token == getattr(self, "trim_token", 0) and self.alive(getattr(self, "trim_wait", None)):
            self.trim_wait.set(fraction)

    def trim_thumbs(self, token, frames):
        if token == getattr(self, "trim_token", 0) and self.trim and self.alive(self.trim["bar"]):
            self.trim["bar"].set_thumbs(frames)

    def icon_sound_bytes(self):
        """EBOOT icon with a different sound: its size (64 kbps), which comes out of the shared 512 KB"""
        if self.mode != "icon" or not self.vars.get("sep") or not self.vars["sep"].get():
            return None
        secs = getattr(self, "sound_secs", {}).get(self.vars.get("sound", tk.StringVar()).get())
        return int(secs * 64 * 125) if secs else None

    def trim_state(self, length):
        return fit.verdict(self.trim_target, length, self.icon_sound_bytes())

    def trim_changed(self, start, end):
        if not self.trim:
            return
        self.trim_sel = (start, end)
        length = end - start
        state = self.trim_state(length)
        bar = self.trim["bar"]
        bar.state = state
        whole = start <= 0.05 and end >= self.trim["dur"] - 0.05
        self.trim_info.configure(text="%s to %s   (%s)" % (clock(start), clock(end), clock(length) if length >= 60 else "%d s" % round(length)))
        good, most = fit.limits(self.trim_target, self.icon_sound_bytes())
        name = {"gameboot": "gameboot", "icon": "icon movie", "cintro": "C-Intro movie"}[self.trim_target]
        if state == "toolong":
            if self.trim_target == "cintro":
                text = "This part would be over 4 GB, too big for a memory stick. Choose a shorter part."
            else:
                text = "Too long for a %s. About %s is the most that fits. Drag the block shorter." % (name, clock(most))
        elif state == "soft":
            text = "Fits, but the picture will look soft. A shorter part (about %s or less) looks better." % clock(good)
        else:
            text = "The whole movie fits." if whole else "This part fits well."
        colour = STATE_COLORS[state] if state != "good" else OK
        if self.trim_target == "gameboot" and length > STOCK_SECONDS + 0.1 and not (self.vars.get("ctf") and self.vars["ctf"].get() and self.vars["rco"].get().strip()):
            text += " Longer than %.1f s: the PSP stops a normal gameboot at about %.1f s. To play it all, tick Create CTF and pick your decrypted RCO, or use a part of %.1f s or less." % (
                STOCK_SECONDS, STOCK_SECONDS, STOCK_SECONDS)
            if state == "good":
                colour = STATE_COLORS["soft"]
        self.trim_msg.configure(text=text, fg=colour)
        if state == "good" or self.trim_target == "cintro":
            self.trim_fit.pack_forget()
        else:
            self.trim_fit.pack(side="left", padx=12)

    def fit_me(self):
        """shrink the block to the longest part that still looks good, keeping its start"""
        if not self.trim:
            return
        good, most = fit.limits(self.trim_target, self.icon_sound_bytes())
        length = min(self.trim["dur"], good if good >= 3 else most)
        start = min(self.trim_sel[0], self.trim["dur"] - length)
        self.trim["bar"].set_selection(start, start + length)
        self.trim_changed(start, start + length)

    def sound_typed(self):
        if getattr(self, "snd_job", None):
            self.after_cancel(self.snd_job)
        self.snd_job = self.after(600, self.sound_probe)

    def sound_probe(self):
        self.snd_job = None
        path = self.vars.get("sound", tk.StringVar()).get().strip() if self.mode == "icon" else ""
        ff = find_tool("ffmpeg")
        if not (path and os.path.isfile(path) and ff):
            self.trim_recompute()
            return
        if path in getattr(self, "sound_secs", {}):
            self.trim_recompute()
            return

        def work():
            try:
                self.q.put(("snd", (path, probe_seconds(ff, path))))
            except Exception:
                self.q.put(("snd", (path, None)))
        threading.Thread(target=work, daemon=True).start()

    def trim_recompute(self):
        if self.trim and self.alive(self.trim["bar"]):
            self.trim_changed(*self.trim_sel)

    def part_args(self):
        """the part to use, for the job: nothing when the whole movie is used"""
        if not self.trim:
            return {}
        start, end = self.trim_sel
        if start <= 0.05 and end >= self.trim["dur"] - 0.05:
            return {}
        return {"part_start": start, "part_length": end - start}

    def trim_blocked(self):
        if self.trim and self.trim_state(self.trim_sel[1] - self.trim_sel[0]) == "toolong":
            good, most = fit.limits(self.trim_target, self.icon_sound_bytes())
            messagebox.showinfo("PMF Studio", "That part is too long. Drag the block on the strip shorter (about %s at the most), or press Fit it for me." % clock(most))
            return True
        return False

    def pick(self, key, kind, types):
        cur = self.vars[key].get()
        init = os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else settings.output_dir(self.settings)
        if kind == "open":
            p = filedialog.askopenfilename(initialdir=init, filetypes=types or [("All files", "*.*")])
        elif kind == "dir":
            p = filedialog.askdirectory(initialdir=init)
        else:
            ext = os.path.splitext(cur)[1] or (types[0][1].split()[0][1:] if types else "")
            p = filedialog.asksaveasfilename(initialdir=init, initialfile=os.path.basename(cur), defaultextension=ext, filetypes=types or [("All files", "*.*")])
        if p:
            self.chosen(key, p)

    def chosen(self, key, p):
        """a file or folder was put in a box (Browse, or dragged in): fill the box and whatever follows from it"""
        self.vars[key].set(os.path.normpath(p))
        if key == "eboot":
            self.load_eboot()
        elif key == "src" and "out" in self.vars and self.mode == "extract":
            self.vars["out"].set(self.out_default(os.path.splitext(os.path.basename(p))[0] + ".mp4"))
        elif key == "sound" and self.mode == "at3" and "fmt" in self.vars and "out" in self.vars:
            self.vars["out"].set(self.out_default(os.path.splitext(os.path.basename(p))[0] + "." + self.vars["fmt"].get()))

    def on_drop(self, files):
        """files dragged onto the window (or given on the command line): the page and box each belongs in are chosen for you"""
        if self.busy:
            messagebox.showinfo("PMF Studio", "PMF Studio is busy with a job. Drop the file again when it is done.")
            return
        files = [f for f in files if os.path.exists(f)]
        page, box, path, text = dropfiles.route(files, self.mode)
        if not page:
            messagebox.showinfo("PMF Studio", text or "Nothing to open.")
            return
        if page != self.mode:
            self.show(page)
        if page == "player":
            if self.player:
                self.player.load(path)
        else:
            if page == "gameboot" and box in ("preview", "rco") and not self.vars["ctf"].get():
                self.vars["ctf"].set(True)
                self.gb_sub()
            if page == "at3" and box == "sound" and path.lower().endswith(".at3") and self.vars["task"].get() == "make":
                self.vars["task"].set("shrink")
                self.at3_refresh()
            self.chosen(box, path)
        if self.alive(getattr(self, "status", None)):
            self.status.configure(text=text, fg=T.muted)

    def tick(self, key, text, command=None, initial=False, parent=None):
        v = self.vars.setdefault(key, tk.BooleanVar(value=initial))
        Check(parent or self.main, text, v, command).pack(anchor="w", pady=(6, 2))
        return v

    def text_row(self, key, label, initial="", parent=None, hint=""):
        f = tk.Frame(parent or self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        self.label_cell(f, label, hint)
        ttk.Entry(f, textvariable=self.vars.setdefault(key, tk.StringVar(value=initial))).pack(side="left", fill="x", expand=True)

    def note(self, text, warn=False, parent=None):
        if warn:
            tk.Label(parent or self.main, text=text, bg=T.warn_bg, fg=T.warn_ink, font=(FONT, 10), anchor="w", justify="left", wraplength=S(680), padx=10, pady=8).pack(fill="x", pady=6)
        else:
            tk.Label(parent or self.main, text=text, bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w", justify="left", wraplength=S(700)).pack(fill="x", pady=(2, 4))

    def footer(self, button_text, command, bar=True):
        foot = self.foot
        head = tk.Frame(foot, bg=T.bg)
        head.pack(fill="x")
        self.progress_label = tk.Label(head, text="Ready", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w")
        self.progress_label.pack(side="left")
        self.progress_pct = tk.Label(head, text="", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold"), anchor="e")
        self.progress_pct.pack(side="right")
        self.progress = ProgressBar(foot, height=10)
        self.progress.pack(fill="x", pady=(3, 10))
        if bar:                                              # these two appear once the job is done: how full the size limit is
            self.size_label = tk.Label(foot, text="", bg=T.bg, fg=T.ink, font=(FONT, 10), anchor="w")
            self.size_bar = ProgressBar(foot, height=6)
        self.log = tk.Text(foot, height=3, bg=T.side, fg=T.muted, font=("Consolas", 9), relief="flat", state="disabled", wrap="word")   # appears with the first message
        f = tk.Frame(foot, bg=T.bg)
        f.pack(fill="x")
        self.foot_row = f
        self.status = tk.Label(f, text="", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w")
        self.status.pack(side="left")
        self.go = ttk.Button(f, text=button_text, style="Go.TButton", command=command)
        self.go.pack(side="right")
        self.ring = Ring(f)
        self.ring.pack(side="right", padx=10)
        self.stop_btn = ttk.Button(f, text="Stop", command=self.stop_job)          # appears only while a job is running

    def out_default(self, name):
        return os.path.join(settings.output_dir(self.settings), name)

    # ---------- pages ----------
    def page_gameboot(self):
        self.heading("Gameboot", "The movie that plays when you start a game.")
        h = self.main
        self.row("movie", "Your movie", types=VIDEO)
        self.fit_row(h)
        self.trim_panel("gameboot", h)
        self.row("out", "Save as", "save", [("Gameboot movie", "*.pmf")], initial=self.out_default("gameboot.pmf"))
        self.tick("sep", "Use a different sound", self.gb_sub)
        self.sep_holder = tk.Frame(h, bg=T.bg)
        self.sep_holder.pack(fill="x")
        self.tick("ctf", "Create CTF", self.gb_sub)
        self.ctf_holder = tk.Frame(h, bg=T.bg)
        self.ctf_holder.pack(fill="x")
        self.note("A gameboot can't be bigger than about 3 MB, so PMF Studio lowers the quality until it fits.")
        self.footer("Build", self.run_gameboot)
        self.gb_sub()

    def gb_sub(self):
        for w in self.sep_holder.winfo_children():
            w.destroy()
        if self.vars["sep"].get():
            self.row("sound", "Sound file", types=AUDIO, parent=self.sep_holder)
            self.note("It replaces the movie's own sound, and counts toward the size limit.", parent=self.sep_holder)
        on = self.vars["ctf"].get()
        for w in self.ctf_holder.winfo_children():
            w.destroy()
        self.row("preview", "Preview picture", types=IMAGES, enabled=on, parent=self.ctf_holder)
        f = tk.Frame(self.ctf_holder, bg=T.bg)
        f.pack(fill="x", pady=3)
        self.label_cell(f, "Firmware", enabled=on)
        fw = self.vars.setdefault("firmware", tk.StringVar(value="6.61"))
        ttk.Combobox(f, textvariable=fw, values=[rcomod.label(x) for x in rcomod.FIRMWARES], state="readonly" if on else "disabled", width=8).pack(side="left")
        tk.Label(f, text="the firmware your PSP runs", bg=T.bg, fg=T.muted, font=(FONT, 9)).pack(side="left", padx=10)
        self.row("rco", "Decrypted RCO", types=[("RCO files", "*.rco"), ("All files", "*.*")], enabled=on, parent=self.ctf_holder)
        self.rco_status = tk.Label(self.ctf_holder, text="", bg=T.bg, fg=T.muted, font=(FONT, 9), anchor="w", justify="left", wraplength=S(640))
        self.rco_status.pack(fill="x")
        if on:
            self.note("A CTF is a theme file for CXMB. Copy it to PSP/THEME. For a movie longer than 2.5 seconds, pick the decrypted opening_plugin.rco "
                      "from the same firmware as your PSP (it is only patched in a copy).", parent=self.ctf_holder)
        rco = self.vars["rco"]
        if not getattr(rco, "_hint_traced", False):
            rco.trace_add("write", lambda *a: self.rco_picked())
            fw.trace_add("write", lambda *a: self.rco_check())
            rco._hint_traced = True
        self.rco_check()
        self.trim_recompute()
        out = self.vars["out"]
        if on and out.get().lower().endswith(".pmf"):
            out.set(out.get()[:-4] + ".ctf")
        elif not on and out.get().lower().endswith(".ctf"):
            out.set(out.get()[:-4] + ".pmf")
        self.go.configure(text="Build CTF" if on else "Build")

    def rco_file(self):
        """-> (plain RCO bytes, None) for the file in the RCO box, (None, sentence) when it can't be used, (None, None) when there is none to look at"""
        path = self.vars["rco"].get().strip().strip('"')
        if not path or not os.path.isfile(path):
            return None, None
        try:
            with open(path, "rb") as fh:
                data = rcomod.load(fh.read(4_000_000))
            rcomod.find_delay(data)
            return data, None
        except (ValueError, OSError) as e:
            return None, str(e)

    def rco_picked(self):
        """a new file in the RCO box: when it is a known firmware's file, the firmware box follows it (the newest version that shares the file)"""
        data, _ = self.rco_file()
        group = rcomod.identify(data) if data else None
        if group and rcomod.digits(self.vars["firmware"].get()) not in group:
            self.vars["firmware"].set(rcomod.label(group[-1]))
        self.rco_check()
        self.trim_recompute()

    def rco_check(self):
        lab = getattr(self, "rco_status", None)
        if lab is None or not self.alive(lab):
            return
        data, problem = self.rco_file()
        text, colour = "", T.muted
        if not self.vars["ctf"].get():
            pass
        elif problem:
            text, colour = problem, BAD
        elif data:
            group = rcomod.identify(data)
            wrong = rcomod.mismatch(data, self.vars["firmware"].get())
            if wrong:
                text, colour = wrong, BAD
            elif group:
                text, colour = "This is the opening_plugin.rco of firmware %s." % rcomod.names(group), OK
            else:
                text = "This looks like an opening_plugin.rco, but it is not one PMF Studio knows. It will be used as it is."
        lab.configure(text=text, fg=colour)

    def page_cintro(self):
        self.heading("C-Intro", "A movie for the C-Intro plugin. Any length, any size.")
        self.row("movie", "Your movie", types=VIDEO)
        self.fit_row()
        self.trim_panel("cintro")
        self.row("out", "Save as", "save", [("PMF movie", "*.pmf")], initial=self.out_default("intro.pmf"))
        self.note("Not tested with the plugin on a PSP yet.")
        self.footer("Build", self.run_cintro, bar=False)

    def page_icon(self):
        self.heading("EBOOT icon", "Change how a game looks in the XMB. Leave anything empty to keep what the game already has.")
        self.eboot_title = ""
        self.row("eboot", "EBOOT.PBP", types=[("EBOOT", "*.pbp"), ("All files", "*.*")], hint="The game file. Only a copy is changed.")
        self.text_row("title", "TITLE", hint="The name under the icon.")
        self.row("movie", "ICON1.PMF", types=VIDEO, hint="Short movie when the game is selected.")
        self.fit_row()
        self.trim_panel("icon")
        self.tick("sep", "Use a different sound", self.icon_refresh)
        self.sep_holder = tk.Frame(self.main, bg=T.bg)
        self.sep_holder.pack(fill="x")
        self.row("icon0", "ICON0.PNG", types=IMAGES, hint="The small icon in the list.")
        self.row("pic1", "PIC1.PNG", types=IMAGES, hint="Background behind the game.")
        self.row("pic0", "PIC0.PNG", types=IMAGES, hint="Picture over the background.")
        self.row("out", "Save copy as", "save", [("EBOOT", "*.pbp")], initial=self.out_default("EBOOT.PBP"))
        self.note("Pictures are resized for you. Your original EBOOT stays untouched: you get a copy.")
        self.footer("Save copy", self.run_icon)

    def load_eboot(self):
        """fill in the title the game already has"""
        from pmfkit import pbp
        try:
            self.eboot_title = pbp.Pbp.read(self.vars["eboot"].get()).title() or ""
        except (OSError, ValueError):
            self.eboot_title = ""
        self.vars["title"].set(self.eboot_title)

    def icon_refresh(self):
        for w in self.sep_holder.winfo_children():
            w.destroy()
        self.trim_recompute()
        if self.vars["sep"].get():
            self.row("sound", "SND0.AT3", types=AUDIO, parent=self.sep_holder, hint="Sound while the game is selected.")
            self.vars["sound"].trace_add("write", lambda *a: self.sound_typed())
            self.note("This sound replaces the icon movie's own sound. They never play together, and they share 512 KB, so a long sound means a smaller picture.", warn=True, parent=self.sep_holder)

    def page_shrink(self):
        self.heading("Shrink game movies", "Make a game's own movies (.pmf) smaller, so the game takes less room. Pick one movie, a folder of them, or the whole game "
                     "(a .cso or .iso file). Each movie keeps its name, picture size and length.")
        f = tk.Frame(self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        self.label_cell(f, "Movies")
        self.vars["src"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["src"]).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(f, text="A movie", command=lambda: self.pick_movies(False)).pack(side="left", padx=(0, 6))
        ttk.Button(f, text="A folder", command=lambda: self.pick_movies(True)).pack(side="left", padx=(0, 6))
        ttk.Button(f, text="A game", command=self.pick_game).pack(side="left")
        self.shrink_info = tk.Label(self.main, text="Pick one movie, a whole folder of them, or a game.", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w", justify="left", wraplength=S(700))
        self.shrink_info.pack(fill="x", pady=(0, 8))
        self.vars["keep"] = tk.StringVar(value="")                       # the sound tracks to keep, counted from 1 ("" = all of them)
        self.vars["trackmode"] = tk.StringVar(value="all")
        self.tracks_holder = tk.Frame(self.main, bg=T.bg)
        self.tracks_holder.pack(fill="x")
        self.track_sources = None
        self.vars["picture"] = tk.StringVar(value="0.5")
        self.vars["sound"] = tk.StringVar(value="keep")
        self.picture_holder = tk.Frame(self.main, bg=T.bg)
        self.picture_holder.pack(fill="x")
        self.picture_note = tk.Label(self.main, text="", bg=T.bg, fg=T.muted, font=(FONT, 9), anchor="w", justify="left", wraplength=S(700))
        self.picture_note.pack(fill="x", pady=(2, 8))
        self.sound_holder = tk.Frame(self.main, bg=T.bg)
        self.sound_holder.pack(fill="x")
        self.sound_note = tk.Label(self.main, text="", bg=T.bg, fg=T.muted, font=(FONT, 9), anchor="w", justify="left", wraplength=S(700))
        self.sound_note.pack(fill="x", pady=(2, 8))
        self.shrink_result = tk.Label(self.main, text="", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold"), anchor="w")
        self.shrink_result.pack(fill="x", pady=(0, 4))
        self.vars["out"] = tk.StringVar(value=self.out_default("Shrunk movies"))
        self.shrink_out_auto = self.vars["out"].get()
        f = tk.Frame(self.main, bg=T.bg)
        f.pack(fill="x", pady=3)
        self.shrink_out_label = tk.Label(f, text="Save to folder", width=14, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10))
        self.shrink_out_label.pack(side="left")
        ttk.Entry(f, textvariable=self.vars["out"]).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(f, text="Browse", command=self.pick_shrink_out).pack(side="left")
        self.shrink_note = tk.Label(self.main, text="", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w", justify="left", wraplength=S(700))
        self.shrink_note.pack(fill="x", pady=(2, 4))
        self.footer("Shrink", self.run_shrink, bar=False)
        self.vars["src"].trace_add("write", lambda *a: self.shrink_typed())
        self.shrink_job = None
        self.shrink_info_data = None
        self.shrink_image_mode = None
        self.shrink_survey(True)

    PICTURE_CHOICES = (("1.0", "As it is"), ("0.75", "75%"), ("0.5", "50%"), ("0.4", "40%"), ("0.3", "30%"), ("0.2", "20%"))
    SOUND_WORDS = {"keep": "no change", "128": "high quality", "96": "good", "64": "okay", "48": "thin", "32": "lowest"}
    SOUND_CHOICES = (("keep", "As it is"), ("128", "128 kbps"), ("96", "96 kbps"), ("64", "64 kbps"), ("48", "48 kbps"), ("32", "32 kbps"))

    def pick_movies(self, folder):
        cur = self.vars["src"].get()
        init = cur if cur and os.path.isdir(cur) else (os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else settings.output_dir(self.settings))
        p = filedialog.askdirectory(initialdir=init) if folder else filedialog.askopenfilename(initialdir=init, filetypes=[("PMF movies", "*.pmf"), ("All files", "*.*")])
        if p:
            self.vars["src"].set(os.path.normpath(p))

    def pick_game(self):
        cur = self.vars["src"].get()
        init = os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else settings.output_dir(self.settings)
        p = filedialog.askopenfilename(initialdir=init, filetypes=[("Game disc images", "*.cso *.iso"), ("All files", "*.*")])
        if p:
            self.vars["src"].set(os.path.normpath(p))

    def shrink_is_game(self):
        from pmfkit import umdimage
        p = self.vars["src"].get().strip()
        return bool(p) and umdimage.is_image(p)

    def pick_shrink_out(self):
        if self.shrink_is_game():
            self.pick("out", "save", [("Game image (.cso is smaller)", "*.cso *.iso")])
        else:
            self.pick("out", "dir", None)

    def shrink_out_refresh(self):
        """the 'save to' row follows what was picked: a folder for movies, a new game file for a game"""
        game = self.shrink_is_game()
        if game:
            name = os.path.splitext(os.path.basename(self.vars["src"].get().strip()))[0] + " - downsampled.cso"
            auto = self.out_default(name)
            self.shrink_out_label.configure(text="Save game as")
            self.shrink_note.configure(text="Your game file is never changed: the smaller game is saved as a new file (.cso is the smaller kind, .iso works too). "
                                       "Only the movies inside it change; everything else on the disc is copied exactly as it was, in the same places. "
                                       "Movies a game keeps inside one of its big files (such as a movie.bin) are found too and stay in their places there. "
                                       "A whole game takes several minutes. Try the new game on your PSP before you delete anything.")
        else:
            auto = self.out_default("Shrunk movies")
            self.shrink_out_label.configure(text="Save to folder")
            self.shrink_note.configure(text="Your originals are never changed: the smaller movies go to the folder above with the same names. "
                                       "Always try one of them in your game before you use them all.")
        if self.vars["out"].get() in ("", self.shrink_out_auto):          # the box still holds what was filled in for you: follow the choice
            self.vars["out"].set(auto)
        self.shrink_out_auto = auto

    def shrink_typed(self):
        if self.shrink_job:
            self.after_cancel(self.shrink_job)
        self.shrink_job = self.after(500, lambda: self.shrink_survey(True))

    def shrink_survey(self, reread):
        """looks at the chosen movies (their picture and sound bitrates), then draws the choices with real numbers"""
        from pmfkit import shrink
        self.shrink_job = None
        if not self.alive(getattr(self, "picture_holder", None)):
            return
        path = self.vars["src"].get().strip()
        if reread:
            self.shrink_info_data = None
            if not path:
                self.shrink_info.configure(text="Pick one movie, a whole folder of them, or a game.", fg=T.muted)
            elif not os.path.exists(path):
                self.shrink_info.configure(text="Can't find that movie, folder or game.", fg=BAD)
            else:
                bad = ""
                try:
                    self.shrink_info_data = shrink.survey(path)
                except ValueError as e:
                    self.shrink_info_data, bad = None, str(e)
                except OSError:
                    self.shrink_info_data = None
                info = self.shrink_info_data
                if not info or not info.count:
                    self.shrink_info_data = None
                    self.shrink_info.configure(text=bad or "There are no .pmf movies there.", fg=BAD)
                else:
                    self.shrink_info.configure(text="%s%d movie%s, %s. Now: picture about %s kbps, sound about %s kbps." % (
                        "The game has " if self.shrink_is_game() else "", info.count, "" if info.count == 1 else "s", self.fmt(info.total),
                        format(int(info.picture_kbps), ","), int(info.sound_kbps)), fg=T.ink)
        if reread:
            self.vars["keep"].set("")
            self.vars["trackmode"].set("all")
            self.track_sources = None
        self.shrink_out_refresh()
        self.tracks_draw()
        self.shrink_draw()

    def tracks_draw(self):
        """movies with several sound tracks (languages): offer to keep only the ones you want"""
        holder = getattr(self, "tracks_holder", None)
        if not self.alive(holder):
            return
        for w in holder.winfo_children():
            w.destroy()
        info = self.shrink_info_data
        if not info or info.tracks < 2:
            self.vars["keep"].set("")
            return
        f = tk.Frame(holder, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text="Sound tracks", width=14, anchor="nw", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(side="left", anchor="n", pady=(S(6), 0))
        Segmented(f, [("all", "Keep all\nas they are"), ("choose", "Choose which\nto keep")], self.vars["trackmode"], self.tracks_mode, pad=12).pack(side="left")
        if self.vars["trackmode"].get() == "choose" and self.vars["keep"].get():
            ttk.Button(f, text="Change\u2026", command=self.tracks_choose).pack(side="left", padx=(10, 0))
        self.tracks_note = tk.Label(holder, text="", bg=T.bg, fg=T.muted, font=(FONT, 9), anchor="w", justify="left", wraplength=S(700))
        self.tracks_note.pack(fill="x", pady=(2, 8))
        self.tracks_text()

    def tracks_text(self):
        info = self.shrink_info_data
        if not info or not self.alive(getattr(self, "tracks_note", None)):
            return
        keep = self.vars["keep"].get().strip()
        if self.vars["trackmode"].get() == "choose" and keep:
            many = "," in keep
            self.tracks_note.configure(text="Keeping sound track%s %s. The other tracks stay in their places but empty, so a game that picks its track by "
                                       "the PSP's language still finds the one you kept (movies play without sound under a language you removed)." % (
                                           "s" if many else "", keep.replace(",", ", ")))
        else:
            self.tracks_note.configure(text="%s sound tracks (usually one per language) were found: up to %d per movie. All of them are kept. "
                                       "Choose which to keep to make %s smaller." % (
                                           "Several", info.tracks, "the game" if self.shrink_is_game() else "the movies"))

    def tracks_mode(self):
        if self.vars["trackmode"].get() == "choose":
            self.tracks_choose()
        else:
            self.vars["keep"].set("")
            self.tracks_draw()
            self.shrink_texts()

    def tracks_choose(self):
        """the window with a Play button and a tick box for each track"""
        from pmfkit import tracks as track_tools
        from .trackdialog import TrackDialog
        info = self.shrink_info_data
        path = self.vars["src"].get().strip()
        if self.track_sources is None:
            self.config(cursor="watch")
            self.update_idletasks()
            try:
                self.track_sources = track_tools.multitrack_movies(path)
            except (ValueError, OSError):
                self.track_sources = []
            finally:
                self.config(cursor="")
        try:
            now = track_tools.parse_keep(self.vars["keep"].get())
        except ValueError:
            now = None
        ff = find_tool("ffmpeg")
        if not ff:
            messagebox.showinfo("PMF Studio", "PMF Studio can't find ffmpeg, which it needs to play the sound. Put it in the tools folder next to the program.")
            self.vars["trackmode"].set("all")
            self.tracks_draw()
            return
        answer = TrackDialog(self, self.track_sources, info.tracks, now, ff, self.shrink_is_game()).show()
        if answer is None:                                                    # cancelled: the choice stays as it was
            if not self.vars["keep"].get():
                self.vars["trackmode"].set("all")
        elif not answer:                                                      # every track ticked = keep them all
            self.vars["keep"].set("")
            self.vars["trackmode"].set("all")
        else:
            self.vars["keep"].set(",".join(str(i + 1) for i in answer))
        self.tracks_draw()
        self.shrink_texts()

    def shrink_draw(self):
        """the two rows of choices; each picture choice shows the picture bitrate it gives for these movies"""
        from pmfkit import shrink
        info = self.shrink_info_data
        for holder in (self.picture_holder, self.sound_holder):
            for w in holder.winfo_children():
                w.destroy()
        f = tk.Frame(self.picture_holder, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text="Picture", width=14, anchor="nw", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(side="left", anchor="n", pady=(S(6), 0))
        options = []
        for value, name in self.PICTURE_CHOICES:
            if info and info.picture_kbps:
                second = "no change" if value == "1.0" else "%s kbps" % format(max(shrink.FLOOR_KBPS, int(info.picture_kbps * float(value))), ",")
            else:
                second = "no change" if value == "1.0" else "of what it is now"
            options.append((value, "%s\n%s" % (name, second)))
        Segmented(f, options, self.vars["picture"], self.shrink_texts, pad=12).pack(side="left")
        f = tk.Frame(self.sound_holder, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text="Sound", width=14, anchor="nw", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(side="left", anchor="n", pady=(S(6), 0))
        Segmented(f, [(v, "%s\n%s" % (n, self.SOUND_WORDS[v])) for v, n in self.SOUND_CHOICES], self.vars["sound"], self.shrink_texts, pad=12).pack(side="left")
        self.shrink_texts()

    def shrink_texts(self):
        """the sentences under the choices say what will actually happen; the last line is the size to expect"""
        from pmfkit import shrink
        info = self.shrink_info_data
        ratio = float(self.vars["picture"].get())
        now = "%s kbps" % format(int(info.picture_kbps), ",") if info and info.picture_kbps else "what it is now"
        if ratio >= 0.999:
            self.picture_note.configure(text="The picture is left exactly as it is.")
        else:
            then = " to about %s kbps" % format(max(shrink.FLOOR_KBPS, int(info.picture_kbps * ratio)), ",") if info and info.picture_kbps else ""
            self.picture_note.configure(text="The picture is encoded again with %d%% of its data (from about %s%s). Less data makes a smaller file and a softer picture.%s" % (
                round(ratio * 100), now, then, " This is one of the smallest settings: some games do not accept it. Try the new game before you delete anything, and use a milder choice if it fails." if ratio <= 0.25 else ""))
        sound = self.vars["sound"].get()
        if sound == "keep":
            self.sound_note.configure(text="The sound is kept exactly as it is.")
        else:
            was = " (now about %d kbps)" % int(info.sound_kbps) if info and info.sound_kbps else ""
            self.sound_note.configure(text="The sound is encoded again at %s kbps%s. Lower is smaller and flatter; a sound that is already lower stays as it is.%s" % (
                sound, was, " This is the lowest quality: some games do not accept it." if sound == "32" else ""))
        if info:
            from pmfkit import tracks as track_tools
            try:
                kept = track_tools.parse_keep(self.vars["keep"].get())
            except ValueError:
                kept = None
            after = shrink.predict(info, ratio, int(sound) if sound != "keep" else None, len(kept) if kept else None)
            self.shrink_result.configure(text="%s: about %s (now %s)." % ("The movies in the game will take" if self.shrink_is_game() else "After shrinking", self.fmt(after), self.fmt(info.total)))
        else:
            self.shrink_result.configure(text="")

    def run_shrink(self):
        from pmfkit import umdimage
        if self.shrink_is_game():
            out = self.vars["out"].get().strip()
            if out and not out.lower().endswith((".cso", ".iso")):
                self.vars["out"].set(out + ".cso")
            out = self.vars["out"].get().strip()
            safe = os.path.join(os.path.dirname(out), umdimage.psp_safe_name(os.path.basename(out))) if out else out
            if out and safe != out and messagebox.askyesno(
                    "PMF Studio", "A game file with a % in its name may not start on a PSP (it happened on a real one).\n\nSave it as\n%s\ninstead?" % os.path.basename(safe)):
                self.vars["out"].set(safe)
        self.start(jobs.shrink, [("src", "a movie, a folder of movies or a game"), ("out", "where to save")])

    def page_at3(self):
        self.heading("AT3 Tools", "Make a new AT3 sound, shrink one that came with a game, or turn an AT3 into a WAV or MP3.")
        self.vars["task"] = tk.StringVar(value=getattr(self, "at3_task", "make"))
        Segmented(self.main, [("make", "Make an AT3"), ("shrink", "Shrink an AT3"), ("extract", "Extract")], self.vars["task"], self.at3_refresh).pack(anchor="w", pady=(0, 8))
        self.at3_holder = tk.Frame(self.main, bg=T.bg)
        self.at3_holder.pack(fill="x")
        self.footer("Make AT3", self.run_at3)
        self.at3_refresh()

    def loudness_row(self, parent, keep):
        """Loudness in dB (LUFS): closer to 0 is louder. Or leave the sound as it is."""
        self.vars["keep"] = tk.BooleanVar(value=keep)
        self.vars["lufs"] = tk.IntVar(value=-12)
        f = tk.Frame(parent, bg=T.bg)
        f.pack(fill="x", pady=3)
        tk.Label(f, text="Loudness", width=14, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10)).pack(side="left")
        self.loud_slider = Slider(f, from_=-24, to=-6, value=-12, length=S(260), command=self.loudness_moved)
        self.loud_slider.pack(side="left", padx=(0, 12))
        self.loud_label = tk.Label(f, text="", width=7, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold"))
        self.loud_label.pack(side="left")
        Check(f, "Keep as it is", self.vars["keep"], self.loudness_refresh).pack(side="left", padx=(12, 0))
        self.loud_note = tk.Label(parent, text="", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w")
        self.loud_note.pack(fill="x")
        self.loudness_refresh()

    def loudness_moved(self, value):
        self.vars["lufs"].set(int(round(value)))
        self.loudness_refresh()

    def loudness_refresh(self):
        keep = self.vars["keep"].get()
        self.loud_label.configure(text="" if keep else "%d dB" % self.vars["lufs"].get())
        self.loud_slider.configure(state="disabled" if keep else "normal")
        if keep:
            self.loud_slider.pack_forget()
            self.loud_note.configure(text="The sound keeps the loudness it has now.")
        else:
            if not self.loud_slider.winfo_ismapped():
                self.loud_slider.pack(side="left", padx=(0, 12), before=self.loud_label)
            self.loud_note.configure(text="Closer to 0 is louder. -12 dB suits the PSP's small speakers.")

    def extract_format_changed(self):
        """WAV or MP3: swap the file type of the save name, and show the MP3 quality when it matters"""
        fmt = self.vars["fmt"].get()
        out = self.vars["out"]
        out.set(os.path.splitext(out.get())[0] + "." + fmt)
        for w in self.mp3_holder.winfo_children():
            w.destroy()
        if fmt == "mp3":
            self.choice("mp3kbps", "MP3 quality", ["128 kbps", "192 kbps", "256 kbps", "320 kbps"], "192 kbps", self.mp3_holder)

    def at3_refresh(self):
        task = self.vars["task"].get()
        self.at3_task = task
        for k in ("sound", "out", "kbps", "loop", "keep", "lufs", "fmt", "mp3kbps"):
            self.vars.pop(k, None)
        for w in self.at3_holder.winfo_children():
            w.destroy()
        h = self.at3_holder
        if task == "extract":
            self.row("sound", "AT3 file", types=[("AT3 sounds", "*.at3"), ("All sound files", "*.at3 *.wav *.mp3 *.oma *.aa3"), ("All files", "*.*")], parent=h)
            f = tk.Frame(h, bg=T.bg)
            f.pack(fill="x", pady=3)
            tk.Label(f, text="Save as", width=14, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10)).pack(side="left")
            self.vars["fmt"] = tk.StringVar(value="wav")
            Segmented(f, [("wav", "WAV"), ("mp3", "MP3")], self.vars["fmt"], self.extract_format_changed).pack(side="left")
            self.mp3_holder = tk.Frame(h, bg=T.bg)
            self.mp3_holder.pack(fill="x")
            self.row("out", "Save to", "save", [("WAV sound", "*.wav"), ("MP3 sound", "*.mp3")], initial=self.out_default("sound.wav"), parent=h)
            self.note("WAV is the exact sound, uncompressed. MP3 is smaller and plays everywhere. The sound itself isn't changed, only the file type.", parent=h)
            self.go.configure(text="Extract")
            return
        if task == "make":
            self.row("sound", "Sound file", types=AUDIO, parent=h)
            self.choice("kbps", "Quality", KBPS, "64 kbps", h)
            self.loudness_row(h, keep=False)
            self.tick("loop", "Make it loop", initial=True, parent=h)
            self.row("out", "Save as", "save", [("AT3 sound", "*.at3")], initial=self.out_default("sound.at3"), parent=h)
            self.note("Lower quality means a smaller file. 64 kbps is a good middle.", parent=h)
            self.go.configure(text="Make AT3")
        else:
            self.row("sound", "AT3 file", types=[("AT3 sounds", "*.at3"), ("All files", "*.*")], parent=h)
            self.choice("kbps", "New quality", KBPS, "48 kbps", h)
            self.loudness_row(h, keep=True)
            self.vars["loop"] = tk.BooleanVar(value=False)
            self.row("out", "Save as", "save", [("AT3 sound", "*.at3")], initial=self.out_default("sound_small.at3"), parent=h)
            self.note("Saves a smaller copy of the sound. Loop points inside the original aren't kept.", parent=h)
            self.go.configure(text="Shrink AT3")

    def page_extract(self):
        self.heading("Extract", "Take a PMF movie apart: you get an MP4 to watch, and the sound on its own if you like.")
        self.row("src", "PMF movie", types=[("PMF movies and CTF themes", "*.pmf *.ctf"), ("All files", "*.*")])
        self.row("out", "Save as", "save", [("MP4 movie", "*.mp4")], initial=self.out_default("extracted.mp4"))
        self.tick("sound_too", "Also save the sound on its own (AT3 and WAV)")
        self.note("Works with any PMF: a gameboot, a movie from a game, an icon movie. The picture is copied exactly as it is. A CTF theme works too: you get the gameboot inside it.")
        self.footer("Extract", self.run_extract, bar=False)

    def run_extract(self):
        self.start(jobs.extract, [("src", "the PMF movie"), ("out", "where to save")])

    def page_player(self):
        from .player import Player
        ff = find_tool("ffmpeg")
        self.heading("Player", "Play a PMF movie here, or any other video or sound.")
        if not ff:
            self.note("PMF Studio can't find ffmpeg, which the player needs. Put it in the tools folder next to the program.")
            return
        top = tk.Frame(self.main, bg=T.bg)
        top.pack(fill="x", pady=(0, 6))
        self.player = Player(self.main, ff, T, T.scale, FONT)
        ttk.Button(top, text="Open a file", command=self.player.choose).pack(side="left")

    def page_help(self):
        self.heading("Help")
        text = ("Getting started\n"
                "Pick what you want to make on the left, choose your files, and press the button at the bottom. "
                "Your original files are never changed. You can also drag files onto the window (or onto the PMF Studio icon): "
                "a movie, an EBOOT.PBP, a PMF, a sound or a folder goes to the right page and box. "
                "A Stop button appears while something is working.\n\n"
                "Gameboot\n"
                "The movie that plays when you start a game. Tick Create CTF to also get a theme file for CXMB: copy it to PSP/THEME and pick it in your PSP's theme settings. "
                "A gameboot can't be much bigger than 3 MB, so PMF Studio lowers the quality until it fits. "
                "Movies longer than 2.5 seconds need your own opening_plugin.rco, decrypted, from the same firmware as your PSP. "
                "Choose your PSP's firmware in the Firmware box; PMF Studio recognises the opening_plugin.rco of firmware 5.00 to 6.61 and tells you when the file and the firmware don't match. "
                "The RCO you give is never changed: the longer boot is patched into a copy inside the theme.\n\n"
                "C-Intro\n"
                "A movie for the C-Intro plugin. There is no size limit.\n\n"
                "Shrink game movies\n"
                "Makes the .pmf movies of a game smaller so the game takes less room. Pick one movie or a whole folder. Each smaller movie keeps its name, picture size and length, "
                "and goes to another folder: your originals are never changed. You choose how much data the picture keeps and the quality of the sound (or leave either as it is); "
                "the page shows the picture and sound bitrates of your movies and what each choice gives. "
                "You can also pick the whole game (A game: a .cso or .iso file). PMF Studio finds the movies inside it (also those a game keeps inside one of its big files, such as a movie.bin), shrinks them, and saves a new game file; only the movies change and everything else on the disc stays exactly as it was, "
                "except that Sony's UPDATE folder is emptied (the firmware update it offers is useless on custom firmware; the folder itself stays) and the game's "
                "own XMB icon movie is never touched. "
                "Movies with several sound tracks (usually one per language) are found for you: by default all of them are kept, or choose which to keep. "
                "In the window that opens, press Play to hear each track and tick the ones you want; the other tracks stay in their places but empty, "
                "which makes the movies smaller. A game such as 007 From Russia With Love picks its track by the PSP's language, so under a language you removed "
                "its movies play without sound. "
                "Try the new game on your PSP before you delete anything.\n\n"
                "EBOOT icon\n"
                "The small movie that plays in the XMB when you highlight a game. It's saved into a copy of the game's EBOOT. "
                "The movie's own sound is used, unless you tick Use a different sound. The movie and sound together must fit in 512 KB.\n\n"
                "AT3 Tools\n"
                "Make a new AT3 sound from any sound file, or shrink an AT3 that came with a game. Lower quality means a smaller file. "
                "Loudness is how loud the new sound is made.\n\n"
                "Extract\n"
                "Takes any PMF movie apart into an MP4 you can watch anywhere. Tick the box to also save its sound as an AT3 and a WAV. "
                "AT3 Tools has an Extract mode too, which turns an AT3 into a WAV or an MP3.\n\n"
                "Player\n"
                "Opens a PMF, or any video or sound, so you can check it before it goes on your PSP.")
        t = tk.Text(self.main, bg=T.bg, fg=T.ink, font=(FONT, 10), relief="flat", wrap="word", spacing3=2)
        t.insert("1.0", text)
        for line in ("Getting started", "Gameboot", "C-Intro", "Shrink game movies", "EBOOT icon", "AT3 Tools", "Extract", "Player"):
            i = t.search(line + "\n", "1.0")
            t.tag_add("h", i, i + " lineend")
        t.tag_configure("h", font=(FONT, 10, "bold"), spacing1=6)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

    def page_about(self):
        self.heading("About PMF Studio %s %s" % (VERSION, STAGE), "Make PSP movies, boot movies and AT3 sounds. Part of the coming PSP CTF Studio.")
        for k, v in (("Source and downloads", "github.com/" + REPO), ("License", "PMF Studio is free software under the GNU GPL version 3."),
                     ("Tools inside", "atracdenc (LGPL-2.1) and FFmpeg. Their notices come with the program."),
                     ("How files are made", "PMF Studio writes the PMF movies with its own code, and makes AT3 sound with the open-source atracdenc encoder. "
                                            "It contains no Sony code, firmware or game content; the RCO you give it stays your own file and is only patched in a copy."),
                     ("Portable", "Runs from any folder or memory stick. It saves nothing outside its own folder.")):
            f = tk.Frame(self.main, bg=T.bg)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=k, width=20, anchor="nw", bg=T.bg, fg=T.muted, font=(FONT, 10)).pack(side="left")
            tk.Label(f, text=v, anchor="w", justify="left", wraplength=S(500), bg=T.bg, fg=T.ink, font=(FONT, 10)).pack(side="left")
        self.note("Not made by or connected to Sony. Contains no game content.")

    def page_options(self):
        self.heading("Options")
        tk.Label(self.main, text="Theme", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w").pack(fill="x")
        self.vars["look"] = tk.StringVar(value="dark" if self.settings["dark"] else "light")
        Segmented(self.main, [("light", "Light"), ("dark", "Dark")], self.vars["look"], self.change_look).pack(anchor="w", pady=(4, 10))
        for key, text in (("auto_update", "Check for updates on startup"), ("open_folder", "Open output folder upon completion")):
            v = tk.BooleanVar(value=self.settings[key])
            self.vars[key] = v
            Check(self.main, text, v, lambda k=key, v=v: self.set_option(k, v.get())).pack(anchor="w", pady=4)
        v = tk.BooleanVar(value=self.settings["low_priority"])
        self.vars["low_priority"] = v
        Check(self.main, "Keep the PC responsive while working (helper programs run at lower priority)", v, lambda: self.set_option("low_priority", v.get())).pack(anchor="w", pady=4)
        self.row("output_dir", "Save files in", "dir", initial=settings.output_dir(self.settings))
        self.vars["output_dir"].trace_add("write", lambda *a: self.set_option("output_dir", settings.to_stored(self.vars["output_dir"].get())))
        self.note("Everything PMF Studio saves stays in its own folder unless you choose another one. If you move or rename the PMF Studio folder, it still finds its files.")
        tk.Label(self.main, text="Helper programs", bg=T.bg, fg=T.muted, font=(FONT, 10), anchor="w").pack(fill="x", pady=(14, 2))
        for name, (path, text) in getattr(self, "tool_status", {}).items():
            line = "%s: %s" % (name, ("ready" if path and text and "won't" not in text else text) if path else text)
            tk.Label(self.main, text=line + ("   (%s)" % path if path else ""), bg=T.bg, fg=T.ink if path and "won't" not in text else BAD, font=(FONT, 9), anchor="w").pack(fill="x")

        f = tk.Frame(self.main, bg=T.bg)
        f.pack(fill="x", pady=(14, 0))
        ttk.Button(f, text="Copy diagnostics", command=self.copy_diagnostics).pack(side="left")
        tk.Label(f, text="Text for a bug report: program and helper versions, Windows, what went wrong last. It leaves out your folder names and user name.",
                 bg=T.bg, fg=T.muted, font=(FONT, 9), wraplength=S(520), justify="left").pack(side="left", padx=12)

    def diagnostics_text(self):
        def scrub(text):
            for real, shown in ((paths.app_dir(), "<program>"), (os.path.expanduser("~"), "<home>"), (os.environ.get("USERNAME", ""), "<user>")):
                if real and len(real) > 2:
                    text = text.replace(real, shown).replace(real.replace("\\", "/"), shown)
            return text
        lines = ["PMF Studio %s %s (%s)" % (VERSION, STAGE, "exe" if getattr(sys, "frozen", False) else "from source"),
                 "Windows: %s" % platform.platform(), "Python %s, Tk %s, screen scale %.2f" % (platform.python_version(), tk.TkVersion, T.scale)]
        for name, (path, text) in getattr(self, "tool_status", {}).items():
            lines.append("%s: %s" % (name, text if path else "not found"))
        try:
            folder = settings.output_dir(self.settings)
            anc = preflight.nearest_existing(folder)
            lines.append("Free space where files are saved: %s" % (preflight.fmt(shutil.disk_usage(anc).free) if anc else "unknown"))
        except OSError:
            pass
        ram = preflight.free_ram()
        lines.append("Free memory: %s" % (preflight.fmt(ram) if ram else "unknown"))
        lines.append("Settings: theme %s, lower priority %s, updates on startup %s" % ("dark" if self.settings["dark"] else "light", self.settings["low_priority"], self.settings["auto_update"]))
        trace = getattr(self, "last_trace", "")
        lines.append("Last unexpected error:\n" + scrub(trace[-1500:]) if trace else "No unexpected errors in this run.")
        return "\n".join(lines)

    def copy_diagnostics(self):
        self.clipboard_clear()
        self.clipboard_append(self.diagnostics_text())
        messagebox.showinfo("PMF Studio", "Copied. Paste it into your bug report.")

    def change_look(self):
        self.set_option("dark", self.vars["look"].get() == "dark")
        set_theme(self.settings["dark"])
        self.build_ui()
        self.show("options")

    def set_option(self, key, value):
        self.settings[key] = value
        settings.save(self.settings)

    # ---------- jobs ----------
    def tools(self):
        t = {"ffmpeg": find_tool("ffmpeg"), "atracdenc": find_tool("atracdenc")}
        missing = [k for k, v in t.items() if not v]
        if missing:
            raise BuildError("PMF Studio can't find %s. Put it in the tools folder next to the program." % " and ".join(missing))
        return t

    def start(self, func, need, extra=None):
        if self.busy:
            return
        v = {k: x.get() for k, x in self.vars.items()}
        v.update(extra or {})
        for key, what in need:
            if not v.get(key):
                messagebox.showinfo("PMF Studio", "Choose %s first." % what)
                return
            if key != "out" and not os.path.exists(v[key]):
                messagebox.showinfo("PMF Studio", "Can't find %s:\n%s" % (what, v[key]))
                return
        if v.get("sep") and not v.get("sound"):
            messagebox.showinfo("PMF Studio", "Choose the sound file, or untick Use a different sound.")
            return
        try:
            preflight.run(self.mode, v, self.tools())
        except BuildError as e:
            messagebox.showinfo("PMF Studio", str(e))
            return
        from pmfkit import umdimage
        game = self.mode == "shrink" and umdimage.is_image(v.get("src", ""))
        if self.mode == "shrink" and not game:
            from pmfkit import shrink as shrinkmod
            same = sum(os.path.exists(os.path.join(v["out"], rel if os.path.isdir(v["src"]) else os.path.basename(v["src"]))) for _, rel in shrinkmod.find_movies(v["src"]))
            if same and not messagebox.askyesno("PMF Studio", "%d movie%s with the same name%s already in that folder. Replace %s?" % (
                    same, "" if same == 1 else "s", "" if same == 1 else "s", "it" if same == 1 else "them")):
                return
        if (self.mode != "shrink" or game) and os.path.exists(v["out"]) and not messagebox.askyesno("PMF Studio", "%s already exists. Replace it?" % os.path.basename(v["out"])):
            return
        try:
            tools = self.tools()
            os.makedirs(os.path.dirname(os.path.abspath(v["out"])), exist_ok=True)
        except (BuildError, OSError) as e:
            messagebox.showerror("PMF Studio", str(e))
            return
        self.busy = True
        cli.CANCEL.clear()
        cli.PRIORITY = 0x4000 if self.settings.get("low_priority", True) and os.name == "nt" else 0       # below normal: the PC stays usable
        self.go.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.stop_btn.pack(side="right", padx=(0, 6))
        self.ring.start()
        self.status.configure(text="Working\u2026", fg=T.muted)
        cli.PROGRESS.reset()
        cli.PROGRESS.callback = lambda fraction, text: self.q.put(("progress", (fraction, text)))
        self.show_progress(0.0, "Starting\u2026")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log.pack_forget()
        if hasattr(self, "size_bar"):
            self.size_label.pack_forget()
            self.size_bar.pack_forget()

        def work():
            try:
                if os.name == "nt":
                    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)    # the PC doesn't go to sleep in the middle of a long job
                func(v, tools, lambda line: self.q.put(("log", line)))
                self.q.put(("done", v["out"]))
            except BuildError as e:
                self.q.put(("error", str(e)))
            except Exception as e:                      # keep the window alive whatever happens
                self.last_trace = traceback.format_exc()
                self.q.put(("error", "Something unexpected went wrong (%s: %s).\n\nOptions > Copy diagnostics gives you text to send with a bug report." % (type(e).__name__, e)))
            finally:
                if os.name == "nt":
                    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def pump(self):
        latest = None
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "progress":
                    latest = data                                    # only the newest position is drawn
                    continue
                if kind == "log":
                    if self.alive(getattr(self, "log", None)):
                        if not self.log.winfo_ismapped():
                            self.log.pack(fill="x", pady=(0, 8), before=self.foot_row)
                        self.log.configure(state="normal")
                        self.log.insert("end", data + "\n")
                        self.log.see("end")
                        self.log.configure(state="disabled")
                elif kind in ("done", "error"):
                    self.finish(kind, data)
                elif kind == "tools":
                    self.tools_checked(data)
                elif kind == "trim_progress":
                    self.trim_wait_update(*data)
                elif kind == "trim":
                    self.trim_arrived(*data)
                elif kind == "trim_thumbs":
                    self.trim_thumbs(*data)
                elif kind == "snd":
                    if not hasattr(self, "sound_secs"):
                        self.sound_secs = {}
                    if data[1]:
                        self.sound_secs[data[0]] = data[1]
                    self.trim_recompute()
                elif kind == "upd_progress":
                    self.update_progress(*data)
                elif kind == "upd_done":
                    self.update_finished(*data)
                elif kind == "update":
                    self.after(1000, lambda r=data: self.finish_update(*r))      # the arrows spin for at least a second
        except queue.Empty:
            pass
        if latest:
            self.show_progress(*latest)
        self.after(100, self.pump)

    def alive(self, w):
        try:
            return w is not None and w.winfo_exists()
        except tk.TclError:
            return False

    def show_progress(self, fraction, text):
        if self.busy and self.alive(getattr(self, "progress", None)):
            self.progress.set(fraction)
            self.progress_label.configure(text=text or "Working\u2026", fg=T.ink)
            self.progress_pct.configure(text="%d%%" % int(fraction * 100))

    def finish(self, kind, data):
        self.busy = False
        cli.PROGRESS.callback = None
        if not self.alive(getattr(self, "go", None)):
            return
        if kind == "error":
            self.progress.set(self.progress.value, BAD)
            self.progress_label.configure(text="Stopped", fg=BAD)
        else:
            self.progress.set(1.0, OK)
            self.progress_label.configure(text="Done", fg=OK)
            self.progress_pct.configure(text="100%")
        self.ring.stop()
        self.go.configure(state="normal")
        self.stop_btn.pack_forget()
        if kind == "error" and cli.CANCEL.is_set():
            self.progress.set(self.progress.value, T.muted)
            self.progress_label.configure(text="Stopped", fg=T.muted)
            self.status.configure(text="Stopped. Nothing half-finished was kept.", fg=T.muted)
            return
        if kind == "error":
            self.status.configure(text="Stopped", fg=BAD)
            messagebox.showerror("PMF Studio", data)
            return
        self.status.configure(text="\u2713 Done", fg=OK)
        size = os.path.getsize(data)
        if self.alive(getattr(self, "size_bar", None)) and self.mode in ("gameboot", "icon", "at3"):
            self.size_label.pack(fill="x", before=self.foot_row)
            self.size_bar.pack(fill="x", pady=(2, 8), before=self.foot_row)
            if self.mode == "at3" and self.vars["task"].get() == "extract":
                self.size_label.pack_forget()                        # sound extraction has no size limit to show
                self.size_bar.pack_forget()
            else:
                limit = 3030000 if self.mode == "gameboot" else 512000
                self.size_label.configure(text="Result: %s" % self.fmt(size) if self.mode == "gameboot" and self.vars["ctf"].get() else "Result: %s of %s" % (self.fmt(size), self.fmt(limit)))
                self.size_bar.set(min(1.0, size / limit))
        if self.settings["open_folder"]:
            try:
                os.startfile(os.path.abspath(data) if os.path.isdir(data) else os.path.dirname(os.path.abspath(data)))
            except (OSError, AttributeError):
                pass

    @staticmethod
    def fmt(n):
        return "%.2f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % round(n / 1000)

    def run_gameboot(self):
        if self.trim_blocked():
            return
        self.start(jobs.gameboot, [("movie", "your movie"), ("out", "where to save")] + ([("rco", "your decrypted opening_plugin.rco")] if self.vars["ctf"].get() and self.vars["rco"].get() else []), self.part_args())

    def run_cintro(self):
        if self.trim_blocked():
            return
        self.start(jobs.cintro, [("movie", "your movie"), ("out", "where to save")], self.part_args())

    def run_icon(self):
        if self.trim_blocked():
            return
        self.start(jobs.icon, [("eboot", "the game's EBOOT"), ("out", "where to save")], dict(self.part_args(), title0=self.eboot_title))

    def run_at3(self):
        if self.vars["task"].get() == "extract":
            self.start(jobs.extract_sound, [("sound", "the AT3 file"), ("out", "where to save")])
            return
        self.start(jobs.at3, [("sound", "your sound file"), ("out", "where to save")], {"kbps": int(self.vars["kbps"].get().split()[0])})

    # ---------- updates ----------
    def check_updates(self, manual=True):
        if self.checking:
            return
        self.update_manual = manual
        self.checking = True
        self.upbtn.set_text("Checking\u2026")
        self.upbtn.icon.start()
        threading.Thread(target=lambda: self.q.put(("update", updater.check())), daemon=True).start()

    def finish_update(self, kind, info):
        if not self.alive(self.upbtn):
            self.checking = False
            return
        self.upbtn.icon.stop()
        if kind == "newer":
            self.reset_update()
            if getattr(self, "update_manual", True) or self.settings.get("skip_version") != info["tag"]:
                self.offer_update(info)
            return
        self.upbtn.set_text("\u2713 You're up to date" if kind == "latest" else "Couldn't check for updates", OK if kind == "latest" else BAD)
        self.after(2500, self.reset_update)

    def ask_update_choice(self, msg):
        """three buttons -> "now" | "later" | "skip" """
        result = {"v": "later"}
        win = tk.Toplevel(self)
        win.title("PMF Studio update")
        win.configure(bg=T.bg)
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text=msg, bg=T.bg, fg=T.ink, font=(FONT, 10), justify="left", wraplength=S(520)).pack(padx=22, pady=(20, 12))
        bf = tk.Frame(win, bg=T.bg)
        bf.pack(padx=22, pady=(0, 18), anchor="e")

        def pick(v):
            result["v"] = v
            win.destroy()
        ttk.Button(bf, text="Update now", style="Go.TButton", command=lambda: pick("now")).pack(side="left")
        ttk.Button(bf, text="Remind me next time", command=lambda: pick("later")).pack(side="left", padx=8)
        ttk.Button(bf, text="Skip this version", command=lambda: pick("skip")).pack(side="left")
        win.protocol("WM_DELETE_WINDOW", lambda: pick("later"))
        win.update_idletasks()
        win.geometry("+%d+%d" % (max(self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2, 0), self.winfo_rooty() + 120))
        win.grab_set()
        win.wait_window()
        return result["v"]

    def offer_update(self, info):
        """a newer version exists: say what is new and offer to install it (or, when it can't install itself, to open the download page)"""
        notes = (info.get("notes") or "").strip().split("\n\n")[0][:300]
        head = "PMF Studio %s is out. You have %s %s." % (info["tag"], VERSION, STAGE) + ("\n\n" + notes if notes else "")
        if self.busy:
            messagebox.showinfo("PMF Studio", head + "\n\nPMF Studio is busy with a job. Click Check for updates again when it is done.")
            return
        problem = updater.can_install(app_dir())
        asset = info.get("asset")
        if problem or not asset or not asset.get("sha"):
            why = problem or "This release has no checksum or zip that PMF Studio can install by itself."
            if messagebox.askyesno("Update available", "%s\n\n%s\n\nOpen the download page?" % (head, why)):
                import webbrowser
                webbrowser.open(info["url"])
            return
        choice = self.ask_update_choice("%s\n\nUpdate now? PMF Studio downloads the new version (%d MB), checks it, tests it, and restarts into it. "
                                        "Your settings and saved files stay as they are." % (head, (asset.get("size") or 0) // 1_000_000))
        if choice == "skip":
            self.set_option("skip_version", info["tag"])
        elif choice == "now":
            self.install_update(info)

    def install_update(self, info):
        """downloads, checks and tests the new version in a small window, then closes and lets the swap script do the rest"""
        win = tk.Toplevel(self)
        win.title("Updating PMF Studio")
        win.configure(bg=T.bg)
        win.transient(self)
        win.resizable(False, False)
        label = tk.Label(win, text="Starting\u2026", bg=T.bg, fg=T.ink, font=(FONT, 10), width=60, anchor="w")
        label.pack(padx=22, pady=(20, 8))
        bar = ProgressBar(win, height=10)
        bar.pack(fill="x", padx=22)
        stop = {"v": False}
        btn = ttk.Button(win, text="Stop", command=lambda: stop.update(v=True))
        btn.pack(pady=14)
        win.protocol("WM_DELETE_WINDOW", lambda: stop.update(v=True))
        win.update_idletasks()
        win.geometry("+%d+%d" % (max(self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2, 0), self.winfo_rooty() + 140))
        win.grab_set()
        self.update_ui = (win, label, bar)
        self.updating = True
        work = tempfile.mkdtemp(prefix="update_")

        def thread():
            try:
                script = updater.install(info["asset"], info["tag"], app_dir(), work, lambda text, f: self.q.put(("upd_progress", (text, f))),
                                         lambda: stop["v"])
                self.q.put(("upd_done", (script, "")))
            except updater.UpdateError as e:
                self.q.put(("upd_done", (None, str(e))))
            except Exception as e:                                  # whatever goes wrong, the installed version stays as it is
                self.last_trace = traceback.format_exc()
                self.q.put(("upd_done", (None, "Something unexpected went wrong (%s: %s). Nothing was changed." % (type(e).__name__, e))))
            finally:
                shutil.rmtree(work, ignore_errors=True)
        threading.Thread(target=thread, daemon=True).start()

    def clean_after_update(self):
        if not self.updating:                                                    # never while an update is being installed: it uses the staging folder
            updater.cleanup_after_update(app_dir())

    def update_progress(self, text, fraction):
        win, label, bar = getattr(self, "update_ui", (None, None, None))
        if self.alive(win):
            label.configure(text=text)
            bar.set(fraction)

    def update_finished(self, script, error):
        self.updating = False
        win = getattr(self, "update_ui", (None,))[0]
        if self.alive(win):
            win.grab_release()
            win.destroy()
        if error:
            if error != "Stopped.":
                messagebox.showerror("PMF Studio", "The update did not go through.\n\n%s" % error)
            return
        self.settings["skip_version"] = ""
        settings.save(self.settings)
        updater.run_swap(script)                                    # it waits for this program to end, swaps the files and starts the new version
        if self.player:
            self.player.close()
        self.destroy()

    def reset_update(self):
        if self.alive(self.upbtn):
            self.upbtn.set_text("Check for updates")
        self.checking = False


def main():
    base = os.path.join(app_dir(), "temp")                 # working files stay beside the program too, not in the Windows temp folder
    work = os.path.join(base, "run%d" % os.getpid())       # one folder per running program: a second PMF Studio never deletes the first one's files
    paths.sweep_temp(base, os.getpid())                    # and folders left behind by a program that was killed are removed
    if settings.usable(base):
        os.makedirs(work, exist_ok=True)
        tempfile.tempdir = work
    else:                                                  # a read-only folder: use the system's temp folder instead of failing
        work = None
    try:
        App([a for a in sys.argv[1:] if not a.startswith("--")]).mainloop()
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
