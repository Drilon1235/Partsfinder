"""Import pipeline: read a folder of CAD files into the database.

Per part:
  group files (chair.step + chair.sldprt + chair.json = one part)
  -> checksum (already imported? skip)
  -> measure geometry -> determine metadata -> render preview -> store
Then: link assembly components and compute all embeddings in batches.

Company separation: the library (company_id) is decided by who imports,
never by what is in a JSON file. Folder rules (.partsfinderignore: never read; .partsfinderaccess: restricted group)
come from rules.py; with sync=True parts whose file is gone or now excluded are removed completely.
See docs/10_COMPANY_LIBRARIES.md.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import PROJECT_DIR
from ..access import full
from ..config import get_settings
from ..models import Part, PartCreate, PartFile
from ..repository import Repository
from . import rules, thumbnail
from .embeddings import Embedder, part_text
from .geometry import CAD_FORMATS, PRIMARY_ORDER, analyze, file_checksum, file_format
from .metadata import REVIEW_TAG, Enricher, guess_from_filename, load_sidecar
from .. import preview


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)        # sync: file gone or now excluded
    needs_review: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    components_linked: int = 0
    seconds: float = 0.0

    def summary(self) -> str:
        lines = [
            f"New: {len(self.added)}, updated: {len(self.updated)}, "
            f"already present: {len(self.skipped)}, removed: {len(self.removed)}, failed: {len(self.failed)} "
            f"({self.seconds:.0f} s)",
            f"Assembly links: {self.components_linked}",
        ]
        if self.needs_review:
            lines.append(f"Needs review (metadata guessed): {len(self.needs_review)}")
        for name, err in self.failed[:20]:
            lines.append(f"  ERROR {name}: {err}")
        for w in self.warnings[:10]:
            lines.append(f"  NOTE {w}")
        return "\n".join(lines)


def _group_files(found: list[tuple[Path, str | None]]) -> list[tuple[list[Path], str | None]]:
    """chair.step + chair.sldprt in one folder = one part; all files of a folder share its access group."""
    groups: dict[tuple[Path, str], list[Path]] = {}
    group_of: dict[Path, str | None] = {}
    for p, group in found:
        groups.setdefault((p.parent, p.stem.lower()), []).append(p)
        group_of[p.parent] = group
    return [(files, group_of[key[0]]) for key, files in groups.items()]


def _under(path: str, folder: Path) -> bool:
    """Does a stored file path (relative to the project or absolute) lie in this folder?"""
    p = Path(path)
    absolute = os.path.normcase(os.path.abspath(p if p.is_absolute() else PROJECT_DIR / p))
    root = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
    return absolute == root or absolute.startswith(root + os.sep)


MASS_REMOVAL = (20, 0.5)        # more than 20 parts AND more than half of the folder: refuse without --allow-mass-removal


def remove_parts(repo: Repository, part_ids: list[str], company_id: str | None,
                 data_dir: Path | None = None) -> list[str]:
    """Remove parts completely: database (see Repository.remove_parts), previews and 3D caches."""
    removed = repo.remove_parts(part_ids, company_id)
    mesh_dir = (data_dir or get_settings().data_dir) / "meshes"
    for part in removed:
        if part.thumbnail_path:
            t = Path(part.thumbnail_path)
            (t if t.is_absolute() else PROJECT_DIR / t).unlink(missing_ok=True)
        if mesh_dir.is_dir():
            for f in mesh_dir.glob(preview.mesh_prefix(part.id) + "*.stl"):
                f.unlink(missing_ok=True)
    return [p.id for p in removed]


def remove_folder(repo: Repository, folder: str | Path, company_id: str | None,
                  data_dir: Path | None = None) -> list[str]:
    """Remove every part of this library whose main file lies in this folder (the folder may be gone)."""
    folder = Path(folder).expanduser()
    folder = folder.resolve() if folder.exists() else Path(os.path.abspath(folder))
    ids = [pid for pid, path in repo.primary_paths(company_id) if _under(path, folder)]
    return remove_parts(repo, ids, company_id, data_dir)


def _primary(files: list[Path]) -> Path:
    rank = {fmt: i for i, fmt in enumerate(PRIMARY_ORDER)}
    return sorted(files, key=lambda p: (rank.get(file_format(p), 99), p.name))[0]


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def ingest_folder(
    folder: str | Path,
    repo: Repository,
    embedder: Embedder,
    company_id: str | None = None,
    enricher: Enricher | None = None,
    thumbnail_dir: Path | None = None,
    make_thumbnails: bool = True,
    log: Callable[[str], None] = print,
    sync: bool = False,
    allow_mass_removal: bool = False,
    data_dir: Path | None = None,
) -> IngestReport:
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {folder}")
    company_id = full(company_id)          # the import sees and replaces every part of its own library
    thumb_root = thumbnail_dir or PROJECT_DIR / "data" / "thumbnails" / (company_id or "global")
    report, start = IngestReport(), time.time()
    assemblies: list[tuple[str, list[dict[str, Any]]]] = []
    to_embed: list[str] = []

    found = rules.walk(folder)
    for where, why in found.skipped:
        report.failed.append((f"{where}/", f"folder skipped: {why}"))
        log(f"SKIPPED folder {where}: {why}")
    if found.excluded:
        report.warnings.append(f"{found.excluded} files or folders left out by .partsfinderignore (never read)")
    # the library's own AI rules: a confidential company, or a restricted folder, never gets an AI description
    confidential = repo.is_confidential(company_id)
    groups = _group_files(found.files)
    present: set[str] = set()
    for i, (files, group) in enumerate(groups, 1):
        primary = _primary(files)
        present.add(_rel(primary))
        label = primary.relative_to(folder).as_posix()
        if group is not None and company_id is None:
            report.failed.append((label, f"restricted folder (group '{group}') can only be imported into a company library"))
            log(f"[{i}/{len(groups)}] ERROR {label}: restricted folder in the general library")
            continue
        try:
            status, part_id, components = _ingest_one(
                files, primary, repo, company_id, None if (group or confidential) else enricher,
                thumb_root if make_thumbnails else None, report, group, found.ignored_files)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
            report.failed.append((label, f"{type(exc).__name__}: {exc}"))
            log(f"[{i}/{len(groups)}] ERROR {label}: {exc}")
            continue
        getattr(report, status).append(part_id)
        if status != "skipped":
            to_embed.append(part_id)
            if components:
                assemblies.append((part_id, components))
        log(f"[{i}/{len(groups)}] {status:8s} {label}")

    for assembly_id, components in assemblies:
        for comp in components:
            try:
                repo.add_component(assembly_id, str(comp["id"]), int(comp.get("quantity", 1)), company_id)
                report.components_linked += 1
            except Exception as exc:  # noqa: BLE001
                report.failed.append((assembly_id, f"part {comp.get('id')}: {exc}"))

    if to_embed:
        log(f"Computing embeddings for {len(to_embed)} parts...")
        for k in range(0, len(to_embed), 64):
            parts = [repo.get_part(pid, company_id) for pid in to_embed[k:k + 64]]
            vectors = embedder.embed_passages([part_text(p) for p in parts])
            for p, vec in zip(parts, vectors):
                repo.set_embedding(p.id, vec)

    if sync:
        _sync_removals(folder, repo, company_id, present, len(found.files), allow_mass_removal, report, data_dir, log)
    report.seconds = time.time() - start
    return report


def _sync_removals(folder: Path, repo: Repository, company_id: str | None, present: set[str], files_found: int,
                   allow_mass_removal: bool, report: IngestReport, data_dir: Path | None,
                   log: Callable[[str], None]) -> None:
    """Remove the parts of this folder whose file is gone or now excluded. A share that is only half
    reachable must not empty the library: a large removal needs allow_mass_removal."""
    here = [(pid, path) for pid, path in repo.primary_paths(company_id) if _under(path, folder)]
    gone = [pid for pid, path in here if path not in present]
    if not gone:
        return
    big = len(gone) > MASS_REMOVAL[0] and len(gone) > MASS_REMOVAL[1] * len(here)
    if not allow_mass_removal and (files_found == 0 or big):
        msg = (f"sync would remove {len(gone)} of {len(here)} parts of this folder"
               + (" (no CAD file found at all: is the share reachable?)" if files_found == 0 else "")
               + "; nothing removed. Run again with --allow-mass-removal if this is right.")
        report.warnings.append(msg)
        log(f"NOTE {msg}")
        return
    removed = remove_parts(repo, gone, company_id, data_dir)
    report.removed.extend(removed)
    for pid in removed:
        log(f"removed  {pid}")


_COMPARED = ("kind", "name", "description", "category_path", "sectors", "tags", "material", "color",
             "standards", "properties", "source_ref", "license")


def _metadata_changed(sidecar: dict[str, Any], existing: Part) -> bool:
    """Was the JSON next to an already imported file changed? (then import again)"""
    if sidecar.get("id") not in (None, existing.id):
        return True
    try:
        new = PartCreate(**{k: v for k, v in sidecar.items() if k not in ("id", "components", "source")})
    except Exception:  # noqa: BLE001 - invalid JSON: let the normal import report the error
        return True
    return any(getattr(new, f) != getattr(existing, f) for f in _COMPARED if f in sidecar)


def _ingest_one(
    files: list[Path],
    primary: Path,
    repo: Repository,
    company_id: str | None,
    enricher: Enricher | None,
    thumb_root: Path | None,
    report: IngestReport,
    group: str | None = None,
    ignored: set[Path] | frozenset[Path] = frozenset(),
) -> tuple[str, str, list[dict[str, Any]]]:
    checksum = file_checksum(primary)
    existing = repo.find_by_checksum(checksum, company_id)
    # a JSON that .partsfinderignore excludes is never read either
    sidecar = None if primary.with_suffix(".json") in ignored else load_sidecar(primary)
    if existing and not (sidecar and _metadata_changed(sidecar, existing)):
        if existing.access_group != group:              # only who may see it changed (.partsfinderaccess)
            repo.set_access_group(existing.id, company_id, group)
            return "updated", existing.id, []
        return "skipped", existing.id, []
    # the same file with new content: the same part (same id), not a second one next to the old
    same_path = None if existing else repo.find_by_primary_path(_rel(primary), company_id)

    geom = analyze(primary)
    if sidecar:
        meta = dict(sidecar)
        if existing:                         # same CAD file, changed JSON: update under the same id
            meta.setdefault("id", existing.id)
        elif same_path:
            meta.setdefault("id", same_path.id)
    else:
        meta = guess_from_filename(primary, geom, repo.taxonomy)
        if enricher is not None:
            try:
                meta = enricher.enrich(primary, geom, meta)
            except Exception as exc:  # noqa: BLE001 - it works without AI too
                report.warnings.append(f"{primary.name}: AI description failed ({exc}), guess from file name")

    if same_path:
        meta.setdefault("id", same_path.id)
    meta.pop("access_group", None)           # never from a JSON or an AI: only from the folder rules
    components = meta.pop("components", None) or []
    source = meta.pop("source", None) or "upload"
    part_id = meta.pop("id", None) or str(uuid.uuid4())

    # first check everything and build the new part completely; only then replace an old version.
    # Otherwise an error in the new data would lose the existing part.
    repo.taxonomy.validate_category(meta.get("category_path", ""))
    repo.taxonomy.validate_sectors(meta.get("sectors", []))
    row = repo.conn.execute("SELECT company_id FROM parts WHERE id = ?", (part_id,)).fetchone()
    if row is not None and row["company_id"] != company_id:
        raise ValueError(f"id '{part_id}' already exists in another library")
    thumb = thumbnail.render(geom, thumb_root / f"{part_id}.png") if (geom and thumb_root) else None
    new_part = PartCreate(
        **meta,
        id=part_id,
        company_id=company_id,
        source=source,
        checksum=checksum,
        bbox_mm=geom.bbox_mm if geom else None,
        volume_mm3=geom.volume_mm3 if geom else None,
        thumbnail_path=_rel(thumb) if thumb else None,
        files=[PartFile(format=file_format(f), path=_rel(f), is_primary=(f == primary)) for f in files],
        access_group=group,
    )
    status = "added"
    replace_id: str | None = None
    links: list[tuple[str, int]] = []
    renamed_from = existing.id if (existing and existing.id != part_id) else None
    if renamed_from:
        # same CAD file, JSON with a new id (e.g. a clearer English id): move the part to the new id,
        # keeping the assemblies it belongs to and the feedback given on it
        if row is not None:
            raise ValueError(f"cannot rename '{renamed_from}' to '{part_id}': that id is already in use")
        links = [(r["assembly_id"], r["quantity"]) for r in repo.conn.execute(
            "SELECT assembly_id, quantity FROM assembly_components WHERE part_id = ?", (renamed_from,))]
        replace_id = renamed_from
        status = "updated"
    elif row is not None:
        # the links in which this part is a component disappear with the old part
        # (ON DELETE CASCADE); remember and restore them, because the assembly itself is not read again
        links = [(r["assembly_id"], r["quantity"]) for r in repo.conn.execute(
            "SELECT assembly_id, quantity FROM assembly_components WHERE part_id = ?", (part_id,))]
        replace_id = part_id
        status = "updated"
    # old version out and new version in, in one transaction: a failed insert keeps the old part
    part = repo.add_part(new_part, replace_id=replace_id)
    if links:
        with repo.conn:
            repo.conn.executemany(
                "INSERT OR IGNORE INTO assembly_components(assembly_id, part_id, quantity) VALUES (?,?,?)",
                [(a, part.id, q) for a, q in links])
    if renamed_from:
        with repo.conn:
            repo.conn.execute("UPDATE feedback SET part_id = ? WHERE part_id = ?", (part.id, renamed_from))
        report.warnings.append(f"renamed {renamed_from} -> {part.id}")
    if REVIEW_TAG in part.tags:
        report.needs_review.append(part.id)
    return status, part.id, components
