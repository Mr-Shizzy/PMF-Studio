#!/bin/bash
# Builds tkdnd (drag and drop for Tk on X11) against the Tk 9.0 of the build Python, and puts the result in tools/tkdnd/
# (libtkdnd2.9.5.so + its Tcl scripts + licence texts). Run in WSL/Linux from the project folder.
#
# Sources (official, checked by hash; downloaded once to ~/pmf_build/downloads/tkdnd):
#   tkdnd 2.9.5  https://github.com/petasis/tkdnd/archive/refs/tags/tkdnd-release-test-v2.9.5.tar.gz   (Tcl-style licence, GPL-compatible)
#   Tcl 9.0.4    https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tcl9.0.4-src.tar.gz           (Tcl licence; only its headers and stub code are used)
#   Tk 9.0.4     https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tk9.0.4-src.tar.gz            (Tk licence; its headers, bundled X11 headers and stub code)
# The result links to the system's libX11.so.6 only (every X11 desktop and XWayland has it). No system development packages are needed:
# the X11 headers come with the Tk source. The build folder is outside the user's home so no user name is written into the file.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
DL="${PMF_TKDND_DOWNLOADS:-$HOME/pmf_build/downloads/tkdnd}"
WORK=/var/tmp/pmf_tkdnd_build
OUT="$HERE/tools/tkdnd"
VER=2.9.5
declare -A SHA=(
  [tkdnd-2.9.5.tar.gz]=7ab2d1d7c0f57a5dc7f6d5542895b44762a31a01621c9d7f80f3bbd67c7bcc39
  [tcl9.0.4-src.tar.gz]=d0aed49230bc02a65c1e0229e65f34590a4b037ec40d546f32573b467f7551ea
  [tk9.0.4-src.tar.gz]=d7a146d2917eb8b5cc95276dbf0e3d03c7464d2b19c1675357857c989301dbb4
)
declare -A URL=(
  [tkdnd-2.9.5.tar.gz]=https://github.com/petasis/tkdnd/archive/refs/tags/tkdnd-release-test-v2.9.5.tar.gz
  [tcl9.0.4-src.tar.gz]=https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tcl9.0.4-src.tar.gz
  [tk9.0.4-src.tar.gz]=https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tk9.0.4-src.tar.gz
)
mkdir -p "$DL"
for f in "${!SHA[@]}"; do
  [ -f "$DL/$f" ] || curl -sL -o "$DL/$f" "${URL[$f]}"
  echo "${SHA[$f]}  $DL/$f" | sha256sum -c --quiet - || { echo "hash of $f does not match"; exit 1; }
done

rm -rf "$WORK"; mkdir -p "$WORK/src" "$WORK/obj"
cd "$WORK/src"
for f in "${!SHA[@]}"; do tar xzf "$DL/$f"; done
TKDND="$(echo "$WORK"/src/tkdnd-*)"; TCL="$WORK/src/tcl9.0.4"; TK="$WORK/src/tk9.0.4"

mkdir -p "$WORK/shim/X11"                                    # Tk's own X11 headers lack Xproto.h and Xresource.h; the stub code needs them only to compile
: > "$WORK/shim/X11/Xproto.h"
echo 'typedef struct _XrmHashBucketRec *XrmDatabase;' > "$WORK/shim/X11/Xresource.h"
INC="-I$WORK/shim -I$TCL/generic -I$TCL/unix -I$TK/generic -I$TK/unix -I$TK/xlib -I$TKDND/generic -I$TKDND/unix"
DEFS="-DUSE_TCL_STUBS -DUSE_TK_STUBS -DPACKAGE_NAME=\"tkdnd\" -DPACKAGE_VERSION=\"$VER\" -DHAVE_LIMITS_H -DTKDND_USE_XKEYCODETOKEYSYM -DSTDC_HEADERS"
CFLAGS="-O2 -fPIC -fvisibility=hidden -Wall -Wno-unused-variable -Wno-unused-function -Wno-deprecated-declarations -ffile-prefix-map=$WORK=. -g0 $DEFS $INC"
cd "$WORK/obj"
gcc $CFLAGS -c "$TKDND/unix/TkDND_XDND.c" -o xdnd.o
gcc $CFLAGS -c "$TKDND/unix/tkUnixSelect.c" -o select.o
gcc $CFLAGS -c "$TKDND/generic/TkDND_Cursors.c" -o cursors_generic.o             # plain Tk cursors: the Xcursor theme library is not used
gcc $CFLAGS -c "$TKDND/unix/Cursors.c" -o cursors_unix.o
gcc $CFLAGS -c "$TCL/generic/tclStubLib.c" -o tclstub.o
gcc $CFLAGS -c "$TK/generic/tkStubLib.c" -o tkstub.o
gcc -shared -o "libtkdnd$VER.so" xdnd.o select.o cursors_generic.o cursors_unix.o tclstub.o tkstub.o /usr/lib/x86_64-linux-gnu/libX11.so.6 -Wl,-soname,"libtkdnd$VER.so" -Wl,--no-undefined -Wl,-z,relro
strip --strip-unneeded "libtkdnd$VER.so"

rm -rf "$OUT"; mkdir -p "$OUT"
cp "libtkdnd$VER.so" "$OUT/"
cp "$TKDND"/library/tkdnd.tcl "$TKDND"/library/tkdnd_compat.tcl "$TKDND"/library/tkdnd_generic.tcl "$TKDND"/library/tkdnd_unix.tcl "$TKDND"/library/tkdnd_utils.tcl "$OUT/"
sed -e "s/@PACKAGE_VERSION@/$VER/g" -e "s/@PKG_LIB_FILE@/libtkdnd$VER.so/g" -e "s/@PACKAGE_NAME@/tkdnd/g" "$TKDND/pkgIndex.tcl.in" > "$OUT/pkgIndex.tcl"
cp "$TKDND/license.terms" "$OUT/license.tkdnd.txt"
cp "$TCL/license.terms" "$OUT/license.tcl.txt"
cp "$TK/license.terms" "$OUT/license.tk.txt"
echo "built:"; ls -l "$OUT"; sha256sum "$OUT/libtkdnd$VER.so"
echo "private strings in the library (must print nothing):"; strings "$OUT/libtkdnd$VER.so" | grep -E "/home/|/mnt/c|/Users/|${USER:-nobody-here}" || true
