# PMF Studio

Make PSP movies, boot movies and AT3 sounds on Windows, and (new in 0.2, experimental) on Linux. No installer and nothing else to download: unzip it and run it.
Its movie engine (`pmfkit`, standard library only) can also be used on its own from the command line: `python -m pmfkit --help`.

<p align="center"><img src="docs/screenshots/gameboot-long-movie.png" alt="Gameboot page: choosing the part of a long movie that fits" width="720"></p>

More: [gameboot built](docs/screenshots/gameboot-built.png), [EBOOT icon](docs/screenshots/eboot-icon.png),
[Shrink game movies](docs/screenshots/shrink.png), [AT3 Tools](docs/screenshots/at3-tools.png), [Extract](docs/screenshots/extract.png), [Player](docs/screenshots/player.png),
[light theme](docs/screenshots/gameboot-light.png). The pictures were made with made-up sample files and a short video of the author's own.

## What it does

- **Gameboot**: turns a movie into the PSP gameboot, fitted to the size the PSP can play. Optionally makes a CTF theme for CXMB,
  and lengthens the boot with your own `opening_plugin.rco`.
- **C-Intro**: a movie for the C-Intro boot plugin.
- **EBOOT icon**: changes the icon movie, the sound, the pictures and the title in a copy of a game's EBOOT.
- **Shrink game movies**: makes a game's own `.pmf` movies smaller (one movie or a whole folder): same names, picture size and
  length, you choose how much of the picture's bitrate to keep (100% to 20%, shown in kbps for your movies) and the sound quality (as it is, or 128 down to 32 kbps). Every result is checked before it is saved.
  Movies with several sound tracks (one per language) keep all of them, or you press Play to hear each track and keep only the ones you want (the others
  stay in their places but empty, so the movies get smaller; the game plays the kept language and is silent under a removed one). You can also pick a whole game (a `.cso` or `.iso` of your own backup): PMF Studio finds
  the movies inside it, shrinks them and writes a new game file in which only the movies changed and every other byte of the disc stays as it was.
  Movies that a game keeps inside one of its own big files (a `movie.bin`, for example) are found too, by their own header, and stay in their places
  (the game finds them by position, so the rest of each place is left empty; in a `.cso` that empty space takes no room).
- **AT3 Tools**: make an AT3 from any sound, shrink an AT3 from a game, or turn an AT3 into a WAV or MP3.
- **Extract**: takes any PMF apart into an MP4 (and its sound as AT3 and WAV).
- **Player**: plays PMF movies and sounds inside the program, with full screen.
- Picks the part of a long movie that fits (a strip with a block you drag), keeps the best quality the size limit allows, shows a
  progress bar for everything that takes time, light and dark themes.
- Drag and drop: drop a movie, EBOOT.PBP, PMF, sound or folder on the window (or on the exe) and it lands in the right box.
  On Linux, drop files on the window, or on the `PMF Studio.desktop` launcher the program writes beside itself, or use *Open with*.
- Self-test on the Options page, with a Copy report button that makes text for a bug report without your folder names or user name.
- Stop button, checks before a job (free space, odd names, saving over your own file), working files cleaned up.
- Updates itself when you ask: downloads the new release, verifies its SHA-256, tests it, swaps it in, and rolls back if that fails.
- C-Intro movies of any length: written to disk a piece at a time, so a 2-hour movie needs no more memory than a 2-minute one.
- Portable: it saves nothing outside its own folder, and you can move or rename the folder.

## Download and use

**Windows:** get `PMF-Studio-<version>-win64.zip` from the Releases page, unzip anywhere, run `PMF Studio.exe`. Windows may warn that the
program isn't signed: choose *More info*, then *Run anyway*. The release notes list the SHA-256 of every file.

**Linux (experimental):** get either `PMF-Studio-<version>-linux-x64.tar.gz` (unpack anywhere, run `./"PMF Studio"`) or
`PMF-Studio-<version>-linux-x64.AppImage` (`chmod +x` it and run it; it keeps its settings and saved files beside the AppImage file, and
updates itself by replacing that file, keeping its name). The 0.2 beta AppImage predates this: download the next one by hand once. Both are 64-bit and need a desktop with X11 or Wayland. The Linux ffmpeg is built from source by `packaging/linux/build_ffmpeg.sh`;
its source and build script are attached to every release as `PMF-Studio-ffmpeg-source.tar.xz`.

## Status

Beta. Everything was checked on one PSP (firmware 6.61 with ARK-5 and CXMB).

