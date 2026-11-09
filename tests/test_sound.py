import ctypes
import os
import sys
import time
import unittest
from array import array
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pmfstudio import sound  # noqa: E402


class FakePulse:
    """stands in for libpulse-simple: keeps what was written, and says the sound takes 100 ms to come out"""

    def __init__(self, fail_write_after=None):
        self.written, self.flushed, self.drained, self.freed, self.opened = [], 0, 0, 0, 0
        self.fail_write_after = fail_write_after

    def pa_simple_write(self, stream, data, n, err):
        if self.fail_write_after is not None and len(self.written) >= self.fail_write_after:
            return -1
        self.written.append(bytes(data))
        time.sleep(n / 4 / sound.RATE)                          # a real server takes the sound at the speed it is played
        return 0

    def pa_simple_get_latency(self, stream, err):
        return 100000

    def pa_simple_drain(self, stream, err):
        self.drained += 1
        return 0

    def pa_simple_flush(self, stream, err):
        self.flushed += 1
        return 0

    def pa_simple_free(self, stream):
        self.freed += 1


def pcm(seconds, value=1000):
    n = int(seconds * sound.RATE)
    return (ctypes.c_char * (n * 4)).from_buffer_copy(array("h", [value] * (n * 2)).tobytes())


@unittest.skipIf(sys.byteorder != "little", "software volume is written for little-endian machines")
class PulseOutTests(unittest.TestCase):
    def make(self, fake):
        for p in (mock.patch.object(sound, "load_pulse", return_value=(fake, None)), mock.patch.object(sound, "open_stream", return_value=7)):
            p.start()
            self.addCleanup(p.stop)
        out = sound.PulseOut()
        self.addCleanup(out.close)
        fake.freed = 0                                           # the start-up probe opened and freed one stream
        return out

    def wait_end(self, out, limit=5.0):
        t = time.time()
        while out.samples() < out.end and time.time() - t < limit:
            time.sleep(0.01)

    def test_it_writes_exactly_the_sound_from_the_chosen_spot_and_reports_the_end(self):
        fake = FakePulse()
        out = self.make(fake)
        buf = pcm(0.5)
        out.play(buf, 4 * sound.RATE // 10 * 4)                 # from 0.4 s: 0.1 s are left
        self.wait_end(out)
        self.assertEqual(b"".join(fake.written), bytes(buf)[4 * sound.RATE // 10 * 4:])
        self.assertEqual(out.samples(), sound.RATE // 10 * 1)    # 0.1 s of sound played
        self.assertEqual(fake.drained, 1)
        self.assertEqual(fake.freed, 1)

    def test_the_clock_starts_at_zero_never_runs_past_the_end_and_waits_for_the_delay(self):
        fake = FakePulse()
        out = self.make(fake)
        self.assertEqual(out.samples(), 0)
        buf = pcm(3.0)
        out.play(buf, 0)
        time.sleep(0.4)
        s = out.samples()
        self.assertGreater(s, 0)
        self.assertLess(s, 0.45 * sound.RATE)                    # about 0.3 s, with the 0.1 s the server says it holds back
        out.stop()
        self.assertEqual(out.samples(), 0)

    def test_stop_discards_what_is_buffered_and_ends_the_thread(self):
        fake = FakePulse()
        out = self.make(fake)
        out.play(pcm(5.0), 0)
        time.sleep(0.1)
        out.stop()
        self.assertGreaterEqual(fake.flushed, 1)
        self.assertEqual(fake.freed, 1)
        self.assertIsNone(out.thread)

    def test_playing_again_replaces_the_sound_that_was_playing(self):
        fake = FakePulse()
        out = self.make(fake)
        out.play(pcm(5.0, 1000), 0)
        time.sleep(0.05)
        out.play(pcm(0.2, 2000), 0)
        self.wait_end(out)
        self.assertEqual(fake.freed, 2)
        last = array("h")
        last.frombytes(fake.written[-1])
        self.assertTrue(all(x == 2000 for x in last))

    def test_volume_scales_the_next_pieces_and_zero_is_silence(self):
        fake = FakePulse()
        out = self.make(fake)
        out.volume(0.5)
        out.play(pcm(0.1, 1000), 0)
        self.wait_end(out)
        a = array("h")
        a.frombytes(b"".join(fake.written))
        self.assertTrue(all(x == 500 for x in a))
        fake.written.clear()
        out.volume(0.0)
        out.play(pcm(0.1, 1000), 0)
        self.wait_end(out)
        self.assertTrue(all(b == 0 for b in b"".join(fake.written)))

    def test_a_sound_that_cannot_be_written_ends_instead_of_hanging(self):
        fake = FakePulse(fail_write_after=2)
        out = self.make(fake)
        out.play(pcm(2.0), 0)
        self.wait_end(out, limit=3)
        self.assertEqual(out.samples(), out.end)                 # reported as finished: the Player carries on without sound
        self.assertEqual(fake.freed, 1)

    def test_playing_from_the_very_end_does_nothing(self):
        fake = FakePulse()
        out = self.make(fake)
        buf = pcm(0.1)
        out.play(buf, ctypes.sizeof(buf))
        time.sleep(0.05)
        self.assertEqual(fake.written, [])
        self.assertEqual(out.samples(), 0)


class NoSoundServerTests(unittest.TestCase):
    def test_a_system_without_the_library_gives_oserror(self):
        with mock.patch.object(ctypes, "CDLL", side_effect=OSError("not found")):
            with self.assertRaises(OSError):
                sound.load_pulse()

    def test_a_server_that_refuses_gives_oserror_with_its_words(self):
        class Lib:
            def pa_simple_new(self, *a):
                return None

        class Main:
            def pa_strerror(self, code):
                return b"Connection refused"

        with self.assertRaises(OSError) as ctx:
            sound.open_stream((Lib(), Main()), sound.PA_STREAM_PLAYBACK, b"x")
        self.assertIn("Connection refused", str(ctx.exception))

    @unittest.skipIf(os.name == "nt", "Linux only")
    def test_open_output_without_a_server_is_oserror_not_a_crash(self):
        with mock.patch.dict(os.environ, {"PULSE_SERVER": "unix:/nonexistent/pulse-socket", "PULSE_RUNTIME_PATH": "/nonexistent"}):
            try:
                out = sound.open_output()
            except OSError:
                return
            out.close()                                         # a machine with a sound server reachable another way: fine too


if __name__ == "__main__":
    unittest.main()
