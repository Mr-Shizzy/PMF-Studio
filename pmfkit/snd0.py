"""SND0.AT3 (XMB background sound) = ATRAC3plus frames in a RIFF/WAVE wrapper. EXPERIMENTAL: layout taken from
psp-media-toolkit's FINDINGS.md (see RESEARCH_NOTES section 30), not yet confirmed on our own hardware.

fmt  (52 bytes) WAVE_FORMAT_EXTENSIBLE, 2 ch, 44100 Hz, blockAlign = frame bytes, 2048 samples per block,
                ATRAC3plus GUID, then `01 00 28 XX 00..` with XX = frame_bytes / 8 - 1  (this is the same 0x28XX word
                as in the PMF audio unit header)
fact (8 bytes)  total samples, encoder delay.  Rule that decides sound/silence on a real PSP:
                samples + delay + 368 <= frames * 2048
smpl (60 bytes) one forward loop from `delay` to `delay + samples - 1` (needs `fact` too, else silent)
data            the raw frames
"""
import struct

SAMPLES_PER_FRAME = 2048
TAIL_MARGIN = 368
ATRAC3P_GUID = bytes.fromhex("bfaa23e958cb7144a119fffa01e4ce62")      # E923AABF-CB58-4471-A119-FFFA01E4CE62
DEFAULT_DELAY = 2048
# No length cap: 63 s at 64 kbps and 84 s at 48 kbps played on hardware (notes section 53); only the byte budget below matters.
# XMB rule (notes sections 47-49, hardware-verified): ICON1.PMF + SND0.AT3 together must be at most 512,000 bytes
# (500 KiB). Up to that the SND0 plays and silences the sound inside ICON1; over it the SND0 is NOT played at all and
# the ICON1's own sound is heard instead. Checked with two icon sizes (100,352 B and 251,904 B): the SND0 played at a
# combined 511,860 / 511,884 B and was silent at 512,236 / 512,260 B. Length does not matter, only bytes.
COMBINED_LIMIT = 512000
COMBINED_VERIFIED_OK = 511884
COMBINED_VERIFIED_FAIL = 512236
# The same limit applies to an SND0 with no ICON1 at all (notes section 51): 511,292 B played, 512,036 B was silent.
# The icon sound and the SND0 were never heard together: either the SND0 plays or the icon's own sound does.


def _chunk(tag, body):
    return tag + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def build(frames, frame_bytes, pcm_samples=None, delay=DEFAULT_DELAY, loop=True):
    """frames: list of raw ATRAC3plus frames (each frame_bytes long). pcm_samples: real length of the audio in samples
    (default: as many as fit). -> SND0.AT3 bytes."""
    n = len(frames)
    if n == 0 or any(len(f) != frame_bytes for f in frames):
        raise ValueError("need at least one frame and all frames must be %d bytes" % frame_bytes)
    capacity = n * SAMPLES_PER_FRAME - delay - TAIL_MARGIN
    if capacity <= 0:
        raise ValueError("audio too short for an SND0")
    samples = capacity if pcm_samples is None else min(pcm_samples, capacity)
    avg_bytes = round(frame_bytes * 44100 / SAMPLES_PER_FRAME)
    fmt = (struct.pack("<HHIIHHH", 0xFFFE, 2, 44100, avg_bytes, frame_bytes, 0, 34)
           + struct.pack("<HI", SAMPLES_PER_FRAME, 3) + ATRAC3P_GUID
           + bytes([0x01, 0x00, 0x28, frame_bytes // 8 - 1]) + bytes(8))
    assert len(fmt) == 52
    body = _chunk(b"fmt ", fmt) + _chunk(b"fact", struct.pack("<II", samples, delay))
    if loop:
        smpl = struct.pack("<IIIIIIIII", 0, 0, round(1e9 / 44100), 60, 0, 0, 0, 1, 0)
        smpl += struct.pack("<IIIIII", 0, 0, delay, delay + samples - 1, 0, 0)
        assert len(smpl) == 60
        body += _chunk(b"smpl", smpl)
    body += _chunk(b"data", b"".join(frames))
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body
