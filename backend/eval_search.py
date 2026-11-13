"""Evaluation of the search engine with the 50 test questions from tests/queries.yaml (phase 8).

Works without AI (as the system runs now): plain search engine + "nothing found" check.
Measures per group how often the right answer is at position 1 and in the top 3, how often
"nothing found" is correct, how fast it is, and whether anything of another company ever leaks.
The report is also written to backend/eval_log.txt.

Usage:  python eval_search.py [--offline] [--verbose]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import yaml

from partsfinder.ai import search_without_ai
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest.embeddings import HashingEmbedder, SentenceTransformerEmbedder
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, SearchFilters

HERE = Path(__file__).resolve().parent
QUERIES = HERE / "tests" / "queries.yaml"
LOG = HERE / "eval_log.txt"
GROUPS = ["clear", "vague", "requirements", "none", "separation"]
# goals from docs/06_TESTPLAN.md
GOAL_TOP1, GOAL_TOP3, GOAL_NONE = 0.60, 0.80, 0.90


def load_cases(path: Path = QUERIES) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    for c in cases:
        c.setdefault("group", "clear")
    return cases


def case_filters(case: dict[str, Any]) -> SearchFilters | None:
    f = case.get("filters")
    if not f:
        return None
    f = dict(f)
    for key in ("max_dims_mm", "min_dims_mm"):
        if f.get(key):
            f[key] = tuple(float(x) for x in f[key])
    return SearchFilters(**f)


def is_correct(case: dict[str, Any], part) -> bool:
    """Does this part meet everything the test question expects?"""
    checks = ("ids", "category", "material", "company_top")
    if not any(k in case for k in checks):
        return False
    if "ids" in case and part.id not in case["ids"]:
        # also fine: another part whose name contains everything asked (e.g. from the demo library)
        names = case.get("name_has") or []
        if not names or not all(n.lower() in part.name.lower() for n in names):
            return False
    if "category" in case and not part.category_path.startswith(case["category"]):
        return False
    if "material" in case and case["material"].lower() not in (part.material or "").lower():
        return False
    if "company_top" in case and part.company_id != case["company_top"]:
        return False
    return True


def pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "-"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    verbose = "--verbose" in sys.argv
    s = get_settings()
    conn = connect(s.db_path, s.embedding_dim)
    row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
    offline = "--offline" in sys.argv or bool(row and row[0] == "hashing")
    embedder = HashingEmbedder(s.embedding_dim) if offline else \
        SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim)
    engine = SearchEngine(Repository(conn), embedder)
    engine.search("warm up", None, limit=1)        # loading the model does not count in the time

    lines: list[str] = []

    def out(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    cases = load_cases()
    out(f"Evaluation without AI: {len(cases)} questions, embeddings {'offline (hashing)' if offline else s.embedding_model}")
    out("Only deviations are shown (--verbose for everything).\n")

    results = []          # (case, ok1, ok3, status)
    leaks = 0
    times: list[float] = []
    for case in cases:
        company = case.get("company")
        t0 = time.perf_counter()
        r = search_without_ai(engine, case["q"], company, limit=10, filters=case_filters(case))
        times.append(time.perf_counter() - t0)
        parts = [j.hit.part for j in r.results]
        leak = [p.id for p in parts if p.company_id not in (None, company)]
        leaks += bool(leak)
        if case.get("status") == "none":
            ok1 = ok3 = r.status == "none"
        else:
            ok1 = bool(parts) and is_correct(case, parts[0])
            ok3 = any(is_correct(case, p) for p in parts[:3])
        results.append((case, ok1, ok3, r.status))
        if verbose or not ok1 or leak:
            mark = "OK  " if ok1 else ("top3" if ok3 else "MIS ")
            who = f" [{company}]" if company else ""
            first = parts[0].name if parts else "(nothing found)"
            out(f"[{mark}] {case['group']:9} {case['q']}{who}  ->  {first}" + (f"   LEAK: {leak}" if leak else ""))

    out("")
    out(f"{'group':12} {'questions':>9} {'position 1':>10} {'top 3':>7}")
    for g in GROUPS:
        rs = [x for x in results if x[0]["group"] == g]
        if rs:
            out(f"{g:12} {len(rs):>9} {pct(sum(x[1] for x in rs), len(rs)):>10} {pct(sum(x[2] for x in rs), len(rs)):>7}")

    items = [x for x in results if x[0].get("status") != "none"]
    nones = [x for x in results if x[0].get("status") == "none"]
    top1, top3 = sum(x[1] for x in items), sum(x[2] for x in items)
    none_ok = sum(x[1] for x in nones)
    false_none = sum(1 for x in items if x[3] == "none")
    lat = sorted(times)

    def goal(value: float, target: float) -> str:
        return "met" if value >= target else "NOT met"

    out("")
    out(f"Existing part at position 1:  {pct(top1, len(items)):>5}  (goal {GOAL_TOP1:.0%}: {goal(top1 / len(items), GOAL_TOP1)})")
    out(f"Existing part in top 3:        {pct(top3, len(items)):>5}  (goal {GOAL_TOP3:.0%}: {goal(top3 / len(items), GOAL_TOP3)})")
    out(f"Correct 'nothing found':       {pct(none_ok, len(nones)):>5}  (goal {GOAL_NONE:.0%}: {goal(none_ok / len(nones), GOAL_NONE)})")
    out(f"Wrong 'nothing found':         {false_none} of {len(items)}")
    out(f"Leaks between companies:        {leaks}  (goal 0: {'met' if leaks == 0 else 'NOT met'})")
    out(f"Speed: average {sum(times) / len(times) * 1000:.0f} ms, slowest {lat[-1] * 1000:.0f} ms per question")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if leaks == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
