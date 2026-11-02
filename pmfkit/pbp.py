"""EBOOT.PBP container: read, swap sections (ICON1.PMF, ICON0, PIC1, SND0, ...), patch the XMB title, write.

Layout (all little-endian): 4 bytes "\\0PBP", 4 bytes version, then eight u32 offsets, in this order:
PARAM.SFO, ICON0.PNG, ICON1.PMF, PIC0.PNG, PIC1.PNG, SND0.AT3, DATA.PSP, DATA.PSAR.
There are no length fields: a section runs from its offset to the next offset (the last one to the end of the file),
so an absent section simply has the same offset as the one after it.

Editing only moves the offsets; every section that is not replaced is carried over byte for byte. This does not
decrypt, sign or otherwise touch the executable, so it is meant for homebrew-style EBOOTs. Encrypted/NPDRM/PS1 EBOOTs
may care about where DATA.PSAR sits; `Pbp.alignment_notes` reports when an edit moved it.
"""
import struct

MAGIC = b"\x00PBP"
NAMES = ["PARAM.SFO", "ICON0.PNG", "ICON1.PMF", "PIC0.PNG", "PIC1.PNG", "SND0.AT3", "DATA.PSP", "DATA.PSAR"]
HEADER = 8 + 4 * len(NAMES)             # 0x28


class PbpError(ValueError):
    pass


class Pbp:
    def __init__(self, version, sections, head=b""):
        self.version = version          # the 4 version bytes, kept exactly as read
        self.sections = sections        # list of 8 bytes objects, in NAMES order
        self.head = head                # bytes between the offset table and the first section (normally empty)
        self._old_offsets = None

    # ---- reading
    @classmethod
    def parse(cls, data):
        if len(data) < HEADER or data[:4] != MAGIC:
            raise PbpError("not an EBOOT.PBP (missing \\0PBP signature)")
        offs = list(struct.unpack("<8I", data[8:HEADER]))
        if offs[0] < HEADER or any(b < a for a, b in zip(offs, offs[1:])) or offs[-1] > len(data):
            raise PbpError("corrupt PBP offset table %s" % [hex(o) for o in offs])
        ends = offs[1:] + [len(data)]
        p = cls(data[4:8], [bytes(data[a:b]) for a, b in zip(offs, ends)], bytes(data[HEADER:offs[0]]))
        p._old_offsets = offs
        return p

    @classmethod
    def read(cls, path):
        with open(path, "rb") as f:
            return cls.parse(f.read())

    # ---- access
    def index(self, name):
        key = name.upper()
        for i, n in enumerate(NAMES):
            if key in (n, n.split(".")[0]):
                return i
        raise PbpError("unknown section %r (use one of %s)" % (name, ", ".join(NAMES)))

    def get(self, name):
        return self.sections[self.index(name)]

    def replace(self, name, data):
        """Replace one section; data=b"" removes it."""
        self.sections[self.index(name)] = bytes(data)

    def offsets(self):
        out, pos = [], HEADER + len(self.head)
        for s in self.sections:
            out.append(pos)
            pos += len(s)
        return out

    def to_bytes(self):
        return MAGIC + self.version + struct.pack("<8I", *self.offsets()) + self.head + b"".join(self.sections)

    def write(self, path):
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ---- title
    def title(self):
        return _sfo_get_title(self.get("PARAM.SFO"))[0]

    def set_title(self, text):
        self.sections[0] = _sfo_set_title(self.sections[0], text)

    def realign(self):
        """Keep DATA.PSAR on the alignment it had in the file that was read (both PS1-style samples put it on a
        0x8000/0x10000 boundary, with the gap as zero padding at the tail of DATA.PSP). Returns the pad size."""
        old = self._old_offsets[7] if self._old_offsets else 0
        if not old or not self.sections[7]:
            return 0
        align = min(old & -old, 0x10000)
        cur = self.offsets()[7]
        pad = (-cur) % align
        if pad:
            self.sections[6] += bytes(pad)
        return pad

    # ---- reporting
    def alignment_notes(self):
        """Warnings about sections whose position/alignment changed compared with the file that was read."""
        notes = []
        if self._old_offsets and self.sections[7]:
            old, new = self._old_offsets[7], self.offsets()[7]
            if old != new:
                notes.append("DATA.PSAR moved from 0x%X to 0x%X (still on a 0x%X boundary); whether a PS1/NPDRM EBOOT "
                             "still boots with this is untested" % (old, new, min(old & -old, 0x10000)))
        return notes

    def describe(self):
        lines = ["version bytes %s, %d bytes total" % (self.version.hex(" "), HEADER + len(self.head) + sum(map(len, self.sections)))]
        for name, off, s in zip(NAMES, self.offsets(), self.sections):
            lines.append("  %-10s offset 0x%06X  %8d bytes%s" % (name, off, len(s), "" if s else "  (absent)"))
        try:
            lines.append("  title: %r" % self.title())
        except PbpError:
            pass
        return "\n".join(lines)


# ---------------------------------------------------------------- PARAM.SFO title patching
def _sfo_entries(sfo):
    if sfo[:4] != b"\x00PSF":
        raise PbpError("PARAM.SFO is missing or invalid")
    key_off, data_off, count = struct.unpack("<III", sfo[8:20])
    for i in range(count):
        k, fmt, ln, mx, d = struct.unpack("<HHIII", sfo[20 + 16 * i:36 + 16 * i])
        end = sfo.index(b"\x00", key_off + k)
        yield sfo[key_off + k:end].decode("ascii", "replace"), fmt, ln, mx, data_off + d


def _sfo_get_title(sfo):
    for key, fmt, ln, mx, pos in _sfo_entries(sfo):
        if key == "TITLE":
            return sfo[pos:pos + ln].rstrip(b"\x00").decode("utf-8", "replace"), mx
    raise PbpError("PARAM.SFO has no TITLE entry")


def _sfo_set_title(sfo, text):
    for i, (key, fmt, ln, mx, pos) in enumerate(_sfo_entries(sfo)):
        if key == "TITLE":
            raw = text.encode("utf-8")[:mx - 1]
            while True:                                    # never cut a multi-byte character in half
                try:
                    raw.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    raw = raw[:-1]
            out = bytearray(sfo)
            out[pos:pos + mx] = raw + b"\x00" * (mx - len(raw))
            struct.pack_into("<I", out, 20 + 16 * i + 4, len(raw) + 1)
            return bytes(out)
    raise PbpError("PARAM.SFO has no TITLE entry")
