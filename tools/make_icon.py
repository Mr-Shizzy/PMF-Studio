"""Draws the PMF Studio icon (a film frame with a play triangle) and writes pmfstudio/assets/icon.ico and icon.png.

    python tools/make_icon.py

Needs Pillow (only for making the icon; the program itself does not use it). The files it writes are committed.
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "pmfstudio", "assets")
BIG = 1024                                              # drawn large, then shrunk for smooth edges


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw():
    img = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    # rounded square with a top-to-bottom blue gradient (the program's accent colour)
    grad = Image.new("RGBA", (BIG, BIG))
    top, bottom = (110, 170, 255), (38, 92, 200)
    gp = grad.load()
    for y in range(BIG):
        c = lerp(top, bottom, y / (BIG - 1))
        for x in range(BIG):
            gp[x, y] = c + (255,)
    mask = Image.new("L", (BIG, BIG), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, BIG - 32, BIG - 32), radius=210, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # film strip holes down both sides
    hole = (255, 255, 255, 235)
    for i in range(5):
        y = 150 + i * 160
        d.rounded_rectangle((92, y, 152, y + 90), radius=16, fill=hole)
        d.rounded_rectangle((BIG - 152, y, BIG - 92, y + 90), radius=16, fill=hole)
    # the picture area, dark, with a white play triangle
    d.rounded_rectangle((210, 190, BIG - 210, BIG - 190), radius=70, fill=(20, 28, 48, 255))
    cx, cy, r = BIG // 2 + 28, BIG // 2, 175
    d.polygon([(cx - r * 0.78, cy - r), (cx - r * 0.78, cy + r), (cx + r * 1.1, cy)], fill=(255, 255, 255, 255))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    # Pillow writes the ICO from the largest image and shrinks it for each size
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.ico"), sizes=[(s, s) for s in sizes])
    print("wrote", os.path.join(OUT, "icon.ico"), "and icon.png")


if __name__ == "__main__":
    main()
