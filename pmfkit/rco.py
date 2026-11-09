"""Patch the gameboot length in a (decrypted, decompressed) opening_plugin.rco. See RESEARCH_NOTES.md sections 71-73.

The animation `anim_gameboot_movie` runs: fade 100 ms, Delay 300, Recolour 200, Delay 700, Delay <last>, then fires
`anim_gameboot_movie_finished`. The stock last delay is 1500 ms, so 300 + 700 + 1500 = 2,500 ms: the stock gameboot length.
The delays are float32 values. The last one sits 44 bytes after the 700.0 and 160 bytes after the 300.0 in every
firmware's RCO checked (5.00 to 6.61, nine files). Setting it to (movie length in ms - 1000) lets the whole movie play.
The RCO must be a plain, decrypted RCO (magic \0PRF); a gzip-compressed one is decompressed first.
"""
import gzip
import hashlib
import re
import struct

STOCK_LAST_DELAY_MS = 1500.0
BEFORE_700 = 44               # bytes from the 700.0 to the last delay
BEFORE_300 = 160              # bytes from the 300.0 to the last delay
MAGIC = b"\x00PRF"


INVALID = "Invalid File. Please choose a decrypted opening_plugin.rco from your specific firmware version"

# The firmware versions a CTF can be marked for (the folders of CTFtool's base files). Firmware 3.71, 3.90 and 4.01 have no opening_plugin.rco
# there and 6.31 has none either, so nothing is known about their files.
FIRMWARES = ("371", "390", "401", "500", "550", "620", "631", "635", "637", "638", "639", "660", "661")
# sha256 of the plain (decrypted, decompressed) opening_plugin.rco -> the firmware versions whose file it is, from CTFtool's base folders.
# Several versions share one byte-identical file, so a file can name its family but not always the exact version.
KNOWN = {
    "6b50a847dc5cc67a9feb9eeda28ce98774959d113f0ca92b78c394134b93964b": ("500", "550"),
    "705538916a36bfe83bd915f0bfeedf027f890e241ab1d26a2a8cd90709724e0b": ("620", "635", "637", "638", "639"),
    "96e4d336968da8f5db513369382a29e2d7357bf61665bae2a3fedc22204500d7": ("660", "661"),
}


def label(fw):
    """'661' -> '6.61'"""
    return "%s.%s" % (fw[0], fw[1:])


def digits(text):
    """'6.61' -> '661' (also accepts '661')"""
    return str(text).strip().replace(".", "")


def names(group):
    """('660', '661') -> '6.60 or 6.61'"""
    parts = [label(f) for f in group]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " or " + parts[-1]


def identify(rco):
    """the firmware versions this plain RCO is the file of, or None when it is not one of the known files"""
    return KNOWN.get(hashlib.sha256(rco).hexdigest())


def mismatch(rco, firmware):
    """a sentence when this RCO is a known firmware's file and the chosen firmware is not one of that file's versions; None otherwise
    (a firmware with no known file, or a file that is not a known one, is not judged)"""
    fw = digits(firmware)
    group = identify(rco)
    if group is None or fw in group or not any(fw in g for g in KNOWN.values()):
        return None
    return ("This opening_plugin.rco is the one from firmware %s, but the theme is for firmware %s. Choose the firmware your PSP runs, "
            "and the opening_plugin.rco from that firmware." % (names(group), label(fw)))


def _f(v):
    return struct.pack("<f", v)


def load(data):
    """bytes of a plain RCO (gunzipped if needed); raises ValueError for anything else (e.g. encrypted)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != MAGIC:
        if data[:4] == b"~PSP":
            raise ValueError("This file is encrypted. Please choose a decrypted opening_plugin.rco from your specific firmware version")
        raise ValueError(INVALID)
    return data


def find_delay(rco):
    """file offset of the last delay of anim_gameboot_movie; raises ValueError unless exactly one place matches"""
    if b"anim_gameboot_movie" not in rco:
        raise ValueError(INVALID)
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
