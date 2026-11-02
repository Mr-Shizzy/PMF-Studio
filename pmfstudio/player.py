"""The Player page: plays a PMF (or any video or sound) inside the window, or full screen.

A PMF is split with pmfkit's own reader: the picture goes to ffmpeg as a plain H.264 stream and the ATRAC3plus sound is wrapped as an AT3
file that ffmpeg decodes. Sound is played straight through the Windows wave-out API (ctypes, nothing to install), which gives an exact
clock for the picture, instant volume changes and instant seeking. Pictures come back from ffmpeg as raw frames shown in a Label.
While the timeline is dragged, small preview pictures (made once, in the background) follow the knob.
"""
import ctypes
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import filedialog

from .theme import S
from .widgets import IconButton, ProgressBar, Slider
from pmfkit import atrac3p, snd0
from pmfkit.demux import demux, duration_seconds
from pmfkit.toolinfo import passthrough_args
from pmfkit.h264 import split_access_units, _nal_spans

FPS = 30000 / 1001
RATE = 44100
NOWND = 0x08000000                                       # CREATE_NO_WINDOW


# ---------------------------------------------------------------- sound (Windows wave-out)
class _WaveFormat(ctypes.Structure):
    _fields_ = [("tag", wintypes.WORD), ("channels", wintypes.WORD), ("rate", wintypes.DWORD), ("bytes_per_sec", wintypes.DWORD),
                ("align", wintypes.WORD), ("bits", wintypes.WORD), ("extra", wintypes.WORD)]


class _WaveHeader(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("length", wintypes.DWORD), ("recorded", wintypes.DWORD), ("user", ctypes.c_void_p),
                ("flags", wintypes.DWORD), ("loops", wintypes.DWORD), ("next", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]


class _MMTime(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("kind", ctypes.c_uint), ("value", ctypes.c_uint), ("pad", ctypes.c_uint)]


class WaveOut:
    """One output stream: play(sound, from_byte), pause, reset, volume, and how many samples have been played."""

    def __init__(self):
        self.lib = ctypes.WinDLL("winmm")
        self.lib.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.POINTER(_WaveFormat), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        for name in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
            getattr(self.lib, name).argtypes = [ctypes.c_void_p, ctypes.POINTER(_WaveHeader), ctypes.c_uint]
        for name in ("waveOutReset", "waveOutPause", "waveOutRestart", "waveOutClose"):
            getattr(self.lib, name).argtypes = [ctypes.c_void_p]
        self.lib.waveOutSetVolume.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.lib.waveOutGetVolume.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        self.lib.waveOutGetPosition.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MMTime), ctypes.c_uint]
        fmt = _WaveFormat(1, 2, RATE, RATE * 4, 4, 16, 0)
        self.h = ctypes.c_void_p()
        if self.lib.waveOutOpen(ctypes.byref(self.h), 0xFFFFFFFF, ctypes.byref(fmt), None, None, 0):
            raise OSError("no sound device")
        self.hdr = None
        self.buf = None

    def _release(self):
        if self.hdr is not None:
            self.lib.waveOutReset(self.h)
            self.lib.waveOutUnprepareHeader(self.h, ctypes.byref(self.hdr), ctypes.sizeof(self.hdr))
            self.hdr = None

    def play(self, buf, offset=0):
        """buf: a ctypes buffer holding all the 16-bit stereo sound; starts at byte `offset` (a multiple of 4)"""
        self._release()
        total = ctypes.sizeof(buf)
        offset = max(0, min(offset, total)) // 4 * 4
        if total - offset < 4:
            return
        self.buf = buf
        self.hdr = _WaveHeader(ctypes.addressof(buf) + offset, total - offset)
        self.lib.waveOutPrepareHeader(self.h, ctypes.byref(self.hdr), ctypes.sizeof(self.hdr))
        self.lib.waveOutRestart(self.h)
        self.lib.waveOutWrite(self.h, ctypes.byref(self.hdr), ctypes.sizeof(self.hdr))

    def pause(self):
        self.lib.waveOutPause(self.h)

    def stop(self):
        self._release()

    def samples(self):
        t = _MMTime(2)                                       # TIME_SAMPLES
        if self.lib.waveOutGetPosition(self.h, ctypes.byref(t), ctypes.sizeof(t)) or t.kind != 2:
            return 0
        return t.value

    def volume(self, v):
        """0.0 to 1.0, takes effect straight away"""
        level = int(max(0.0, min(1.0, v)) * 0xFFFF)
        self.lib.waveOutSetVolume(self.h, level | (level << 16))

    def close(self):
        self._release()
        self.lib.waveOutClose(self.h)


