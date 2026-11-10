#!/bin/bash
# Builds Tk 9.0.4 WITH font support (Xft/fontconfig/FreeType) for the Linux release, and puts the result in tools/tk-xft/ (libtcl9tk9.0.so).
#
# Why: the Python we pack (python-build-standalone) has a Tk built without Xft, so Tk can only draw with the plain X font "fixed" (a small
# bitmap font: no titles, no bold, no scaling; font families: 1). The Python project knows (issue #740, "not currently scheduled"). Tk 9.0.4 is
# the same version as in that Python, so our libtcl9tk9.0.so can replace its one (the Tcl library stays theirs: Tk reaches Tcl through stubs).
#
# Sources (official, checked by hash; downloaded once to ~/pmf_build/downloads/tkxft, or reused from the tkdnd build's folder):
#   Tcl 9.0.4  https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tcl9.0.4-src.tar.gz  (Tcl licence; only built to configure Tk)
#   Tk 9.0.4   https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tk9.0.4-src.tar.gz   (Tk licence)
# Header files only (never installed on the system) from seven Ubuntu 24.04 packages, fetched with `apt-get download` (signed by the archive,
# no root needed) and unpacked into a private folder: libxft-dev libfontconfig-dev libfreetype-dev libx11-dev libxrender-dev x11proto-dev libxext-dev.
# The library links the system's libX11.so.6, libXft.so.2, libXrender.so.1, libfontconfig.so.1, libfreetype.so.6 (every desktop has them).
#
#   packaging/linux/build_tk_xft.sh                      builds into tools/tk-xft/
#   packaging/linux/build_tk_xft.sh --install-into-python    also replaces libtcl9tk9.0.so in the Python the release is built with
#                                                         (the original is kept beside it as libtcl9tk9.0.so.pbs-original)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
DL="${PMF_TKXFT_DOWNLOADS:-$HOME/pmf_build/downloads/tkxft}"
OLD_DL="$HOME/pmf_build/downloads/tkdnd"
WORK=/var/tmp/pmf_tkxft_build                           # outside the home folder: no user name ends up in the library
OUT="$HERE/tools/tk-xft"
declare -A SHA=(
  [tcl9.0.4-src.tar.gz]=d0aed49230bc02a65c1e0229e65f34590a4b037ec40d546f32573b467f7551ea
  [tk9.0.4-src.tar.gz]=d7a146d2917eb8b5cc95276dbf0e3d03c7464d2b19c1675357857c989301dbb4
)
declare -A URL=(
  [tcl9.0.4-src.tar.gz]=https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tcl9.0.4-src.tar.gz
  [tk9.0.4-src.tar.gz]=https://downloads.sourceforge.net/project/tcl/Tcl/9.0.4/tk9.0.4-src.tar.gz
)
DEBS=(libxft-dev=2.3.6-1build1 libfontconfig-dev=2.15.0-1.1ubuntu2 libfreetype-dev=2.13.2+dfsg-1build3 libx11-dev=2:1.8.7-1build1
      libxrender-dev=1:0.9.10-1.1build1 x11proto-dev=2023.2-1 libxext-dev=2:1.3.4-1build2)
declare -A DEBSHA=(
  [libxft-dev_2.3.6-1build1_amd64.deb]=c50b6489d22037e8e602fcf3b14c4b36b689923c1d0171eafbcae88426d1c3a9
  [libfontconfig-dev_2.15.0-1.1ubuntu2_amd64.deb]=7948f3037b39d8bc751dc6104ff490c2d2f1b145d2969227ba591ceb917f9f05
  [libfreetype-dev_2.13.2+dfsg-1build3_amd64.deb]=ffb5f0abfb76cb9c1189879fad2bbe5a9d4ffda359ba864b5c949d72b5871d70
  [libx11-dev_2%3a1.8.7-1build1_amd64.deb]=1969e200607ffe34070b92fe1bd3ba76ac2e2bd2f3a54530800c5872076fad24
  [libxrender-dev_1%3a0.9.10-1.1build1_amd64.deb]=839558c9de049636e13e22e409c04f3226614abf176c4a3b7088058576d74848
  [x11proto-dev_2023.2-1_all.deb]=3bf13a2ffb79ecd4014d438936014e5863f79eb59ebf76e8f43356271c90e7ce
  [libxext-dev_2%3a1.3.4-1build2_amd64.deb]=b5bdb6724f228cb8eee8cf39cbbe1289dd3f8f06dd022748312df7844c94dcf2
)
mkdir -p "$DL/debs"
for f in "${!SHA[@]}"; do
  [ -f "$DL/$f" ] || { [ -f "$OLD_DL/$f" ] && cp "$OLD_DL/$f" "$DL/$f"; } || curl -sL -o "$DL/$f" "${URL[$f]}"
  echo "${SHA[$f]}  $DL/$f" | sha256sum -c --quiet - || { echo "hash of $f does not match"; exit 1; }
