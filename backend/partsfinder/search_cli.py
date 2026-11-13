"""Search from the command line (to try the search engine, without Claude if you like).

    python -m partsfinder.search_cli "green garden chair" [--company company_a] [--sector horticulture]
    python -m partsfinder.search_cli                    interactive: keep asking questions

Filters: --category, --sector (meerdere keren), --material, --color, --standard,
         --kind part|assembly, --max 600x600x900, --min 10x10x10, --library all|global|company
In interactive mode you switch company with:  :company company_a   (or :company -)

With a Claude API key in backend/.env Claude judges the results (AI mode).
Use --no-ai to see only the search engine. Filters after the question switch that
question to the plain search engine.
"""
from __future__ import annotations

import argparse
import shlex
import sys

from .ai import AIError, PartFinder, ai_label, make_finder
from .config import get_settings
from .db import connect
from .ingest.embeddings import HashingEmbedder, SentenceTransformerEmbedder
from .repository import Repository
from .search import SearchEngine, SearchFilters


def parse_dims(text: str | None) -> tuple[float, float, float] | None:
    if not text:
        return None
    parts = [float(x) for x in text.lower().replace("*", "x").split("x")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("dimensions like 600x600x900")
    return tuple(parts)  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m partsfinder.search_cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="*")
    ap.add_argument("--company")
    ap.add_argument("--category")
    ap.add_argument("--sector", action="append", default=[])
    ap.add_argument("--material")
    ap.add_argument("--color")
    ap.add_argument("--standard", action="append", default=[])
    ap.add_argument("--kind", choices=["part", "assembly"])
    ap.add_argument("--max")
    ap.add_argument("--min")
    ap.add_argument("--library", default="all", choices=["all", "global", "company"])
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--offline", action="store_true", help="simple embeddings (for tests only)")
    ap.add_argument("--no-ai", action="store_true", help="without Claude, search engine only")
    return ap


FILTER_FLAGS = ("--category", "--sector", "--material", "--color", "--standard", "--kind", "--max",
                "--min", "--library")


def print_ai(result, usage) -> None:
    print(f"  {result.status.upper()}: {result.message}")
    req = result.requirements
    extra = f", category {req['category']}" if req.get("category") else ""
    print(f"  (search text: {req.get('search_text')!r}{extra})")
    for i, j in enumerate(result.results, 1):
        p = j.hit.part
        dims = "x".join(f"{d:.0f}" for d in p.bbox_mm) if p.bbox_mm else "-"
        print(f"  {i}. [{j.verdict}] {p.name}  ({p.company_id or 'general'}, {dims} mm)")
        for m in j.match_reasons:
            print(f"       + {m}")
        for m in j.mismatch_reasons:
            print(f"       - {m}")
    print(f"  [{usage.summary()}]")


def print_hits(hits) -> None:
    if not hits:
        print("  (nothing found)")
        return
    print(f"  {'#':>2} {'score':>6} {'sim.':>6}  {'library':9} {'name':34} {'size (mm)':>14}  category")
    for i, h in enumerate(hits, 1):
        p = h.part
        dims = "x".join(f"{d:.0f}" for d in p.bbox_mm) if p.bbox_mm else "-"
        sim = f"{h.vector_similarity:.3f}" if h.vector_similarity is not None else "-"
        lib = p.company_id or "general"
        print(f"  {i:>2} {h.score:6.4f} {sim:>6}  {lib[:9]:9} {p.name[:34]:34} {dims[:14]:>14}  "
              f"{p.category_path[:40]}")


def run_query(engine: SearchEngine, args: argparse.Namespace) -> None:
    filters = SearchFilters(
        category=args.category, sectors=args.sector, material=args.material, color=args.color,
        standards=args.standard, kind=args.kind, max_dims_mm=parse_dims(args.max),
        min_dims_mm=parse_dims(args.min), library=args.library,
    )
    hits = engine.search(" ".join(args.query), args.company, filters, limit=args.limit)
    print_hits(hits)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = build_parser()
    args = ap.parse_args(argv)
    settings = get_settings()
    conn = connect(settings.db_path, settings.embedding_dim)
    row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
    stored = row[0] if row else None
    if args.offline or stored == "hashing":
        embedder = HashingEmbedder(settings.embedding_dim)
    else:
        embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_dim)
    repo = Repository(conn)
    engine = SearchEngine(repo, embedder)
    count = conn.execute("SELECT count(*) FROM parts").fetchone()[0]
    finder: PartFinder | None = None
    if not args.no_ai:
        try:
            finder = make_finder(engine, repo.taxonomy, settings)
        except AIError:
            finder = None

    def answer(sub: argparse.Namespace, raw: str) -> None:
        if finder and not any(flag in raw for flag in FILTER_FLAGS):
            try:
                print_ai(finder.find(" ".join(sub.query), sub.company, limit=sub.limit), finder.usage)
                return
            except AIError as exc:
                print(f"  AI not available: {exc}\n  Plain search results:")
        run_query(engine, sub)

    if args.query:
        answer(args, " ".join(argv or sys.argv[1:]))
        return 0

    company = args.company
    mode = f"with Claude ({ai_label(finder)})" if finder else "without Claude (search engine only)"
    print(f"Partsfinder search {mode} - {count} parts in the database. Type a question (empty = quit).")
    print("Filters may follow, e.g.:  chair --sector horticulture --max 600x600x900")
    print("Switch company:  :company company_a   (or :company - for the general library only)")
    while True:
        try:
            line = input(f"\n[{company or 'general'}] search> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        if line.startswith(":company"):
            value = line.split(maxsplit=1)[1].strip() if " " in line else "-"
            company = None if value == "-" else value
            continue
        try:
            sub = ap.parse_args(shlex.split(line, posix=True))
        except SystemExit:
            continue
        sub.company = company
        answer(sub, line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
