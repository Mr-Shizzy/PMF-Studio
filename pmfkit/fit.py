"""How long a clip can be for each target, before the picture has to look bad (or no longer fits at all).

The size budgets are the measured ones (RESEARCH_NOTES.md): a gameboot movie up to about 3.03 MB, an ICON1 movie plus its sound up to
512,000 bytes. The quality thresholds (video kbps that still looks good / still acceptable) are judgement calls, kept in one place to tune.
"""
from .mux import ICON1_MAX_BYTES, ICON1_AUDIO_KBPS
from .gameboot import BUDGET_BYTES

OVERHEAD = 0.05                      # packaging and index bytes on top of the pictures and the sound
FAT32_LIMIT = 3900000000             # a memory stick is FAT32: files must stay under 4 GB
CINTRO_KBPS = 2000 + 128             # what the C-Intro job writes (video + sound)

TARGETS = {
    "gameboot": dict(budget=BUDGET_BYTES, good=300, soft=100),     # 480x272
    "icon": dict(budget=ICON1_MAX_BYTES, good=50, soft=20),        # 144x80
}


def pick_audio_kbps(seconds, wanted, budget):
    """highest of 128/96/64/48/32 (not above `wanted`) whose sound takes at most 35% of the budget"""
    for kbps in (128, 96, 64, 48, 32):
        if kbps <= wanted and seconds * kbps * 125 <= 0.35 * budget:
            return kbps
    return 32


def video_kbps(target, seconds, sound_bytes=None):
    """video bitrate left for a clip of this length once the sound is paid for"""
    t = TARGETS[target]
    if target == "gameboot":
        sound = seconds * pick_audio_kbps(seconds, 128, t["budget"]) * 125
    else:
        sound = sound_bytes if sound_bytes is not None else seconds * ICON1_AUDIO_KBPS * 125
    return (t["budget"] * (1 - OVERHEAD) - sound) * 8 / max(seconds, 0.1) / 1000


def verdict(target, seconds, sound_bytes=None):
    """'good', 'soft' (fits but looks soft) or 'toolong'"""
    if target == "cintro":
        return "toolong" if CINTRO_KBPS * 125 * seconds > FAT32_LIMIT else "good"
    kbps = video_kbps(target, seconds, sound_bytes)
    t = TARGETS[target]
    return "good" if kbps >= t["good"] else "soft" if kbps >= t["soft"] else "toolong"


def limits(target, sound_bytes=None):
    """-> (longest clip in seconds that still looks good, longest that fits at all)"""
    if target == "cintro":
        return FAT32_LIMIT / (CINTRO_KBPS * 125), FAT32_LIMIT / (CINTRO_KBPS * 125)
    out = []
    for want in ("good", "soft"):
        lo, hi = 0.0, 7200.0
        if verdict(target, 0.5, sound_bytes) == "toolong" or (want == "good" and verdict(target, 0.5, sound_bytes) != "good"):
            out.append(0.0)
            continue
        for _ in range(40):
            mid = (lo + hi) / 2
            ok = verdict(target, mid, sound_bytes) == "good" if want == "good" else verdict(target, mid, sound_bytes) != "toolong"
            lo, hi = (mid, hi) if ok else (lo, mid)
        out.append(lo)
    return out[0], out[1]