Linux is new in 0.2 and experimental. It was tested on Ubuntu 24.04 running inside Windows (WSL2), not on a physical Linux desktop or other
distributions: all the tests pass there, the movie writer and the sound encoder make byte-for-byte the same files as on Windows from the same
input, the finished tar.gz and AppImage pass their self-test, and the updater was tried with a release file on disk (not against a published
release). The player's sound (PulseAudio or PipeWire) and dragging files onto the window (X11 drag and drop, through XWayland on Wayland) were tried there with a recorded sound check and a drag made by a program that follows the protocol, not with a real speaker or a real file manager.

The movie writer follows Sony's own muxer: pack timing, the video buffer (a pack waits until it fits the buffer the movie declares) and
the encoder's buffer limit were matched against about 85 retail movies, whose streams it reproduces byte for byte. 49 of them come out with
the same time stamp on every pack; the rest differ only in a few packs, mostly the last ones, and the older-composer style and
LocoRoco 2's clock are not matched yet. Movies made this way played on the PSP: busy and plain gameboots, game movies with pictures up to 95,545 bytes (the limit), a movie
that ends in a still scene, B-frame movies from LocoRoco 2 (shrunk to 50% and 80%), and a 60-second movie played both in a PMF player and as a
real C-Intro with the C-Intro plugin. Five whole games shrunk to 50% picture (Battlezone, Coded Arms, Hammerin Hero, HISTORY Ice Road
Truckers, Hot Shots Shorties) played on the PSP, and on a PC emulator, at least two movies each; not every movie in them was played.
Queen's Gate: Spiral Chaos keeps its 13 movies inside one file (`movie.bin`). Shrunk to 50% picture, its opening movie played all the way through on the PSP, and
three more of its movies (the longest, the shortest and the last) also played through when put in the opening's place; the other nine were not played on the PSP,
only checked on the PC. Monster Hunter Portable 3rd keeps 12 movies inside `DATA.BIN`; they are found, but that game was not shrunk or played.

Keeping only some sound tracks of a game's movies works in 007 From Russia With Love: shrunk with only the second language kept, the movies played silent with the PSP set to English and played in French with it set to French. The PMF players that play only the first sound track (such as the OneLua player) play silence if you remove the first track. Once, quitting a movie through the HOME button crashed the PSP; the same movie was quit three more times and played to the end without a problem, so it was not reproduced and its cause is unknown (possibly the custom firmware).
Not tested on a real PSP: the updater (it needs a published release) and the files these tools produce on other firmware.

Smaller game movies have run inside real games: 007 From Russia With Love and Family Guy at 50% picture, and Gun Showdown,
shrunk with the whole game at the lowest picture (20%) and sound (32 kbps) settings, played through its start-up logos and the
first Story movies. Shrinking keeps each movie built the way the game's own movie was (B-frames or not, reference frames, where
the pictures start, buffer sizes, jump-point list) and changes only the bitrate. An earlier build that forced B-frames and
2 reference frames at the lowest picture setting crashed Gun Showdown, so that is not offered in the window. Whether a given
game accepts smaller movies is still up to the game: try the new game before you delete anything, and start with a milder
choice if it fails. When it shrinks a whole game it also empties Sony's UPDATE folder (the firmware-update offer, useless on
custom firmware) and never touches the game's XMB icon. The size limits come from tests on that PSP and may differ on other setups.

## Running from the source

Needs Python 3.12 with Tk (standard library only for the program itself), plus `ffmpeg` and `atracdenc` (`.exe` on Windows) in a `tools` folder
or on the PATH. Start it with `python -m pmfstudio`. Tests: `python -W ignore -m unittest discover -s tests -t .`.
`python packaging/build_release.py` builds the release folder and its archive on the system it runs on (see the notes at the top of that file;
on Linux, `packaging/linux/` has the scripts that set up a private build environment and build ffmpeg, and `tools/atracdenc/README.txt` says how
to build atracdenc).

## Credits

Built with help from Claude (Anthropic); designed and tested by Mr-Shizzy.

## Licence

PMF Studio is copyright (C) 2026 Mr-Shizzy and released under the GNU General Public License, version 3 (see `LICENSE`): you may use, share and
change it, but a program built from it must stay open under the same licence, with credit kept. The release also contains FFmpeg (GPL) and atracdenc
(LGPL-2.1), which keep their own licences: see `THIRD_PARTY_NOTICES.txt`. Not affiliated with Sony. Includes no copyrighted game
content: bring your own files.
