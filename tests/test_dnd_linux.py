"""Linux drag and drop, tried for real: a drag SOURCE written from the XDND protocol (the way file managers do it: enter, position, drop,
answer the selection request with percent-encoded file:// links) sends files to a Tk window set up by dropfiles.enable. Needs an X display
and tools/tkdnd (built by packaging/linux/build_tkdnd.sh); skipped without them."""
import ctypes
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import dropfiles  # noqa: E402

CLIENT_MESSAGE, SELECTION_REQUEST, SELECTION_NOTIFY = 33, 30, 31


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong), ("format", ctypes.c_int), ("l", ctypes.c_long * 5)]


class _SelRequest(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("owner", ctypes.c_ulong), ("requestor", ctypes.c_ulong), ("selection", ctypes.c_ulong), ("target", ctypes.c_ulong),
                ("property", ctypes.c_ulong), ("time", ctypes.c_ulong)]


class _SelNotify(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("requestor", ctypes.c_ulong), ("selection", ctypes.c_ulong), ("target", ctypes.c_ulong), ("property", ctypes.c_ulong), ("time", ctypes.c_ulong)]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("client", _ClientMessage), ("req", _SelRequest), ("notify", _SelNotify), ("pad", ctypes.c_long * 24)]


def _x11():
    x = ctypes.CDLL("libX11.so.6")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XCreateSimpleWindow.restype = ctypes.c_ulong
    x.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 2 + [ctypes.c_uint] * 3 + [ctypes.c_ulong] * 2
    x.XSetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
    x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    x.XPending.argtypes = [ctypes.c_void_p]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x


def drag(files, target_window, result, at=(50, 50)):
    """the file manager's side of a drop; fills `result` with what happened"""
    x = _x11()
    dpy = x.XOpenDisplay(None)
    atom = lambda name: x.XInternAtom(dpy, name.encode(), 0)       # noqa: E731
    s = x.XCreateSimpleWindow(dpy, x.XDefaultRootWindow(dpy), 0, 0, 10, 10, 0, 0, 0)
    uri_list, selection = atom("text/uri-list"), atom("XdndSelection")
    x.XSetSelectionOwner(dpy, selection, s, 0)
    data = "".join("file://" + quote(p) + "\r\n" for p in files).encode()

    def send(message, d0=0, d1=0, d2=0, d3=0):
        ev = _XEvent()
        ev.client = _ClientMessage(CLIENT_MESSAGE, 0, 1, None, target_window, atom(message), 32, (ctypes.c_long * 5)(s, d0, d1, d2, d3))
        x.XSendEvent(dpy, target_window, 0, 0, ctypes.byref(ev))
        x.XFlush(dpy)

    def wait_for(message, limit):
        want, ev, t = atom(message), _XEvent(), time.time()
        while time.time() - t < limit:
            while x.XPending(dpy):
                x.XNextEvent(dpy, ctypes.byref(ev))
                if ev.type == SELECTION_REQUEST:                    # the target asks for the list of files
                    r = ev.req
                    x.XChangeProperty(dpy, r.requestor, r.property, uri_list, 8, 0, data, len(data))
                    out = _XEvent()
                    out.notify = _SelNotify(SELECTION_NOTIFY, 0, 1, None, r.requestor, r.selection, r.target, r.property, r.time)
                    x.XSendEvent(dpy, r.requestor, 0, 0, ctypes.byref(out))
                    x.XFlush(dpy)
                elif ev.type == CLIENT_MESSAGE and ev.client.message_type == want:
                    return ev.client
            time.sleep(0.01)
        return None

    try:
        send("XdndEnter", 5 << 24, uri_list)
        send("XdndPosition", 0, (at[0] << 16) | at[1], 0, atom("XdndActionCopy"))
        status = wait_for("XdndStatus", 4)
        result["accepted"] = bool(status is not None and status.l[1] & 1)
        result["status"] = None if status is None else list(status.l)
        if status is None:
            return
        send("XdndDrop", 0, 0)
        result["finished"] = wait_for("XdndFinished", 6) is not None
    finally:
        x.XCloseDisplay(dpy)


def have_display():
    if os.name == "nt" or not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter
        tkinter.Tk().destroy()
        _x11()
        return True
    except Exception:
        return False


class WithoutTheLibrary(unittest.TestCase):
    def test_a_missing_library_is_a_reason_not_a_crash(self):
        with mock.patch.object(dropfiles, "tkdnd_dir", return_value=None):
            self.assertIn("missing", dropfiles.enable_tkdnd(object(), lambda f: None))

    def test_a_library_that_will_not_load_is_a_reason_not_a_crash(self):
        class Window:
            tk = mock.Mock(call=mock.Mock(side_effect=RuntimeError("can't find package tkdnd")))
        with mock.patch.object(dropfiles, "tkdnd_dir", return_value="/nowhere"):
            self.assertIn("tkdnd", dropfiles.enable_tkdnd(Window(), lambda f: None))


@unittest.skipUnless(dropfiles.tkdnd_dir(), "tools/tkdnd is not built here")
@unittest.skipUnless(have_display(), "needs an X display")
class RealDrop(unittest.TestCase):
    def setUp(self):
        import tkinter
        self.root = tkinter.Tk()
        self.root.geometry("300x200+50+50")
        self.addCleanup(self.root.destroy)
        self.got = []
        self.problem = dropfiles.enable(self.root, lambda files: self.got.append(list(files)))
        self.pump(0.8)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def drop(self, files):
        result = {}
        t = threading.Thread(target=drag, args=(files, self.root.winfo_id(), result), daemon=True)
        t.start()
        end = time.time() + 15
        while t.is_alive() and time.time() < end:
            self.pump(0.05)
        self.pump(0.5)
        return result

    def test_files_dropped_on_the_window_reach_the_program_with_their_real_names(self):
        d = tempfile.mkdtemp(prefix="José drop ")
        files = [os.path.join(d, "a movie (1).pmf"), os.path.join(d, "second.mp4"), os.path.join(d, "100% sure & more.wav")]
        self.assertIsNone(self.problem)
        r = self.drop(files)
        self.assertTrue(r.get("accepted"), r)
        self.assertTrue(r.get("finished"), r)
        self.assertEqual(self.got, [files])

    def test_a_second_drop_works_as_well(self):
        d = tempfile.mkdtemp(prefix="drop two ")
        self.drop([os.path.join(d, "one.pmf")])
        self.drop([os.path.join(d, "two.pbp")])
        self.assertEqual(self.got, [[os.path.join(d, "one.pmf")], [os.path.join(d, "two.pbp")]])


if __name__ == "__main__":
    unittest.main()
