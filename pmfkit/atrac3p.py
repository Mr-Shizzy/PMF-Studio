"""ATRAC3plus audio: read an OMA/raw stream, expose PSMF audio units (8-byte header + frame)."""
from dataclasses import dataclass

SAMPLES_PER_FRAME = 2048
SAMPLE_RATE = 44100


@dataclass
class Atrac3pStream:
    frames: list          # list[bytes], all the same length
    param: int            # 16-bit codec parameter word, e.g. 0x285c

    @property
    def frame_bytes(self):
        return frame_bytes_from_param(self.param)

    @property
    def unit_header(self):
        return b"\x0f\xd0" + self.param.to_bytes(2, "big") + b"\x00\x00\x00\x00"

    @property
    def unit_bytes(self):
        return 8 + self.frame_bytes

    @property
    def kbps(self):
        return self.frame_bytes * 8 * SAMPLE_RATE / SAMPLES_PER_FRAME / 1000

    def units(self):
        h = self.unit_header
        return [h + f for f in self.frames]


def frame_bytes_from_param(param):
    return (param & 0x3FF) * 8 + 8


def param_for(frame_bytes, channels=2, rate_idx=1):
    return (rate_idx << 13) | (channels << 10) | ((frame_bytes - 8) // 8)


def from_units(data):
    """Parse a PSMF audio ES (repeating 8-byte header + frame) back into frames."""
    if data[:2] != b"\x0f\xd0":
        raise ValueError("not a PSMF ATRAC3plus stream")
    param = int.from_bytes(data[2:4], "big")
    fb = frame_bytes_from_param(param)
    unit = fb + 8
    frames = []
    for o in range(0, len(data) - unit + 1, unit):
        if data[o:o + 4] != data[:4]:
            raise ValueError("audio unit header changed at %d" % o)
        frames.append(data[o + 8:o + unit])
    return Atrac3pStream(frames, param)


def read_oma(path):
    d = open(path, "rb").read()
    if d[:3] != b"EA3":
        raise ValueError("not an OMA file")
    hsize = int.from_bytes(d[4:6], "big")        # EA3 tag: 'EA3', version, header size (96)
    if d[32] != 1:
        raise ValueError("OMA codec is not ATRAC3plus (codec id %d)" % d[32])
    param = int.from_bytes(d[34:36], "big")
    fb = frame_bytes_from_param(param)
    body = d[hsize:]
    n = len(body) // fb
    return Atrac3pStream([body[i * fb:(i + 1) * fb] for i in range(n)], param)
