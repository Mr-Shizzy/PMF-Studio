"""Build a PSP game ISO (ISO 9660) from an extracted game folder and the file list UMDGen exports ("LBA , \\path" per line),
putting every file at the sector the list gives, so a game that depends on file positions still works. (Command line: tools/build_umd_iso.py;
`sequential_list(folder)` makes a list for a folder that has none: files back to back from sector 50, as on a disc.)

    python tools/build_umd_iso.py GAME_FOLDER FILE_LIST.txt OUT.iso [--replace FOLDER ...] [--template ORIGINAL.cso|.iso]

--replace FOLDER    files in FOLDER (found by their path below GAME_FOLDER, or for movies by name) are used instead of the game's own; a replacement
                    must not be larger than the original (it has to fit where the list puts the file).
--template IMAGE    the game's own disc image (a CSO or ISO): its first 16 sectors and the identity fields of its volume descriptor (volume name,
                    publisher, dates, the disc id in the application-use area) are copied, as a real disc has them.
Names that share one sector in the list (a backup that points several names at one copy) stay sharing it.

The layout follows a real UMD (checked against a working 007 From Russia With Love image): file names without ';1', a 14 byte CD-ROM XA
area on every directory record, two copies of each path table (sectors 18-21), the root directory at sector 22, two sectors of spaces at 14-15.
Everything before the first file must fit in the sectors the list leaves free."""
import datetime
import hashlib
import os
import struct

SECTOR = 2048
XA_FILE = b"\x00\x00\x00\x00\x0d\x55XA" + b"\x00" * 6           # group, owner, attributes (0x550d file, 0x558d folder), 'XA', file number, reserved
XA_DIR = b"\x00\x00\x00\x00\x8d\x55XA" + b"\x00" * 6


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def date7(t):
    return bytes([t.year - 1900, t.month, t.day, t.hour, t.minute, t.second, 0])


def date17(t):
    return t.strftime("%Y%m%d%H%M%S").encode() + b"00" + b"\x00"


def record(lba, size, ident, is_dir, t, xa=True):
    fi = ident if isinstance(ident, bytes) else ident.encode("ascii")
    su = (XA_DIR if is_dir else XA_FILE) if xa else b""
    n = 33 + len(fi) + (0 if len(fi) % 2 else 1) + len(su)
    return (bytes([n, 0]) + both32(lba) + both32(size) + date7(t) + bytes([2 if is_dir else 0, 0, 0]) + both16(1) + bytes([len(fi)]) + fi
            + (b"" if len(fi) % 2 else b"\x00") + su)


class Dir:
    def __init__(self, name, parent):
        self.name, self.parent = name, parent
        self.dirs, self.files = {}, []               # files: (identifier, lba, size)
        self.lba = self.size = self.number = None


def read_list(path):
    """UMDGen's file list (a path), or rows already made -> [(sector, "\\\\path")]"""
    if not isinstance(path, (str, bytes, os.PathLike)):
        rows = [(int(a), p) for a, p in path]
    else:
        rows = []
        with open(path, encoding="utf8", errors="replace") as f:
            for line in f:
                if "," in line:
                    lba, p = line.split(",", 1)
                    rows.append((int(lba.strip()), p.strip()))
    if not rows:
        raise SystemExit("the file list has no entries")
    return rows


