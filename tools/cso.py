"""Read sectors out of a CSO (compressed ISO) and make a CSO from an ISO. (The code lives in pmfkit/cso.py.)

    python tools/cso.py FILE.cso FIRST_SECTOR COUNT OUT.bin     # raw bytes of those sectors
    python tools/cso.py FILE.cso --info
    python tools/cso.py compress IN.iso OUT.cso [LEVEL]         # ISO -> CSO v1"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pmfkit.cso import Cso, compress  # noqa: E402,F401

if __name__ == "__main__":
    if sys.argv[1] == "compress":
        n = compress(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 9)
        print("wrote %s: %.1f MB (the ISO was %.1f MB)" % (sys.argv[3], n / 1e6, os.path.getsize(sys.argv[2]) / 1e6))
        sys.exit(0)
    c = Cso(sys.argv[1])
    if "--info" in sys.argv:
        print("CSO v%d: ISO of %d bytes (%d sectors of %d), index shift %d, header %d" % (c.version, c.total, c.blocks, c.block, c.shift, c.header))
    else:
        open(sys.argv[4], "wb").write(c.read(int(sys.argv[2]), int(sys.argv[3])))
