Throwaway analysis scripts from the first session, kept so the evidence in RESEARCH_NOTES.md can be re-checked.
Most find the project folder from their own location (tools\analysis inside the project); some import each other via %TEMP%\scr
(copy them there) or expect sample files in local-only folders that are not in the repository. Not part of pmfkit.

survey.py     header version/PTS/audio table of every PMF in the gameboot pack (notes section 13)
an2.py        sector-by-sector dump, audio pointer/PTS checks     an3.py  video PES stamping + GOP index   an4.py  audio packet headers
remux_all.py  re-mux every gameboot's own streams with pmfkit and count identical packs (the oracle test)
diffpk.py     which packs differ for one file                     seq.py  V/A/G pack-order strings, orig vs ours
scrfit*.py    fits for the SCR (send time) rule                    sps.py  early SPS/PPS parser (now pmfkit/sps.py)

Regenerate the synthetic test source (3 s, 640x360, tone):
  ffmpeg -f lavfi -i testsrc2=size=640x360:rate=30000/1001:duration=3 -f lavfi -i sine=f=440:d=3:sample_rate=44100 -c:v libx264 -c:a aac src.mp4
Beep tone used for the loudness retests:
  ffmpeg -f lavfi -i sine=f=660:beep_factor=4:duration=3:sample_rate=44100 -ac 2 beep.wav
Audio length is NOT a constraint (G series), the PSP only needs 1 ref frame and audio units <= 2016 bytes.
