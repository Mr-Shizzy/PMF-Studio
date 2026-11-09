#!/bin/bash
# Builds the ffmpeg that PMF Studio ships on Linux, from official source tarballs, as one static program:
#   FFmpeg 9.0.2 with libx264 (H.264 encoder), libmp3lame (MP3 encoder), libdav1d (AV1 decoder) and zlib; everything else is FFmpeg's own code.
# Nothing is installed system-wide: all work happens in $PMF_FFMPEG_BUILD (default /var/tmp/pmf_ffmpeg_build). It needs gcc, make, perl, curl, gpg
# and the private build environment from setup_build_env.sh (meson and ninja for dav1d). nasm is built here from source.
# Every download is checked against a pinned SHA-256 (FFmpeg's is also checked against its signature).
# Result: tools/ffmpeg in the project (not committed), packaging/linux/ffmpeg-licenses/ (licence texts, committed), and a source bundle
# ($WORK/PMF-Studio-ffmpeg-source.tar.xz) to attach to each release, which is how the GPL's source offer is met.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/../.." && pwd)"
WORK="${PMF_FFMPEG_BUILD:-/var/tmp/pmf_ffmpeg_build}"      # a folder whose name holds no user name: ffmpeg writes its build folder into itself
SRC="$WORK/src"
PREFIX="$WORK/prefix"
TOOLS="$WORK/tools"
JOBS="$(nproc)"
mkdir -p "$SRC" "$PREFIX" "$TOOLS/bin"
export PATH="$TOOLS/bin:${PMF_BUILD:-$HOME/pmf_build}/venv/bin:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

FFMPEG=ffmpeg-9.0.2;  FFMPEG_SHA=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
X264_COMMIT=b35605ace3ddf7c1a5d67a2eb553f034aef41d55;  X264_SHA=6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224
LAME=lame-3.100;      LAME_SHA=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
ZLIB=zlib-1.3.1;      ZLIB_SHA=38ef96b8dfe510d42707d9c781877914792541133e1870841463bfa73f883e32
DAV1D=dav1d-1.5.4;    DAV1D_SHA=686616b7c69eb88d44459391ab25cac13b6647a3b288835c5784e71c1514a5c5
NASM=nasm-2.16.03;    NASM_SHA=1412a1c760bbd05db026b6c0d1657affd6631cd0a63cddb6f73cc6d4aa616148
FFMPEG_KEY=FCF986EA15E6E293A5644F10B4322F04D67658D8      # FFmpeg's release signing key

fetch() {   # file url sha256
  if [ ! -s "$SRC/$1" ]; then curl -fsSL --retry 3 -o "$SRC/$1" "$2"; fi
  echo "$3  $SRC/$1" | sha256sum -c - >/dev/null || { echo "CHECKSUM MISMATCH: $1" >&2; exit 1; }
  echo "ok  $1"
}
unpack() {  # file -> folder in $WORK/build
  rm -rf "$WORK/build/$2"; mkdir -p "$WORK/build"; tar -xf "$SRC/$1" -C "$WORK/build"
}

fetch "$FFMPEG.tar.xz" "https://ffmpeg.org/releases/$FFMPEG.tar.xz" "$FFMPEG_SHA"
fetch "$FFMPEG.tar.xz.asc" "https://ffmpeg.org/releases/$FFMPEG.tar.xz.asc" "d617fd94ea354dadd2a8bb16243d37c44e1e9729b06b6ad58fe30bfb0fa943f2"
fetch ffmpeg-devel.asc "https://ffmpeg.org/ffmpeg-devel.asc" "397b3becedcd5a98769967ff1ff8501ddc89f8368b8f766e4701377d7dbaabe5"
fetch "x264-$X264_COMMIT.tar.bz2" "https://code.videolan.org/videolan/x264/-/archive/$X264_COMMIT/x264-$X264_COMMIT.tar.bz2" "$X264_SHA"
fetch "$LAME.tar.gz" "https://downloads.sourceforge.net/project/lame/lame/3.100/$LAME.tar.gz" "$LAME_SHA"
fetch "$ZLIB.tar.xz" "https://github.com/madler/zlib/releases/download/v1.3.1/$ZLIB.tar.xz" "$ZLIB_SHA"
fetch "$DAV1D.tar.xz" "https://downloads.videolan.org/pub/videolan/dav1d/1.5.4/$DAV1D.tar.xz" "$DAV1D_SHA"
fetch "$NASM.tar.xz" "https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/$NASM.tar.xz" "$NASM_SHA"

GNUPGHOME="$(mktemp -d)"; export GNUPGHOME; chmod 700 "$GNUPGHOME"
gpg --quiet --import "$SRC/ffmpeg-devel.asc" 2>/dev/null
gpg --status-fd 1 --verify "$SRC/$FFMPEG.tar.xz.asc" "$SRC/$FFMPEG.tar.xz" 2>/dev/null | grep -q "VALIDSIG $FFMPEG_KEY" \
  || { echo "FFmpeg's signature does not check out" >&2; exit 1; }
echo "ok  FFmpeg's signature is valid (key $FFMPEG_KEY)"

