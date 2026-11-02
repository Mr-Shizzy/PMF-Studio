"""Colours (light and dark) and screen scale, shared by every part of the window."""
from types import SimpleNamespace

LIGHT = dict(bg="#ffffff", side="#f4f4f2", line="#d9d9d5", ink="#1d1d1b", muted="#6b6b66", accent="#2f6fdb", shine="#9fc2ff",
             warn_bg="#fff4d6", warn_ink="#7a5200", hover="#ebebe7", sel="#e4e4e0", btn="#e8e8e4", go="#1d1d1b", go_ink="#ffffff", go_hover="#3a3a37",
             on_accent="#ffffff")
DARK = dict(bg="#1e1e1c", side="#262624", line="#3b3b38", ink="#ecece8", muted="#a0a09a", accent="#5b9bff", shine="#5b9bff",
            warn_bg="#3d3317", warn_ink="#f1d28a", hover="#2f2f2c", sel="#34342f", btn="#3a3a37", go="#ecece8", go_ink="#1d1d1b", go_hover="#ffffff",
            on_accent="#0d1b33")
T = SimpleNamespace(scale=1.0, **LIGHT)


def S(n):
    return int(n * T.scale)


def set_scale(value):
    T.scale = value


def set_theme(dark):
    for k, v in (DARK if dark else LIGHT).items():
        setattr(T, k, v)


def mix(a, b, t):
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))