def sequential_list(game, first=50):
    """a file list for a folder that has none: every file after the other from sector `first`, in path order (UMD_DATA.BIN first)"""
    paths = []
    for root, _, names in os.walk(game):
        for n in names:
            paths.append("\\" + os.path.relpath(os.path.join(root, n), game).replace("/", "\\"))
    paths.sort(key=lambda p: (p.upper() != "\\UMD_DATA.BIN", p.upper()))
    rows, lba = [], first
    for p in paths:
        rows.append((lba, p))
        size = os.path.getsize(game + p)
        lba += -(-size // SECTOR)
    return rows


def sort_key(ident):
    return ident.encode("ascii")


def read_template(path, sectors=17):
    """the first sectors of a disc image (a CSO is read through its index)"""
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"CISO":
        from .cso import Cso
        c = Cso(path)
        try:
            return c.read(0, sectors)
        finally:
            c.close()
    with open(path, "rb") as f:
        return f.read(sectors * SECTOR)


def build(game, list_path, out, replace=(), template=None, log=print):
    rows = read_list(list_path)
    tpl = read_template(template) if template else None
    if tpl is not None and (tpl[16 * SECTOR] != 1 or tpl[16 * SECTOR + 1:16 * SECTOR + 6] != b"CD001"):
        raise SystemExit("the template image has no ISO 9660 volume descriptor")
    now = datetime.datetime.now(datetime.timezone.utc)
    if tpl is not None:                                  # the dates of the records follow the disc's own creation date
        c = tpl[16 * SECTOR + 813:16 * SECTOR + 827].decode("ascii", "replace")
        try:
            now = datetime.datetime(int(c[0:4]), int(c[4:6]), int(c[6:8]), int(c[8:10]), int(c[10:12]), int(c[12:14]))
        except ValueError:
            pass
    root = Dir("", None)
    placements = []                                  # (lba, size, source path, listed path)
    for lba, p in rows:
        orig = game + p
        if not os.path.isfile(orig):
            raise SystemExit("not in the game folder: " + p)
        src = orig
        for r in replace:
            full = os.path.join(r, p.lstrip("\\"))
            by_name = os.path.join(r, os.path.basename(p))
            if os.path.isfile(full):
                src = full
            elif "\\FMV\\" in p.upper() and os.path.isfile(by_name):
                src = by_name
        size = os.path.getsize(src)
        if src != orig and size > os.path.getsize(orig):
            raise SystemExit("%s is larger than the original and would not fit where the file list puts it" % p)
        parts = [x for x in p.split("\\") if x]
        d = root
        for part in parts[:-1]:
            d = d.dirs.setdefault(part, Dir(part, d))
        d.files.append((parts[-1], lba, size))
        placements.append((lba, size, src, p))

    # one copy of the data per sector; names that share a sector must hold the same bytes
    by_lba = {}
    for lba, size, src, p in placements:
        if size == 0:
            continue
        by_lba.setdefault(lba, []).append((size, src, p))
    for lba, lst in by_lba.items():
        if len({s for s, _, _ in lst}) > 1:
            raise SystemExit("files at sector %d have different sizes: %s" % (lba, [p for _, _, p in lst]))
        if len(lst) > 1:
            digests = set()
            for _, src, _ in lst:
                with open(src, "rb") as f:
                    digests.add(hashlib.sha256(f.read()).hexdigest())
            if len(digests) > 1:
                raise SystemExit("files at sector %d share a position but their data differs: %s" % (lba, [p for _, _, p in lst]))
    starts = sorted(by_lba)
    for i, lba in enumerate(starts):
        need = -(-by_lba[lba][0][0] // SECTOR)
        if i + 1 < len(starts) and lba + need > starts[i + 1]:
            raise SystemExit("%s does not fit before the next file (needs %d sectors, %d free)" % (by_lba[lba][0][2], need, starts[i + 1] - lba))

    # directory numbering (breadth first, sorted) and sizes
    order = [root]
    i = 0
    while i < len(order):
        for name in sorted(order[i].dirs, key=sort_key):
            order.append(order[i].dirs[name])
        i += 1
    for n, d in enumerate(order, 1):
        d.number = n

    def dir_bytes(d):
        recs = [record(d.lba or 0, d.size or SECTOR, b"\x00", True, now), record((d.parent or d).lba or 0, (d.parent or d).size or SECTOR, b"\x01", True, now)]
        entries = [(sort_key(name), record(c.lba or 0, c.size or SECTOR, name, True, now)) for name, c in d.dirs.items()]
        entries += [(sort_key(ident), record(lba, size, ident, False, now)) for ident, lba, size in d.files]
        recs += [r for _, r in sorted(entries, key=lambda e: e[0])]                 # one list in name order, folders and files together
        out_b, cur = bytearray(), bytearray()
        for r in recs:
            if len(cur) + len(r) > SECTOR:
                out_b += cur.ljust(SECTOR, b"\x00")
                cur = bytearray()
            cur += r
        out_b += cur.ljust(SECTOR, b"\x00")
        return bytes(out_b)

    # sector map: 16 volume descriptor, 17 end, 18-19 path table (little endian, two copies), 20-21 path table (big endian, two copies), directories from 22
    nxt = 22
    for d in order:
        d.lba = nxt
        d.size = SECTOR
        sectors = len(dir_bytes(d)) // SECTOR            # the size of a directory does not depend on its own location
        d.size = sectors * SECTOR
        nxt += sectors
    first_file = min(by_lba)
    if nxt > first_file:
        raise SystemExit("the directories need sectors up to %d but the first file starts at sector %d" % (nxt - 1, first_file))
    log("directories: %d in sectors 22..%d; first file at sector %d" % (len(order), nxt - 1, first_file))

    def path_table(big):
        pk = ">" if big else "<"
        b = bytearray()
        for d in order:
            ident = b"\x00" if d.parent is None else d.name.encode("ascii")
            b += bytes([len(ident), 0]) + struct.pack(pk + "I", d.lba) + struct.pack(pk + "H", 1 if d.parent is None else d.parent.number) + ident
            if len(ident) % 2:
                b += b"\x00"
        return bytes(b)

    ptl, ptm = path_table(False), path_table(True)
    if len(ptl) > SECTOR:
        raise SystemExit("the path table does not fit in one sector")

    last = max(lba + -(-by_lba[lba][0][0] // SECTOR) for lba in by_lba)
    total = max(last, nxt)

    # volume descriptor: the identity fields come from the template disc when there is one
    pvd = bytearray(SECTOR)
    if tpl is not None:
        t = tpl[16 * SECTOR:17 * SECTOR]
        for a, b in ((8, 80), (190, 881), (881, 882), (883, 1395)):
            pvd[a:b] = t[a:b]
    else:
        pvd[8:40] = b"PSP GAME".ljust(32)
        pvd[40:72] = b"PSP GAME".ljust(32)
        for off, ln in ((190, 128), (318, 128), (446, 128), (574, 128)):
            pvd[off:off + ln] = b" " * ln
        for off in (702, 739, 776):
            pvd[off:off + 37] = b" " * 37
        pvd[813:830] = date17(now)
        pvd[830:847] = b"0" * 16 + b"\x00"
        pvd[847:864] = b"0" * 16 + b"\x00"
        pvd[864:881] = b"0" * 16 + b"\x00"
        pvd[881] = 2
        game_id = os.path.join(game, "UMD_DATA.BIN")
        if os.path.isfile(game_id):                      # the disc id, as the application-use area of a real disc carries it
            text = open(game_id, "rb").read(48).split(b"|G")[0].rstrip(b"\x00")
            pvd[883:1395] = text.ljust(512, b" ")
    pvd[0:8] = b"\x01CD001\x01\x00"
    pvd[80:88] = both32(total)
    pvd[120:124] = both16(1)
    pvd[124:128] = both16(1)
    pvd[128:132] = both16(SECTOR)
    pvd[132:140] = both32(len(ptl))
    pvd[140:144] = struct.pack("<I", 18)
    pvd[144:148] = struct.pack("<I", 19)
    pvd[148:152] = struct.pack(">I", 20)
    pvd[152:156] = struct.pack(">I", 21)
    pvd[156:190] = record(root.lba, root.size, b"\x00", True, now, xa=False)
    end = bytearray(SECTOR)
    end[0:8] = b"\xffCD001\x01\x00"

    tmp = out + ".part"
    with open(tmp, "wb") as f:
        f.truncate(total * SECTOR)
        if tpl is not None:
            f.write(tpl[:16 * SECTOR])
        else:
            f.seek(14 * SECTOR)
            f.write(b" " * (2 * SECTOR))
        f.seek(16 * SECTOR)
        f.write(bytes(pvd))
        f.write(bytes(end))
        f.write(ptl.ljust(SECTOR, b"\x00"))
        f.write(ptl.ljust(SECTOR, b"\x00"))
        f.write(ptm.ljust(SECTOR, b"\x00"))
        f.write(ptm.ljust(SECTOR, b"\x00"))
        for d in order:
            f.seek(d.lba * SECTOR)
            f.write(dir_bytes(d))
        for lba in starts:
            size, src, p = by_lba[lba][0]
            f.seek(lba * SECTOR)
            with open(src, "rb") as g:
                while True:
                    block = g.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
    os.replace(tmp, out)
    log("wrote %s: %d sectors, %.1f MB, %d names, %d separate pieces of data" % (out, total, total * SECTOR / 1e6, len(rows), len(starts)))
    return total

