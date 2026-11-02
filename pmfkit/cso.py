"""CSO (compressed ISO) files: reading sectors without unpacking the image, and writing one.

CSO v1: 'CISO', u32 header size (unreliable: some writers leave 0), u64 size of the ISO, u32 block size (2048), u8 version, u8 index shift, 2 spare
bytes; then (blocks + 1) u32 offsets (bit 31 set = the block is stored as it is, otherwise raw deflate; the offset is shifted left by the index
shift; a block's data ends where the next block's starts; the last entry is the end of the data)."""
import os
import struct
import zlib

SECTOR = 2048


class Cso:
    def __init__(self, path):
        self.f = open(path, "rb")
        head = self.f.read(24)
        if head[:4] != b"CISO":
            self.f.close()
            raise ValueError("not a CSO file")
        self.header, self.total, self.block, self.version, self.shift = struct.unpack("<IQIBB", head[4:22])
        self.blocks = -(-self.total // self.block)
        self.header = self.header or 24                     # some writers leave the header size at 0
        self.f.seek(self.header)
        self.index = struct.unpack("<%dI" % (self.blocks + 1), self.f.read(4 * (self.blocks + 1)))

    def close(self):
        self.f.close()

    def sector(self, n):
        a, b = self.index[n], self.index[n + 1]
        start, end = (a & 0x7FFFFFFF) << self.shift, (b & 0x7FFFFFFF) << self.shift
        self.f.seek(start)
        raw = self.f.read(end - start)
        if a & 0x80000000:
            return raw[:self.block]
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:                      # some writers pad a block; the deflate stream still ends by itself
            return zlib.decompressobj(-15).decompress(raw)

    def read(self, first, count):
        return b"".join(self.sector(first + i) for i in range(count))


def write_cso(blocks, nblocks, total_bytes, cso_path, level=9, progress=None, cancelled=lambda: False):
    """blocks: an iterator of nblocks chunks of 2048 bytes -> CSO v1 (header size 0x18, no index shift, raw deflate, a block that doesn't get
    smaller is stored as it is). Written to a .part file and renamed when complete. -> size of the CSO in bytes"""
    block = SECTOR
    if total_bytes + 24 + 4 * (nblocks + 1) >= 1 << 31:
        raise ValueError("this image is too big for a CSO without an index shift (over 2 GB)")
    index = []
    tmp = cso_path + ".part"
    try:
        with open(tmp, "wb") as out:
            out.write(b"\0" * (24 + 4 * (nblocks + 1)))                 # header and index go here at the end
            for n, data in enumerate(blocks):
                if len(data) < block:
                    data = data.ljust(block, b"\0")                      # the last block is padded, as other writers do
                co = zlib.compressobj(level, zlib.DEFLATED, -15)
                packed = co.compress(data) + co.flush()
                pos = out.tell()
                if len(packed) < block:
                    index.append(pos)
                    out.write(packed)
                else:
                    index.append(pos | 0x80000000)
                    out.write(data)
                if n % 4096 == 0:
                    if cancelled():
                        raise InterruptedError("stopped")
                    if progress:
                        progress(n / max(nblocks, 1))
            if len(index) != nblocks:
                raise ValueError("the image gave %d sectors, expected %d" % (len(index), nblocks))
            index.append(out.tell())
            out.seek(0)
            out.write(b"CISO" + struct.pack("<IQIBB", 24, total_bytes, block, 1, 0) + b"\0\0")
            out.write(struct.pack("<%dI" % (nblocks + 1), *index))
            size = out.seek(0, 2)
        os.replace(tmp, cso_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return size


def compress(iso_path, cso_path, level=9, progress=None):
    """ISO file -> CSO file. -> size of the CSO in bytes"""
    total = os.path.getsize(iso_path)
    nblocks = -(-total // SECTOR)

    def blocks():
        with open(iso_path, "rb") as f:
            while True:
                data = f.read(SECTOR)
                if not data:
                    return
                yield data
    return write_cso(blocks(), nblocks, total, cso_path, level, progress)
