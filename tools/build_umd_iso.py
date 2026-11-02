"""Build a PSP game ISO (ISO 9660) from an extracted game folder and the file list UMDGen exports ("LBA , \\path" per line),
putting every file at the sector the list gives, so a game that depends on file positions still works. (The code is pmfkit/umdbuild.py.)

    python tools/build_umd_iso.py GAME_FOLDER FILE_LIST.txt OUT.iso [--replace FOLDER ...] [--template ORIGINAL.cso|.iso]

--replace FOLDER    files in FOLDER (found by their path below GAME_FOLDER, or for movies by name) are used instead of the game's own; a replacement
                    must not be larger than the original (it has to fit where the list puts the file).
--template IMAGE    the game's own disc image (a CSO or ISO): its first 16 sectors and the identity fields of its volume descriptor are copied.
Then `python tools/cso.py compress OUT.iso OUT.cso` makes the smaller CSO. (To shrink the movies of a game you already have as a CSO/ISO,
the Shrink page's 'A game' button or `pmfkit shrink GAME.cso -o NEW.cso` works on the image itself and needs neither this nor a file list.)"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pmfkit.umdbuild import XA_DIR, XA_FILE, build, sequential_list  # noqa: E402,F401

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("file_list")
    ap.add_argument("out")
    ap.add_argument("--replace", action="append", default=[])
    ap.add_argument("--template")
    a = ap.parse_args()
    build(a.game.rstrip("\\"), a.file_list, a.out, a.replace, a.template)
