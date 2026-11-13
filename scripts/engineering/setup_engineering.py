"""One step: build the engineering demo library, enrich the standard parts, import, evaluate.

Imports data/global/engineering, data/global/standard-parts and data/global/freecad; changed JSON files
(new English ids, polished names) update the existing parts in place.

    backend\\.venv\\Scripts\\python scripts\\engineering\\setup_engineering.py      (Windows, or scripts\\windows\\engineering.bat)
    backend/.venv/bin/python scripts/engineering/setup_engineering.py            (Mac/Linux)

Options: --skip-build (STEP files already there), --no-thumbnails, --db PATH
Log: backend/engineering_log.txt. Safe to run again: unchanged parts are skipped, changed JSON updates.
Before the first import the current database is copied to backend/partsfinder.pre-engineering.db.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
BACKEND = PROJECT / "backend"
LOG = BACKEND / "engineering_log.txt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-thumbnails", action="store_true")
    ap.add_argument("--db")
    args = ap.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if args.db:
        env["PARTSFINDER_DB_PATH"] = args.db
    lines: list[str] = []

    def out(text: str) -> None:
        print(text, flush=True)
        lines.append(text)

    def run(title: str, cmd: list[str], cwd: Path, keep: int = 12) -> int:
        out(f"\n== {title}")
        t0 = time.time()
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = (p.stdout + p.stderr).replace("\r", "\n")
        rows = [r for r in text.splitlines() if r.strip()]
        for r in rows[-keep:]:
            out("   " + r)
        out(f"   ({time.time() - t0:.0f} s, exit code {p.returncode})")
        return p.returncode

    py = sys.executable
    db = Path(env.get("PARTSFINDER_DB_PATH") or BACKEND / "partsfinder.db")
    backup = BACKEND / "partsfinder.pre-engineering.db"
    if db.exists() and not backup.exists():
        shutil.copy2(db, backup)
        out(f"Backup of the database: {backup.name}")

    codes = []
    if not args.skip_build:
        codes.append(run("Build engineering library (STEP + JSON)", [py, str(HERE / "build.py")], PROJECT, 4))
    codes.append(run("Enrich standard parts (property classes, DIN numbers, bearing designations)",
                     [py, str(HERE / "enrich_standard_parts.py")], PROJECT, 3))
    extra = ["--no-thumbnails"] if args.no_thumbnails else []
    for folder in ("engineering", "standard-parts", "freecad"):
        path = PROJECT / "data" / "global" / folder
        if path.is_dir():
            codes.append(run(f"Import data/global/{folder}",
                             [py, "-m", "partsfinder.ingest", str(path), "--no-ai", *extra], BACKEND, 6))
    codes.append(run("Engineering evaluation (no AI)", [py, "eval_engineering.py"], BACKEND, 14))
    codes.append(run("Original 50-question evaluation (no AI)", [py, "eval_search.py"], BACKEND, 10))
    codes.append(run("Unit tests", [py, "-m", "pytest", "-q"], BACKEND, 4))
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(f"\nLog written to {LOG}")
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main())
