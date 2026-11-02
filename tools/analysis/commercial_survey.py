"""Survey PMF files (also commercial ones with several audio streams): header entries, video traits, every audio
stream, pack/stamp structure. Read-only. usage: python tools/analysis/commercial_survey.py FOLDER_OR_FILE [-v]"""
import collections
import glob
import os
import struct
import sys

sys.path.insert(0, ".")
from pmfkit.h264 import split_access_units
from pmfkit.sps import stream_info


def ue(b, pos):
    z = 0
    while not (b[pos >> 3] >> (7 - (pos & 7))) & 1:
        z += 1
        pos += 1
    pos += 1
    v = 0
    for _ in range(z):
        v = (v << 1) | ((b[pos >> 3] >> (7 - (pos & 7))) & 1)
        pos += 1
    return (1 << z) - 1 + v, pos


def slice_type(au):
    i = au.find(b"\x00\x00\x01")
    while i >= 0:
        if au[i + 3] & 0x1F in (1, 5):
            _, p = ue(au[i + 4:i + 16], 0)
            st, _ = ue(au[i + 4:i + 16], p)
            return st % 5          # 0 P, 1 B, 2 I
        i = au.find(b"\x00\x00\x01", i + 3)


def ts(b):
    return ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


def survey(path):
    d = open(path, "rb").read()
    h = d[:2048]
    r = {"name": os.path.basename(path), "mb": len(d) / 1e6, "ver": h[4:8].decode("latin1"),
         "streams_hdr": struct.unpack(">H", h[0x80:0x82])[0]}
    r["mux_rate"] = struct.unpack(">I", h[0x60:0x64])[0]
    r["dur"] = (int.from_bytes(h[0x5A:0x60], "big") - int.from_bytes(h[0x54:0x5A], "big")) / 90000
    r["wh"] = "%dx%d" % (h[0x8E] * 16, h[0x8F] * 16)
    r["entries"] = [h[0x82 + 16 * k:0x92 + 16 * k].hex(" ") for k in range(r["streams_hdr"])]
    body = d[2048:]
    n = len(body) // 2048
    cnt = collections.Counter()
    vid, aud = bytearray(), collections.defaultdict(bytearray)
    first_ptr = {}
    vstamps, astamps = [], collections.defaultdict(list)
    sysflags = set()
    pad = 0
    for k in range(n):
        p = body[k * 2048:(k + 1) * 2048]
        i = 14 + (p[13] & 7)
        while i + 6 <= 2048 and p[i:i + 3] == b"\x00\x00\x01":
            sid = p[i + 3]
            L = (p[i + 4] << 8) | p[i + 5]
            cnt[sid] += 1
            if sid == 0xBB:
                sysflags.add(p[i + 6:i + 6 + L].hex())
            if sid == 0xBE:
                pad += 1
            if sid == 0xE0 or sid == 0xBD:
                fl, hl = p[i + 7], p[i + 8]
                pts = ts(p[i + 9:i + 14]) if fl & 0x80 else None
                pl = p[i + 9 + hl:i + 6 + L]
                if sid == 0xE0:
                    vid += pl
                    if pts is not None:
                        vstamps.append(pts)
                else:
                    sub = pl[0]
                    aud[sub] += pl[4:]
                    if sub not in first_ptr:
                        first_ptr[sub] = (pl[2] << 8) | pl[3]
                    if pts is not None:
                        astamps[sub].append(pts)
            i += 6 + L
    r["pes"] = {hex(k): v for k, v in sorted(cnt.items())}
    r["pad"] = pad
    r["sysh"] = sorted(sysflags)
    try:
        aus = split_access_units(bytes(vid), strip_x264_sei=False)
    except ValueError as e:
        r["video_err"] = str(e)
        aus = []
    if aus:
        sps, pps = stream_info(bytes(vid))
        types = collections.Counter(slice_type(a.data) for a in aus)
        idr = [j for j, a in enumerate(aus) if a.is_idr]
        gops = collections.Counter(b - a for a, b in zip(idr, idr[1:]))
        r["frames"] = len(aus)
        r["sps"] = sps
        r["types"] = "P%d B%d I%d" % (types.get(0, 0), types.get(1, 0), types.get(2, 0))
        r["gops"] = gops.most_common(3)
        r["maxpic"] = max(len(a.data) for a in aus)
        secs = len(aus) * 1001 / 30000
        r["vkbps"] = len(vid) * 8 / secs / 1000
    r["audio"] = {}
    for sub, es in sorted(aud.items()):
        ptr = first_ptr[sub]
        hd = bytes(es[ptr:ptr + 8])
        info = {"first_ptr": ptr, "bytes": len(es), "hdr": hd.hex(" ")}
        if hd[:2] == b"\x0f\xd0":
            fb = ((hd[2] & 3) << 8 | hd[3]) * 8 + 8
            info["frame"] = fb
            info["kbps"] = round(fb * 44100 / 2048 * 8 / 1000, 1)
            info["secs"] = round(len(es) / (fb + 8) * 2048 / 44100, 1)
        r["audio"][sub] = info
    return r


def show(r, verbose):
    print("%-14s %6.1f MB  v%s %s  hdr-streams %d  dur(hdr) %.1fs  mux %d" % (r["name"], r["mb"], r["ver"], r["wh"], r["streams_hdr"], r["dur"], r["mux_rate"]))
    if "frames" in r:
        s = r["sps"]
        print("   video: %d frames (%.1fs) %s  profile %s level %s refs %s poc %s  GOPs %s  max pic %d B  %.0f kbps" % (
            r["frames"], r["frames"] * 1001 / 30000, r["types"], s["profile"], s["level"], s["num_ref_frames"], s["poc_type"], r["gops"], r["maxpic"], r["vkbps"]))
    else:
        print("   video error:", r.get("video_err"))
    for sub, a in r["audio"].items():
        print("   audio sub %02x: %s" % (sub, {k: v for k, v in a.items() if k != "bytes"}))
    print("   PES:", r["pes"], " padding PES:", r["pad"], " system headers:", r["sysh"])
    if verbose:
        for e in r["entries"]:
            print("   hdr entry:", e)


if __name__ == "__main__":
    target = sys.argv[1]
    verbose = "-v" in sys.argv
    files = [target] if os.path.isfile(target) else sorted(glob.glob(target + "/**/*.[pP][mM][fF]", recursive=True))
    for f in files:
        try:
            show(survey(f), verbose)
        except Exception as e:
            print(os.path.basename(f), "ERROR", type(e).__name__, e)
