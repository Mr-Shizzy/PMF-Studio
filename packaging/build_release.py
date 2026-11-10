"""Builds the PMF Studio release: a folder (and a zip on Windows, a tar.gz and an AppImage on Linux) that works on a PC with nothing installed.

    python packaging/build_release.py            build everything, check it, pack it
    python packaging/build_release.py --no-zip   stop before packing
    python packaging/build_release.py --zip-only pack the folder that was just built and tested
    python packaging/build_release.py --appimage (Linux) also make the AppImage from the folder that was just built and tested

What it does, in order:
  1. gets FFmpeg: on Windows pinned in packaging/ffmpeg_pin.json (the download is checked against the pinned SHA-256 and the one GitHub
     publishes); on Linux tools/ffmpeg built from official source by packaging/linux/build_ffmpeg.sh, with its licence texts
     - nothing from the internet is trusted without a check;
  2. packs the program with PyInstaller (one folder, no console window);
  3. puts the helper programs (ffmpeg and atracdenc) in tools/, with the licences and the atracdenc source patches;
  4. runs the finished program's own --selftest;
  5. checks that no personal strings (this PC's user name) ended up in the release;
  6. packs it and prints the SHA-256.
Third-party programs are never committed; they only appear in the release folder. Needs: Python 3.12 with PyInstaller installed
(pip install pyinstaller) and tools/atracdenc/bin/atracdenc(.exe) built as described in tools/atracdenc/README.txt.
Linux: the same script, run on Linux (it cannot cross-build). The AppImage step downloads appimagetool and its runtime, both pinned
in packaging/appimage_pin.json and checked.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pmfstudio import VERSION, STAGE                       # noqa: E402

WINDOWS = os.name == "nt"
PIN = os.path.join(ROOT, "packaging", "ffmpeg_pin.json")                    # Windows only: the Linux ffmpeg is built from source
APPIMAGE_PIN = os.path.join(ROOT, "packaging", "appimage_pin.json")
CACHE = os.path.join(ROOT, "packaging", "cache")
BUILD = os.path.join(ROOT, "build")
RELEASE = os.path.join(ROOT, "release")
NAME = "PMF Studio"
FOLDER = os.path.join(RELEASE, NAME)
EXE = ".exe" if WINDOWS else ""
PROGRAM = NAME + EXE
ARCHIVE = os.path.join(RELEASE, "PMF-Studio-%s-%s-%s" % (VERSION, STAGE, "win64.zip" if WINDOWS else "linux-x64.tar.gz"))
APPIMAGE = os.path.join(RELEASE, "PMF-Studio-%s-%s-linux-x64.AppImage" % (VERSION, STAGE))


def say(text):
    print(text, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def published_digest(pin):
    """the SHA-256 GitHub lists for the pinned asset (None when it can't be read, or when the pin is not a GitHub release)"""
    if "repo" not in pin:
        return None
    try:
        url = "https://api.github.com/repos/%s/releases/tags/%s" % (pin["repo"], pin["tag"])
        info = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pmf-studio-build"}), timeout=30))
        for a in info.get("assets", []):
            if a["name"] == pin["asset"] and str(a.get("digest", "")).startswith("sha256:"):
                return a["digest"].split(":", 1)[1].lower()
    except Exception as e:
        say("  (could not read GitHub's published hash: %s)" % e)
    return None


LINUX_FFMPEG = os.path.join(ROOT, "tools", "ffmpeg")
LINUX_FFMPEG_LICENCES = os.path.join(ROOT, "packaging", "linux", "ffmpeg-licenses")


def linux_ffmpeg():
    """Linux: the ffmpeg is built from source by packaging/linux/build_ffmpeg.sh (nothing is downloaded here) -> (its path, a description)"""
    if not os.path.isfile(LINUX_FFMPEG) or not os.path.isdir(LINUX_FFMPEG_LICENCES):
        sys.exit("tools/ffmpeg is missing: build it first with packaging/linux/build_ffmpeg.sh (see setup_build_env.sh)")
    with open(LINUX_FFMPEG, "rb") as f:
        if f.read(4) != b"\x7fELF":
            sys.exit("tools/ffmpeg is not a Linux program")
    digest = sha256(LINUX_FFMPEG)
    say("FFmpeg for Linux: our own build, SHA-256 %s" % digest)
    return LINUX_FFMPEG, dict(version="9.0.2", asset="built from source by packaging/linux/build_ffmpeg.sh",
                              url="the source is the release file PMF-Studio-ffmpeg-source.tar.xz", sha256=digest)


def fetch_ffmpeg():
    if not WINDOWS:
        return linux_ffmpeg()
    pin = json.load(open(PIN, encoding="utf8"))
    os.makedirs(CACHE, exist_ok=True)
    zpath = os.path.join(CACHE, pin["asset"])
    if not (os.path.exists(zpath) and pin.get("sha256") and sha256(zpath) == pin["sha256"]):
        say("downloading %s (%.0f MB) from %s" % (pin["asset"], pin["size"] / 1e6, pin["url"]))
        urllib.request.urlretrieve(pin["url"], zpath)
    got = sha256(zpath)
    published = published_digest(pin)
    if pin.get("sha256") and got != pin["sha256"]:
        sys.exit("FFmpeg download does not match the pinned SHA-256 - not using it.\n  pinned %s\n  got    %s" % (pin["sha256"], got))
    if published and got != published:
        sys.exit("FFmpeg download does not match the SHA-256 GitHub publishes - not using it.\n  published %s\n  got       %s" % (published, got))
    if pin.get("md5_published") and md5(zpath) != pin["md5_published"]:
        sys.exit("FFmpeg download does not match the MD5 its publisher lists - not using it.")
    if not pin.get("sha256"):
        pin["sha256"] = got
        json.dump(pin, open(PIN, "w", encoding="utf8"), indent=2)
        say("pinned the SHA-256 of this download in %s: %s (publisher's own: %s)" % (os.path.basename(PIN), got, published or "not available"))
    else:
        say("FFmpeg download verified: %s" % got)
    return zpath, pin


def unpack_ffmpeg(zpath, dest_tools, dest_lic):
    if WINDOWS:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            exe = next(n for n in names if n.endswith("/bin/ffmpeg.exe"))
            with z.open(exe) as src, open(os.path.join(dest_tools, "ffmpeg.exe"), "wb") as out:
                shutil.copyfileobj(src, out)
            for suffix, target in (("/LICENSE", "ffmpeg-LICENSE.txt"), ("/README.txt", "ffmpeg-README.txt")):
                name = next((n for n in names if n.count("/") == 1 and n.endswith(suffix)), None)
                if name:
                    open(os.path.join(dest_lic, target), "wb").write(z.read(name))
        return
    out = os.path.join(dest_tools, "ffmpeg")                       # Linux: our own build, and the licence texts of everything inside it
    shutil.copyfile(zpath, out)
    os.chmod(out, 0o755)
    for name in sorted(os.listdir(LINUX_FFMPEG_LICENCES)):
        shutil.copy(os.path.join(LINUX_FFMPEG_LICENCES, name), os.path.join(dest_lic, name))


TKDND = os.path.join(ROOT, "tools", "tkdnd")


def add_tkdnd(dest_tools, dest_lic):
    """Linux: the drag-and-drop extension for Tk, built by packaging/linux/build_tkdnd.sh (tkdnd 2.9.5 against Tk 9.0.4), with its licence texts"""
    lib = next((f for f in sorted(os.listdir(TKDND)) if f.startswith("libtkdnd") and f.endswith(".so")), None) if os.path.isdir(TKDND) else None
    if not lib or not os.path.isfile(os.path.join(TKDND, "pkgIndex.tcl")):
        sys.exit("tools/tkdnd is missing: build it first with packaging/linux/build_tkdnd.sh")
    with open(os.path.join(TKDND, lib), "rb") as f:
        if f.read(4) != b"ELF":
            sys.exit("tools/tkdnd/%s is not a Linux library" % lib)
    out = os.path.join(dest_tools, "tkdnd")
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(TKDND)):
        if name.startswith("license."):
            shutil.copy(os.path.join(TKDND, name), os.path.join(dest_lic, name.replace("license.", "").replace(".txt", "") + "-LICENSE.txt"))
        else:
            shutil.copy(os.path.join(TKDND, name), os.path.join(out, name))
    os.chmod(os.path.join(out, lib), 0o755)
    say("drag and drop for Linux: %s, SHA-256 %s" % (lib, sha256(os.path.join(out, lib))))


