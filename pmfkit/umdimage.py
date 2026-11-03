"""A game's own disc image (ISO or CSO): read its file system, shrink the movies inside it, and write the image again with only those
files changed.

The image already holds every file's position (sector) and size in its directory records, so nothing has to be extracted with another
program and no file list is needed. A shrunk movie goes back into the sectors the original had (the unused rest is zeros, which a CSO
squeezes away), the size in each directory record that points at it is corrected, and every other byte of the disc stays as it was:
volume name, dates, the disc id, all positions. Names that share one copy of a movie on the disc keep sharing it."""
import hashlib
import os
import struct
from collections import defaultdict

from .cso import SECTOR, Cso, write_cso

CHUNK = 256                                 # sectors read at a time


def is_image(path):
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in (".cso", ".iso")


class Image:
    """sector access to an ISO or a CSO"""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic == b"CISO":
            self.cso, self.f = Cso(path), None
            self.sectors, self.size = self.cso.blocks, self.cso.total
        else:
            self.cso, self.f = None, open(path, "rb")
            self.size = os.path.getsize(path)
            self.sectors = -(-self.size // SECTOR)

    def close(self):
        (self.cso or self.f).close()

    def read(self, first, count):
        count = max(0, min(count, self.sectors - first))
        if self.cso:
            return self.cso.read(first, count)
        self.f.seek(first * SECTOR)
        data = self.f.read(count * SECTOR)
        return data.ljust(count * SECTOR, b"\0")

    def sector(self, n):
        return self.read(n, 1)


class Entry:
    __slots__ = ("path", "extent", "size", "rec_sector", "rec_offset")

    def __init__(self, path, extent, size, rec_sector, rec_offset):
        self.path, self.extent, self.size, self.rec_sector, self.rec_offset = path, extent, size, rec_sector, rec_offset


def walk(img):
    """every file on the disc -> list of Entry (path with backslashes, first sector, size in bytes, where its directory record is).
    ValueError says what is wrong when this isn't a disc image."""
    pvd = img.sector(16)
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise ValueError("That isn't a game disc image (no ISO 9660 volume descriptor).")
    root = pvd[156:190]
    stack = [(struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0], "")]
    seen, files = set(), []
    while stack:
        lba, size, path = stack.pop()
        if lba in seen or size <= 0 or lba + size // SECTOR > img.sectors + 1:
            continue
        seen.add(lba)
        data = img.read(lba, -(-size // SECTOR))
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            rec = data[o:o + n]
            if len(rec) < 34 or o // SECTOR != (o + n - 1) // SECTOR:
                raise ValueError("The disc's directory records are damaged.")
            ident = rec[33:33 + rec[32]]
            if ident not in (b"\x00", b"\x01"):
                name = ident.decode("latin1").split(";")[0]
                extent, length = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
                if rec[25] & 2:
                    stack.append((extent, length, path + "\\" + name))
                else:
                    files.append(Entry(path + "\\" + name, extent, length, lba + o // SECTOR, o % SECTOR))
            o += n
    return files


def _dirs(img):
    """every folder on the disc, root first -> list of (path, extent, size, rec_sector, rec_offset, rec_len); the root has no record (None, None, 0)"""
    pvd = img.sector(16)
    root = pvd[156:190]
    start = (struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0])
    out, stack, seen = [("", start[0], start[1], None, None, 0)], [("", start[0], start[1])], set()
    while stack:
        path, lba, size = stack.pop()
        if lba in seen or size <= 0 or lba + size // SECTOR > img.sectors + 1:
            continue
        seen.add(lba)
        data = img.read(lba, -(-size // SECTOR))
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            rec = data[o:o + n]
            if len(rec) < 34 or o // SECTOR != (o + n - 1) // SECTOR:
                raise ValueError("The disc's directory records are damaged.")
            ident = rec[33:33 + rec[32]]
            if ident not in (b"\x00", b"\x01") and rec[25] & 2:
                name = ident.decode("latin1").split(";")[0]
                extent, length = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
                out.append((path + "\\" + name, extent, length, lba + o // SECTOR, o % SECTOR, n))
                stack.append((path + "\\" + name, extent, length))
            o += n
    return out


UPDATE_DIR = "\\PSP_GAME\\SYSDIR\\UPDATE"      # Sony's own firmware-update offer: obsolete, never wanted on custom firmware


class UpdateRemoval:
    """what emptying the UPDATE folder changes: its directory sectors lose the records of the files in it (the folder, with its '.' and '..',
    stays) and the sectors that held those files become zeros"""

    def __init__(self, extra, wipe, files, nbytes):
        self.extra, self.wipe, self.files, self.bytes = extra, wipe, files, nbytes

    @property
    def touched(self):
        return set(self.extra) | self.wipe


def _sectors_of(extent, size):
    return range(extent, extent + -(-size // SECTOR))


def plan_update_removal(img, entries, keep_sectors=()):
    """None when there is nothing to empty (no UPDATE folder, no files in it, or it has folders of its own / shares sectors with something else:
    then it is left alone); otherwise an UpdateRemoval. keep_sectors: sectors that must not change (directory sectors with other edits)."""
    dirs = _dirs(img)
    top = next((d for d in dirs if d[0].upper() == UPDATE_DIR), None)
    if top is None or any(d[0].upper().startswith(UPDATE_DIR + "\\") for d in dirs):
        return None
    files = [e for e in entries if e.path.upper().startswith(UPDATE_DIR + "\\")]
    if not files:
        return None
    dir_sectors = list(_sectors_of(top[1], top[2]))
    if set(dir_sectors) & set(keep_sectors):
        return None
    used = set(range(0, dirs[0][1]))                         # the system area, volume descriptors and path tables
    for d in dirs:
        used.update(_sectors_of(d[1], d[2]))
    for e in entries:
        if e not in files:
            used.update(_sectors_of(e.extent, e.size))
    wipe = set()
    for e in files:
        wipe.update(_sectors_of(e.extent, e.size))
    wipe -= used
    data = img.read(top[1], len(dir_sectors))
    keep = b""
    o = 0
    for _ in range(2):                                       # the '.' and '..' records stay
        n = data[o]
        ident = data[o + 33:o + 33 + data[o + 32]]
        if not n or ident not in (b"\x00", b"\x01"):
            return None
        keep += data[o:o + n]
        o += n
    new = keep.ljust(len(data), b"\0")
    extra = {top[1] + k: new[k * SECTOR:(k + 1) * SECTOR] for k in range(len(dir_sectors))}
    if wipe & set(extra):
        return None
    return UpdateRemoval(extra, wipe, files, sum(e.size for e in files))


class Movie:
    """one movie on the disc: its data, and every name that points at it"""

    def __init__(self, extent, size, entries):
        self.extent, self.size, self.entries = extent, size, entries

    @property
    def sectors(self):
        return -(-self.size // SECTOR)

    @property
    def name(self):
        return self.entries[0].path

    def raw(self, img):
        return img.read(self.extent, self.sectors)[:self.size]


LEAVE_ALONE = ("\\PSP_GAME\\ICON1.PMF",)          # the XMB's own icon movie: tiny, belongs to the menu, never worth any risk


def find_movies(entries):
    groups = defaultdict(list)
    for e in entries:
        if e.path.upper().endswith(".PMF") and e.size > 0 and e.path.upper() not in LEAVE_ALONE:
            groups[(e.extent, e.size)].append(e)
    per_extent = defaultdict(int)
    for (ex, _) in groups:
        per_extent[ex] += 1
    # a movie whose first sector is also the start of a different-sized movie can't be replaced safely: left out
    return sorted((Movie(ex, sz, sorted(es, key=lambda e: e.path)) for (ex, sz), es in groups.items() if per_extent[ex] == 1), key=lambda m: m.extent)


def survey_image(path, samples=3):
    """what the movies on a disc look like (see shrink.survey)"""
    from . import shrink
    img = Image(path)
    try:
        movies = find_movies(walk(img))
        if not movies:
            return shrink.Survey()
        picked = sorted(movies, key=lambda m: -m.size)[:samples]
        return shrink.survey_stats([m.raw(img) for m in picked], len(movies), sum(m.size for m in movies))
    finally:
        img.close()


class Replacement:
    def __init__(self, movie, path, new_size):
        self.movie, self.path, self.new_size = movie, path, new_size


def _blocks(img, replacements, check, removal=None, files=None):
    """every sector of the new image in order: the old sector, the new movie data (padded with zeros to the old length), or a directory sector
    with the size of a replaced movie corrected; with `removal`, also the sectors the UPDATE folder's removal changes"""
    patches = defaultdict(list)
    for rp in replacements:
        for e in rp.movie.entries:
            patches[e.rec_sector].append((e.rec_offset, rp.new_size))
    over = _file_sectors(files, patches)
    lba = 0
    for rp in sorted(replacements, key=lambda r: r.movie.extent):
        start = rp.movie.extent
        yield from _plain(img, lba, start, patches, check, removal, over)
        with open(rp.path, "rb") as f:
            data = f.read().ljust(rp.movie.sectors * SECTOR, b"\0")                      # the movie, then zeros up to the old length
        for k in range(0, len(data), SECTOR):
            yield data[k:k + SECTOR]
        lba = start + rp.movie.sectors
    yield from _plain(img, lba, img.sectors, patches, check, removal, over)


def _file_sectors(files, patches):
    """files: [(Entry, bytes)], each no bigger than the sectors the file has now -> {sector: new data}; the file's size is patched in its directory record"""
    over = {}
    for ent, data in files or []:
        cap = -(-ent.size // SECTOR)
        if len(data) > cap * SECTOR:
            raise ValueError("%s has room for %d bytes, not %d" % (ent.path, cap * SECTOR, len(data)))
        body = data.ljust(cap * SECTOR, b"\0")
        for k in range(cap):
            over[ent.extent + k] = body[k * SECTOR:(k + 1) * SECTOR]
        patches[ent.rec_sector].append((ent.rec_offset, len(data)))
    return over


def _plain(img, a, b, patches, check, removal=None, over=None):
    n = 0
    for first in range(a, b, CHUNK):
        data = img.read(first, min(CHUNK, b - first))
        for k in range(len(data) // SECTOR):
            sec = data[k * SECTOR:(k + 1) * SECTOR]
            if removal is not None:
                if first + k in removal.extra:
                    sec = removal.extra[first + k]
                elif first + k in removal.wipe:
                    sec = b"\0" * SECTOR
            if over and first + k in over:
                sec = over[first + k]
            if first + k in patches:
                sec = bytearray(sec)
                for off, size in patches[first + k]:
                    sec[off + 10:off + 14] = struct.pack("<I", size)
                    sec[off + 14:off + 18] = struct.pack(">I", size)
                sec = bytes(sec)
            yield sec
        n += 1
        if n % 16 == 0:
            check()


def shrink_image(src, out, ffmpeg, atracdenc=None, ratio=0.5, sound_kbps=None, bframes=None, log=print, verify=True, level=9, drop_update=True):
    """A game's image (ISO or CSO) -> a new image at `out` (.cso or .iso) with its movies made smaller. -> list of shrink.ShrinkResult
    (one per movie; before and after are the movie's size), the images' sizes are in the last result's note.
    drop_update: take Sony's UPDATE folder (the firmware-update offer, useless on custom firmware) off the disc; its sectors become zeros."""
    import shutil
    import tempfile
    from . import shrink as sh
    from .cli import PROGRESS, BuildError, Cancelled, check_cancel
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(out)):
        raise BuildError("Save the smaller game under another name. PMF Studio never replaces your original.")
    img = Image(src)
    work = tempfile.mkdtemp(prefix="pmfgame_")
    try:
        try:
            entries = walk(img)
            movies = find_movies(entries)
        except ValueError as e:
            raise BuildError(str(e))
        if not movies:
            raise BuildError("There are no .pmf movies on that disc.")
        results, replacements, done = [], [], {}
        for i, m in enumerate(movies):
            check_cancel()
            PROGRESS.window(0.85 * i / len(movies), 0.85 * (i + 1) / len(movies))
            PROGRESS.report(0.0, "Movie %d of %d: %s" % (i + 1, len(movies), os.path.basename(m.name)))
            raw = m.raw(img)
            key = hashlib.sha256(raw).hexdigest()
            names = ", ".join(os.path.basename(e.path) for e in m.entries)
            if key in done:                                # the same movie stored twice on the disc: shrunk once, the result used for both
                lead = done[key]
                if lead is None:
                    results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "same movie as one that could not be made smaller"))
                else:
                    replacements.append(Replacement(m, lead[0], lead[1]))
                    results.append(sh.ShrinkResult(m.name, m.name, m.size, lead[1], "same movie as an earlier one"))
                    log("%s: %s -> %s KB (same movie as an earlier one)" % (names, m.size // 1000, lead[1] // 1000))
                continue
            p_in, p_out = os.path.join(work, "m%d.pmf" % i), os.path.join(work, "m%d.new.pmf" % i)
            with open(p_in, "wb") as f:
                f.write(raw)
            try:
                r = sh.shrink_one(p_in, p_out, ffmpeg, atracdenc, ratio, sound_kbps, bframes, log)
            except Cancelled:
                raise
            except (ValueError, BuildError, OSError) as e:
                log("%s: %s" % (names, e))
                results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "failed: %s" % e))
                done[key] = None
                os.remove(p_in)
                continue
            os.remove(p_in)
            if r.after < r.before and os.path.exists(p_out) and os.path.getsize(p_out) == r.after:
                replacements.append(Replacement(m, p_out, r.after))
                done[key] = (p_out, r.after)
                log("%s: %s -> %s KB (%s)" % (names, r.before // 1000, r.after // 1000, r.note))
                results.append(sh.ShrinkResult(m.name, m.name, m.size, r.after, r.note))
            else:
                done[key] = None
                log("%s: left as it is (%s)" % (names, r.note))
                results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, r.note))
        if not replacements:
            raise BuildError("None of the movies could be made smaller, so no new game was written.")

        # the new image: the same disc with the smaller movies in the same places
        removal = None
        if drop_update:
            try:
                removal = plan_update_removal(img, entries, {e.rec_sector for rp in replacements for e in rp.movie.entries})
            except (ValueError, struct.error) as e:
                removal = None
                log("The update folder was left on the disc (%s)." % e)
            if removal:
                log("The UPDATE folder is emptied (%d files, %.1f MB): Sony's firmware update offer is useless on custom firmware."
                    % (len(removal.files), removal.bytes / 1e6))
        PROGRESS.window(0.85, 0.97)
        PROGRESS.report(0.0, "Writing the new game…")
        total_bytes = img.size
        blocks = _blocks(img, replacements, check_cancel, removal)
        tmp = out + ".part"
        try:
            if out.lower().endswith(".iso"):
                with open(tmp, "wb") as f:
                    for n, sec in enumerate(blocks):
                        f.write(sec)
                        if n % 8192 == 0:
                            PROGRESS.report(n / img.sectors)
                    f.truncate(total_bytes)
                os.replace(tmp, out)
                new_size = os.path.getsize(out)
            else:
                new_size = write_cso(blocks, img.sectors, total_bytes, out, level, progress=lambda f: PROGRESS.report(f))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if verify:
            PROGRESS.window(0.97, 1.0)
            PROGRESS.report(0.0, "Checking the new game…")
            problem = _verify(img, out, replacements, check_cancel, removal)
            if problem:
                try:
                    os.remove(out)
                except OSError:
                    pass
                raise BuildError("The new game did not pass the check (%s), so it was not kept." % problem)
        PROGRESS.report(1.0)
        results.append(sh.ShrinkResult(src, out, os.path.getsize(src), new_size, "game image"))
        return results
    finally:
        img.close()
        shutil.rmtree(work, ignore_errors=True)


def retrack_image(src, out, keep, others, ffmpeg=None, atracdenc=None, log=print, verify=True, level=9, files=None, short_frames=1):
    """A game's image (ISO or CSO) -> a new image at `out` in which every movie with several sound tracks keeps only the tracks in `keep`
    (track numbers; a movie that has fewer tracks than that is left alone). others: "delete", "silent" or "short" (see pmfkit.tracks).
    The picture and everything else on the disc stay as they are. files: [(path inside the disc, bytes)] small files to replace
    (a picture), each no bigger than the file is now. -> list of shrink.ShrinkResult"""
    import shutil
    import tempfile
    from . import shrink as sh
    from . import tracks as tk
    from .cli import PROGRESS, BuildError, check_cancel
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(out)):
        raise BuildError("Save the new game under another name. PMF Studio never replaces your original.")
    img = Image(src)
    work = tempfile.mkdtemp(prefix="pmftracks_")
    try:
        try:
            entries = walk(img)
            movies = find_movies(entries)
        except ValueError as e:
            raise BuildError(str(e))
        by_path = {e.path.upper(): e for e in entries}
        extra = []
        for path, data in files or []:
            ent = by_path.get(path.upper())
            if ent is None:
                raise BuildError("There is no %s on that disc." % path)
            extra.append((ent, data))
        results, replacements, done = [], [], {}
        for i, m in enumerate(movies):
            check_cancel()
            PROGRESS.window(0.85 * i / len(movies), 0.85 * (i + 1) / len(movies))
            PROGRESS.report(0.0, "Movie %d of %d: %s" % (i + 1, len(movies), os.path.basename(m.name)))
            raw = m.raw(img)
            key = hashlib.sha256(raw).hexdigest()
            if key in done:
                lead = done[key]
                if lead is not None:
                    replacements.append(Replacement(m, lead[0], lead[1]))
                    results.append(sh.ShrinkResult(m.name, m.name, m.size, lead[1], "same movie as an earlier one"))
                else:
                    results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "left as it is"))
                continue
            try:
                n_tracks = len(tk.read_tracks(raw))
            except (ValueError, KeyError):
                n_tracks = 0
            if n_tracks < 2 or any(k >= n_tracks for k in keep):
                done[key] = None
                results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "no sound tracks to choose from"))
                continue
            p_out = os.path.join(work, "m%d.new.pmf" % i)
            try:
                new = tk.retrack(raw, keep, others, ffmpeg, atracdenc, work, short_frames)
            except (ValueError, BuildError, OSError) as e:
                log("%s: %s" % (os.path.basename(m.name), e))
                done[key] = None
                results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "failed: %s" % e))
                continue
            if len(new) >= m.size:
                done[key] = None
                results.append(sh.ShrinkResult(m.name, m.name, m.size, m.size, "would not get smaller"))
                continue
            with open(p_out, "wb") as f:
                f.write(new)
            replacements.append(Replacement(m, p_out, len(new)))
            done[key] = (p_out, len(new))
            log("%s: %s -> %s KB (%d tracks, %s)" % (os.path.basename(m.name), m.size // 1000, len(new) // 1000, n_tracks, others))
            results.append(sh.ShrinkResult(m.name, m.name, m.size, len(new), "%d sound tracks, others %s" % (n_tracks, others)))
        if not replacements:
            raise BuildError("None of the movies has several sound tracks, so no new game was written.")
        PROGRESS.window(0.85, 0.97)
        PROGRESS.report(0.0, "Writing the new game…")
        total_bytes = img.size
        blocks = _blocks(img, replacements, check_cancel, None, extra)
        tmp = out + ".part"
        try:
            if out.lower().endswith(".iso"):
                with open(tmp, "wb") as f:
                    for n, sec in enumerate(blocks):
                        f.write(sec)
                        if n % 8192 == 0:
                            PROGRESS.report(n / img.sectors)
                    f.truncate(total_bytes)
                os.replace(tmp, out)
                new_size = os.path.getsize(out)
            else:
                new_size = write_cso(blocks, img.sectors, total_bytes, out, level, progress=lambda f: PROGRESS.report(f))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if verify:
            PROGRESS.window(0.97, 1.0)
            PROGRESS.report(0.0, "Checking the new game…")
            problem = _verify(img, out, replacements, check_cancel, None, extra)
            if problem:
                try:
                    os.remove(out)
                except OSError:
                    pass
                raise BuildError("The new game did not pass the check (%s), so it was not kept." % problem)
        PROGRESS.report(1.0)
        results.append(sh.ShrinkResult(src, out, os.path.getsize(src), new_size, "game image"))
        return results
    finally:
        img.close()
        shutil.rmtree(work, ignore_errors=True)


def _verify(old, out_path, replacements, check, removal=None, files=None):
    """None when the new image is the old one with exactly the replaced movies changed (and the UPDATE folder emptied, if that was planned):
    same files at the same places, replaced movies equal to the smaller ones and sized right, every other sector equal to the old one"""
    new = Image(out_path)
    try:
        if new.sectors != old.sectors:
            return "its length changed"
        a = {(e.path, e.extent): e.size for e in walk(old)}
        b = {(e.path, e.extent): e.size for e in walk(new)}
        if removal:
            a = {k: v for k, v in a.items() if k not in {(e.path, e.extent) for e in removal.files}}
            if not any(d[0].upper() == UPDATE_DIR for d in _dirs(new)):
                return "the UPDATE folder itself went missing"
        if set(a) != set(b):
            return "the files or their places changed"
        changed = {}
        for rp in replacements:
            for e in rp.movie.entries:
                changed[(e.path, e.extent)] = rp.new_size
        for ent, data in files or []:
            changed[(ent.path, ent.extent)] = len(data)
        for k, size in b.items():
            if size != changed.get(k, a[k]):
                return "the size of %s is wrong" % k[0]
        patched = {e.rec_sector for rp in replacements for e in rp.movie.entries}
        patched |= {ent.rec_sector for ent, _ in files or []}
        skip = set()
        for rp in replacements:
            skip.update(range(rp.movie.extent, rp.movie.extent + rp.movie.sectors))
        for ent, _ in files or []:
            skip.update(range(ent.extent, ent.extent + -(-ent.size // SECTOR)))
        skip |= patched
        if removal:
            skip |= removal.touched
        for first in range(0, old.sectors, CHUNK):
            n = min(CHUNK, old.sectors - first)
            x, y = old.read(first, n), new.read(first, n)
            for k in range(n):
                if first + k not in skip and x[k * SECTOR:(k + 1) * SECTOR] != y[k * SECTOR:(k + 1) * SECTOR]:
                    return "sector %d changed" % (first + k)
            if (first // CHUNK) % 16 == 0:
                check()
        if removal:
            for n, wanted in removal.extra.items():
                if new.sector(n) != wanted:
                    return "the emptied UPDATE folder was not written right"
            for n in removal.wipe:
                if any(new.sector(n)):
                    return "the sectors of the update files are not empty"
        for rp in replacements:
            data = new.read(rp.movie.extent, rp.movie.sectors)
            with open(rp.path, "rb") as f:
                wanted = f.read()
            if data[:rp.new_size] != wanted or any(data[rp.new_size:]):
                return "a replaced movie (%s) is not what was written" % os.path.basename(rp.movie.name)
        for ent, wanted in files or []:
            data = new.read(ent.extent, -(-ent.size // SECTOR))
            if data[:len(wanted)] != wanted or any(data[len(wanted):]):
                return "a replaced file (%s) is not what was written" % os.path.basename(ent.path)
        return None
    finally:
        new.close()
