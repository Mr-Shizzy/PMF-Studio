"""Gameboot facts measured on a real PSP (6.61 ARK-5 with CXMB; RESEARCH_NOTES.md sections 71-77)."""
STOCK_SECONDS = 2.5                 # what the firmware plays unless opening_plugin.rco is patched
BUDGET_BYTES = 3030000              # size budget for gameboot.pmf (picture + sound), chosen just below the largest size that played
VERIFIED_OK_BYTES = 3065856         # largest gameboot.pmf shown to play
VERIFIED_FAIL_BYTES = 3280896       # smallest size shown NOT to play (4.0 and 4.3 MB also failed)
# Length is not limited, only size: a 30 s movie of 1.47 MB played; a 12 s one of 4.0 MB did not.


def movie_ms(pmf):
    """length of a PMF in milliseconds, rounded up to 100 ms (counted from the streams, not the header times)"""
    from .demux import demux, duration_seconds
    _, v, a, _ = demux(pmf)
    return int(-(-duration_seconds(v, a) * 1000 // 100) * 100)