LIB_DIRS = ("/usr/lib64", "/lib64", "/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu")


def system_package_of(path):
    """(package, version, licence text) of the system package that owns this file, from dpkg (Debian, Ubuntu) or rpm (Red Hat family); None if neither
    knows it. A Debian package keeps its licence in /usr/share/doc/<package>/copyright, an rpm lists its licence files (rpm -qL)."""
    real = os.path.realpath(path)
    if shutil.which("dpkg"):
        r = subprocess.run(["dpkg", "-S", real], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if r.returncode or not r.stdout.strip():
            return None
        package = r.stdout.split(":")[0].strip()
        version = subprocess.run(["dpkg-query", "-W", "-f=${Version}", package], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
        doc = os.path.join("/usr/share/doc", package, "copyright")
        return package, version, open(doc, encoding="utf8", errors="replace").read() if os.path.exists(doc) else "(no copyright file found in the package)"
    if shutil.which("rpm"):
        r = subprocess.run(["rpm", "-qf", "--qf", "%{NAME}\n%{VERSION}-%{RELEASE}", real], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if r.returncode or "\n" not in r.stdout:
            return None
        package, version = r.stdout.split("\n", 1)
        files = subprocess.run(["rpm", "-qL", package], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.split()
        text = "".join("--- %s\n%s\n" % (os.path.basename(f), open(f, encoding="utf8", errors="replace").read()) for f in files if os.path.isfile(f))
        return package, version, text or "(no licence file found in the package)"
    return None


def add_system_library_notices(internal, dest_lic):
    """Linux: PyInstaller copies the system libraries the program needs (X11, Xft, FreeType, fontconfig, ...) from this build machine into
    _internal. Each has its own licence, kept by the package that owns the file (see system_package_of). Collects those texts, with the package
    names and versions, in licenses/bundled-system-libraries.txt. Only a file that really is the system's copy counts (Python brings its own)."""
    if not (shutil.which("dpkg") or shutil.which("rpm")):
        say("WARNING: neither dpkg nor rpm found: the licence texts of the bundled system libraries were NOT collected")
        return
    packages, versions, texts = {}, {}, {}
    for name in sorted(os.listdir(internal)):
        if ".so" not in name or not os.path.isfile(os.path.join(internal, name)):
            continue
        for libdir in LIB_DIRS:
            path = os.path.join(libdir, name)
            if not os.path.exists(path) or sha256(path) != sha256(os.path.join(internal, name)):
                continue
            owner = system_package_of(path)
            if owner:
                package, versions[owner[0]], texts[owner[0]] = owner
                packages.setdefault(package, []).append(name)
                break
    distro = ""
    if os.path.exists("/etc/os-release"):
        m = re.search(r'^PRETTY_NAME="?([^"\n]+)', open("/etc/os-release", encoding="utf8").read(), re.M)
        distro = m.group(1) if m else ""
    parts = ["Licence texts of the system libraries that are copied into the _internal folder of this program.\n"
             "They come from the packages of the build machine (%s) named below; the texts are the packages' own licence files.\n"
             "FreeType is used under the FreeType Licence (the choice its own text offers next to the GPL 2).\n" % (distro or "a Linux system")]
    for package in sorted(packages):
        parts.append("\n" + "=" * 78 + "\n%s %s  (%s)\n" % (package, versions[package], ", ".join(packages[package])) + "=" * 78 + "\n" + texts[package])
    with open(os.path.join(dest_lic, "bundled-system-libraries.txt"), "w", encoding="utf8", newline="\n") as f:
        f.write("".join(parts))
    say("system libraries inside the program: %s" % ", ".join("%s (%s)" % (p, ", ".join(packages[p])) for p in sorted(packages)))


FONT_PIN = os.path.join(ROOT, "packaging", "linux", "font_pin.json")


def add_fonts(dest_tools, dest_lic):
    """Linux: the Selawik font (Regular and Bold), Microsoft's metric-compatible stand-in for Segoe UI, SIL Open Font License 1.1. The download is
    pinned (packaging/linux/font_pin.json) and checked, and so is each font file taken out of it; it is never committed. The licence text goes
    in licenses/. pmfstudio/fonts.py tells fontconfig about the files when the program starts."""
    pin = json.load(open(FONT_PIN, encoding="utf8"))["selawik"]
    path = fetch_pinned(pin)
    out = os.path.join(dest_tools, "fonts")
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        for name, want in pin["files"].items():
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != want:
                sys.exit("%s in %s does not match its pinned SHA-256 - not using it." % (name, pin["asset"]))
            with open(os.path.join(out, name), "wb") as f:
                f.write(data)
    lic = os.path.join(ROOT, "packaging", "licenses", "Selawik-OFL-1.1.txt")
    if sha256(lic) != pin["licence_sha256"]:
        sys.exit("packaging/licenses/Selawik-OFL-1.1.txt has changed: check it against the font's licence and update font_pin.json")
    shutil.copy(lic, os.path.join(dest_lic, "Selawik-OFL-1.1.txt"))
    say("fonts for Linux: %s" % ", ".join(sorted(os.listdir(out))))


def pyinstaller():
    say("packing the program with PyInstaller")
    for d in (os.path.join(BUILD, "dist"), os.path.join(BUILD, "work")):
        shutil.rmtree(d, ignore_errors=True)
    atrac = os.path.join(ROOT, "tools", "atracdenc", "bin", "atracdenc" + EXE)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir", "--name", NAME,
           "--distpath", os.path.join(BUILD, "dist"), "--workpath", os.path.join(BUILD, "work"), "--specpath", BUILD,
           "--add-data", os.path.join(ROOT, "pmfstudio", "assets") + os.pathsep + os.path.join("pmfstudio", "assets"),
           "--add-data", atrac + os.pathsep + "spare",       # a spare copy, put back if the file in tools/ is removed
           "--paths", ROOT, "--exclude-module", "PIL", "--exclude-module", "numpy", os.path.join(ROOT, "packaging", "entry.py")]
    if WINDOWS:
        cmd[cmd.index("--add-data"):cmd.index("--add-data")] = ["--icon", os.path.join(ROOT, "pmfstudio", "assets", "icon.ico")]
    r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        sys.exit("PyInstaller failed:\n" + r.stdout[-3000:])
    return os.path.join(BUILD, "dist", NAME)


def atracdenc_source_files(folder):
    """BASE_COMMIT.txt, README.txt and EVERY patch in tools/atracdenc: the shipped atracdenc is built with all of them, and its
    licence (LGPL-2.1) means the release must carry the same changes (a fixed list once left one out)"""
    patches = sorted(f for f in os.listdir(folder) if f.endswith(".patch"))
    return ["BASE_COMMIT.txt", "README.txt"] + patches


def python_licence():
    """the licence text of the Python the program is packed with (None when this Python's folder holds none)"""
    for base in (sys.base_prefix, os.path.join(sys.base_prefix, "lib", "python%d.%d" % sys.version_info[:2]), os.path.dirname(os.__file__)):
        for name in ("LICENSE.txt", "LICENSE"):
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
    return None


def assemble(packed, zpath, pin):
    shutil.rmtree(FOLDER, ignore_errors=True)
    shutil.copytree(packed, FOLDER, symlinks=True)
    tools, lic, src = (os.path.join(FOLDER, d) for d in ("tools", "licenses", os.path.join("source", "atracdenc")))
    for d in (tools, lic, src):
        os.makedirs(d, exist_ok=True)
    unpack_ffmpeg(zpath, tools, lic)
    if not WINDOWS:
        add_tkdnd(tools, lic)
        add_fonts(tools, lic)
        add_system_library_notices(os.path.join(FOLDER, "_internal"), lic)
    atrac = os.path.join(ROOT, "tools", "atracdenc")
    shutil.copy(os.path.join(atrac, "bin", "atracdenc" + EXE), os.path.join(tools, "atracdenc" + EXE))
    for f in atracdenc_source_files(atrac):
        shutil.copy(os.path.join(atrac, f), src)
    shutil.copy(os.path.join(ROOT, "packaging", "licenses", "atracdenc-LICENSE-LGPL-2.1.txt"), lic)
    py = python_licence()
    if py:
        shutil.copy(py, os.path.join(lic, "python-LICENSE.txt"))
    else:
        say("WARNING: no Python licence file found next to this Python; add it to licenses/ by hand")
    shutil.copy(os.path.join(ROOT, "LICENSE"), FOLDER)
    suffix = "" if WINDOWS else "_linux"                    # the notices and the readme differ per system
    shutil.copy(os.path.join(ROOT, "packaging", "THIRD_PARTY_NOTICES%s.txt" % suffix), os.path.join(FOLDER, "THIRD_PARTY_NOTICES.txt"))
    text = open(os.path.join(ROOT, "packaging", "README_release%s.txt" % suffix), encoding="utf8").read().replace("%VERSION%", "%s %s" % (VERSION, STAGE))
    open(os.path.join(FOLDER, "README.txt"), "w", encoding="utf8").write(text)
    open(os.path.join(FOLDER, "tools", "ffmpeg-build.txt"), "w", encoding="utf8").write(
        "FFmpeg %s, %s\nfrom %s\nSHA-256 of the download: %s\n" % (pin.get("tag") or pin.get("version"), pin["asset"], pin["url"], pin["sha256"]))


def selftest():
    say("running the finished program's own self-test")
    exe = os.path.join(FOLDER, PROGRAM)
    result = os.path.join(FOLDER, "selftest_result.txt")
    if os.path.exists(result):
        os.remove(result)
    r = subprocess.run([exe, "--selftest"], cwd=FOLDER, timeout=900)
    text = open(result, encoding="utf8").read() if os.path.exists(result) else "(no result file written)"
    say(text)
    for leftover in (result, os.path.join(FOLDER, "Output"), os.path.join(FOLDER, "temp"), os.path.join(FOLDER, "PMF Studio settings.json")):
        if os.path.isdir(leftover):
            shutil.rmtree(leftover, ignore_errors=True)
        elif os.path.exists(leftover):
            os.remove(leftover)
    if r.returncode or "SELFTEST OK" not in text:
        sys.exit("the self-test failed - not packing")


PERSONAL_MAIL = re.compile(rb"[A-Za-z0-9._%+-]+@(?:gmail|googlemail|outlook|hotmail|live|yahoo|icloud|proton|protonmail)\.[a-z]{2,}", re.I)
# public author lines in Python's own io module (CPython source), carried inside python312.dll and base_library.zip
KNOWN_MAIL = {b"mike.verdone@gmail.com", b"amauryfa@gmail.com",
              b"petasisg@yahoo.gr",                # the author line of tkdnd, in its licence text (licenses/tkdnd-LICENSE.txt)
              b"aixtools@gmail.com"}               # a contributor's public attribution line in libbsd's copyright file (licenses/bundled-system-libraries.txt)


def scan_personal(folder=None):
    """no user names, personal paths or personal mail addresses inside the release (text files, programs and Python files alike)"""
    folder = folder or FOLDER
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), os.path.basename(os.path.expanduser("~"))}
    words = [w.encode() for w in names if len(w) > 2 and w.lower() != "root"]       # ("root" is the build user in a clean build system, and an ordinary word everywhere)
    bad = []
    for dp, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(dp, f)
            if os.path.islink(p) or os.path.getsize(p) > 400_000_000:
                continue
            data = open(p, "rb").read()
            low = data.lower()
            for w in words:
                if w.lower() in low:
                    bad.append((os.path.relpath(p, folder), w.decode(), low.count(w.lower())))
            for m in set(PERSONAL_MAIL.findall(data)):
                if m.lower() in KNOWN_MAIL:
                    continue
                bad.append((os.path.relpath(p, folder), "a personal e-mail address (%s...)" % m[:3].decode("latin1"), data.count(m)))
    return bad


def make_archive():
    """the zip (Windows) or the tar.gz (Linux) of the finished folder"""
    if os.path.exists(ARCHIVE):
        os.remove(ARCHIVE)
    if WINDOWS:
        with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for dp, _, files in os.walk(FOLDER):
                for f in files:
                    p = os.path.join(dp, f)
                    z.write(p, os.path.join(NAME, os.path.relpath(p, FOLDER)))
    else:
        def anonymous(info):                                             # no builder name or number inside the archive
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            return info
        with tarfile.open(ARCHIVE, "w:gz", compresslevel=9) as t:          # permissions are kept: the programs must stay startable
            t.add(FOLDER, arcname=NAME, filter=anonymous)
    digest = sha256(ARCHIVE)
    with open(ARCHIVE + ".sha256", "w", newline="\n") as f:                    # LF line ending on every system, so sha256sum -c works everywhere
        f.write("%s  %s\n" % (digest, os.path.basename(ARCHIVE)))
    say("\n%s\n  %.1f MB\n  SHA-256 %s" % (ARCHIVE, os.path.getsize(ARCHIVE) / 1e6, digest))


def fetch_pinned(entry):
    """downloads one file listed in appimage_pin.json (cached) and checks it against the pinned SHA-256 -> its path"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, entry["asset"])
    if not (os.path.exists(path) and sha256(path) == entry["sha256"]):
        say("downloading %s from %s" % (entry["asset"], entry["url"]))
        urllib.request.urlretrieve(entry["url"], path)
    if sha256(path) != entry["sha256"]:
        sys.exit("%s does not match its pinned SHA-256 - not using it." % entry["asset"])
    os.chmod(path, 0o755)
    return path


APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/PMF Studio/PMF Studio" "$@"
"""
DESKTOP = """[Desktop Entry]
Type=Application
Name=PMF Studio
Comment=Make PSP movies, boot movies and AT3 sounds
Exec=AppRun %F
Icon=pmf-studio
Categories=AudioVideo;Video;
Terminal=false
StartupWMClass=Pmfstudio
"""


def make_appimage():
    """the AppImage: the finished folder inside an AppDir, packed by appimagetool with a pinned runtime. It keeps its settings beside
    the .AppImage file (paths.data_dir), never inside itself."""
    if WINDOWS:
        sys.exit("AppImages are made on Linux.")
    pin = json.load(open(APPIMAGE_PIN, encoding="utf8"))
    tool = fetch_pinned(pin["appimagetool"])
    runtime = fetch_pinned(pin["runtime"])
    appdir = os.path.join(BUILD, "AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(appdir)
    shutil.copytree(FOLDER, os.path.join(appdir, NAME), symlinks=True)
    open(os.path.join(appdir, "AppRun"), "w").write(APPRUN)
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    open(os.path.join(appdir, "pmf-studio.desktop"), "w").write(DESKTOP)
    shutil.copy(os.path.join(ROOT, "pmfstudio", "assets", "icon.png"), os.path.join(appdir, "pmf-studio.png"))
    if os.path.exists(APPIMAGE):
        os.remove(APPIMAGE)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")      # appimagetool is itself an AppImage: run it without needing FUSE
    r = subprocess.run([tool, "--runtime-file", runtime, appdir, APPIMAGE], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode or not os.path.exists(APPIMAGE):
        sys.exit("appimagetool failed:\n" + r.stdout[-3000:])
    os.chmod(APPIMAGE, 0o755)
    digest = sha256(APPIMAGE)
    with open(APPIMAGE + ".sha256", "w", newline="\n") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(APPIMAGE)))
    shutil.rmtree(appdir, ignore_errors=True)
    say("\n%s\n  %.1f MB\n  SHA-256 %s" % (APPIMAGE, os.path.getsize(APPIMAGE) / 1e6, digest))


OLDEST_GLIBC = (2, 28)         # the Linux files are built on AlmaLinux 8 (glibc 2.28): see packaging/linux/BUILD_ON_ALMALINUX8.txt


def glibc_floor(folder):
    """-> (highest glibc version any program or library in the folder asks for, the file that asks), from objdump; None when objdump isn't there.
    A program built on a newer system than the oldest one it should run on quietly asks for that newer C library and then won't start on older
    systems (the Ubuntu 24.04 build of 0.3 needed 2.38; the published 0.2 needed 2.17)."""
    if WINDOWS or not shutil.which("objdump"):
        return None
    best = ((0,), "")
    for dp, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    if os.path.islink(p) or fh.read(4) != b"\x7fELF":
                        continue
            except OSError:
                continue
            out = subprocess.run(["objdump", "-T", p], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
            v = highest_glibc(out)
            if v > best[0]:
                best = (v, os.path.relpath(p, folder))
    return best


def highest_glibc(objdump_output):
    """the highest glibc version named in the output of `objdump -T` (old objdump prints GLIBC_2.2.5, new prints (GLIBC_2.2.5)); (0,) if none"""
    found = [tuple(int(x) for x in m.split(".")) for m in re.findall(r"GLIBC_([0-9]+(?:\.[0-9]+)+)", objdump_output)]
    return max(found) if found else (0,)


def check_glibc_floor(folder=None):
    best = glibc_floor(folder or FOLDER)
    if best is None:
        return
    text = ".".join(map(str, best[0]))
    if best[0] > OLDEST_GLIBC:
        say("WARNING: this program needs glibc %s (%s), newer than the %s it should run with: build on AlmaLinux 8, not on a newer system"
            % (text, best[1], ".".join(map(str, OLDEST_GLIBC))))
        if "--allow-new-glibc" not in sys.argv:
            sys.exit(1)
    else:
        say("oldest glibc the program needs: %s (%s): runs on Linux systems from about 2018 on" % (text, best[1]))


def main():
    if "--zip-only" in sys.argv or "--appimage" in sys.argv:           # pack the folder built (and tested) a moment ago
        bad = scan_personal()
        if bad:
            sys.exit("personal strings found: %s" % bad[:5])
        if "--zip-only" in sys.argv:
            make_archive()
        if "--appimage" in sys.argv:
            make_appimage()
        return
    zpath, pin = fetch_ffmpeg()
    packed = pyinstaller()
    assemble(packed, zpath, pin)
    selftest()
    bad = scan_personal()
    if bad:
        say("PERSONAL STRINGS FOUND (fix before publishing):")
        for item in bad[:20]:
            say("  %s contains %r %d times" % item)
        if "--allow-personal" not in sys.argv:
            sys.exit(1)
    else:
        say("no personal strings found in the release")
    check_glibc_floor()
    if "--no-zip" not in sys.argv:
        make_archive()
    shutil.rmtree(BUILD, ignore_errors=True)               # the half-finished copies in build/ also contain a PMF Studio program; only release/ should
    say("\nthe finished program is the folder %s (and the archive beside it)" % FOLDER)


if __name__ == "__main__":
    main()
