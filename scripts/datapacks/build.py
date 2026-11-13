"""Builds a data pack: thousands of openly licensed parts, ready to install in Partsfinder.

A data pack is one folder (or .zip) with:
    pack.json        name, version, licence, attribution, number of parts
    parts.jsonl      one part per line (the fields of PartCreate, see docs/03_DATAMODEL.md)
    thumbnails/      a preview per part (<id>.png)
    files/           the CAD files, for packs that ship them ("files": "included")
    LICENSE.txt      the licence of the data, ATTRIBUTION.md who made it
Packs with "files": "remote" link every part to its file at the original repository, pinned to one commit,
so the pack stays small; the app downloads a file only when someone opens it.

Usage (from the project folder, with the backend environment):
    python scripts/datapacks/build.py kicad    --src PATH/TO/kicad-packages3D
    python scripts/datapacks/build.py freecad  --src PATH/TO/FreeCAD-library
    python scripts/datapacks/build.py adafruit --src PATH/TO/Adafruit_CAD_Parts
    python scripts/datapacks/build.py standard-parts --src FOLDER_MADE_BY_generate_standard_parts.py
Options: --out dist/packs  --workers 2  --limit N (a quick test)  --zip
The work is saved as it goes (work/done.jsonl): run the same command again to continue after a stop.
Install a pack: python -m partsfinder.packs install dist/packs/<name>  (from backend/), or in the app.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import shutil
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "backend"))
sys.path.insert(0, str(HERE))

from common import PACK_FORMAT, Item, Source, git_commit  # noqa: E402,F401


def sources() -> dict[str, Source]:
    """Every module in sources/ with a SOURCE."""
    import importlib
    import pkgutil

    import sources as pkg
    found = [importlib.import_module(f"sources.{m.name}") for m in pkgutil.iter_modules(pkg.__path__)]
    return {mod.SOURCE.name: mod.SOURCE for mod in found if hasattr(mod, "SOURCE")}


# ---- one part (runs in a worker process) ------------------------------------------------------------
_taxonomy = None


def _work(item: Item, out: Path) -> dict[str, Any]:
    global _taxonomy
    from partsfinder.ingest import thumbnail
    from partsfinder.ingest.geometry import analyze, file_checksum, file_format
    from partsfinder.models import PartCreate
    from partsfinder.taxonomy import Taxonomy

    if _taxonomy is None:
        _taxonomy = Taxonomy.load()
    meta = dict(item.meta)
    meta["category_path"] = _taxonomy.validate_category(meta["category_path"])
    meta["sectors"] = _taxonomy.validate_sectors(meta.get("sectors", []))
    geom = analyze(item.file)
    if geom is None:
        raise ValueError("cannot read the CAD file")
    if not all(d > 0 for d in geom.bbox_mm):
        raise ValueError(f"empty or flat model {geom.bbox_mm}")
    thumb = out / "thumbnails" / f"{item.id}.png"
    thumbnail.render(geom, thumb)
    fmt = file_format(item.file)
    path = item.url or f"files/{item.id}{item.file.suffix.lower()}"
    if not item.url:
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.file, target)
    part = PartCreate(**meta, id=item.id, checksum=file_checksum(item.file), bbox_mm=geom.bbox_mm,
                      volume_mm3=geom.volume_mm3, thumbnail_path=f"thumbnails/{item.id}.png",
                      files=[{"format": fmt, "path": path, "is_primary": True}])
    return json.loads(part.model_dump_json(exclude_none=True, exclude={"company_id", "access_group"}))


def _refresh(row: dict[str, Any], item: Item) -> dict[str, Any]:
    """The metadata as the source gives it now (a better name or category needs no new geometry)."""
    from partsfinder.models import PartCreate
    from partsfinder.taxonomy import Taxonomy

    global _taxonomy
    if _taxonomy is None:
        _taxonomy = Taxonomy.load()
    meta = dict(item.meta)
    meta["category_path"] = _taxonomy.validate_category(meta["category_path"])
    meta["sectors"] = _taxonomy.validate_sectors(meta.get("sectors", []))
    keep = {k: row[k] for k in ("id", "checksum", "bbox_mm", "volume_mm3", "thumbnail_path", "files") if k in row}
    part = PartCreate(**meta, **keep)
    return json.loads(part.model_dump_json(exclude_none=True, exclude={"company_id", "access_group"}))


def _safe(item: Item, out: Path) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        return item.id, _work(item, out), None
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the pack
        return item.id, None, f"{type(exc).__name__}: {exc}"[:300]


# ---- the pack ----------------------------------------------------------------------------------------
def build(source: Source, src: Path, out_root: Path, workers: int, limit: int | None, make_zip: bool) -> Path:
    out = out_root / source.name
    work = out / "work"
    for d in (out, work, out / "thumbnails"):
        d.mkdir(parents=True, exist_ok=True)
    items = source.items(src)
    ids = [i.id for i in items]
    dupes = {i for i in ids if ids.count(i) > 1} if len(ids) != len(set(ids)) else set()
    if dupes:
        raise SystemExit(f"duplicate ids in {source.name}: {sorted(dupes)[:10]}")
    if limit:
        items = items[:limit]
    done_file, failed_file = work / "done.jsonl", work / "failed.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if done_file.exists():
        for line in done_file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["id"]] = row
    todo = [i for i in items if i.id not in done]
    print(f"{source.name}: {len(items)} parts, {len(done)} already done, {len(todo)} to do ({workers} workers)", flush=True)
    t0, n, failed = time.time(), 0, 0
    with open(done_file, "a", encoding="utf-8") as fd, open(failed_file, "a", encoding="utf-8") as ff, \
            ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=200,
                                mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(_safe, i, out) for i in todo]
        for fut in as_completed(futures):
            pid, row, err = fut.result()
            n += 1
            if row is not None:
                done[pid] = row
                fd.write(json.dumps(row, ensure_ascii=False) + "\n")
                fd.flush()
            else:
                failed += 1
                ff.write(json.dumps({"id": pid, "error": err}) + "\n")
                ff.flush()
            if n % 100 == 0 or n == len(todo):
                rate = n / max(time.time() - t0, 1e-6)
                print(f"  {n}/{len(todo)}  failed {failed}  {rate:.1f}/s  ~{(len(todo) - n) / max(rate, 1e-6) / 60:.0f} min left",
                      flush=True)

    rows = [_refresh(done[i.id], i) for i in sorted(items, key=lambda x: x.id) if i.id in done]
    with open(out / "parts.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    info = {
        "format": PACK_FORMAT, "name": source.name, "title": source.title,
        "version": date.today().isoformat(), "license": source.license, "homepage": source.homepage,
        "files": source.files, "source_revision": source.revision(src) if source.revision else git_commit(src),
        "parts": len(rows), "built_with": "scripts/datapacks/build.py",
    }
    (out / "pack.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    lic = src / source.license_file if source.license_file else None
    (out / "LICENSE.txt").write_text(lic.read_text(encoding="utf-8") if lic and lic.exists() else source.license_text,
                                     encoding="utf-8")
    (out / "ATTRIBUTION.md").write_text(source.attribution, encoding="utf-8")
    print(f"{source.name}: {len(rows)} parts in {out}", flush=True)
    if make_zip:
        target = out_root / f"partsfinder-pack-{source.name}-{info['version']}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob("*")):
                if p.is_file() and work not in p.parents:
                    stored = p.suffix.lower() == ".png"           # already compressed
                    z.write(p, p.relative_to(out).as_posix(),
                            compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        print(f"zip: {target} ({target.stat().st_size / 1e6:.0f} MB)", flush=True)
    return out


def main() -> int:
    all_sources = sources()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", choices=sorted(all_sources))
    ap.add_argument("--src", required=True, help="the clone (or generated folder) of the source")
    ap.add_argument("--out", default=str(PROJECT / "dist" / "packs"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--zip", action="store_true")
    args = ap.parse_args()
    build(all_sources[args.source], Path(args.src).resolve(), Path(args.out), args.workers, args.limit, args.zip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