if [ ! -x "$TOOLS/bin/nasm" ]; then
  unpack "$NASM.tar.xz" "$NASM"; cd "$WORK/build/$NASM"
  ./configure --prefix="$TOOLS" >/dev/null; make -j"$JOBS" nasm ndisasm >/dev/null
  cp nasm ndisasm "$TOOLS/bin/"
fi
echo "nasm: $(nasm -v)"

build_zlib() { unpack "$ZLIB.tar.xz" "$ZLIB"; cd "$WORK/build/$ZLIB"; ./configure --prefix="$PREFIX" --static >/dev/null; make -j"$JOBS" >/dev/null; make install >/dev/null; }
build_x264() { unpack "x264-$X264_COMMIT.tar.bz2" "x264-$X264_COMMIT"; cd "$WORK/build/x264-$X264_COMMIT"
  ./configure --prefix="$PREFIX" --enable-static --disable-cli --disable-opencl --enable-pic >/dev/null; make -j"$JOBS" >/dev/null; make install >/dev/null; }
build_lame() { unpack "$LAME.tar.gz" "$LAME"; cd "$WORK/build/$LAME"
  ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-frontend --with-pic >/dev/null; make -j"$JOBS" >/dev/null; make install >/dev/null; }
build_dav1d() { unpack "$DAV1D.tar.xz" "$DAV1D"; cd "$WORK/build/$DAV1D"
  meson setup build --prefix="$PREFIX" --libdir=lib --default-library=static --buildtype=release -Denable_tools=false -Denable_tests=false >/dev/null
  ninja -C build install >/dev/null; }
[ -f "$PREFIX/lib/libz.a" ] || build_zlib;        echo "built zlib"
[ -f "$PREFIX/lib/libx264.a" ] || build_x264;     echo "built x264"
[ -f "$PREFIX/lib/libmp3lame.a" ] || build_lame;  echo "built lame"
[ -f "$PREFIX/lib/libdav1d.a" ] || build_dav1d;   echo "built dav1d"

if [ ! -x "$WORK/build/$FFMPEG/ffmpeg" ]; then          # (a build that already finished is not repeated)
  unpack "$FFMPEG.tar.xz" "$FFMPEG"; cd "$WORK/build/$FFMPEG"
  ./configure --prefix="$PREFIX" --pkg-config-flags=--static \
    --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -static" --extra-libs="-lpthread -lm" \
    --enable-gpl --enable-libx264 --enable-libmp3lame --enable-libdav1d --enable-zlib \
    --disable-autodetect --disable-network --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
    --enable-static --disable-shared > "$WORK/ffmpeg-configure.log" 2>&1 || { tail -30 "$WORK/ffmpeg-configure.log"; exit 1; }
  make -j"$JOBS" >/dev/null 2>"$WORK/ffmpeg-make-warnings.log"
fi
cd "$WORK/build/$FFMPEG"
strip -o "$WORK/ffmpeg-stripped" ffmpeg
cp "$WORK/ffmpeg-stripped" "$PROJECT/tools/ffmpeg"
chmod 755 "$PROJECT/tools/ffmpeg"

# licence texts that ship with the program (committed)
L="$HERE/ffmpeg-licenses"; mkdir -p "$L"
cp "$WORK/build/$FFMPEG/COPYING.GPLv2" "$L/ffmpeg-COPYING.GPLv2.txt"
cp "$WORK/build/$FFMPEG/COPYING.LGPLv2.1" "$L/ffmpeg-COPYING.LGPLv2.1.txt"
cp "$WORK/build/$FFMPEG/LICENSE.md" "$L/ffmpeg-LICENSE.md"
cp "$WORK/build/x264-$X264_COMMIT/COPYING" "$L/x264-COPYING.txt"
cp "$WORK/build/$LAME/COPYING" "$L/lame-COPYING.txt"
cp "$WORK/build/$DAV1D/COPYING" "$L/dav1d-COPYING.txt"
sed -n '/(C) 1995-/,/madler@alumni.caltech.edu/p' "$WORK/build/$ZLIB/zlib.h" > "$L/zlib-LICENSE.txt"

# the source bundle: the exact tarballs this program was built from and this recipe
B="$WORK/PMF-Studio-ffmpeg-source"; rm -rf "$B"; mkdir -p "$B"
cp "$SRC/$FFMPEG.tar.xz" "$SRC/$FFMPEG.tar.xz.asc" "$SRC/x264-$X264_COMMIT.tar.bz2" "$SRC/$LAME.tar.gz" "$SRC/$ZLIB.tar.xz" "$SRC/$DAV1D.tar.xz" "$B/"
cp "$HERE/build_ffmpeg.sh" "$B/"
"$PROJECT/tools/ffmpeg" -version | sed -n '1p;3p' > "$B/configuration.txt"
tar -cJf "$WORK/PMF-Studio-ffmpeg-source.tar.xz" -C "$WORK" PMF-Studio-ffmpeg-source
echo
"$PROJECT/tools/ffmpeg" -version | head -3
ls -l "$PROJECT/tools/ffmpeg" "$WORK/PMF-Studio-ffmpeg-source.tar.xz"
file "$PROJECT/tools/ffmpeg" | cut -c1-160
