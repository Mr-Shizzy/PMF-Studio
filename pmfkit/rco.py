"""Patch the gameboot length in a (decrypted, decompressed) opening_plugin.rco. See RESEARCH_NOTES.md sections 71-73.

The animation `anim_gameboot_movie` runs: fade 100 ms, Delay 300, Recolour 200, Delay 700, Delay <last>, then fires
`anim_gameboot_movie_finished`. The stock last delay is 1500 ms, so 300 + 700 + 1500 = 2,500 ms: the stock gameboot length.
The delays are float32 values. The last one sits 44 bytes after the 700.0 and 160 bytes after the 300.0 in every
firmware's RCO checked (5.00 to 6.61, nine files). Setting it to (movie length in ms - 1000) lets the whole movie play.
The RCO must be a plain, decrypted RCO (magic \0PRF); a gzip-compressed one is decompressed first.
"""
import gzip
import re
import struct

STOCK_LAST_DELAY_MS = 1500.0
BEFORE_700 = 44               # bytes from the 700.0 to the last delay
BEFORE_300 = 160              # bytes from the 300.0 to the last delay
MAGIC = b"\x00PRF"


def _f(v):
    return struct.pack("<f", v)


def load(data):
    """bytes of a plain RCO (gunzipped if needed); raises ValueError for anything else (e.g. encrypted)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != MAGIC:
        raise ValueError("not a plain RCO (no \0PRF magic): it may be encrypted; decrypt the firmware file first")
    return data


def find_delay(rco):
    """file offset of the last delay of anim_gameboot_movie; raises ValueError unless exactly one place matches"""
    if b"anim_gameboot_movie" not in rco:
        raise ValueError("this RCO has no anim_gameboot_movie: it is not opening_plugin.rco")
    hits = []
    for m in re.finditer(re.escape(_f(700.0)), rco):
        p = m.start() + BEFORE_700
        s = p - BEFORE_300
        if s >= 0 and p + 4 <= len(rco) and rco[s:s + 4] == _f(300.0):
            v = struct.unpack_from("<f", rco, p)[0]
            if 0.0 <= v < 1e7:
                hits.append(p)
    if len(hits) != 1:
        raise ValueError("found %d candidate gameboot delays, expected 1; this firmware's RCO is not recognised" % len(hits))
    return hits[0]


def gameboot_ms(rco):
    """current total gameboot time in ms (300 + 700 + last delay)"""
    return 1000.0 + struct.unpack_from("<f", rco, find_delay(rco))[0]


def patch(rco, movie_ms):
    """-> RCO bytes (same size) whose gameboot lasts movie_ms (never shorter than the stock 2.5 s)."""
    p = find_delay(rco)
    delay = max(STOCK_LAST_DELAY_MS, float(movie_ms) - 1000.0)
    out = bytearray(rco)
    struct.pack_into("<f", out, p, delay)
    return bytes(out)
