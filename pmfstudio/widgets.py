"""Hand-drawn controls (sliders, round icon buttons, tick boxes, segmented choice) so the window looks current, not like old Windows."""
import math
import tkinter as tk

from .theme import T, S, mix

FONT = "Segoe UI"


class Slider(tk.Canvas):
    """A thin rounded track with a filled part and a round knob."""

    def __init__(self, parent, from_=0, to=100, value=0, command=None, on_release=None, length=200, bg=None):
        super().__init__(parent, height=S(22), width=length, bg=bg or T.bg, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.value, self.command, self.on_release = from_, to, value, command, on_release
        self.drag = self.hover = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Enter>", lambda e: self.set_hover(True))
        self.bind("<Leave>", lambda e: self.set_hover(False))

    def set_hover(self, h):
        self.hover = h
        self.draw()

    def range(self, to):
        self.hi = max(to, 0.001)
        self.draw()

    def set(self, v, notify=False):
        if self.drag:
            return                                              # the user is holding the knob: don't fight them
        self.value = min(max(v, self.lo), self.hi)
        self.draw()
        if notify and self.command:
            self.command(self.value)

    def x_of(self, v):
        r = S(8)
        return r + (self.winfo_width() - 2 * r) * (v - self.lo) / (self.hi - self.lo)

    def value_at(self, x):
        r = S(8)
        span = max(self.winfo_width() - 2 * r, 1)
        return self.lo + (self.hi - self.lo) * min(max((x - r) / span, 0), 1)

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        y, r, t = h / 2, S(8), S(4)
        self.create_line(r, y, w - r, y, width=t, capstyle="round", fill=T.line)
        x = self.x_of(self.value)
        if x > r:
            self.create_line(r, y, x, y, width=t, capstyle="round", fill=T.accent)
        k = S(8) if (self.hover or self.drag) else S(6)
        self.create_oval(x - k, y - k, x + k, y + k, fill=T.accent, outline=T.bg, width=S(2))

    def press(self, e):
        self.drag = True
        self.move(e)

    def move(self, e):
        self.value = self.value_at(e.x)
        self.draw()
        if self.command:
            self.command(self.value)

    def release(self, e):
        self.drag = False
        self.draw()
        if self.on_release:
            self.on_release(self.value)


class IconButton(tk.Canvas):
    """A round button with a drawn icon: play, pause, stop, speaker, speaker-low, muted."""

    def __init__(self, parent, icon, command, size=34, filled=False, bg=None, fg=None, hover_bg=None):
        s = S(size)
        self.fg, self.hover_bg = fg, hover_bg
        super().__init__(parent, width=s, height=s, bg=bg or T.bg, highlightthickness=0, cursor="hand2")
        self.icon, self.command, self.filled, self.size, self.hover = icon, command, filled, s, False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.set_hover(True))
        self.bind("<Leave>", lambda e: self.set_hover(False))
        self.draw()

    def set_hover(self, h):
        self.hover = h
        self.draw()

    def set_icon(self, icon):
        self.icon = icon
        self.draw()

    def draw(self):
        self.delete("all")
        s = self.size
        c = s / 2
        if self.filled:
            self.create_oval(1, 1, s - 1, s - 1, fill=mix(T.accent, "#000000", 0.12) if self.hover else T.accent, outline="")
            col = T.on_accent
        else:
            if self.hover:
                self.create_oval(1, 1, s - 1, s - 1, fill=self.hover_bg or T.hover, outline="")
            col = self.fg or T.ink
        u = s / 34
        w = max(2, int(2 * u))
        if self.icon == "play":
            self.create_polygon(c - 5 * u, c - 8 * u, c - 5 * u, c + 8 * u, c + 9 * u, c, fill=col, outline=col, joinstyle="round")
        elif self.icon == "pause":
            self.create_rectangle(c - 7 * u, c - 8 * u, c - 2 * u, c + 8 * u, fill=col, outline=col)
            self.create_rectangle(c + 2 * u, c - 8 * u, c + 7 * u, c + 8 * u, fill=col, outline=col)
        elif self.icon == "fullscreen":
            a, b = 8 * u, 4 * u
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                x0, y0 = c + sx * a, c + sy * a
                self.create_line(x0 - sx * b, y0, x0, y0, x0, y0 - sy * b, fill=col, width=w, capstyle="round", joinstyle="round")
        elif self.icon == "unfullscreen":
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                x0, y0 = c + sx * 3 * u, c + sy * 3 * u
                self.create_line(x0 + sx * 6 * u, y0, x0, y0, x0, y0 + sy * 6 * u, fill=col, width=w, capstyle="round", joinstyle="round")
        elif self.icon == "stop":
            self.create_rectangle(c - 6 * u, c - 6 * u, c + 6 * u, c + 6 * u, fill=col, outline=col)
        else:
            self.create_polygon(c - 9 * u, c - 4 * u, c - 4 * u, c - 4 * u, c + 1 * u, c - 9 * u, c + 1 * u, c + 9 * u, c - 4 * u, c + 4 * u, c - 9 * u, c + 4 * u,
                                fill=col, outline=col, joinstyle="round")
            if self.icon == "muted":
                self.create_line(c + 5 * u, c - 4 * u, c + 11 * u, c + 4 * u, fill="#d64545", width=w, capstyle="round")
                self.create_line(c + 11 * u, c - 4 * u, c + 5 * u, c + 4 * u, fill="#d64545", width=w, capstyle="round")
            else:
                for r in range(1, 3 if self.icon == "speaker" else 2):
                    self.create_arc(c + 1 * u - 5 * u * r + 5 * u, c - 4 * u * r - 1 * u, c + 1 * u + 5 * u * r + 3 * u, c + 4 * u * r + 1 * u,
                                    start=-55, extent=110, style=tk.ARC, outline=col, width=w)


