"""Data packs: openly licensed parts libraries that you install into the general library in one go.

A pack is a folder or .zip made by scripts/datapacks/build.py (format in docs/03_DATAMODEL.md): pack.json,
parts.jsonl, thumbnails/, sometimes files/, LICENSE.txt and ATTRIBUTION.md. Installing copies it to
data/packs/<name>/, adds or updates every part (same id = update, same file already in the library = skipped)
and computes the search vectors with this installation's own model. Removing a pack removes exactly its parts.

    python -m partsfinder.packs list
    python -m partsfinder.packs install PATH.zip|FOLDER [--db FILE]
    python -m partsfinder.packs remove NAME
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_DIR
from .models import PartCreate
from .remote import RemoteFileError, check_url, is_remote

PACK_FORMAT = 1
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
META_PREFIX = "pack:"
BATCH = 64


class PackError(Exception):
    pass


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def read_info(folder: Path) -> dict[str, Any]:
    try:
        info = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError("This is not a Partsfinder data pack (no readable pack.json)") from exc
    if info.get("format") != PACK_FORMAT:
        raise PackError(f"Unknown pack format {info.get('format')!r}: update Partsfinder")
    if not NAME_RE.match(str(info.get("name", ""))):
        raise PackError("The pack has no valid name")
    if not (folder / "parts.jsonl").is_file():
        raise PackError("The pack has no parts.jsonl")
    return info


def _extract(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            name = member.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
                raise PackError(f"Unsafe path in the pack: {name}")
        z.extractall(target)


def _stage(src: Path, packs_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Puts the pack in data/packs/<name>/ and returns that folder and pack.json."""
    packs_dir.mkdir(parents=True, exist_ok=True)
    if src.is_file() and src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix=".unpack-", dir=packs_dir))
        try:
            _extract(src, tmp)
            inner = tmp if (tmp / "pack.json").is_file() else next((p for p in tmp.iterdir() if (p / "pack.json").is_file()), tmp)
            info = read_info(inner)
            target = packs_dir / info["name"]
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(inner), str(target))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return target, info
    if src.is_dir():
        info = read_info(src)
        target = packs_dir / info["name"]
        if src.resolve() != target.resolve():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("work"))
        return target, info
    raise PackError(f"Not found: {src} (give a pack folder or .zip)")


