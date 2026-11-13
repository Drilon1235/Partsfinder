"""Command line for the import.

    python -m partsfinder.ingest FOLDER [--company ID]  import a folder
    python -m partsfinder.ingest FOLDER --company ID --sync
                                                       also remove parts whose file is gone or now excluded
    python -m partsfinder.ingest --remove FOLDER --company ID
                                                       remove every part from that folder, completely
    python -m partsfinder.ingest --company ID --confidential | --not-confidential
                                                       no part of this company ever goes to an outside AI
    python -m partsfinder.ingest --testdata [--fresh]   import all test data from data/

Folder rules (.partsfinderignore, .partsfinderaccess): docs/10_COMPANY_LIBRARIES.md

Options:
    --offline        simple embeddings without an AI model (no download needed)
    --no-ai          no Claude descriptions, even if there is an API key
    --no-thumbnails  do not make PNG previews (faster)
    --db PATH        other database than in the settings
    --fresh          (only with --testdata) empty the database first
    --allow-mass-removal  let --sync remove more than half of a folder (only when that is right)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import PROJECT_DIR, get_settings
from ..db import connect
from ..repository import Repository
from .embeddings import HashingEmbedder, SentenceTransformerEmbedder
from .metadata import make_enricher
from .pipeline import ingest_folder, remove_folder


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m partsfinder.ingest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="folder with CAD files")
    ap.add_argument("--company", help="company (empty = general library)")
    ap.add_argument("--testdata", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--no-thumbnails", action="store_true")
    ap.add_argument("--db")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--allow-mass-removal", action="store_true")
    ap.add_argument("--remove", metavar="FOLDER")
    ap.add_argument("--confidential", action="store_true")
    ap.add_argument("--not-confidential", action="store_true")
    args = ap.parse_args(argv)
    setting_only = args.confidential or args.not_confidential
    if not args.folder and not args.testdata and not args.remove and not setting_only:
        ap.error("give a folder, or use --testdata, --remove or --confidential")
    if (args.remove or setting_only) and not args.company:
        ap.error("--remove and --confidential need --company")
    if args.confidential and args.not_confidential:
        ap.error("choose --confidential or --not-confidential")

    settings = get_settings()
    db_path = Path(args.db) if args.db else settings.db_path
    if args.fresh:
        if not args.testdata:
            ap.error("--fresh only works together with --testdata")
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        print(f"Database emptied: {db_path}")

    conn = connect(db_path, settings.embedding_dim)
    repo = Repository(conn)

    if setting_only:
        repo.set_confidential(args.company, args.confidential)
        repo.audit("local", args.company, "settings", args.company, f"confidential={args.confidential}")
        print(f"Company {args.company}: {'confidential (never sent to an outside AI)' if args.confidential else 'not confidential'}.")
        if not args.folder and not args.remove:
            conn.close()
            return 0
    if args.remove:
        removed = remove_folder(repo, args.remove, args.company)
        repo.audit("local", args.company, "remove", str(args.remove), f"{len(removed)} parts")
        print(f"Removed {len(removed)} parts of {args.company} from {args.remove} (previews and 3D caches too).")
        if not args.folder:
            conn.close()
            return 0

    if args.offline:
        embedder, embedder_name = HashingEmbedder(settings.embedding_dim), "hashing"
    else:
        embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_dim)
        embedder_name = settings.embedding_model
    # all embeddings in one database must come from the same model
    row = conn.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()
    if row and row[0] != embedder_name:
        print(f"ERROR: this database uses embeddings from '{row[0]}', now chosen: '{embedder_name}'.")
        print("Use the same setting, or rebuild the test data with --testdata --fresh.")
        return 1
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('embedder', ?)", (embedder_name,))

    enricher = None
    if not args.no_ai:
        enricher = make_enricher(settings, repo.taxonomy)
    if enricher is not None:
        print("Claude fills in metadata for files without JSON.")
    else:
        print("No Claude (no AI configured or --no-ai): files without JSON get a guess + 'needs-review'.")

    jobs: list[tuple[Path, str | None]] = []
    if args.testdata:
        data = PROJECT_DIR / "data"
        if (data / "global").is_dir():
            jobs.append((data / "global", None))
        companies = data / "companies"
        if companies.is_dir():
            jobs += [(d, d.name) for d in sorted(companies.iterdir()) if d.is_dir()]
    else:
        jobs.append((Path(args.folder), args.company))

    failed = 0
    for folder, company in jobs:
        print(f"\n== {folder} -> {'company ' + company if company else 'general library'} ==")
        report = ingest_folder(folder, repo, embedder, company_id=company, enricher=enricher,
                               make_thumbnails=not args.no_thumbnails, log=lambda s: None,
                               sync=args.sync, allow_mass_removal=args.allow_mass_removal)
        repo.audit("local", company, "ingest", str(folder),
                   f"added {len(report.added)}, updated {len(report.updated)}, removed {len(report.removed)}, "
                   f"failed {len(report.failed)}{', sync' if args.sync else ''}")
        print(report.summary())
        failed += len(report.failed)

    total = conn.execute("SELECT count(*) FROM parts").fetchone()[0]
    with_vec = conn.execute("SELECT count(*) FROM parts_vec").fetchone()[0]
    print(f"\nDatabase {db_path.name}: {total} parts, {with_vec} with embedding.")
    conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
