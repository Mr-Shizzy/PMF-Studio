"""Ask GitHub whether a newer release exists (no download happens without the user's click)."""
import json
import re
import urllib.error
import urllib.request

from . import VERSION, REPO


def _ver(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3]) or (0,)


def check(timeout=8):
    """-> ("latest", None) | ("newer", dict(tag, url, notes)) | ("error", message). A 404 (no release published yet) counts as latest."""
    req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % REPO, headers={"User-Agent": "PMF-Studio", "Accept": "application/vnd.github+json"})
    try:
        info = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return ("latest", None) if e.code == 404 else ("error", "GitHub answered %d" % e.code)
    except (urllib.error.URLError, OSError, ValueError):
        return ("error", "Couldn't reach GitHub. Check your internet connection.")
    tag = info.get("tag_name", "")
    if _ver(tag) > _ver(VERSION):
        return ("newer", dict(tag=tag, url=info.get("html_url", ""), notes=info.get("body", "")))
    return ("latest", None)
