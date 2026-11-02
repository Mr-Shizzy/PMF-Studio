"""Makes pmfstudio/assets/icon.ico and icon.png from the artwork in pmfstudio/assets/icon-source.png.

    python tools/make_icon.py [new artwork file]

Giving a new artwork file replaces icon-source.png (it is cut to a square, rounded at the corners and saved at 1024 px).
Needs Pillow (only for making the icon; the program itself does not use it). The files it writes are committed.
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "pmfstudio", "assets")
SOURCE = os.path.join(OUT, "icon-source.png")
SIZES = [16, 24, 32, 48, 64, 128, 256]
INSET, RADIUS = 0.006, 0.19                             # where the artwork's own rounded edge sits, as a share of its width


def rounded(img):
    """transparent corners: the artwork is a rounded square on a dark square"""
    n = img.width
    big = n * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((INSET * big, INSET * big, big - INSET * big, big - INSET * big), radius=RADIUS * big, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize((n, n), Image.LANCZOS))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1:
        art = Image.open(sys.argv[1]).convert("RGB")
        side = min(art.size)
        art = art.crop(((art.width - side) // 2, (art.height - side) // 2, (art.width + side) // 2, (art.height + side) // 2))
        art.resize((1024, 1024), Image.LANCZOS).save(SOURCE, optimize=True)
    art = rounded(Image.open(SOURCE))
    art.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"), optimize=True)
    frames = [art.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(os.path.join(OUT, "icon.ico"), sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print("wrote icon.ico and icon.png from", SOURCE)


if __name__ == "__main__":
    main()
