"""CTF (CXMB custom theme) container, reverse-engineered from a CTFtool GUI 4.5 file (see RESEARCH_NOTES.md section 68).

  [PTF bytes: 0x140-byte header + 3 compressed blocks]   header dwords rewritten at 0x10: marker, key2, file count, PTF size
  [file data blobs, one after another]                   raw files (resources, pmf) or small patch records (some modules)
  [file table at the very end: N x 72 bytes]             name[64] NUL padded ("/vsh/resource/gameboot.pmf"), u32 offset, u32 size
                                                         (little endian, offsets absolute in the CTF file)
marker = 0xDEAD0000 | firmware as hex digits (0xDEAD0660 = 6.60, 0xDEAD0661 = 6.61), as compared by CTFtool when unpacking.
key2 = 0xEF8203FD in the only sample we have; what it means is NOT known (not a CRC/Adler/byte-sum of any part).
"""
import struct

ENTRY = 72
NAME = 64
KEY2_SAMPLE = 0xEF8203FD
HEADER_FIELDS = 0x10                      # 4 little-endian dwords: marker, key2, file count, PTF size


def marker(firmware):
    """'661' -> 0xDEAD0661"""
    return 0xDEAD0000 | int(str(firmware), 16)


def parse(ctf):
    """-> dict(marker, key2, count, ptf_size, ptf, files={name: bytes}, order=[names])"""
    if ctf[:4] != b"\x00PTF":
        raise ValueError("not a PTF/CTF file")
    mk, key2, n, ptf_size = struct.unpack_from("<IIII", ctf, HEADER_FIELDS)
    start = len(ctf) - n * ENTRY
    if n <= 0 or start < ptf_size:
        raise ValueError("file table does not fit: %d entries" % n)
    files, order = {}, []
    for i in range(n):
        e = ctf[start + i * ENTRY:start + (i + 1) * ENTRY]
        name = e[:NAME].split(b"\x00")[0].decode("latin1")
        off, size = struct.unpack_from("<II", e, NAME)
        if off + size > start:
            raise ValueError("entry %s points outside the data area" % name)
        files[name] = ctf[off:off + size]
        order.append(name)
    return dict(marker=mk, key2=key2, count=n, ptf_size=ptf_size, ptf=ctf[:ptf_size], files=files, order=order)


def build(ptf, files, firmware="661", key2=KEY2_SAMPLE):
    """ptf: PTF bytes (the first `ptf_size` bytes of an existing CTF work); files: {"/vsh/resource/gameboot.pmf": bytes, ...}."""
    if ptf[:4] != b"\x00PTF":
        raise ValueError("ptf does not start with the PTF magic")
    head = bytearray(ptf)
    struct.pack_into("<IIII", head, HEADER_FIELDS, marker(firmware), key2, len(files), len(ptf))
    out = bytearray(head)
    table = bytearray()
    for name, data in files.items():
        raw = name.encode("latin1")
        if len(raw) >= NAME or not name.startswith("/"):
            raise ValueError("bad CTF path %r" % name)
        table += raw.ljust(NAME, b"\x00") + struct.pack("<II", len(out), len(data))
        out += data
    return bytes(out + table)
