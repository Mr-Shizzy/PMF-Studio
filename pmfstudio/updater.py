"""Updates. Asking GitHub whether a newer release exists, and (in the packaged program) installing it:

  download the release zip -> check its SHA-256 (published by GitHub next to the file, or in the release notes) -> unpack it into a
  staging folder, refusing odd entries -> run the new program's own --selftest there and require it to pass and to report the version
  that was announced -> close, swap the program's own files for the new ones with a small batch script that waits for this program to
  end, keeps the old files until the new version has started, and puts them back if the swap fails.

Settings, saved output and anything else the user put beside the program are never touched. Nothing here runs without the user's click
(the program asks first), and a failure at any step leaves the installed version exactly as it was."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from . import VERSION, STAGE, REPO

PREFIX = "https://github.com/%s/" % REPO
WINDOWS = os.name == "nt"
# each system has its own release file: a zip for Windows, a tar.gz for Linux (the AppImage is a separate download that replaces itself by hand)
ASSET = re.compile(r"PMF-Studio-.+-win64\.zip" if WINDOWS else r"PMF-Studio-.+-linux-x64\.tar\.gz")
EXE = "PMF Studio.exe" if WINDOWS else "PMF Studio"
HELPERS = ("ffmpeg.exe", "atracdenc.exe") if WINDOWS else ("ffmpeg", "atracdenc")
PROGRAM_MAGIC = b"MZ" if WINDOWS else b"\x7fELF"
PARTS = ("_internal", "tools", "licenses", "source")                       # folders that belong to the program (swapped as a whole)
PART_FILES = (EXE, "LICENSE", "THIRD_PARTY_NOTICES.txt", "README.txt")      # files that belong to the program
KEEP = ("Output", "temp", "PMF Studio settings.json", "selftest_result.txt", "update_log.txt", "update_result.txt")      # never copied from an update, never removed
MAX_UNPACKED = 700_000_000
MAX_ENTRIES = 6000


class UpdateError(Exception):
    """a step failed in a way worth telling the user; the message is plain text"""


def ver(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3]) or (0,)


def pick_asset(info):
    """the release zip and its SHA-256 from a GitHub release (json) -> dict(name, url, size, sha) or None"""
    asset = next((a for a in info.get("assets", []) if ASSET.fullmatch(a.get("name", ""))), None)
    if not asset:
        return None
    url = asset.get("browser_download_url", "")
    sha = str(asset.get("digest", ""))[7:] if str(asset.get("digest", "")).startswith("sha256:") else ""
    if not sha:
        m = re.search(r"\b([0-9a-fA-F]{64})\b", info.get("body") or "")
        sha = m.group(1) if m else ""
    return dict(name=asset["name"], url=url, size=int(asset.get("size", 0)), sha=sha.lower())


def check(timeout=8):
    """-> ("latest", None) | ("newer", dict(tag, url, notes, asset)) | ("error", message). A 404 (no release published yet) counts as latest."""
    req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % REPO, headers={"User-Agent": "PMF-Studio", "Accept": "application/vnd.github+json"})
    try:
        info = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return ("latest", None) if e.code == 404 else ("error", "GitHub answered %d" % e.code)
    except (urllib.error.URLError, OSError, ValueError):
        return ("error", "Couldn't reach GitHub. Check your internet connection.")
    tag = info.get("tag_name", "")
    if ver(tag) > ver(VERSION):
        return ("newer", dict(tag=tag, url=info.get("html_url", ""), notes=info.get("body", "") or "", asset=pick_asset(info)))
    return ("latest", None)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(asset, dest, progress=None, cancelled=lambda: False, opener=None):
    """asset: dict(name, url, size, sha). Saves the zip at dest and checks it. Only github.com/<this repository>/ is trusted as the source,
    and the SHA-256 must match: a file that doesn't match is deleted."""
    if not asset or not asset.get("sha"):
        raise UpdateError("This release has no published checksum, so PMF Studio can't check it. Download it from the release page by hand.")
    if not asset["url"].startswith(PREFIX) and not asset["url"].startswith("file:"):
        raise UpdateError("The download address isn't on this program's GitHub page, so it was not used.")
    h, got = hashlib.sha256(), 0
    try:
        with (opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "PMF-Studio"}), timeout=60)))(asset["url"]) as r, open(dest, "wb") as f:
            while True:
                if cancelled():
                    raise UpdateError("Stopped.")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress:
                    progress(got, max(asset.get("size") or got, 1))
    except (urllib.error.URLError, OSError) as e:
        _remove(dest)
        raise UpdateError("The download failed (%s). Nothing was changed." % str(e)[:100])
    except UpdateError:
        _remove(dest)
        raise
    if h.hexdigest().lower() != asset["sha"].lower():
        _remove(dest)
        raise UpdateError("The download doesn't match its checksum, so it was thrown away. Nothing was changed.")
    return dest


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def unpack(zip_path, staging):
    """unpack the release zip into staging and return the folder that holds the new program. Refuses entries that would land outside it,
    a zip that is too big or has too many entries, and anything that doesn't look like this program."""
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    root = os.path.realpath(staging)

    def inside(path):
        target = os.path.realpath(path)
        return target == root or target.startswith(root + os.sep)

    odd = "The update file has an entry in an odd place (%s), so it was not used."
    try:
        if str(zip_path).endswith((".tar.gz", ".tgz")):
            with tarfile.open(zip_path, "r:gz") as t:
                members = t.getmembers()
                if len(members) > MAX_ENTRIES or sum(m.size for m in members) > MAX_UNPACKED:
                    raise UpdateError("The update file is larger than expected, so it was not used.")
                for m in members:
                    if m.name.startswith("/") or ".." in m.name.replace("\\", "/").split("/") or not inside(os.path.join(staging, m.name)):
                        raise UpdateError(odd % m.name[:60])
                    if not (m.isfile() or m.isdir() or m.issym()):          # no device files, no hard links
                        raise UpdateError(odd % m.name[:60])
                    if m.issym() and not inside(os.path.join(staging, os.path.dirname(m.name), m.linkname)):
                        raise UpdateError(odd % m.name[:60])
                try:
                    t.extractall(staging, filter="data")
                except TypeError:                                            # an older Python without extraction filters: the checks above still ran
                    t.extractall(staging)
        else:
            with zipfile.ZipFile(zip_path) as z:
                infos = z.infolist()
                if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                    raise UpdateError("The update file is larger than expected, so it was not used.")
                for i in infos:
                    if not inside(os.path.join(staging, i.filename)) or i.filename.startswith(("/", "\\")) or ":" in i.filename:
                        raise UpdateError(odd % i.filename[:60])
                z.extractall(staging)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError):
        raise UpdateError("The update file is damaged. Nothing was changed.")
    tops = [d for d in os.listdir(staging) if os.path.isdir(os.path.join(staging, d))]
    new = os.path.join(staging, tops[0]) if len(tops) == 1 and not os.path.isfile(os.path.join(staging, EXE)) else staging     # (on Linux the folder and the program share the name)
    exe = os.path.join(new, EXE)
    needed = [exe, os.path.join(new, "_internal")] + [os.path.join(new, "tools", h) for h in HELPERS]
    if not all(os.path.exists(p) for p in needed):
        raise UpdateError("The update file doesn't contain a complete PMF Studio, so it was not used.")
    with open(exe, "rb") as f:
        if not f.read(4).startswith(PROGRAM_MAGIC):
            raise UpdateError("The program in the update file isn't a program for this system, so it was not used.")
    if not WINDOWS:
        for p in [exe] + [os.path.join(new, "tools", h) for h in HELPERS]:      # a program that can't be started would fail only after the swap
            if not os.access(p, os.X_OK):
                raise UpdateError("The update file's programs can't be started on this system, so it was not used.")
    for n in KEEP:                                    # whatever a build left in there is not part of the program
        p = os.path.join(new, n)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else _remove(p)
    return new


