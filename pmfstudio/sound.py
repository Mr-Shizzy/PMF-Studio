"""Sound output for the Player and the track picker.

One small object per system, with the same few calls: play(sound, from_byte), pause, stop, samples (how many samples have really been heard
since play), volume, close. Nothing to install on either system:
 - Windows: the wave-out API (winmm), through ctypes.
 - Linux: PulseAudio's "simple" library (libpulse-simple), through ctypes. PipeWire, which most current desktops use, answers the same calls.
A sound is one buffer of 16-bit stereo samples at 44,100 Hz; open_output() raises OSError when there is no way to play it."""
import ctypes
import os
import sys
import threading
import time
from array import array

RATE = 44100


# ---------------------------------------------------------------- Windows: wave-out
if os.name == "nt":
    from ctypes import wintypes

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


# ---------------------------------------------------------------- Linux: PulseAudio (simple API)
class _SampleSpec(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32), ("channels", ctypes.c_uint8)]


class _BufferAttr(ctypes.Structure):
    _fields_ = [("maxlength", ctypes.c_uint32), ("tlength", ctypes.c_uint32), ("prebuf", ctypes.c_uint32), ("minreq", ctypes.c_uint32), ("fragsize", ctypes.c_uint32)]


PA_STREAM_PLAYBACK, PA_STREAM_RECORD, PA_SAMPLE_S16LE = 1, 2, 3
_NONE = 0xFFFFFFFF                                             # "let the server choose" in a buffer attribute


def load_pulse():
    """-> (libpulse-simple, libpulse) set up for ctypes, or raises OSError when the system has no PulseAudio library"""
    last = None
    for simple, main in (("libpulse-simple.so.0", "libpulse.so.0"),):
        try:
            s, m = ctypes.CDLL(simple), ctypes.CDLL(main)
        except OSError as e:
            last = e
            continue
        s.pa_simple_new.restype = ctypes.c_void_p
        s.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
                                    ctypes.POINTER(_SampleSpec), ctypes.c_void_p, ctypes.POINTER(_BufferAttr), ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_drain.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_get_latency.restype = ctypes.c_uint64
        s.pa_simple_get_latency.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        s.pa_simple_free.argtypes = [ctypes.c_void_p]
        m.pa_strerror.restype = ctypes.c_char_p
        m.pa_strerror.argtypes = [ctypes.c_int]
        return s, m
    raise OSError("no PulseAudio library: %s" % last)


def open_stream(lib, direction, name, device=None, latency=0.2):
    """-> a pa_simple stream of 16-bit stereo at RATE, or raises OSError with the sound server's own words"""
    s, m = lib
    spec = _SampleSpec(PA_SAMPLE_S16LE, RATE, 2)
    byte_rate = RATE * 4
    if direction == PA_STREAM_PLAYBACK:
        attr = _BufferAttr(_NONE, int(byte_rate * latency), _NONE, _NONE, _NONE)     # a short buffer: volume changes and seeking come quickly
    else:
        attr = _BufferAttr(_NONE, _NONE, _NONE, _NONE, int(byte_rate * 0.05))
    err = ctypes.c_int(0)
    h = s.pa_simple_new(None, b"PMF Studio", direction, device, name, ctypes.byref(spec), None, ctypes.byref(attr), ctypes.byref(err))
    if not h:
        raise OSError("sound server: %s" % m.pa_strerror(err.value).decode("utf-8", "replace"))
    return h


class PulseOut:
    """The same calls as WaveOut. A thread feeds the sound to the server in small pieces, and samples() is what has come out of the speakers:
    what was written minus the delay the server reports for it (smoothed between two reports by the clock)."""
    CHUNK = 1024                                                 # frames (23 ms) written at a time

    def __init__(self):
        self.lib = load_pulse()
        probe = open_stream(self.lib, PA_STREAM_PLAYBACK, b"Player")          # proves a sound server is there; the real stream opens at play()
        self.lib[0].pa_simple_free(probe)
        self.lock = threading.Lock()
        self.thread = None
        self.stop_flag = threading.Event()
        self.vol = 1.0
        self.buf = None
        self.base = 0.0                                          # frames heard at the moment `stamp`
        self.stamp = 0.0
        self.end = 0                                             # frames in this play
        self.running = False                                     # data is flowing (the clock may interpolate)
        self.finished = False
        self.buffering = False

    # ---- the thread
    def _feed(self, stop, address, first, frames):
        s = self.lib[0]
        err = ctypes.c_int(0)
        try:
            stream = open_stream(self.lib, PA_STREAM_PLAYBACK, b"Player")
        except OSError:
            with self.lock:
                self.finished = True
            return
        try:
            done = 0
            self.stamp = time.perf_counter()
            while done < frames and not stop.is_set():
                n = min(self.CHUNK, frames - done)
                data = ctypes.string_at(address + (first + done) * 4, n * 4)
                v = self.vol
                if v < 0.999 and sys.byteorder == "little":
                    a = array("h")
                    a.frombytes(data)
                    data = array("h", [int(x * v) for x in a]).tobytes()
                elif v < 0.999:
                    data = bytes(len(data))
                if s.pa_simple_write(stream, data, len(data), ctypes.byref(err)) < 0:
                    break
                done += n
                lat = s.pa_simple_get_latency(stream, ctypes.byref(err))
                lat = 0 if lat >= 1 << 62 else lat                                # an error comes back as -1
                heard = max(0.0, done - lat * RATE / 1e6)
                with self.lock:
                    if not stop.is_set():
                        self.base, self.stamp, self.running = heard, time.perf_counter(), True
            if not stop.is_set() and done >= frames:
                s.pa_simple_drain(stream, ctypes.byref(err))                       # waits until the last sound has been heard
                with self.lock:
                    if not stop.is_set():
                        self.base, self.running, self.finished = float(frames), False, True
            elif not stop.is_set():
                with self.lock:
                    self.running, self.finished = False, True
        finally:
            if stop.is_set():
                s.pa_simple_flush(stream, ctypes.byref(err))
            s.pa_simple_free(stream)

    # ---- the calls
    def play(self, buf, offset=0):
        """buf: a ctypes buffer holding all the 16-bit stereo sound; starts at byte `offset`"""
        self.stop()
        total = ctypes.sizeof(buf) // 4
        first = max(0, min(offset // 4, total))
        if total - first < 1:
            return
        self.buf = buf
        stop = threading.Event()
        with self.lock:
            self.stop_flag, self.base, self.stamp, self.end = stop, 0.0, time.perf_counter(), total - first
            self.running = self.finished = False
        self.thread = threading.Thread(target=self._feed, args=(stop, ctypes.addressof(buf), first, total - first), daemon=True)
        self.thread.start()

    def pause(self):
        self.stop()

    def stop(self):
        self.stop_flag.set()
        t, self.thread = self.thread, None
        if t is not None and t is not threading.current_thread():
            t.join(2.0)
        with self.lock:
            self.running = self.finished = False
            self.base = 0.0

    def samples(self):
        with self.lock:
            if self.finished:
                return self.end
            if not self.running:
                return int(self.base)
            heard = self.base + (time.perf_counter() - self.stamp) * RATE
            return int(max(0.0, min(heard, self.end)))

    def volume(self, v):
        """0.0 to 1.0: used on the next piece written, about a fifth of a second from now"""
        self.vol = max(0.0, min(1.0, v))

    def close(self):
        self.stop()


def open_output():
    """the sound output of this system, or OSError when there is none"""
    if os.name == "nt":
        return WaveOut()
    return PulseOut()
