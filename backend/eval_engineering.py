"""Engineering evaluation: questions as a mechanical engineer asks them (tests/queries_engineering.yaml).

Checks per question, without AI:
- the right part at position 1 (exact designation / size)
- the overall status (found / partial / none)
- no "false fit": a part marked "fits" must meet every spec in the question (checked independently)
- for partial: the deviating spec is reported in the first result
Report also in backend/eval_engineering_log.txt.

Usage:  python eval_engineering.py [--verbose] [--offline]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

from partsfinder.ai import search_without_ai
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest.embeddings import HashingEmbedder, SentenceTransformerEmbedder
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.specs import parse_specs, summarize

HERE = Path(__file__).resolve().parent
QUERIES = HERE / "tests" / "queries_engineering.yaml"
LOG = HERE / "eval_engineering_log.txt"


def top_ok(case, part) -> bool:
    if "ids" in case and part.id in case["ids"]:
        return True
    names = case.get("name_has")
    return bool(names) and all(n.lower() in part.name.lower() for n in names)


def run(engine: SearchEngine, cases: list[dict], verbose: bool = False, out=print) -> dict:
    stats = {"n": 0, "top1": 0, "top1_n": 0, "status": 0, "status_n": 0, "false_fit": 0, "deviation": 0,
             "deviation_n": 0, "need": 0, "need_n": 0, "times": []}
    for case in cases:
        stats["n"] += 1
        t0 = time.perf_counter()
        r = search_without_ai(engine, case["q"], case.get("company"), limit=5)
        stats["times"].append(time.perf_counter() - t0)
        specs = parse_specs(case["q"])
        parts = [j.hit.part for j in r.results]
        problems = []
        if "ids" in case or "name_has" in case:
            stats["top1_n"] += 1
            if parts and top_ok(case, parts[0]):
                stats["top1"] += 1
            else:
                problems.append("wrong first result")
        if "status" in case:
            stats["status_n"] += 1
            if r.status == case["status"]:
                stats["status"] += 1
            else:
                problems.append(f"status {r.status}, expected {case['status']}")
        for j in r.results:
            if j.verdict == "fits" and specs:
                s = summarize(specs, j.hit.part)
                if not s.all_match:
                    stats["false_fit"] += 1
                    problems.append(f"FALSE FIT {j.hit.part.id}")
        if case.get("need"):                       # vague question: the open defining value is named first
            stats["need_n"] += 1
            named = [n["spec"] for n in r.requirements.get("need", []) if n["choices"]]
            expected = case["need"] if isinstance(case["need"], list) else [case["need"]]
            if named[:1] and named[0] in expected:
                stats["need"] += 1
            else:
                problems.append(f"open value {named[:1] or 'none'}, expected {case['need']}")
        if case.get("deviation"):
            stats["deviation_n"] += 1
            first = r.results[0] if r.results else None
            reported = (first.hit.specs.mismatched + first.hit.specs.unknown) if first and first.hit.specs else []
            if first and first.verdict == "close" and any(c.key == case["deviation"] for c in reported):
                stats["deviation"] += 1
            else:
                problems.append(f"deviation '{case['deviation']}' not reported")
        if verbose or problems:
            first = r.results[0] if r.results else None
            label = f"{first.verdict}: {first.hit.part.name}" if first else "(nothing)"
            out(f"[{'OK ' if not problems else 'ERR'}] {case['q']}  ->  {r.status} | {label}"
                + (f"   <- {'; '.join(problems)}" if problems else ""))
            if verbose and first:
                for c in (first.hit.specs.checks if first.hit.specs else []):
                    d = c.as_dict()
                    out(f"        {d['label']:18} requested {d['requested']:14} found {d['found'] or '-':16} {d['status']}")
    return stats


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s = get_settings()
    conn = connect(s.db_path, s.embedding_dim)
    row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
    offline = "--offline" in sys.argv or bool(row and row[0] == "hashing")
    embedder = HashingEmbedder(s.embedding_dim) if offline else SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim)
    engine = SearchEngine(Repository(conn), embedder)
    engine.search("warm up", None, limit=1)
    lines: list[str] = []

    def out(t: str = "") -> None:
        print(t, flush=True)
        lines.append(t)

    cases = yaml.safe_load(QUERIES.read_text(encoding="utf-8"))
    out(f"Engineering evaluation without AI: {len(cases)} questions\n")
    st = run(engine, cases, "--verbose" in sys.argv, out)

    def pct(a, b):
        return f"{a / b:.0%}" if b else "-"
    out("")
    out(f"Exact part at position 1:   {pct(st['top1'], st['top1_n'])} ({st['top1']}/{st['top1_n']})")
    out(f"Correct status:             {pct(st['status'], st['status_n'])} ({st['status']}/{st['status_n']})")
    out(f"Deviation reported:         {pct(st['deviation'], st['deviation_n'])} ({st['deviation']}/{st['deviation_n']})")
    out(f"Open value named (vague):   {pct(st['need'], st['need_n'])} ({st['need']}/{st['need_n']})")
    out(f"False fits (wrong spec):    {st['false_fit']}  (goal 0)")
    out(f"Speed: average {sum(st['times']) / len(st['times']) * 1000:.0f} ms")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if st["false_fit"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
