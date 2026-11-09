"""The sound-track window of the Shrink page: a movie (or a game's movies) with several sound tracks, usually one per language.
Press Play to hear each track, tick the ones to keep. The others stay in their places but empty, so a game that picks its track
by the PSP's language still finds the one you kept (007 From Russia With Love plays the other languages' movies silent)."""
import ctypes
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from pmfkit import tracks
from .theme import T, S
from .widgets import Check

FONT = "Segoe UI"


class TrackDialog:
    def __init__(self, app, sources, count, keep, ffmpeg, game):
        """sources: [(name, loader)] movies with several tracks to listen to; count: how many tracks to offer; keep: the tracks ticked now
        (0-based list, None = all); game: a whole game (the wording changes)"""
        self.app, self.sources, self.count, self.ffmpeg, self.game = app, sources, count, ffmpeg, game
        self.index = 0
        self.raws, self.pcm = {}, {}
        self.vars = [tk.BooleanVar(value=keep is None or i in keep) for i in range(count)]
        self.buttons, self.playing, self.wave, self.total = [], None, None, 0
        self.results = queue.Queue()
        self.generation = 0
        self.result = None
        self.closed = False

    # ---------------------------------------------------------------- the window
    def show(self):
        """-> the tracks to keep (0-based list), or None when the window was cancelled"""
        win = self.win = tk.Toplevel(self.app)
        win.title("Sound tracks")
        win.configure(bg=T.bg)
        win.transient(self.app)
        win.resizable(False, False)
        tk.Label(win, text="Which sound tracks do you want to keep?", bg=T.bg, fg=T.ink, font=(FONT, 12, "bold"), anchor="w").pack(fill="x", padx=22, pady=(18, 4))
        what = "Each movie in the game carries" if self.game else "This movie carries"
        tk.Label(win, text="%s %d sound tracks, usually one per language. Press Play to hear each one, then tick the ones you want. "
                 "The others stay in their places but empty, so the game still finds the language you kept (it picks its track by the PSP's "
                 "language setting; under a language you removed, the movies play without sound). Removing tracks makes the movies smaller." % (what, self.count),
                 bg=T.bg, fg=T.muted, font=(FONT, 10), justify="left", anchor="w", wraplength=S(560)).pack(fill="x", padx=22, pady=(0, 10))
        self.which = tk.Label(win, text="", bg=T.bg, fg=T.ink, font=(FONT, 10), anchor="w", justify="left", wraplength=S(560))
        self.which.pack(fill="x", padx=22)
        self.another = None
        if len(self.sources) > 1:
            self.another = ttk.Button(win, text="Listen to another movie", command=self.next_movie)
            self.another.pack(anchor="w", padx=22, pady=(4, 0))
        rows = tk.Frame(win, bg=T.bg)
        rows.pack(fill="x", padx=22, pady=(12, 4))
        for i in range(self.count):
            row = tk.Frame(rows, bg=T.bg)
            row.pack(fill="x", pady=3)
            tk.Label(row, text="Track %d" % (i + 1), width=9, anchor="w", bg=T.bg, fg=T.ink, font=(FONT, 10, "bold")).pack(side="left")
            b = ttk.Button(row, text="▶  Play", width=10, command=lambda i=i: self.toggle(i))
            b.pack(side="left", padx=(0, 14))
            self.buttons.append(b)
            Check(row, "Keep this track", self.vars[i]).pack(side="left")
        self.status = tk.Label(win, text="", bg=T.bg, fg=T.muted, font=(FONT, 9), anchor="w", justify="left", wraplength=S(560))
        self.status.pack(fill="x", padx=22, pady=(6, 0))
        bf = tk.Frame(win, bg=T.bg)
        bf.pack(padx=22, pady=(12, 18), anchor="e")
        ttk.Button(bf, text="Keep these", style="Go.TButton", command=self.accept).pack(side="left")
        ttk.Button(bf, text="Cancel", command=self.close).pack(side="left", padx=(8, 0))
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.name_it()
        win.update_idletasks()
        win.geometry("+%d+%d" % (max(self.app.winfo_rootx() + (self.app.winfo_width() - win.winfo_width()) // 2, 0), self.app.winfo_rooty() + 80))
        win.grab_set()
        self.poll()
        win.wait_window()
        return self.result

    def name_it(self):
        if self.sources:
            self.which.configure(text="Listening to: %s  (about 14 seconds from near its start)" % self.sources[self.index][0])
        else:
            self.which.configure(text="There is no movie here to listen to, but you can still choose.")
            for b in self.buttons:
                b.state(["disabled"])

    def next_movie(self):
        self.stop()
        self.index = (self.index + 1) % len(self.sources)
        self.name_it()

    def accept(self):
        kept = [i for i, v in enumerate(self.vars) if v.get()]
        if not kept:
            messagebox.showinfo("PMF Studio", "Keep at least one sound track.", parent=self.win)
            return
        self.result = [] if len(kept) == self.count else kept             # [] = every track ticked = keep them all
        self.close()

    def close(self):
        self.closed = True
        self.stop()
        if self.wave is not None:
            try:
                self.wave.close()
            except OSError:
                pass
            self.wave = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- listening
    def stop(self):
        if self.wave is not None:
            self.wave.stop()
        self.playing = None
        self.generation += 1                                                # a sound still being prepared is dropped
        for b in self.buttons:
            b.configure(text="▶  Play")
        if not self.closed:
            self.status.configure(text="")

    def toggle(self, i):
        if self.playing == i:
            self.stop()
            return
        self.stop()
        if not self.sources:
            return
        name, loader = self.sources[self.index]
        key = (name, i)
        self.playing = i
        self.buttons[i].configure(text="■  Stop")
        if key in self.pcm:
            self.begin(i, self.pcm[key])
            return
        self.status.configure(text="Getting track %d ready…" % (i + 1))
        gen, results, ffmpeg, have = self.generation, self.results, self.ffmpeg, self.raws.get(name)

        def work():                                                            # (touches nothing of the window: only the queue)
            try:
                raw = have or loader()
                data = tracks.sample_pcm(raw, i, ffmpeg)
                results.put((gen, i, key, data, "", raw))
            except Exception as e:                                             # whatever goes wrong is only a track that can't be played
                results.put((gen, i, key, None, str(e) or type(e).__name__, None))
        threading.Thread(target=work, daemon=True).start()

    def begin(self, i, data):
        from .sound import open_output
        try:
            if self.wave is None:
                self.wave = open_output()
        except OSError:
            self.stop()
            self.status.configure(text="PMF Studio found no sound device to play this on.")
            return
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        self.total = len(data) // 4
        self.wave.play(buf)
        self.status.configure(text="Playing track %d…" % (i + 1))

    def poll(self):
        """results from the thread that prepares a sound, and the end of a sound that is playing"""
        if self.closed:
            return
        try:
            while True:
                gen, i, key, data, err, raw = self.results.get_nowait()
                if raw is not None:
                    self.raws[key[0]] = raw
                if gen != self.generation:
                    continue
                if data is None:
                    self.stop()
                    self.status.configure(text="Track %d could not be played: %s" % (i + 1, err))
                else:
                    self.pcm[key] = data
                    self.begin(i, data)
        except queue.Empty:
            pass
        if self.playing is not None and self.wave is not None and self.total and self.wave.samples() >= self.total:
            self.stop()
        try:
            self.win.after(150, self.poll)
        except tk.TclError:
            pass
