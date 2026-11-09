#!/bin/bash
# Sets up a PRIVATE build environment for the Linux release in $HOME/pmf_build (nothing is installed system-wide):
# uv (a pinned release, checked against GitHub's published SHA-256), a standalone Python 3.12 that includes Tk, and a virtual
# environment with PyInstaller, meson and ninja. Re-running it only repairs what is missing.
set -euo pipefail
BASE="${PMF_BUILD:-$HOME/pmf_build}"
UV_VERSION=0.13.7
UV_SHA256=c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83
mkdir -p "$BASE/bin" "$BASE/downloads"
if [ ! -x "$BASE/bin/uv" ]; then
  f="$BASE/downloads/uv-$UV_VERSION-x86_64-unknown-linux-gnu.tar.gz"
  curl -fsSL --retry 3 -o "$f" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
  echo "$UV_SHA256  $f" | sha256sum -c -
  tar -xzf "$f" -C "$BASE/downloads"
  cp "$BASE/downloads/uv-x86_64-unknown-linux-gnu/uv" "$BASE/bin/uv"
fi
export UV_PYTHON_INSTALL_DIR="$BASE/python" UV_CACHE_DIR="$BASE/cache" UV_PYTHON_DOWNLOADS=automatic
"$BASE/bin/uv" python install 3.12
if [ ! -x "$BASE/venv/bin/python" ]; then
  "$BASE/bin/uv" venv --python 3.12 "$BASE/venv"
fi
"$BASE/bin/uv" pip install --python "$BASE/venv/bin/python" pyinstaller meson ninja
"$BASE/venv/bin/python" -c "import sys, tkinter; print('python', sys.version.split()[0], 'tk', tkinter.TkVersion)"
"$BASE/venv/bin/python" -m PyInstaller --version
"$BASE/venv/bin/meson" --version
"$BASE/venv/bin/ninja" --version