def selftest(new_dir, expect_tag, timeout=420, cancelled=lambda: False, tick=None):
    """run the new program's own check in its staging folder: it must pass and name the announced version.
    tick(seconds so far), if given, is called about three times a second so a window can show that the check is still running"""
    result = os.path.join(new_dir, "selftest_result.txt")
    _remove(result)
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        proc = subprocess.Popen([os.path.join(new_dir, EXE), "--selftest"], cwd=new_dir, env=env, creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError as e:
        raise UpdateError("The new version can't be started on this PC (%s), so it was not installed." % str(e)[:80])
    t0 = time.time()
    while proc.poll() is None:
        if cancelled():
            proc.kill()
            raise UpdateError("Stopped.")
        if time.time() - t0 > timeout:
            proc.kill()
            raise UpdateError("The new version didn't finish its own check in time, so it was not installed.")
        if tick:
            tick(time.time() - t0)
        time.sleep(0.3)
    text = open(result, encoding="utf8", errors="replace").read() if os.path.exists(result) else ""
    m = re.search(r"^PMF Studio (\S+)", text, re.M)
    if "SELFTEST OK" not in text:
        fails = [ln.strip() for ln in text.splitlines() if ln.startswith("FAIL")]
        raise UpdateError("The new version failed its own check, so it was not installed. Nothing was changed." + (" (%s)" % fails[0][:120] if fails else " (it wrote no result)"))
    if expect_tag and (not m or ver(m.group(1)) != ver(expect_tag)):
        raise UpdateError("The new version isn't the one that was announced (%s instead of %s), so it was not installed." % (m.group(1) if m else "unknown", expect_tag))
    _remove(result)
    for n in KEEP:
        p = os.path.join(new_dir, n)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else _remove(p)


SWAP = r"""@echo off
setlocal
rem the two folders arrive as environment variables, never as text in this file: cmd reads a batch file in the old OEM code page, so a
rem folder name with letters like e-acute or u-umlaut would come out garbled here and the swap would fail
set "NEW=%PMF_NEW%"
set "APP=%PMF_APP%"
set "LOG=%APP%\update_log.txt"
echo [%date% %time%] waiting for PMF Studio (process {pid}) to close >> "%LOG%"
set /a waited=0
:wait
tasklist /FI "PID eq {pid}" /NH 2>nul | find /I ".exe" >nul
if errorlevel 1 goto ended
set /a waited+=1
if %waited% geq 20 goto ended
ping -n 2 127.0.0.1 >nul
goto wait
:ended
rem (a program that has ended can still be listed while something holds a handle to it; the next step fails safely while the old files are in use)
rem 1. put the old program aside (renamed, not deleted; the new version removes the .old copies once it has run for a few seconds)
for %%d in ({parts}) do (
  if exist "%APP%\%%d.old" rmdir /s /q "%APP%\%%d.old"
)
for %%f in ({files}) do (
  if exist "%APP%\%%~nxf.old" del /q "%APP%\%%~nxf.old"
)
set /a tries=0
:aside
set /a tries+=1
set "bad="
for %%d in ({parts}) do (
  if exist "%APP%\%%d" if not exist "%APP%\%%d.old" ren "%APP%\%%d" "%%d.old" 2>nul
  if exist "%APP%\%%d" set "bad=1"
)
if defined bad (
  if %tries% lss 30 (
    ping -n 2 127.0.0.1 >nul
    goto aside
  )
  echo could not move the old program aside; putting back what was moved >> "%LOG%"
  goto restore
)
for %%f in ({files}) do (
  if exist "%APP%\%%~f" ren "%APP%\%%~f" "%%~nxf.old" 2>nul
)
rem 2. put the new program in
robocopy "%NEW%" "%APP%" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 (
  echo copying the new program failed; putting the old one back >> "%LOG%"
  goto restore
)
if not exist "%APP%\{exe}" (
  echo the new program is missing after the copy; putting the old one back >> "%LOG%"
  goto restore
)
rem 3. start it
echo swapped in; starting the new program >> "%LOG%"
set "PYINSTALLER_RESET_ENVIRONMENT=1"
start "" "%APP%\{exe}"
rmdir /s /q "%NEW%" 2>nul
rmdir "%APP%\update_staging" 2>nul
(goto) 2>nul & del "%~f0"
:restore
for %%d in ({parts}) do (
  if exist "%APP%\%%d.old" (
    if exist "%APP%\%%d" rmdir /s /q "%APP%\%%d"
    ren "%APP%\%%d.old" "%%d"
  )
)
for %%f in ({files}) do (
  if exist "%APP%\%%~nxf.old" (
    if exist "%APP%\%%~f" del /q "%APP%\%%~f"
    ren "%APP%\%%~nxf.old" "%%~f"
  )
)
echo the old version was put back >> "%LOG%"
start "" "%APP%\{exe}"
exit /b 1
"""


SWAP_SH = r"""#!/bin/sh
# the same swap as the Windows batch file: the two folders arrive as environment variables, never as text in this file
NEW="$PMF_NEW"
APP="$PMF_APP"
LOG="$APP/update_log.txt"
echo "[$(date)] waiting for PMF Studio (process @PID@) to close" >> "$LOG"
waited=0
while kill -0 @PID@ 2>/dev/null && [ "$waited" -lt 20 ]; do
  sleep 1
  waited=$((waited + 1))
done
restore() {
  for d in @PARTS@; do
    if [ -e "$APP/$d.old" ]; then
      rm -rf "$APP/$d"
      mv "$APP/$d.old" "$APP/$d"
    fi
  done
  for f in @FILES@; do
    if [ -e "$APP/$f.old" ]; then
      rm -f "$APP/$f"
      mv "$APP/$f.old" "$APP/$f"
    fi
  done
  echo "the old version was put back" >> "$LOG"
  cd "$APP" && nohup "$APP/@EXE@" > /dev/null 2>&1 &
  exit 1
}
# 1. put the old program aside (renamed, not deleted; the new version removes the .old copies once it has run for a few seconds)
for d in @PARTS@; do rm -rf "$APP/$d.old"; done
for f in @FILES@; do rm -f "$APP/$f.old"; done
bad=""
for d in @PARTS@; do
  if [ -e "$APP/$d" ]; then mv "$APP/$d" "$APP/$d.old" || bad=1; fi
done
for f in @FILES@; do
  if [ -e "$APP/$f" ]; then mv "$APP/$f" "$APP/$f.old" || bad=1; fi
done
if [ -n "$bad" ]; then
  echo "could not move the old program aside; putting back what was moved" >> "$LOG"
  restore
fi
# 2. put the new program in
if ! cp -a "$NEW"/. "$APP"/ >> "$LOG" 2>&1; then
  echo "copying the new program failed; putting the old one back" >> "$LOG"
  restore
fi
if [ ! -x "$APP/@EXE@" ]; then
  echo "the new program is missing after the copy; putting the old one back" >> "$LOG"
  restore
fi
# 3. start it
echo "swapped in; starting the new program" >> "$LOG"
rm -rf "$NEW"
rmdir "$APP/update_staging" 2>/dev/null
cd "$APP" && nohup "$APP/@EXE@" > /dev/null 2>&1 &
rm -f "$0"
exit 0
"""


class SwapScript(str):
    """the path of the batch file; it also remembers the two folders the batch file needs (handed to it as environment variables)"""
    new_dir = app_dir = ""


def write_swap_script(new_dir, app_dir, pid=None):
    """a batch file (Windows) or shell script (Linux) that waits for this program to end, swaps the program's files, starts the new version,
    and undoes it all if that fails"""
    pid = pid or os.getpid()
    if WINDOWS:
        text = SWAP.format(pid=pid, exe=EXE, parts=" ".join(PARTS), files=" ".join('"%s"' % f for f in PART_FILES))
        bat = os.path.join(tempfile.gettempdir(), "pmfstudio_swap_%d.bat" % pid)
        with open(bat, "wb") as f:
            f.write(text.replace("\n", "\r\n").encode("ascii"))          # bytes: text mode would turn \r\n into \r\r\n; plain ASCII on purpose (see SWAP)
    else:
        text = SWAP_SH
        for token, value in (("@PID@", str(pid)), ("@EXE@", EXE), ("@PARTS@", " ".join(PARTS)), ("@FILES@", " ".join('"%s"' % f for f in PART_FILES))):
            text = text.replace(token, value)
        bat = os.path.join(tempfile.gettempdir(), "pmfstudio_swap_%d.sh" % pid)
        with open(bat, "wb") as f:
            f.write(text.encode("ascii"))                                # LF line endings, plain ASCII
    script = SwapScript(bat)
    script.new_dir, script.app_dir = new_dir, app_dir
    return script


def swap_environment(script):
    """the environment the batch file runs in: this program's, without the bookkeeping variables of a PyInstaller program (a program relaunched
    from inside itself would otherwise try to reuse this run's folder, which is gone), plus the two folders"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env["PMF_NEW"], env["PMF_APP"] = script.new_dir, script.app_dir
    return env


def run_swap(script):
    """start the batch file detached"""
    env = swap_environment(script)
    if not WINDOWS:                                                     # a session of its own, so it outlives this program
        subprocess.Popen(["/bin/sh", script], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, env=env)
        return
    # a hidden console of its own (no window) and a group of its own: the batch file's helper commands (tasklist, ping, robocopy) need a
    # console, and with the DETACHED_PROCESS flag the script hung at its first one (found in testing)
    subprocess.Popen(["cmd", "/c", script], creationflags=0x08000000 | 0x00000200, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, env=env)


def cleanup_after_update(app_dir):
    """once the new version has run for a few seconds, the old copies it kept aside (and the staging folder) are no longer needed"""
    for n in PARTS:
        shutil.rmtree(os.path.join(app_dir, n + ".old"), ignore_errors=True)
    for n in PART_FILES:
        _remove(os.path.join(app_dir, n + ".old"))
    shutil.rmtree(os.path.join(app_dir, "update_staging"), ignore_errors=True)


def can_install(app_dir):
    """None when the program can replace itself here; otherwise the reason, in plain words"""
    if not getattr(sys, "frozen", False):
        return "PMF Studio is running from its source files, which can't replace themselves."
    if os.environ.get("APPIMAGE"):
        return "PMF Studio is running as an AppImage, which is one file and can't replace itself. Download the new AppImage from the release page."
    try:
        fd, name = tempfile.mkstemp(prefix=".update_", dir=app_dir)
        os.close(fd)
        os.remove(name)
    except OSError:
        return "PMF Studio can't write in its own folder (%s), so it can't update itself there." % app_dir
    return None


DOWNLOAD_PART, UNPACK_DONE = 0.55, 0.65               # where the bar stands when the download is over and when the unpacking is


def test_fraction(seconds):
    """how far the bar goes while the new version tests itself: the test has no length known in advance, so the bar moves on slowly and
    never quite reaches the end (it takes a minute or so on a normal PC)"""
    return UNPACK_DONE + (0.97 - UNPACK_DONE) * (1.0 - 0.5 ** (seconds / 25.0))


def install(asset, expect_tag, app_dir, work, progress=lambda text, fraction: None, cancelled=lambda: False, opener=None):
    """the whole update up to the swap -> the path of the swap script (not started yet). Raises UpdateError; nothing is changed until the script runs."""
    free = shutil.disk_usage(app_dir).free
    if free < (asset.get("size") or 60_000_000) * 5 + 100_000_000:
        raise UpdateError("There isn't enough free space beside the program for the update (about %d MB is needed)." % (((asset.get("size") or 60_000_000) * 5 + 100_000_000) // 1_000_000))
    zip_path = os.path.join(work, asset["name"])
    progress("Step 1 of 3: downloading the update…", 0.0)
    t0 = time.time()

    def downloading(got, total):
        speed = got / max(time.time() - t0, 0.001) / 1e6
        progress("Step 1 of 3: downloading the update…  %d%%  (%d of %d MB, %.1f MB/s)" % (100 * got // total, got // 1_000_000, total // 1_000_000, speed), DOWNLOAD_PART * got / total)
    download(asset, zip_path, downloading, cancelled, opener)
    progress("Step 2 of 3: unpacking…", DOWNLOAD_PART)
    staging = os.path.join(app_dir, "update_staging")                      # on the same drive as the program, so the swap is a quick move
    new = unpack(zip_path, staging)
    _remove(zip_path)
    progress("Step 3 of 3: testing the new version…", UNPACK_DONE)
    try:
        selftest(new, expect_tag, cancelled=cancelled, tick=lambda secs: progress("Step 3 of 3: testing the new version…  %d s" % secs, test_fraction(secs)))
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    progress("Ready: restarting into the new version", 1.0)
    return write_swap_script(new, app_dir)


def cli_update(argv):
    """PMF Studio.exe --update-from <zip> <sha256> [<version>]: the same update from a file on this PC (for offline PCs and for testing).
    Writes what happened to update_result.txt beside the program and starts the swap. -> exit code"""
    from .paths import app_dir
    i = argv.index("--update-from")
    zip_path, sha = argv[i + 1], argv[i + 2]
    tag = argv[i + 3] if len(argv) > i + 3 else ""
    out = os.path.join(app_dir(), "update_result.txt")
    try:
        problem = can_install(app_dir())
        if problem:
            raise UpdateError(problem)
        asset = dict(name=os.path.basename(zip_path), url="file:" + zip_path, size=os.path.getsize(zip_path), sha=sha.lower())
        work = tempfile.mkdtemp(prefix="update_")
        try:
            script = install(asset, tag, app_dir(), work, opener=lambda u: open(zip_path, "rb"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        run_swap(script)
        open(out, "w", encoding="utf8").write("OK: swap started\n")
        return 0
    except UpdateError as e:
        open(out, "w", encoding="utf8").write("FAILED: %s\n" % e)
        return 1