# ---------------------------------------------------------------- the page
class Player:
    PREVIEW_MAX = 300                                        # most preview pictures kept for scrubbing

    def __init__(self, parent, ffmpeg, theme, scale, font):
        self.ffmpeg, self.T, self.font = ffmpeg, theme, font
        self.w = int(480 * max(1.0, min(scale, 1.5))) // 2 * 2
        self.h = int(self.w * 272 / 480) // 2 * 2
        self.vw, self.vh, self.vz = self.w, self.h, 1         # size the picture is decoded at, and how much it is enlarged on screen
        self.work = tempfile.mkdtemp(prefix="player_")
        self.src_video = self.src_audio = None
        self.has_video = self.has_audio = False
        self.video_args = []
        self.duration = 0.0
        self.pos = 0.0
        self.playing = self.seeking = self.was_playing = False
        self.proc = None
        self.frames = queue.Queue(maxsize=60)
        self.gen = self.vgen = 0
        self.t0 = self.start_at = self.startpos = 0.0
        self.next_index = 0
        self.video_done = False
        self.sound_running = False
        self.pcm = None
        self.pcm_seconds = 0.0
        self.last_audio_t = self.last_wall = 0.0
        self.image = None
        self.thumbs, self.thumb_step, self.thumb_size = [], 1.0, (self.w // 2, self.h // 2)
        self.thumb_job = self.fs_job = 0
        self.fs_thumbs, self.fs_step = [], 1.0
        self.zcache = {}                                       # enlarged preview pictures already made, so dragging back over them is free
        self.last_still = None
        self.scrub_value, self.scrub_job = None, None
        self.volume, self.muted = 0.8, False
        self.es, self.keyframes, self.headers = b"", [], b""
        self.starting = False
        self.start_deadline = 0.0
        self.fs = self.fs_slider = None
        self.root = parent.winfo_toplevel()
        try:
            self.audio = WaveOut()
        except (OSError, AttributeError):
            self.audio = None
        T = theme
        self.name = tk.Label(parent, text="No file chosen yet.", bg=T.bg, fg=T.muted, font=(font, 10), anchor="w")
        self.name.pack(fill="x", pady=(0, 8))
        self.busy_box = tk.Frame(parent, bg=T.bg)                # shown only while a file is being opened
        self.busy_label = tk.Label(self.busy_box, text="", bg=T.bg, fg=T.muted, font=(font, 10), anchor="w")
        self.busy_label.pack(fill="x")
        self.busy_bar = ProgressBar(self.busy_box, height=6)
        self.busy_bar.pack(fill="x", pady=(2, 8))
        self.closed = False
        frame = tk.Frame(parent, bg="#000000", width=self.w, height=self.h)
        frame.pack()
        frame.pack_propagate(False)
        self.screen = tk.Label(frame, bg="#000000", bd=0)
        self.screen.place(relx=0.5, rely=0.5, anchor="center")
        self.target = self.screen
        self.slider = Slider(parent, from_=0, to=1, value=0, command=self.scrub, on_release=self.seek_release, length=self.w)
        self.slider.pack(fill="x", pady=(12, 0))
        bar = tk.Frame(parent, bg=T.bg)
        bar.pack(fill="x", pady=(4, 0))
        self.play_btn = IconButton(bar, "play", self.toggle, size=44, filled=True)
        self.play_btn.pack(side="left")
        IconButton(bar, "stop", self.stop, size=36).pack(side="left", padx=(8, 0))
        self.time = tk.Label(bar, text="0:00 / 0:00", bg=T.bg, fg=T.muted, font=(font, 10), anchor="w")
        self.time.pack(side="left", padx=14)
        IconButton(bar, "fullscreen", self.enter_fullscreen, size=36).pack(side="right", padx=(8, 0))
        self.vol = Slider(bar, from_=0, to=100, value=80, command=self.volume_changed, length=int(100 * max(scale, 1.0)))
        self.vol.pack(side="right", padx=(4, 0))
        self.speaker = IconButton(bar, "speaker", self.toggle_mute, size=36)
        self.speaker.pack(side="right")
        self.apply_volume()

    # ---------- opening a file: a progress bar, redrawn while the sound is read ----------
    def show_busy(self, text):
        self.busy_label.configure(text=text)
        self.busy_bar.set(0)
        self.busy_box.pack(fill="x", before=self.screen.master)
        self.root.update_idletasks()

    def set_busy(self, fraction, text=None):
        if self.closed:
            return
        if text:
            self.busy_label.configure(text=text)
        self.busy_bar.set(fraction)
        self.root.update_idletasks()                           # repaint only: clicks wait until the file is open

    def hide_busy(self):
        if not self.closed:
            self.busy_box.pack_forget()

    # ---------- loading ----------
    def choose(self):
        p = filedialog.askopenfilename(filetypes=[("PSP movies and sounds", "*.pmf *.at3 *.mp4 *.mkv *.avi *.mov *.webm *.wav *.mp3 *.flac *.ogg"), ("All files", "*.*")])
        if p:
            self.load(p)

    def load(self, path):
        self.stop()
        self.thumb_job += 1
        self.thumbs = []
        self.zcache.clear()
        self.last_still = None
        self.show_busy("Opening the file\u2026")
        try:
            if path.lower().endswith(".pmf"):
                self.load_pmf(path)
            else:
                self.load_other(path)
            self.set_busy(0.1, "Reading the sound\u2026")
            self.load_sound()
        except Exception as e:
            self.name.configure(text="Couldn't open that file: %s" % e, fg="#b3261e")
            self.duration = 0
            return
        finally:
            self.hide_busy()
        self.name.configure(text=os.path.basename(path) + ("" if self.has_video else "   (sound only)"), fg=self.T.ink)
        self.slider.range(max(self.duration, 0.1))
        self.exit_fullscreen()
        self.show_time(0)
        if self.has_video:
            threading.Thread(target=self.build_previews, args=(self.thumb_job,), daemon=True).start()
        self.toggle()

    def load_pmf(self, path):
        P, v, a, plist = demux(open(path, "rb").read())
        self.src_video = os.path.join(self.work, "video.264")
        open(self.src_video, "wb").write(v)
        self.index_keyframes(v)
        self.has_video = True
        self.video_args = ["-f", "h264", "-r", "30000/1001"]
        self.has_audio = bool(a)
        self.src_audio = None
        if a:
            st = atrac3p.from_units(a)
            self.src_audio = os.path.join(self.work, "audio.at3")
            open(self.src_audio, "wb").write(snd0.build(st.frames, st.frame_bytes, loop=False))
        self.duration = duration_seconds(v, a)

    def index_keyframes(self, es):
        """where each keyframe starts in the picture stream, so a jump can begin there instead of decoding from the very start"""
        self.es, self.keyframes, self.headers = es, [], b""
        try:
            aus = split_access_units(es, strip_x264_sei=False)
        except ValueError:
            return                                              # an unusual stream: seeking falls back to decoding from the start
        off = 0
        for i, au in enumerate(aus):
            if au.is_idr:
                self.keyframes.append((i / FPS, off))
            off += len(au.data)
        if off != len(es):
            self.keyframes = []
            return
        first = aus[0].data
        spans = _nal_spans(first)
        ends = [s[0] for s in spans[1:]] + [len(first)]
        self.headers = b"".join(first[b:e] for (b, t), e in zip(spans, ends) if t in (7, 8))      # the parameter sets every start needs

    def load_other(self, path):
        r = subprocess.run([self.ffmpeg, "-hide_banner", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWND)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stdout)
        if not m:
            raise ValueError("not a movie or sound")
        self.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        self.has_video = bool(re.search(r"Stream #.*Video:(?!.*attached pic)", r.stdout))
        self.has_audio = "Audio:" in r.stdout
        self.src_video = path
        self.src_audio = path
        self.video_args = []
        self.keyframes = []

    def load_sound(self):
        """decode all the sound once; after that, seeking and volume are instant"""
        self.pcm, self.pcm_seconds = None, 0.0
        if not (self.has_audio and self.audio and self.src_audio):
            return
        proc = subprocess.Popen([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", self.src_audio, "-vn", "-ac", "2", "-ar", str(RATE), "-f", "s16le", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWND)
        expected = max(1, int(self.duration * RATE * 4))
        parts, got = [], 0
        while True:
            chunk = proc.stdout.read(1 << 20)
            if not chunk:
                break
            parts.append(chunk)
            got += len(chunk)
            self.set_busy(0.1 + 0.85 * min(1.0, got / expected))
            if self.closed:
                proc.kill()
                return
        proc.wait()
        r = type("R", (), {"stdout": b"".join(parts)})
        if len(r.stdout) >= 4:
            data = r.stdout[:len(r.stdout) // 4 * 4]
            self.pcm = (ctypes.c_char * len(data)).from_buffer_copy(data)
            self.pcm_seconds = len(data) / (RATE * 4)

    def build_previews(self, job, big=False):
        """pictures spread over the whole movie, so dragging the timeline can show where you are (a bigger set is made for full screen)"""
        pw, ph = ((480, 272) if big else self.thumb_size)
        per_sec = min(10.0, (self.PREVIEW_MAX * (2 / 3 if big else 1)) / max(self.duration, 1.0))
        raw = bool(self.video_args)
        if raw:
            k = max(1, round(FPS / per_sec))
            step = k / FPS
            sel = "select='not(mod(n,%d))'," % k
            tail = passthrough_args(self.ffmpeg)
        else:
            step = 1.0 / per_sec
            sel = "fps=%.4f," % per_sec
            tail = []
        vf = sel + "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (pw, ph, pw, ph)
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + self.video_args + ["-i", self.src_video, "-an", "-vf", vf] + tail + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWND)
        size = pw * ph * 3
        frames = []
        live = (lambda: job == self.fs_job) if big else (lambda: job == self.thumb_job)
        while live():
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            frames.append(buf)
            if len(frames) % 8 == 0 or len(frames) < 8:
                self.store_previews(big, frames, step)           # grows while it is being made: scrubbing works at once
        if live():
            self.store_previews(big, frames, step)
        try:
            proc.kill()
        except OSError:
            pass

    def store_previews(self, big, frames, step):
        if big:
            self.fs_thumbs, self.fs_step = frames, step
        else:
            self.thumbs, self.thumb_step = frames, step

    # ---------- clock ----------
    def now(self):
        if self.pcm and self.audio and self.sound_running:
            t = self.start_at + self.audio.samples() / RATE
            if t < self.pcm_seconds - 0.05:
                self.last_audio_t, self.last_wall = t, time.perf_counter()
                return t
            return self.last_audio_t + (time.perf_counter() - self.last_wall)       # the sound ended first: carry on by the wall clock
        return time.perf_counter() - self.t0

    # ---------- playing ----------
    def toggle(self):
        if not (self.src_video or self.src_audio):
            self.choose()
            return
        if self.playing:
            self.pause()
        else:
            if self.pos >= self.duration - 0.2:
                self.pos = 0
            self.start(self.pos)

    def start(self, at):
        self.last_still = None
        self.halt()
        self.gen += 1
        gen = self.gen
        at = max(0.0, min(at, max(self.duration - 0.05, 0.0)))
        self.pos = self.start_at = at
        self.t0 = time.perf_counter() - at
        self.start_video(at)
        self.playing = True
        self.set_play_icon("pause")
        if self.fs and self.fs_bar.winfo_viewable() and self.fs_hide_job is None:
            self.fs_hide_job = self.root.after(2500, self.fs_hide)
        if self.has_video and self.src_video:
            self.starting = True                                   # the sound waits for the first picture, so they begin together
            self.start_deadline = time.perf_counter() + 2.0
        else:
            self.begin_sound(at)
        self.root.after(5, lambda: self.loop(gen))

    def begin_sound(self, at):
        self.starting = False
        self.t0 = time.perf_counter() - at
        self.last_audio_t, self.last_wall = at, time.perf_counter()
        if self.pcm and self.audio:
            self.audio.play(self.pcm, int(at * RATE) * 4)
            self.sound_running = True
            self.apply_volume()

    def start_video(self, at):
        self.halt_video()
        self.video_done = False
        self.startpos = at
        self.next_index = 0
        self.frames = queue.Queue(maxsize=60)
        if not self.has_video:
            return
        raw = bool(self.video_args)
        vf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (self.vw, self.vh, self.vw, self.vh)
        size = self.vw * self.vh * 3
        if raw and self.keyframes:
            # start at the keyframe just before the spot, so only a moment of pictures is decoded and thrown away
            kt, off = max((k for k in self.keyframes if k[0] <= at + 0.001), default=self.keyframes[0])
            skip = max(0, round((at - kt) * FPS))
            self.startpos = kt + skip / FPS
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + self.video_args + ["-i", "pipe:0"] + (["-ss", "%.4f" % (skip / FPS)] if skip else []) + [
                   "-an", "-vf", vf, *passthrough_args(self.ffmpeg), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWND)
            threading.Thread(target=self.feed, args=(self.proc, off, self.vgen), daemon=True).start()
        else:
            if not raw:
                vf += ",fps=30000/1001"                          # a PMF stream already runs at one picture per step; re-timing it can invent thousands of frames
            seek = ["-ss", "%.3f" % at] if at else []
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + ([] if raw else seek) + self.video_args + ["-i", self.src_video] + (seek if raw else []) + [
                   "-an", "-vf", vf] + (passthrough_args(self.ffmpeg) if raw else []) + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWND)
        threading.Thread(target=self.read_frames, args=(self.proc, self.frames, self.vgen, size), daemon=True).start()

    def feed(self, proc, off, vgen):
        """push the picture stream, from the keyframe at `off`, into ffmpeg"""
        try:
            if off:
                proc.stdin.write(self.headers)                  # parameter sets only sit at the very start of some streams
            view = memoryview(self.es)[off:]
            for i in range(0, len(view), 1 << 16):
                if vgen != self.vgen:
                    break
                proc.stdin.write(view[i:i + (1 << 16)])
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def read_frames(self, proc, q, vgen, size):
        while vgen == self.vgen:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            q.put(buf)
        q.put(None)

    def loop(self, gen):
        if gen != self.gen or not self.playing:
            return
        if self.starting:
            if not self.frames.empty() or self.video_done or time.perf_counter() > self.start_deadline:
                self.begin_sound(self.start_at)
            else:
                self.root.after(5, lambda: self.loop(gen))
                return
        t = self.now()
        self.pos = t
        shown = None
        while not self.video_done:
            if self.startpos + self.next_index / FPS > t:
                break
            try:
                f = self.frames.get_nowait()
            except queue.Empty:
                break
            if f is None:
                self.video_done = True
                break
            shown = f
            self.next_index += 1
        if shown is not None:
            self.paint(shown, self.vw, self.vh, self.vz)
        if (t >= self.duration - 0.05 and (self.video_done or not self.has_video)) or t > self.duration + 1:
            self.finish()
            return
        self.show_time(min(t, self.duration))
        self.root.after(15, lambda: self.loop(gen))

    def set_play_icon(self, icon):
        self.play_btn.set_icon(icon)
        if self.fs_slider:
            self.fs_play.set_icon(icon)

    def paint(self, data, w, h, zoom):
        img = tk.PhotoImage(data=b"P6 %d %d 255\n" % (w, h) + data, format="PPM")
        if zoom > 1:
            img = img.zoom(zoom)
        self.image = img
        try:
            self.target.configure(image=img)
        except tk.TclError:
            pass                                              # the full-screen window was closed a moment ago

    def halt_video(self):
        self.vgen += 1
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None

    def halt(self):
        self.starting = False
        self.gen += 1
        self.halt_video()
        if self.audio:
            self.audio.stop()
        self.sound_running = False

    def finish(self):
        self.halt()
        self.playing = False
        self.pos = 0
        self.set_play_icon("play")
        self.show_time(0)
        self.fs_show(keep=True)                                 # in full screen the controls come up and stay, so the last picture doesn't look frozen

    def pause(self):
        self.pos = self.now()
        self.halt()
        self.playing = False
        self.set_play_icon("play")

    def stop(self):
        self.halt()
        self.playing = False
        self.pos = 0
        if hasattr(self, "play_btn"):
            self.set_play_icon("play")
            self.show_time(0)

    # ---------- timeline ----------
    def scrub(self, value):
        """the knob is being dragged: pause, and show the picture at that spot as it moves"""
        if not self.seeking:
            self.seeking = True
            self.was_playing = self.playing
            if self.playing:
                self.pause()
        self.pos = value
        self.set_time_text(self.stamp(value))
        self.scrub_value = value
        if self.scrub_job is None:                             # many mouse moves arrive faster than pictures can be drawn: draw the newest only
            self.scrub_job = self.root.after(16, self.scrub_paint)

    def scrub_paint(self):
        self.scrub_job = None
        if self.scrub_value is not None and self.seeking:
            self.show_still(self.scrub_value)

    def seek_release(self, value):
        self.seeking = False
        self.scrub_value = None
        if not (self.src_video or self.src_audio):
            return
        self.pos = float(value)
        if self.was_playing:
            self.start(self.pos)

    def still_set(self):
        """(pictures, their size, seconds between them, enlargement): the big set in full screen once it is ready, else the small one"""
        if self.fs and self.fs_thumbs:
            size = (480, 272)
            return self.fs_thumbs, size, self.fs_step, max(1, (self.vw * self.vz) // size[0])
        pw, ph = self.thumb_size
        return self.thumbs, (pw, ph), self.thumb_step, max(1, (self.vw * self.vz) // pw)

    def show_still(self, t):
        frames, size, step, zoom = self.still_set()
        if not frames or not self.has_video:
            return
        i = min(int(t / step + 0.5), len(frames) - 1)
        key = (id(frames), i, zoom)
        if key == self.last_still:
            return                                             # the same picture is already showing
        img = self.zcache.get(key)
        if img is None:
            img = tk.PhotoImage(data=b"P6 %d %d 255\n" % size + frames[i], format="PPM")
            if zoom > 1:
                img = img.zoom(zoom)
            if len(self.zcache) > 40:
                self.zcache.pop(next(iter(self.zcache)))
            self.zcache[key] = img
        self.last_still = key
        self.image = img
        try:
            self.target.configure(image=img)
        except tk.TclError:
            pass

    def stamp(self, t):
        def f(x):
            return "%d:%02d" % (int(x) // 60, int(x) % 60)
        return "%s / %s" % (f(t), f(self.duration))

    def show_time(self, t):
        if not self.seeking:
            self.set_time_text(self.stamp(t))
            self.slider.set(t)
            if self.fs_slider:
                self.fs_slider.set(t)

    def set_time_text(self, text):
        self.time.configure(text=text)
        if self.fs_slider:
            self.fs_time.configure(text=text)

    # ---------- volume ----------
    def apply_volume(self):
        if self.audio:
            self.audio.volume(0.0 if self.muted else self.volume ** 2)      # squared: the middle of the slider feels like half as loud

    def volume_changed(self, value=None):
        self.volume = float(self.vol.value) / 100
        self.muted = self.volume == 0
        self.draw_speaker()
        self.apply_volume()

    def toggle_mute(self, e=None):
        self.muted = not self.muted
        if not self.muted and self.volume == 0:
            self.vol.set(50, notify=True)
            return
        self.draw_speaker()
        self.apply_volume()

    def draw_speaker(self):
        icon = "muted" if self.muted else "speaker" if self.volume > 0.5 else "speaker-low"
        self.speaker.set_icon(icon)
        if self.fs_slider:
            self.fs_speaker.set_icon(icon)

    # ---------- full screen ----------
    DARK = "#141414"
    BAR_OPACITY = 0.78                                         # how solid the control bar is over the picture

    def enter_fullscreen(self):
        if self.fs or not self.has_video:
            return
        top = tk.Toplevel(self.root)
        top.configure(bg="#000000")
        top.attributes("-fullscreen", True)
        top.attributes("-topmost", True)
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        zoom = 2 if sw <= 2200 else 4
        label = tk.Label(top, bg="#000000", bd=0)
        label.place(relx=0.5, rely=0.5, anchor="center")
        label.bind("<Button-1>", lambda e: self.toggle())
        label.bind("<Double-Button-1>", self.exit_fullscreen)
        top.bind("<Escape>", self.exit_fullscreen)
        top.bind("<space>", lambda e: self.toggle())
        top.bind("<Left>", lambda e: self.skip(-5))
        top.bind("<Right>", lambda e: self.skip(5))
        # the control bar appears when the mouse moves and goes away again when it rests
        D, W = self.DARK, "#ffffff"
        bar = tk.Toplevel(top)                                   # a window of its own, so the whole bar can be semi-transparent
        bar.withdraw()
        bar.overrideredirect(True)
        bar.configure(bg=D)
        bar.attributes("-topmost", True)
        bar.attributes("-alpha", self.BAR_OPACITY)
        self.fs_slider = Slider(bar, from_=0, to=max(self.duration, 0.1), value=min(self.pos, self.duration), command=self.scrub, on_release=self.seek_release, bg=D)
        self.fs_slider.pack(fill="x", padx=S(18), pady=(S(12), 0))
        row = tk.Frame(bar, bg=D)
        row.pack(fill="x", padx=S(14), pady=(0, S(10)))
        self.fs_play = IconButton(row, "pause" if self.playing else "play", self.toggle, size=40, fg=W, hover_bg="#2c2c2c", bg=D)
        self.fs_play.pack(side="left")
        self.fs_time = tk.Label(row, text=self.stamp(self.pos), bg=D, fg="#d0d0d0", font=(self.font, 11))
        self.fs_time.pack(side="left", padx=12)
        IconButton(row, "unfullscreen", self.exit_fullscreen, size=40, fg=W, hover_bg="#2c2c2c", bg=D).pack(side="right")
        self.fs_vol = Slider(row, from_=0, to=100, value=self.vol.value, command=lambda v: self.vol.set(v, notify=True), length=S(110), bg=D)
        self.fs_vol.pack(side="right", padx=(0, 6))
        self.fs_speaker = IconButton(row, "muted" if self.muted else "speaker", self.toggle_mute, size=40, fg=W, hover_bg="#2c2c2c", bg=D)
        self.fs_speaker.pack(side="right")
        bar.update_idletasks()
        self.fs_bar, self.fs_hide_job = bar, None
        self.fs_bar_h = bar.winfo_reqheight()
        self.fs_screen = (sw, sh)
        for win in (top, bar):
            win.bind("<Motion>", self.fs_wake)
        for key, fn in (("<Escape>", self.exit_fullscreen), ("<space>", lambda e: self.toggle()), ("<Left>", lambda e: self.skip(-5)), ("<Right>", lambda e: self.skip(5))):
            bar.bind(key, fn)
        self.fs, self.target = top, label
        self.vw, self.vh, self.vz = sw // zoom // 2 * 2, sh // zoom // 2 * 2, zoom
        top.configure(cursor="none")
        top.focus_force()
        self.fs_job += 1
        self.zcache.clear()
        self.last_still = None
        self.fs_pointer = None
        threading.Thread(target=self.build_previews, args=(self.fs_job, True), daemon=True).start()
        self.retarget()

    def fs_wake(self, e=None):
        """the mouse moved: show the controls and the pointer, and hide them again after a moment"""
        if not self.fs:
            return
        if e is not None:                                       # ignore the pointer simply being there: only a real movement counts
            here = (e.x_root, e.y_root)
            last, self.fs_pointer = self.fs_pointer, here
            if last is None or abs(here[0] - last[0]) + abs(here[1] - last[1]) < 4:
                return
        self.fs_show()

    def fs_show(self, keep=False):
        """show the controls and the pointer; they go away after a moment, unless `keep` (the movie has ended, so they stay)"""
        if not self.fs:
            return
        sw, sh = self.fs_screen
        self.fs_bar.geometry("%dx%d+0+%d" % (sw, self.fs_bar_h, sh - self.fs_bar_h))
        self.fs_bar.deiconify()
        self.fs_bar.lift()
        self.fs.configure(cursor="")
        if self.fs_hide_job:
            self.root.after_cancel(self.fs_hide_job)
            self.fs_hide_job = None
        if not keep:
            self.fs_hide_job = self.root.after(2500, self.fs_hide)

    def fs_hide(self):
        self.fs_hide_job = None
        if not self.fs:
            return
        over_bar = self.fs.winfo_pointery() >= self.fs_screen[1] - self.fs_bar_h
        if over_bar or self.seeking or self.fs_slider.drag or self.fs_vol.drag:
            self.fs_hide_job = self.root.after(1000, self.fs_hide)
            return
        self.fs_bar.withdraw()
        self.fs.configure(cursor="none")

    def exit_fullscreen(self, e=None):
        top = self.fs
        if not top:
            return
        if self.fs_hide_job:
            self.root.after_cancel(self.fs_hide_job)
            self.fs_hide_job = None
        self.fs = self.fs_slider = None
        self.fs_job += 1
        self.fs_thumbs = []
        self.zcache.clear()
        self.last_still = None
        self.target = self.screen                          # pictures go back to the page before the full-screen window goes away
        self.vw, self.vh, self.vz = self.w, self.h, 1
        try:
            top.attributes("-topmost", False)
            top.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        top.destroy()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.retarget()

    def retarget(self):
        """the picture size changed: carry on from the same spot at the new size"""
        if self.playing:
            self.start_video(self.now())
        else:
            self.show_still(self.pos)

    def skip(self, seconds):
        t = max(0.0, min((self.now() if self.playing else self.pos) + seconds, self.duration))
        if self.playing:
            self.start(t)
        else:
            self.pos = t
            self.show_still(t)

    def close(self):
        self.closed = True
        self.thumb_job += 1
        self.exit_fullscreen()
        self.halt()
        if self.audio:
            self.audio.close()
            self.audio = None
