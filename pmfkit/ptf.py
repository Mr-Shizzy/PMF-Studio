"""PTF (PSP theme) container as found at the start of a CTF (see ctf.py and RESEARCH_NOTES.md section 68, 69).

0x00-0x13F header (kept from a template; u32 at 0x124 = bytes after the header), then blocks, each:
  0x20-byte header: u32 index, u32 0x00020005, u32 compressed size, u32 uncompressed size, 16 zero bytes
  zlib data zero-padded to a multiple of 4 bytes, the padding counted in the compressed size (a GIM picture; the last block is 4 raw bytes)
block 0 = preview icon, GIM 16x16 INDEX8 + 256-colour RGBA8888 palette; block 1 = preview picture, GIM 300x170 RGBA8888
(swizzled in 16-byte x 8-row tiles, rows padded to a multiple of 8); block 2 = 4 bytes.
"""
import struct
import zlib

HEADER = 0x140
BLOCK_HEADER = 0x20
ICON_W = ICON_H = 16
IMG_W, IMG_H = 300, 170
_ICON_DATA = 128                                  # offset of the 256 index bytes inside block 0
_ICON_PALETTE = 464                               # offset of the 1024 palette bytes inside block 0
_IMG_DATA = 128                                   # offset of the pixel data inside block 1


def blocks(ptf):
    """-> list of (header32, raw_bytes) after decompression"""
    out, pos = [], HEADER
    while pos + BLOCK_HEADER <= len(ptf):
        h = ptf[pos:pos + BLOCK_HEADER]
        csize = struct.unpack_from("<I", h, 8)[0]
        data = ptf[pos + BLOCK_HEADER:pos + BLOCK_HEADER + csize]
        try:
            raw = zlib.decompress(data) if data[:1] == b"\x78" else data
        except zlib.error:
            raw = data
        out.append((h, raw))
        pos += BLOCK_HEADER + csize
    return out


def swizzle_rgba(rgba, w, h):
    """linear RGBA8888 -> PSP swizzled (16-byte x 8-row tiles)."""
    row = w * 4
    ph = (h + 7) // 8 * 8
    buf = bytes(rgba) + bytes(row * (ph - h))
    out = bytearray()
    for by in range(ph // 8):
        for bx in range(row // 16):
            for r in range(8):
                o = (by * 8 + r) * row + bx * 16
                out += buf[o:o + 16]
    return bytes(out)


def unswizzle_rgba(data, w, h):
    row = w * 4
    ph = (h + 7) // 8 * 8
    out = bytearray(row * ph)
    i = 0
    for by in range(ph // 8):
        for bx in range(row // 16):
            for r in range(8):
                o = (by * 8 + r) * row + bx * 16
                out[o:o + 16] = data[i:i + 16]
                i += 16
    return bytes(out[:row * h])


def _pack(index, raw):
    z = zlib.compress(raw) if raw[:3] == b"MIG" else raw          # default level: header 78 9c, as in every real PTF/CTF (level 9 gives 78 da)
    z += bytes(-len(z) % 4)                                         # every block is zero-padded to a multiple of 4 and csize includes the padding
    return struct.pack("<IIII", index, 0x00020005, len(z), len(raw)) + bytes(16) + z


# Fixed GIM header bytes (picture structure only; no artwork) as found in the PTF blocks of CTFtool/Sony themes.
_GIM0_HEAD = bytes.fromhex(
    "4d49472e30302e31505350000000000002000000c0050000100000001000000003000000b005000010000000100000000400000050010000"
    "5001000010000000300000000500010010001000080010000800020000000000300000004000000040010000000000000100010003000100"
    "40000000000000000000000000000000")
_GIM0_MID = bytes.fromhex(
    "0500000050040000500400001000000030000000030000000001010020001000010002000000000030000000400000004004000000000000"
    "020001000300010040000000000000000000000000000000")
_GIM1_HEAD = bytes.fromhex(
    "4d49472e30302e31505350000000000002000000703903001000000010000000030000006039030010000000100000000400000050390300"
    "503903001000000030000000030001002c01aa00200010000800020000000000300000004000000040390300000000000100010003000100"
    "40000000000000000000000000000000")
FIRMWARE_TEXT = (b"6.20", b"1.50")             # strings at 0xB8 / 0xC0 of the PTF header (as written by CTFtool; meaning unverified)


def new(icon_rgba, image_rgba, title="", author=""):
    """A complete PTF made from scratch: icon_rgba = 16*16*4 bytes (every pixel becomes its own palette entry),
    image_rgba = 300*170*4 bytes. title goes to 0x20 (max 103 characters), author to 0x88 (max 47)."""
    if len(icon_rgba) != ICON_W * ICON_H * 4 or len(image_rgba) != IMG_W * IMG_H * 4:
        raise ValueError("unexpected picture sizes")
    title, author = title.encode("latin1", "replace"), author.encode("latin1", "replace")
    if len(title) > 0x67 or len(author) > 0x2f:
        raise ValueError("title or author too long")
    block0 = _GIM0_HEAD + bytes(range(256)) + _GIM0_MID + bytes(icon_rgba)
    block1 = _GIM1_HEAD + swizzle_rgba(image_rgba, IMG_W, IMG_H)
    body = _pack(0, block0) + _pack(1, block1) + _pack(2, bytes(4))
    head = bytearray(HEADER)
    head[0:8] = b"\x00PTF\x00\x01\x00\x00"
    head[0x08:0x08 + 7] = b"pmfkit "
    head[0x20:0x20 + len(title)] = title
    head[0x88:0x88 + len(author)] = author
    head[0xB8:0xB8 + 4], head[0xC0:0xC0 + 4] = FIRMWARE_TEXT
    struct.pack_into("<I", head, 0xC8, 8)
    struct.pack_into("<I", head, 0x100, 0x120)
    struct.pack_into("<H", head, 0x122, 3)
    struct.pack_into("<I", head, 0x124, len(body))
    struct.pack_into("<I", head, 0x128, 0x140)
    return bytes(head) + body


def with_preview(template, icon_index, icon_palette, image_rgba):
    """New PTF = template header + new preview icon (256 index bytes, 1024 palette bytes RGBA) and preview picture
    (300*170*4 RGBA bytes); the colour block is kept."""
    bl = blocks(template)
    if len(bl) != 3 or len(icon_index) != ICON_W * ICON_H or len(icon_palette) != 1024 or len(image_rgba) != IMG_W * IMG_H * 4:
        raise ValueError("unexpected template or picture sizes")
    b0, b1 = bytearray(bl[0][1]), bytearray(bl[1][1])
    b0[_ICON_DATA:_ICON_DATA + 256] = icon_index
    b0[_ICON_PALETTE:_ICON_PALETTE + 1024] = icon_palette
    sw = swizzle_rgba(image_rgba, IMG_W, IMG_H)
    b1[_IMG_DATA:_IMG_DATA + len(sw)] = sw
    body = _pack(0, bytes(b0)) + _pack(1, bytes(b1)) + _pack(2, bl[2][1])
    head = bytearray(template[:HEADER])
    struct.pack_into("<I", head, 0x124, len(body))
    return bytes(head) + body
