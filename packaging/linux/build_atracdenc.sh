#!/bin/bash
# Builds atracdenc for Linux from the upstream source plus PMF Studio's patches (the recipe in tools/atracdenc/README.txt), as one static
# program: tools/atracdenc/bin/atracdenc (not committed). The upstream source stays in $PMF_ATRAC_BUILD (default
# /var/tmp/pmf_atracdenc_build: a folder with no user name in its path). Needs git, cmake, g++ and make. Run it from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/../.." && pwd)"
PATCHES="$PROJECT/tools/atracdenc"
WORK="${PMF_ATRAC_BUILD:-/var/tmp/pmf_atracdenc_build}"
BASE="$(tr -d '\r\n ' < "$PATCHES/BASE_COMMIT.txt")"
rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"
git clone --quiet --recurse-submodules https://github.com/dcherednik/atracdenc src
cd src
git checkout --quiet "$BASE"
git submodule update --init --recursive --quiet
for p in frame-size tonal-trim adaptive-precision windows-no-libsndfile; do      # all four, on every system (the last one only swaps the sound-file reader)
  git apply --whitespace=nowarn "$PATCHES/$p.patch"
  echo "applied $p.patch"
done
git status --short
cmake -S src -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-ffile-prefix-map=$WORK/src=src -fmacro-prefix-map=$WORK/src=src -fdebug-prefix-map=$WORK/src=src" \
  -DCMAKE_C_FLAGS="-ffile-prefix-map=$WORK/src=src" -DCMAKE_EXE_LINKER_FLAGS="-static -s" > "$WORK/cmake.log" 2>&1
cmake --build build -j"$(nproc)" --target atracdenc > "$WORK/make.log" 2>&1      # only the encoder: upstream's demo tools in lib/libgha do not link statically
mkdir -p "$PATCHES/bin"
cp build/atracdenc "$PATCHES/bin/atracdenc"
chmod 755 "$PATCHES/bin/atracdenc"
ls -l "$PATCHES/bin/atracdenc"
sha256sum "$PATCHES/bin/atracdenc"
