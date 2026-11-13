"""Folder rules for an import: which files are never read (.partsfinderignore) and who may see the rest
(.partsfinderaccess). See docs/10_COMPANY_LIBRARIES.md.

Fail closed everywhere: a rule file that cannot be read or understood skips its whole folder (reported as
an error), it never opens it up. Excluded folders are not even walked, so their files are never opened.
Rules in the folders ABOVE the imported folder count too: importing an excluded subfolder directly
imports nothing.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..access import join_groups
from .geometry import CAD_FORMATS, file_format

IGNORE_FILE = ".partsfinderignore"
ACCESS_FILE = ".partsfinderaccess"
COMPANY = "company"                 # in .partsfinderaccess: back to company level for this subfolder


class RuleError(ValueError):
    """A rule file that cannot be used: its folder is skipped."""


@dataclass(frozen=True)
class _Pattern:
    base: PurePosixPath              # folder of the .partsfinderignore, relative to the import root
    pattern: str                     # lower case
    anchored: bool                   # contains a '/': matched from base
    dir_only: bool

    def matches(self, rel: PurePosixPath, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        try:
            below = rel.relative_to(self.base)
        except ValueError:
            return False
        text = below.as_posix().lower()
        if self.anchored:
            return fnmatch.fnmatchcase(text, self.pattern)
        return fnmatch.fnmatchcase(below.name.lower(), self.pattern)


@dataclass
class Walk:
    files: list[tuple[Path, str | None]] = field(default_factory=list)   # CAD file, access group (None = company)
    skipped: list[tuple[str, str]] = field(default_factory=list)          # folder, why (rule errors)
    excluded: int = 0                                                     # files and folders left out
    ignored_files: set[Path] = field(default_factory=set)                 # e.g. a JSON next to a CAD file


def _lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleError(f"{path.name} cannot be read ({exc})") from exc
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def parse_ignore(path: Path, base: PurePosixPath) -> list[_Pattern]:
    out = []
    for line in _lines(path):
        if line.startswith("!"):
            raise RuleError(f"{path.name}: exceptions ('{line}') are not supported, so nothing can be opened up by mistake")
        if "\\" in line:
            line = line.replace("\\", "/")
        dir_only = line.endswith("/")
        pat = line.strip("/").lower()
        if not pat:
            continue
        out.append(_Pattern(base, pat, "/" in pat, dir_only))
    return out


def parse_access(path: Path) -> str | None:
    """Group name(s), or None for company level. Several groups on the first line ("nuclear, aero"): people with
    any of them see the folder; they are stored as "aero,nuclear"."""
    lines = _lines(path)
    if not lines:
        raise RuleError(f"{path.name} is empty: write a group name (or '{COMPANY}')")
    if lines[0].lower() == COMPANY:
        return None
    try:
        return join_groups(lines[0])
    except ValueError as exc:
        raise RuleError(f"{path.name}: {exc}") from None


def _ancestor_rules(root: Path) -> tuple[bool, str | None]:
    """(excluded by a rule above the root, group inherited from above the root)."""
    group: str | None = None
    found_group = False
    chain = list(reversed(root.parents))                 # from the top down to the parent of root
    for anc in chain:
        acc = anc / ACCESS_FILE
        if acc.is_file():
            group, found_group = parse_access(acc), True  # the nearest one (lowest) wins
        ign = anc / IGNORE_FILE
        if ign.is_file():
            patterns = parse_ignore(ign, PurePosixPath("."))
            rel = PurePosixPath(root.relative_to(anc).as_posix())
            parts = rel.parts
            for i in range(1, len(parts) + 1):            # the root itself or any folder between
                sub = PurePosixPath(*parts[:i])
                if any(p.matches(sub, is_dir=True) for p in patterns):
                    return True, group
    return False, group if found_group else None


def walk(root: Path) -> Walk:
    """Every CAD file under root that may be read, with its access group."""
    root = Path(root)
    out = Walk()
    try:
        excluded_above, top_group = _ancestor_rules(root)
    except RuleError as exc:
        out.skipped.append((".", f"rule above this folder: {exc}"))
        return out
    if excluded_above:
        out.skipped.append((".", "this folder is excluded by an .partsfinderignore in a folder above it"))
        return out

    patterns_of: dict[PurePosixPath, list[_Pattern]] = {}
    group_of: dict[PurePosixPath, str | None] = {}
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        here = Path(dirpath)
        rel = PurePosixPath(here.relative_to(root).as_posix()) if here != root else PurePosixPath(".")
        parent = rel.parent if rel != PurePosixPath(".") else None
        inherited = patterns_of.get(parent, []) if parent is not None else []
        group = group_of.get(parent, top_group) if parent is not None else top_group
        try:
            own = parse_ignore(here / IGNORE_FILE, rel) if IGNORE_FILE in filenames else []
            if ACCESS_FILE in filenames:
                group = parse_access(here / ACCESS_FILE)
        except RuleError as exc:
            out.skipped.append((rel.as_posix(), str(exc)))
            dirnames[:] = []                             # the whole folder, subfolders included
            continue
        patterns = inherited + own
        patterns_of[rel], group_of[rel] = patterns, group

        def ignored(name: str, is_dir: bool) -> bool:
            target = rel / name if rel != PurePosixPath(".") else PurePosixPath(name)
            return any(p.matches(target, is_dir) for p in patterns)

        keep = []
        for d in sorted(dirnames):
            if ignored(d, True) or (here / d).is_symlink():
                out.excluded += 1
            else:
                keep.append(d)
        dirnames[:] = keep                               # excluded folders are never entered
        for f in sorted(filenames):
            if f.lower().startswith(".partsfinder"):
                continue
            if ignored(f, False):
                out.excluded += 1
                out.ignored_files.add(here / f)
                continue
            p = here / f
            if p.is_symlink():
                # a link could point into an excluded folder (or anywhere): never followed
                out.excluded += 1
                out.ignored_files.add(p)
                continue
            if file_format(p) in CAD_FORMATS and p.is_file():
                out.files.append((p, group))
    return out
