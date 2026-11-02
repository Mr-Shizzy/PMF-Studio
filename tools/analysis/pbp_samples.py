"""Round-trip and ICON1-injection check of every .PBP in 'EBOOT samples' (local-only, copyrighted files).
usage (from the project folder): python tools/analysis/pbp_samples.py"""
import glob
import os
import sys

sys.path.insert(0, ".")
from pmfkit.pbp import Pbp, NAMES

icon1 = open("test_output/icon1/I4_icon1_audio64.pmf", "rb").read()
for f in sorted(glob.glob("EBOOT samples/**/*.PBP", recursive=True)):
    raw = open(f, "rb").read()
    orig = Pbp.parse(raw)
    print(f, "- round trip exact:", orig.to_bytes() == raw)
    p = Pbp.parse(raw)
    p.replace("ICON1", icon1)
    pad = p.realign()
    out = Pbp.parse(p.to_bytes())
    same = [n for n, x, y in zip(NAMES, orig.sections, out.sections) if x == y]
    print("   pad %d, DATA.PSAR offset old 0x%X new 0x%X" % (pad, orig.offsets()[7], out.offsets()[7]))
    print("   byte-identical sections:", same)
    print("   DATA.PSP identical apart from trailing zeros:",
          out.sections[6].rstrip(bytes(1)) == orig.sections[6].rstrip(bytes(1)))