def _rows(folder: Path) -> list[dict[str, Any]]:
    rows = []
    with open(folder / "parts.jsonl", encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise PackError(f"parts.jsonl line {n} is not valid JSON") from exc
    return rows


def _part(row: dict[str, Any], folder: Path, info: dict[str, Any]) -> PartCreate:
    data = {k: v for k, v in row.items() if k not in ("company_id", "access_group")}
    files = []
    for f in data.get("files", []):
        path = f["path"]
        if is_remote(path):
            check_url(path)
        else:
            local = (folder / path).resolve()
            if folder.resolve() not in local.parents:
                raise PackError(f"File outside the pack: {path}")
            path = _rel(local)
        files.append({**f, "path": path})
    data["files"] = files
    if data.get("thumbnail_path"):
        thumb = (folder / data["thumbnail_path"]).resolve()
        data["thumbnail_path"] = _rel(thumb) if folder.resolve() in thumb.parents and thumb.is_file() else None
    data.setdefault("source", info["name"])
    data.setdefault("license", info.get("license"))
    return PartCreate(**data)


def _same(old, new: PartCreate) -> bool:
    return (old.checksum == new.checksum and old.name == new.name and old.description == new.description
            and old.category_path == new.category_path and old.license == new.license
            and old.thumbnail_path == new.thumbnail_path and old.tags == new.tags
            and [f.path for f in old.files] == [f.path for f in new.files])


def install(src: Path, repo, embedder, data_dir: Path, log: Callable[[str], None] = print,
            progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    from .ingest import part_text
    from .repository import DuplicatePartError

    folder, info = _stage(Path(src), data_dir / "packs")
    rows = _rows(folder)
    log(f"Installing {info['title']} ({len(rows)} parts, licence {info.get('license')})")
    added = updated = unchanged = duplicates = failed = 0
    to_embed = []
    errors: list[str] = []
    for n, row in enumerate(rows, 1):
        try:
            part = _part(row, folder, info)
            old = repo.get_part(part.id, None)
            if old is not None and _same(old, part):
                unchanged += 1
            else:
                if old is None and part.checksum and repo.find_by_checksum(part.checksum, None) is not None:
                    duplicates += 1          # the same file is already in the library under another id
                    continue
                saved = repo.add_part(part, replace_id=old.id if old is not None else None)
                to_embed.append(saved)
                if old is None:
                    added += 1
                else:
                    updated += 1
        except (DuplicatePartError, ValueError, PackError, RemoteFileError) as exc:
            failed += 1
            if len(errors) < 20:
                errors.append(f"{row.get('id')}: {exc}")
        if len(to_embed) >= BATCH or (n == len(rows) and to_embed):
            vectors = embedder.embed_passages([part_text(p) for p in to_embed])
            for p, v in zip(to_embed, vectors):
                repo.set_embedding(p.id, v)
            to_embed = []
        if progress and (n % 200 == 0 or n == len(rows)):
            progress(n, len(rows))
    record = {**info, "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "folder": _rel(folder), "installed_parts": added + updated + unchanged}
    with repo.conn:
        repo.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                          (META_PREFIX + info["name"], json.dumps(record)))
    report = {"name": info["name"], "title": info.get("title"), "parts": len(rows), "added": added,
              "updated": updated, "unchanged": unchanged, "duplicates": duplicates, "failed": failed,
              "errors": errors}
    log(f"{info['name']}: {added} added, {updated} updated, {unchanged} unchanged, {duplicates} already in the "
        f"library, {failed} failed")
    return report


def installed(repo) -> list[dict[str, Any]]:
    rows = repo.conn.execute("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key", (META_PREFIX + "%",)).fetchall()
    return [json.loads(r[1]) for r in rows]


def remove(name: str, repo, data_dir: Path, log: Callable[[str], None] = print) -> dict[str, Any]:
    if not NAME_RE.match(name):
        raise PackError("Invalid pack name")
    row = repo.conn.execute("SELECT value FROM meta WHERE key = ?", (META_PREFIX + name,)).fetchone()
    if row is None:
        raise PackError(f"Pack '{name}' is not installed")
    folder = data_dir / "packs" / name
    ids = [r["id"] for r in _rows(folder)] if (folder / "parts.jsonl").is_file() else []
    from .ingest.pipeline import remove_parts
    removed = 0
    for i in range(0, len(ids), 500):
        removed += len(remove_parts(repo, ids[i:i + 500], None, data_dir))
    with repo.conn:
        repo.conn.execute("DELETE FROM meta WHERE key = ?", (META_PREFIX + name,))
    shutil.rmtree(folder, ignore_errors=True)
    log(f"{name}: {removed} parts removed")
    return {"name": name, "removed": removed}


def main(argv: list[str] | None = None) -> int:
    from .config import get_settings
    from .db import connect
    from .ingest import HashingEmbedder, SentenceTransformerEmbedder
    from .repository import Repository

    ap = argparse.ArgumentParser(prog="python -m partsfinder.packs", description="Install or remove data packs.")
    ap.add_argument("--db", help="library file (default: the one in the settings)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_in = sub.add_parser("install")
    p_in.add_argument("packs", nargs="+")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("name")
    args = ap.parse_args(argv)
    s = get_settings()
    conn = connect(args.db or s.db_path, s.embedding_dim)
    repo = Repository(conn)
    try:
        if args.cmd == "list":
            for p in installed(repo):
                print(f"{p['name']:24} {p.get('installed_parts', p.get('parts'))!s:>6} parts  {p.get('license')}  "
                      f"(version {p.get('version')})")
            return 0
        if args.cmd == "remove":
            remove(args.name, repo, s.data_dir)
            return 0
        row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
        embedder = HashingEmbedder(s.embedding_dim) if (row and row[0] == "hashing") else \
            SentenceTransformerEmbedder(s.embedding_model)
        if not row:
            with conn:
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('embedder', ?)", (s.embedding_model,))
        for p in args.packs:
            install(Path(p), repo, embedder, s.data_dir,
                    progress=lambda n, t: print(f"  {n}/{t}", end="\r", flush=True))
        return 0
    except PackError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