done
(cd "$DL/debs" && for p in "${DEBS[@]}"; do ls "${p%%=*}"_*.deb > /dev/null 2>&1 || apt-get download "$p" > /dev/null; done)
echo "downloaded packages (sha256):"; (cd "$DL/debs" && sha256sum *.deb)
for f in "${!DEBSHA[@]}"; do
  echo "${DEBSHA[$f]}  $DL/debs/$f" | sha256sum -c --quiet - || { echo "hash of $f does not match"; exit 1; }
done

rm -rf "$WORK"; mkdir -p "$WORK/src" "$WORK/sys" "$WORK/tcl" "$WORK/tk"
cd "$WORK/src"
for f in "${!SHA[@]}"; do tar xzf "$DL/$f"; done
for d in "$DL"/debs/*.deb; do dpkg-deb -x "$d" "$WORK/sys"; done
SYS="$WORK/sys"; LIBDIR=/usr/lib/x86_64-linux-gnu
# the -dev packages bring only the .so symlinks, pointing at the runtime packages' files: point them at the system's own copies
find "$SYS$LIBDIR" -maxdepth 1 -type l | while read -r l; do
  t="$(basename "$(readlink "$l")")"; [ -e "$LIBDIR/$t" ] && ln -sf "$LIBDIR/$t" "$l"
done
export PKG_CONFIG_PATH="$SYS$LIBDIR/pkgconfig:$SYS/usr/share/pkgconfig" PKG_CONFIG_SYSROOT_DIR="$SYS"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"

# Tk's configure asks `xft-config` first, then pkg-config; pkg-config would also want the .pc files of freetype's own dependencies (libpng, ...),
# whose packages are not needed just to compile against Xft. So answer the question directly:
mkdir -p "$WORK/bin"
cat > "$WORK/bin/xft-config" <<EOF
#!/bin/sh
case "\$1" in
  --cflags) echo "-I$SYS/usr/include -I$SYS/usr/include/freetype2" ;;
  --libs) echo "-L$SYS$LIBDIR -lXft -lXrender -lfontconfig -lfreetype -lX11" ;;
esac
EOF
chmod +x "$WORK/bin/xft-config"
export PATH="$WORK/bin:$PATH"

echo "== Tcl 9.0.4 (only to configure Tk)"
cd "$WORK/tcl" && "$WORK/src/tcl9.0.4/unix/configure" --enable-threads --enable-64bit --enable-shared --disable-rpath --disable-zipfs > "$WORK/tcl-configure.log" 2>&1
make -j"$(nproc)" libtcl9.0.so tclsh > "$WORK/tcl-make.log" 2>&1 || { tail -20 "$WORK/tcl-make.log"; exit 1; }      # (not its optional packages)
export LD_LIBRARY_PATH="$WORK/tcl"

echo "== Tk 9.0.4 with Xft"
cd "$WORK/tk"
export CFLAGS="-O2 -g0 -ffile-prefix-map=$WORK=. -I$SYS/usr/include -I$SYS/usr/include/freetype2"
export LDFLAGS="-L$SYS$LIBDIR -Wl,-z,relro"
"$WORK/src/tk9.0.4/unix/configure" --with-tcl="$WORK/tcl" --enable-threads --enable-64bit --enable-shared --enable-xft --disable-rpath --disable-zipfs \
  --x-includes="$SYS/usr/include" --x-libraries="$SYS$LIBDIR" > "$WORK/tk-configure.log" 2>&1 || { tail -30 "$WORK/tk-configure.log"; exit 1; }
grep -iE "xft" "$WORK/tk-configure.log" | head -5
grep -q "whether to use xft... yes" "$WORK/tk-configure.log" || { echo "Tk's configure did not accept Xft: not building a Tk without fonts"; exit 1; }
make -j"$(nproc)" libtcl9tk9.0.so > "$WORK/tk-make.log" 2>&1 || { tail -30 "$WORK/tk-make.log"; exit 1; }
strip --strip-unneeded libtcl9tk9.0.so

rm -rf "$OUT"; mkdir -p "$OUT"
cp libtcl9tk9.0.so "$OUT/"
cp "$WORK/src/tk9.0.4/license.terms" "$OUT/license.tk.txt"
echo "built:"; ls -l "$OUT"; sha256sum "$OUT/libtcl9tk9.0.so"
echo "needs (must be the system's own libraries only):"; readelf -d "$OUT/libtcl9tk9.0.so" | grep NEEDED
echo "Xft inside:"; strings "$OUT/libtcl9tk9.0.so" | grep -c XftFontOpen || true
echo "private strings in the library (must print nothing):"; strings "$OUT/libtcl9tk9.0.so" | grep -E "/home/|/mnt/c|/Users/|${USER:-nobody-here}" || true

if [ "${1:-}" = "--install-into-python" ]; then
  BASE="$("$HOME/pmf_build/venv/bin/python" -c 'import sys; print(sys.base_prefix)')"
  [ -f "$BASE/lib/libtcl9tk9.0.so.pbs-original" ] || cp "$BASE/lib/libtcl9tk9.0.so" "$BASE/lib/libtcl9tk9.0.so.pbs-original"
  cp "$OUT/libtcl9tk9.0.so" "$BASE/lib/libtcl9tk9.0.so"
  echo "installed into $BASE/lib (original kept as libtcl9tk9.0.so.pbs-original)"
fi
