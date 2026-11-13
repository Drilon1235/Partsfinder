"""The data packs you can download: the pack zips of the newest Partsfinder release on GitHub.

Settings -> Data packs lists them with their size, licence and number of parts, and downloads one in a click:
over https, only from GitHub's release hosts (also after a redirect), checked against the SHA-256 that GitHub
publishes for the file, and then installed exactly like a zip chosen by hand (packs.install).

A fork points PARTSFINDER_PACKS_RELEASES at its own releases API.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

RELEASES = os.getenv("PARTSFINDER_PACKS_RELEASES",
                     "https://api.github.com/repos/Drilon1235/Partsfinder/releases?per_page=10")
HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
ASSET_RE = re.compile(r"^partsfinder-pack-([a-z0-9][a-z0-9-]{1,60}?)-(\d{4}-\d{2}-\d{2})\.zip$")
MAX_SIZE = 4 * 1024 ** 3                               # a pack is a few hundred MB at most
TIMEOUT = 60

# What each pack is, for the list in Settings (the release only has the file name and size)
KNOWN = {
    "standard-parts": {"title": "Standard parts (ISO, DIN, ASME)", "license": "Apache-2.0", "parts": 5834,
                       "about": "Bolts, nuts, washers, bearings, O-rings, retaining rings, keys, flanges and gears.",
                       "recommended": True},
    "kicad-3d": {"title": "KiCad 3D models (electronic components)", "license": "CC-BY-SA-4.0 WITH KiCad exception",
                 "parts": 6188, "about": "SMD and through-hole packages, connectors, switches, crystals, LEDs."},
    "freecad-library": {"title": "FreeCAD parts library", "license": "CC-BY-3.0", "parts": 2489,
                        "about": "Steel profiles, fasteners, motors and machine parts."},
    "adafruit-cad-parts": {"title": "Adafruit CAD parts", "license": "MIT", "parts": 489,
                           "about": "Adafruit boards, breakouts and displays."},
}


class CatalogueError(Exception):
    pass


def _check(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in HOSTS:
        raise CatalogueError(f"Not a GitHub release address: {url}")
    return url


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib's signature
        _check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_open = urllib.request.build_opener(_GitHubOnly).open


def _get(url: str, opener, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(_check(url), headers={"Accept": accept, "User-Agent": "Partsfinder"})
    try:
        return opener(req, timeout=TIMEOUT)
    except CatalogueError:
        raise
    except Exception as exc:  # noqa: BLE001 - every network problem gets the same plain answer
        raise CatalogueError(f"GitHub could not be reached ({type(exc).__name__}). Check the internet "
                             "connection, or download the pack from the releases page and use "
                             "Install a data pack…") from exc


def available(opener=_open, releases: str = RELEASES) -> dict[str, Any]:
    """The packs of the newest published release that has packs: name, title, licence, size, version, url."""
    with _get(releases, opener) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for release in data if isinstance(data, list) else []:
        if release.get("draft") or release.get("prerelease"):
            continue
        found = []
        for asset in release.get("assets") or []:
            m = ASSET_RE.match(str(asset.get("name", "")))
            if not m:
                continue
            digest = str(asset.get("digest") or "")
            name = m.group(1)
            found.append({"name": name, "version": m.group(2), "file": asset["name"],
                          "size": int(asset.get("size") or 0), "url": asset.get("browser_download_url"),
                          "sha256": digest[7:] if digest.startswith("sha256:") else None,
                          "title": name, "license": None, "parts": None, "about": "", "recommended": False,
                          **KNOWN.get(name, {})})
        if found:
            found.sort(key=lambda p: (not p["recommended"], p["name"]))
            return {"release": release.get("tag_name"), "packs": found}
    return {"release": None, "packs": []}


def download(pack: dict[str, Any], folder: Path, opener=_open,
             progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    """Download one pack zip into folder (kept, so a second install needs no download) and check it."""
    folder.mkdir(parents=True, exist_ok=True)
    if not ASSET_RE.match(str(pack.get("file", ""))):
        raise CatalogueError("Not a Partsfinder data pack")
    target = folder / pack["file"]
    want = (pack.get("sha256") or "").lower()
    if target.is_file() and want and _sha256(target) == want:
        progress(target.stat().st_size, target.stat().st_size)
        return target
    total = int(pack.get("size") or 0)
    if total > MAX_SIZE:
        raise CatalogueError("The pack is larger than 4 GB; it is not a Partsfinder data pack")
    part = target.with_suffix(".zip.part")
    digest, done = hashlib.sha256(), 0
    with _get(pack["url"], opener, accept="application/octet-stream") as resp, open(part, "wb") as out:
        while chunk := resp.read(1 << 20):
            done += len(chunk)
            if done > MAX_SIZE:
                raise CatalogueError("The download is larger than 4 GB; stopped")
            digest.update(chunk)
            out.write(chunk)
            progress(done, total)
    if total and done != total:
        part.unlink(missing_ok=True)
        raise CatalogueError("The download stopped before the end; try again")
    if want and digest.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise CatalogueError("The downloaded file does not match its checksum; it was not installed")
    part.replace(target)
    return target


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