class Check(tk.Frame):
    """A tick box with a square and a drawn tick."""

    def __init__(self, parent, text, variable, command=None, bg=None):
        super().__init__(parent, bg=bg or T.bg, cursor="hand2")
        self.var, self.command = variable, command
        b = S(18)
        self.box = tk.Canvas(self, width=b, height=b, bg=self["bg"], highlightthickness=0)
        self.box.pack(side="left")
        self.label = tk.Label(self, text=text, bg=self["bg"], fg=T.ink, font=(FONT, 10), cursor="hand2")
        self.label.pack(side="left", padx=(8, 0))
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self.toggle)
        self.trace = variable.trace_add("write", lambda *a: self.draw())
        self.bind("<Destroy>", self.cleanup)
        self.draw()

    def cleanup(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self.trace)
            except (tk.TclError, ValueError):
                pass

    def toggle(self, e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        try:
            on = bool(self.var.get())
            c = self.box
            c.delete("all")
            b = S(18)
            if on:
                c.create_rectangle(1, 1, b - 1, b - 1, fill=T.accent, outline=T.accent)
                c.create_line(b * 0.26, b * 0.52, b * 0.43, b * 0.70, b * 0.76, b * 0.32, fill=T.on_accent, width=max(2, S(2)), capstyle="round", joinstyle="round")
            else:
                c.create_rectangle(1, 1, b - 1, b - 1, fill=T.bg, outline=T.muted, width=1)
        except tk.TclError:
            pass


class Segmented(tk.Frame):
    """Two or three choices side by side; the chosen one is filled."""

    def __init__(self, parent, options, variable, command=None, pad=18):
        super().__init__(parent, bg=T.line, padx=1, pady=1)
        self.var, self.command, self.items = variable, command, {}
        for value, text in options:
            lab = tk.Label(self, text=text, font=(FONT, 10), padx=S(pad), pady=S(6), cursor="hand2")
            lab.pack(side="left")
            lab.bind("<Button-1>", lambda e, v=value: self.choose(v))
            self.items[value] = lab
        self.refresh()

    def choose(self, v):
        if self.var.get() != v:
            self.var.set(v)
            self.refresh()
            if self.command:
                self.command()

    def refresh(self):
        for v, lab in self.items.items():
            on = self.var.get() == v
            lab.configure(bg=T.accent if on else T.bg, fg=T.on_accent if on else T.ink, font=(FONT, 10, "bold" if on else "normal"))


_SHAPE_CACHE = {}


def _example_pixel(u, v):
    """a made-up 4:3 picture (sky, sun, hill, white edge line); u and v run 0..1 across it. The round sun shows squashing."""
    if u < 0.05 or u > 0.95 or v < 0.06 or v > 0.94:
        return (245, 245, 245)
    if ((u - 0.70) * 4) ** 2 + ((v - 0.32) * 3) ** 2 < 0.30:
        return (255, 205, 60)
    if v > 0.70 + 0.07 * math.sin(u * 7):
        return (70, 170, 90)
    return (int(80 + 60 * v), int(150 + 70 * v), 255)


def _shape_image(kind, w):
    """what a 4:3 picture looks like on the PSP's wide screen with each choice: 'source' (as it is), 'crop', 'pad', 'stretch'"""
    key = (kind, w)
    if key in _SHAPE_CACHE:
        return _SHAPE_CACHE[key]
    h = round(w * 9 / 16)
    sw, sh = (w * 3 // 4, h) if kind == "source" else (w, h)
    img = tk.PhotoImage(width=sw, height=sh)
    rows = []
    for y in range(sh):
        row = []
        for x in range(sw):
            r = g = b = n = 0
            for dy in (0.25, 0.75):                                   # 2 x 2 samples per pixel: smoother edges
                for dx in (0.25, 0.75):
                    px, py = x + dx, y + dy
                    if kind == "source":
                        c = _example_pixel(px / sw, py / sh)
                    elif kind == "crop":                              # picture as wide as the screen, top and bottom cut off
                        c = _example_pixel(px / w, 0.5 + (py - h / 2) / (w * 3 / 4))
                    elif kind == "pad":                               # picture as tall as the screen, black bars at the sides
                        u = 0.5 + (px - w / 2) / (h * 4 / 3)
                        c = _example_pixel(u, py / h) if 0 <= u <= 1 else (0, 0, 0)
                    else:                                             # stretch: pulled to the screen's shape
                        c = _example_pixel(px / w, py / h)
                    r, g, b, n = r + c[0], g + c[1], b + c[2], n + 1
            row.append("#%02x%02x%02x" % (r // n, g // n, b // n))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    _SHAPE_CACHE[key] = img
    return img


class FitPicker(tk.Frame):
    """'Picture shape': the example picture, then one small picture per choice showing what you get (Fill / Black bars / Stretch)."""

    def __init__(self, parent, variable, command=None):
        super().__init__(parent, bg=T.bg)
        self.var, self.command, self.cards = variable, command, {}
        w = S(104)
        src = tk.Frame(self, bg=T.bg)
        src.pack(side="left", padx=(0, S(6)))
        tk.Label(src, image=_shape_image("source", w), bd=0, bg=T.line, padx=1, pady=1).pack(pady=(S(4), S(2)))
        tk.Label(src, text="Your picture", bg=T.bg, fg=T.muted, font=(FONT, 9)).pack()
        tk.Label(self, text="→", bg=T.bg, fg=T.muted, font=(FONT, 16)).pack(side="left", padx=S(4))
        for value, name in (("crop", "Fill"), ("pad", "Black bars"), ("stretch", "Stretch")):
            card = tk.Frame(self, bg=T.line, padx=2, pady=2, cursor="hand2")
            card.pack(side="left", padx=S(4))
            inner = tk.Frame(card, bg=T.bg, padx=S(4), pady=S(4))
            inner.pack()
            pic = tk.Label(inner, image=_shape_image(value, w), bd=0, bg=T.line, padx=1, pady=1)
            pic.pack()
            lab = tk.Label(inner, text=name, bg=T.bg, font=(FONT, 10))
            lab.pack(pady=(S(3), 0))
            for widget in (card, inner, pic, lab):
                widget.bind("<Button-1>", lambda e, v=value: self.choose(v))
            self.cards[value] = (card, inner, lab)
        self.refresh()

    def choose(self, v):
        if self.var.get() != v:
            self.var.set(v)
            self.refresh()
            if self.command:
                self.command()

    def refresh(self):
        for v, (card, inner, lab) in self.cards.items():
            on = self.var.get() == v
            card.configure(bg=T.accent if on else T.line)
            lab.configure(fg=T.accent if on else T.ink, font=(FONT, 10, "bold" if on else "normal"))


class ScrollArea(tk.Frame):
    """A page that scrolls (mouse wheel and a thin bar) only when it is taller than the window."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.bg)
        self.canvas = tk.Canvas(self, bg=T.bg, highlightthickness=0)
        self.bar = tk.Canvas(self, width=S(8), bg=T.bg, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=T.bg)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.update_view())
        self.canvas.bind("<Configure>", self.resized)
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self.wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
        self.bar.bind("<Button-1>", self.bar_click)
        self.bar.bind("<B1-Motion>", self.bar_click)

    def resized(self, e):
        self.canvas.itemconfigure(self.window, width=e.width)
        self.update_view()

    def content_height(self):
        return self.inner.winfo_reqheight()

    def scrollable(self):
        return self.content_height() > self.canvas.winfo_height() + 2

    def update_view(self):
        self.canvas.configure(scrollregion=(0, 0, 1, max(self.content_height(), self.canvas.winfo_height())))
        if self.scrollable():
            self.bar.pack(side="right", fill="y", padx=(6, 0))
        else:
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)
        self.draw_bar()

    def draw_bar(self):
        self.bar.delete("all")
        if not self.scrollable():
            return
        lo, hi = self.canvas.yview()
        h = self.bar.winfo_height()
        self.bar.create_line(S(4), S(4), S(4), h - S(4), width=S(3), capstyle="round", fill=T.line)
        self.bar.create_line(S(4), max(S(4), lo * h), S(4), min(h - S(4), hi * h), width=S(5), capstyle="round", fill=T.muted)

    def wheel(self, e):
        if self.scrollable():
            self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
            self.canvas.yview_scroll(-2 if e.delta > 0 else 2, "units")
            self.draw_bar()

    def bar_click(self, e):
        h = max(self.bar.winfo_height(), 1)
        lo, hi = self.canvas.yview()
        self.canvas.yview_moveto(min(max(e.y / h - (hi - lo) / 2, 0), 1))
        self.draw_bar()


STATE_COLORS = {"good": "#2e9d4f", "soft": "#d99a00", "toolong": "#d64545", "plain": None}


def clock(t):
    t = int(round(t))
    return "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60) if t >= 3600 else "%d:%02d" % (t // 60, t % 60)


class TrimBar(tk.Canvas):
    """The whole movie as a strip of small pictures, with a block to drag over the part you want.
    Drag the ends to change the length, drag the middle to move it, or click the strip to jump the block there."""

    GRAB = 9                                             # pixels around a handle that count as grabbing it

    def __init__(self, parent, duration, on_change, thumbs=None):
        super().__init__(parent, height=S(92), bg=T.bg, highlightthickness=0, cursor="hand2")
        self.duration, self.on_change = max(duration, 0.1), on_change
        self.start, self.end = 0.0, self.duration
        self.state = "plain"
        self.thumbs = []                                 # PhotoImages, one per slice of the movie
        self.mode = None
        self.anchor = (0.0, 0.0, 0.0)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "mode", None))
        self.bind("<Motion>", self.hover)
        if thumbs:
            self.set_thumbs(thumbs)

    def set_thumbs(self, frames, size=(96, 54)):
        self.thumbs = [tk.PhotoImage(data=b"P6 %d %d 255\n" % size + f, format="PPM") for f in frames]
        self.draw()

    def set_selection(self, start, end, state=None):
        self.start, self.end = max(0.0, start), min(self.duration, end)
        if state:
            self.state = state
        self.draw()

    # --- geometry
    def px(self, t):
        pad = S(10)
        return pad + (self.winfo_width() - 2 * pad) * t / self.duration

    def secs(self, x):
        pad = S(10)
        return min(max((x - pad) / max(self.winfo_width() - 2 * pad, 1), 0.0), 1.0) * self.duration

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 60:
            return
        top, bottom = S(20), S(68)
        x0, x1 = self.px(0), self.px(self.duration)
        self.create_rectangle(x0, top, x1, bottom, fill=T.side, outline=T.line)
        n = len(self.thumbs)
        for i, img in enumerate(self.thumbs):
            cx = x0 + (x1 - x0) * (i + 0.5) / n
            self.create_image(cx, (top + bottom) / 2, image=img)
        a, b = self.px(self.start), self.px(self.end)
        for lo, hi in ((x0, a), (b, x1)):                # the parts that are not used are dimmed
            if hi > lo:
                self.create_rectangle(lo, top, hi, bottom, fill=T.bg, outline="", stipple="gray50")
        col = STATE_COLORS.get(self.state) or T.accent
        self.create_rectangle(a, top - 2, b, bottom + 2, outline=col, width=S(3))
        for x in (a, b):
            self.create_rectangle(x - S(4), top - S(6), x + S(4), bottom + S(6), fill=col, outline=col)
        self.create_text(a, S(8), text=clock(self.start), fill=T.ink, font=("Segoe UI", 9), anchor="w" if a < x0 + S(40) else "center")
        self.create_text(b, S(8), text=clock(self.end), fill=T.ink, font=("Segoe UI", 9), anchor="e" if b > x1 - S(40) else "center")
        self.create_text(x0, S(82), text="0:00", fill=T.muted, font=("Segoe UI", 9), anchor="w")
        self.create_text(x1, S(82), text=clock(self.duration), fill=T.muted, font=("Segoe UI", 9), anchor="e")

    # --- mouse
    def where(self, x):
        a, b = self.px(self.start), self.px(self.end)
        g = S(self.GRAB)
        if abs(x - a) <= g and abs(x - a) <= abs(x - b):
            return "start"
        if abs(x - b) <= g:
            return "end"
        if a < x < b:
            return "move"
        return "jump"

    def hover(self, e):
        self.configure(cursor={"start": "sb_h_double_arrow", "end": "sb_h_double_arrow", "move": "fleur", "jump": "hand2"}[self.where(e.x)])

    def press(self, e):
        self.mode = self.where(e.x)
        if self.mode == "jump":                          # put the block's middle where it was clicked
            length = self.end - self.start
            s = min(max(self.secs(e.x) - length / 2, 0.0), self.duration - length)
            self.start, self.end = s, s + length
            self.mode = "move"
            self.anchor = (self.secs(e.x), self.start, self.end)
            self.changed()
        else:
            self.anchor = (self.secs(e.x), self.start, self.end)

    def move(self, e):
        if not self.mode:
            return
        t = self.secs(e.x)
        t0, s0, e0 = self.anchor
        if self.mode == "move":
            d = min(max(t - t0, -s0), self.duration - e0)
            self.start, self.end = s0 + d, e0 + d
        elif self.mode == "start":
            self.start = min(max(s0 + (t - t0), 0.0), self.end - 0.5)
        elif self.mode == "end":
            self.end = max(min(e0 + (t - t0), self.duration), self.start + 0.5)
        self.changed()

    def changed(self):
        self.on_change(self.start, self.end)
        self.draw()


class ProgressBar(tk.Canvas):
    """A formal progress bar: a rounded track with a filled part; or a block sliding back and forth when the length of the work isn't known."""

    def __init__(self, parent, height=10, bg=None):
        super().__init__(parent, height=S(height), bg=bg or T.bg, highlightthickness=0)
        self.value, self.color, self.busy, self.phase = 0.0, None, False, 0.0
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, value, color=None):
        self.busy = False
        self.value, self.color = min(max(value, 0.0), 1.0), color
        self.draw()

    def indeterminate(self):
        if not self.busy:
            self.busy = True
            self.tick()

    def stop(self):
        self.busy = False

    def tick(self):
        if not self.busy:
            return
        self.phase = (self.phase + 0.02) % 2.0
        self.draw()
        self.after(30, self.tick)

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        y, t = h / 2, h - 2
        self.create_line(t / 2, y, w - t / 2, y, width=t, capstyle="round", fill=T.line)
        col = self.color or T.accent
        if self.busy:
            p = self.phase if self.phase <= 1 else 2 - self.phase
            size = w * 0.25
            x0 = t / 2 + (w - size - t) * p
            self.create_line(x0, y, x0 + size, y, width=t, capstyle="round", fill=col)
        elif self.value > 0:
            self.create_line(t / 2, y, max(t / 2 + 0.5, (w - t) * self.value + t / 2), y, width=t, capstyle="round", fill=col)
