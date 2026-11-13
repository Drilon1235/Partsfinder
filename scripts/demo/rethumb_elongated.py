"""Re-render the previews of elongated parts (profiles, shafts, tubes, threaded rod) as a short piece.

A 30 x 30 x 1000 mm profile used to show as a thin line. New imports do this automatically
(ingest/thumbnail.py); this script redoes the existing previews. Only the PNG files change, not the
database. Run it from the project folder:

    backend\\.venv\\Scripts\\python scripts\\demo\\rethumb_elongated.py [--db path] [--start N] [--count N]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from partsfinder.ingest.geometry import analyze  # noqa: E402
from partsfinder.ingest.thumbnail import is_elongated, render  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "backend" / "partsfinder.db"))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=100000)
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)       # read only
    rows = con.execute("""
        SELECT p.id, p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm, p.thumbnail_path,
               (SELECT f.path FROM part_files f WHERE f.part_id = p.id AND f.format IN ('step', 'stp', 'stl')
                ORDER BY f.is_primary DESC LIMIT 1)
        FROM parts p WHERE p.thumbnail_path IS NOT NULL AND p.bbox_x_mm > 0 ORDER BY p.id""").fetchall()
    todo = [r for r in rows if r[5] and is_elongated(r[1:4])][args.start:args.start + args.count]
    done = failed = 0
    t0 = time.time()
    for pid, *_dims, thumb, src in todo:
        src_p = Path(src) if Path(src).is_absolute() else ROOT / src
        out = Path(thumb) if Path(thumb).is_absolute() else ROOT / thumb
        try:
            geom = analyze(src_p)
            if geom and render(geom, out):
                done += 1
        except Exception as exc:                    # one broken file must not stop the rest
            failed += 1
            print(f"  {pid}: {exc}")
    print(f"{done} previews redone, {failed} failed, {len(todo)} in this batch ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
