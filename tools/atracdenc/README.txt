atracdenc patches for pmfkit
============================

atracdenc (https://github.com/dcherednik/atracdenc, LGPL-2.1) is the open ATRAC3plus encoder we use for PMF audio.
The upstream source is NOT stored here; only our two small patches against commit BASE_COMMIT.txt are.
The patches are derivative works of atracdenc and fall under the same LGPL-2.1 licence.

frame-size.patch
  Lets the ATRAC3plus encoder use a smaller frame size via the environment variable AT3P_FRAME (bytes, default 2048).
  Upstream is hard-wired to 2048 bytes = 352 kbps. A real PSP plays NO sound from a PMF with 352 kbps audio (the
  8-byte unit header + 2048 bytes no longer fits one 2048-byte pack), but plays 128 kbps (744 bytes) and 96 kbps
  (560 bytes). pmfkit sets AT3P_FRAME itself (see --audio-kbps).

tonal-trim.patch   (apply after frame-size.patch)
  Small frames (32 kbps = 192 bytes) made upstream abort with "TODO" when a frame had more tone bands than quant units
  (it stopped at about 116 s of a 120 s clip). The patch drops the highest tone bands and re-writes the tonal part instead.
  With it a 120 s clip encodes in full at 192 bytes per frame. Needed for 32 kbps; 48 kbps and up never hit the abort.

windows-no-libsndfile.patch
  Only needed to build with clang/ninja on Windows without libsndfile: replaces the PCM I/O backend with a tiny
  16-bit PCM WAV reader/writer. Skip it if you build with libsndfile or with MSVC (Media Foundation backend).

Build (the exact recipe used for the binary that ships; Windows, clang + cmake + ninja):
  git clone --recurse-submodules <upstream>; git checkout <BASE_COMMIT>
  git apply frame-size.patch tonal-trim.patch windows-no-libsndfile.patch
  cmake -S src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release ^
        -DCMAKE_CXX_FLAGS="-ffile-prefix-map=<source dir>=src -fmacro-prefix-map=<source dir>=src -fdebug-prefix-map=<source dir>=src" ^
        -DCMAKE_C_FLAGS="-ffile-prefix-map=<source dir>=src" -DCMAKE_EXE_LINKER_FLAGS="-static -s"
  cmake --build build
After building, check that the build has ALL the patches: `git status` in the source folder must list at3p.cpp, at3p_bitstream.cpp and
at3p_bitstream_impl.h as modified, and `python -m unittest tests.test_atrac_low_kbps` must pass (a build without tonal-trim.patch stops
with "TODO" at 32 and 48 kbps on busy sound; the build shipped on 2026-11-01 lacked it until this was caught on 2026-11-02).
The prefix-map flags keep the build folder (and so the builder's user name) out of the program; -static -s links the C++ runtime in
(no libunwind.dll to carry along) and strips symbols. The result needs only the Windows 10 system libraries.
Verified: this build writes byte-identical OMA files to the earlier one.
Do not commit the built atracdenc.exe or the upstream source.
