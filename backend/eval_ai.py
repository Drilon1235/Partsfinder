"""Evaluation of the AI layer (phase 5) with the real Claude.

Runs the 50 test questions from tests/queries.yaml with Claude as judge, on the API key in backend/.env.
Writes everything to backend/ai_log.txt. It stops as soon as the spending cap (PARTSFINDER_MAX_SPEND_USD)
is reached.

Usage:  python eval_ai.py [--model claude-sonnet-5-5] [--only text]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from eval_search import case_filters, is_correct, load_cases
from partsfinder.ai import AIError, BudgetExceeded, ai_label, make_finder
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest.embeddings import HashingEmbedder, SentenceTransformerEmbedder
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine

LOG = Path(__file__).resolve().parent / "ai_log.txt"

# Extra questions that only make sense with AI: the right answer is a status
EXTRA_AI_CASES = [
    {"group": "ai", "q": "hex bolt M30x200", "status": ["partial", "none"]},   # M20 is the largest
    {"group": "ai", "q": "purple garden chair", "status": ["partial"]},        # garden chairs exist, no purple ones
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--only")
    args = ap.parse_args()

    s = get_settings()
    model = args.model or s.claude_model
    lines: list[str] = []

    def out(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    def save() -> None:
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    conn = connect(s.db_path, s.embedding_dim)
    row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
    embedder = HashingEmbedder(s.embedding_dim) if (row and row[0] == "hashing") else \
        SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim)
    engine = SearchEngine(Repository(conn), embedder)
    try:
        finder = make_finder(engine, Repository(conn).taxonomy, s, model=model)
    except AIError as exc:
        out(f"ERROR: {exc}")
        save()
        return 1

    cap = f"cap ${s.max_spend_usd:.2f}"
    out(f"AI evaluation {time.strftime('%Y-%m-%d %H:%M')} - {ai_label(finder)}, {cap}")
    cases = [*load_cases(), *EXTRA_AI_CASES]
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["q"].lower()]
    good = total = leaks = 0
    for case in cases:
        company = case.get("company")
        t0 = time.time()
        try:
            r = finder.find(case["q"], company, limit=5, fixed_filters=case_filters(case))
        except BudgetExceeded as exc:
            out(f"\nSTOPPED: {exc}")
            break
        except AIError as exc:
            out(f"\nERROR at '{case['q']}': {exc}")
            save()
            return 1
        total += 1
        leak = [j.hit.part.id for j in r.results if j.hit.part.company_id not in (None, company)]
        leaks += bool(leak)
        if "status" in case:
            wanted = case["status"] if isinstance(case["status"], list) else [case["status"]]
            ok = r.status in wanted
        else:
            ok = bool(r.results) and is_correct(case, r.results[0].hit.part)
        good += ok
        who = f" [{company}]" if company else ""
        out(f"\n[{'OK ' if ok else 'MIS'}] {case['q']}{who}   ({r.status}, {time.time() - t0:.1f} s)")
        out(f"      search text: {r.requirements.get('search_text')!r}"
            + (f", category: {r.requirements['category']}" if r.requirements.get("category") else "")
            + f", steps: {', '.join(r.requirements.get('search_steps', []))}")
        out(f"      {r.message}")
        for j in r.results[:3]:
            p = j.hit.part
            reasons = "; ".join(j.match_reasons + [f"NOT: {m}" for m in j.mismatch_reasons])
            out(f"      - [{j.verdict}] {p.name} ({p.company_id or 'general'}) {reasons}")
        if leak:
            out(f"      LEAK: {leak}")

    out(f"\nResult: {good}/{total} correct ({good / max(total, 1):.0%}), leaks: {leaks}")
    out(finder.usage.summary())
    if total:
        out(f"Average per search: ${finder.usage.cost_usd / total:.5f}")
    save()
    return 0 if leaks == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
