"""Shared by the data pack builder and its sources."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACK_FORMAT = 1


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class Item:
    """One part to put in the pack: its CAD file, its metadata, and where the file lives."""
    id: str
    file: Path
    meta: dict[str, Any]                 # name, description, category_path, tags, standards, properties, ...
    url: str | None = None               # pinned URL at the original repository; None = ship the file in the pack
    extra_files: list[Path] = field(default_factory=list)


@dataclass
class Source:
    name: str                            # pack name: a-z, 0-9 and '-'
    title: str
    license: str                         # SPDX-style, shown per part
    license_text: str                    # LICENSE.txt in the pack (when the source has no licence file)
    attribution: str                     # ATTRIBUTION.md in the pack
    homepage: str
    files: str                           # "remote" or "included"
    items: Any                           # callable(src: Path) -> list[Item]
    revision: Any = None                 # callable(src: Path) -> str (commit of the source)
    license_file: str | None = None      # the source's own licence file, copied as LICENSE.txt


def git_commit(src: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - not a git clone
        return ""


