"""Files of data pack parts that stay at their original repository (pinned to one commit).

A part file whose path is an https URL is downloaded the first time someone needs it (download, 3D view) and kept
in data/cache/files. Only the hosts of the open libraries are allowed, so a library cannot make the search engine
fetch arbitrary addresses.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

ALLOWED_HOSTS = {"raw.githubusercontent.com", "gitlab.com"}
MAX_BYTES = 300 * 1024 * 1024
TIMEOUT_S = 60


class RemoteFileError(Exception):
    pass


def is_remote(path: str | None) -> bool:
    return bool(path) and path.startswith(("https://", "http://"))


def check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise RemoteFileError(f"Files can only come from {', '.join(sorted(ALLOWED_HOSTS))} over https")
    return url


def file_name(url: str) -> str:
    return Path(unquote(urlparse(url).path)).name or "part"


def cached_path(url: str, cache_dir: Path) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    return cache_dir / key / file_name(url)


def fetch(url: str, cache_dir: Path, opener=urllib.request.urlopen) -> Path:
    """The local copy of the file at url, downloading it once."""
    check_url(url)
    target = cached_path(url, cache_dir)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{os.getpid()}.part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Partsfinder (open source parts library)"})
        with opener(req, timeout=TIMEOUT_S) as resp, open(tmp, "wb") as out:
            total = 0
            while chunk := resp.read(1 << 16):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RemoteFileError("The file is too large")
                out.write(chunk)
        tmp.replace(target)
    except RemoteFileError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - network: say it in plain words
        tmp.unlink(missing_ok=True)
        raise RemoteFileError(f"Could not download the file from its library ({type(exc).__name__}). "
                              "Check the internet connection.") from exc
    return target
