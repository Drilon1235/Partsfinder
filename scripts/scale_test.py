"""Scale test: how fast does search stay as the database grows?

Makes a temporary database with N artificial parts (variants of the test data,
with random dimensions) and measures the search time. The real database is not touched.

Usage (from the project folder):
    backend\\.venv\\Scripts\\python scripts\\scale_test.py [--sizes 10000,50000,100000] [--real]

--real uses the real embedding model (much slower to build, ~5-15 min per 100,000).
Without --real simple embeddings are used: the search speed is then the same,
only the quality of the results says nothing.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))
sys.path.insert(0, str(PROJECT / "scripts"))

import sqlite_vec  # noqa: E402

from partsfinder.config import get_settings  # noqa: E402
from partsfinder.db import connect  # noqa: E402
from partsfinder.ingest.embeddings import HashingEmbedder, SentenceTransformerEmbedder  # noqa: E402
from partsfinder.repository import Repository  # noqa: E402
from partsfinder.search import SearchEngine, SearchFilters  # noqa: E402

QUERIES = ["green garden chair", "hex bolt M8x40 DIN 933", "ball bearing 6204", "waterproof enclosure for electronics",
           "something to hang a shelf on the wall", "titanium rocket engine"]
COMPANIES = [None] * 6 + [f"company_{i:03d}" for i in range(40)]


def load_templates() -> list[dict]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", PROJECT / "scripts" / "generate_testdata.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen"] = mod
    spec.loader.exec_module(mod)
    return [m.metadata() for m in mod.catalog()]


def fill(conn, n: int, embedder, rng: random.Random, templates: list[dict]) -> float:
    start = time.time()
    batch = 2000
    now = "2026-01-01T00:00:00+00:00"
    done = conn.execute("SELECT count(*) FROM parts").fetchone()[0]
    while done < n:
        rows, texts = [], []
        for _ in range(min(batch, n - done)):
            t = rng.choice(templates)
            scale = rng.uniform(0.5, 2.0)
            dims = [round(rng.uniform(5, 2000) if not t.get("bbox_mm") else d * scale, 1) for d in (t.get("bbox_mm") or [0, 0, 0])]
            name = f"{t['name']} variant {rng.randint(1, 9999)}"
            company = rng.choice(COMPANIES)
            rows.append((str(uuid.uuid4()), company, t["kind"], name, t["description"], t["category_path"],
                         json.dumps(t["sectors"]), json.dumps(t["tags"]), t.get("material"), t.get("color"),
                         *dims, json.dumps(t["standards"]), "{}", "scale_test", now, now))
            texts.append(f"{name}. {t['description']}. {' '.join(t['tags'])}")
        with conn:
            for c in {r[1] for r in rows if r[1]}:
                conn.execute("INSERT OR IGNORE INTO companies(id, name, created_at) VALUES (?, ?, ?)", (c, c, now))
            conn.executemany(
                """INSERT INTO parts (id, company_id, kind, name, description, category_path, sectors, tags,
                   material, color, bbox_x_mm, bbox_y_mm, bbox_z_mm, standards, properties, source,
                   created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            pks = [r[0] for r in conn.execute(
                f"SELECT pk FROM parts ORDER BY pk DESC LIMIT {len(rows)}").fetchall()][::-1]
            vecs = embedder.embed_passages(texts)
            conn.executemany("INSERT INTO parts_vec(rowid, embedding) VALUES (?, ?)",
                             [(pk, sqlite_vec.serialize_float32(v)) for pk, v in zip(pks, vecs)])
        done += len(rows)
        print(f"  {done:>7} parts ({time.time() - start:.0f} s)", end="\r", flush=True)
    print()
    return time.time() - start


def measure(engine: SearchEngine, repeat: int = 3) -> dict[str, float]:
    times = []
    for _ in range(repeat):
        for q in QUERIES:
            for company in (None, "company_001"):
                t0 = time.perf_counter()
                engine.search(q, company, limit=10)
                times.append(time.perf_counter() - t0)
    t0 = time.perf_counter()
    engine.search("chair", None, SearchFilters(max_dims_mm=(600, 600, 900), category="furniture"), limit=10)
    filtered = time.perf_counter() - t0
    times.sort()
    return {"avg": sum(times) / len(times), "p95": times[int(len(times) * 0.95) - 1], "max": times[-1],
            "filtered": filtered}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10000,50000,100000")
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args()
    sizes = sorted(int(x) for x in args.sizes.split(","))
    s = get_settings()
    embedder = SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim) if args.real \
        else HashingEmbedder(s.embedding_dim)
    rng = random.Random(42)
    templates = load_templates()

    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "scale.db", s.embedding_dim)
        engine = SearchEngine(Repository(conn), embedder)
        print(f"Scale test with {'the real model' if args.real else 'simple embeddings'}\n")
        report = []
        for n in sizes:
            print(f"Building up to {n} parts...")
            build = fill(conn, n, embedder, rng, templates)
            m = measure(engine)
            report.append((n, build, m))
        conn.close()

    print(f"\n{'parts':>10} {'average':>10} {'95%':>8} {'slowest':>8} {'with filters':>12}")
    for n, _, m in report:
        print(f"{n:>10} {m['avg'] * 1000:>8.0f} ms {m['p95'] * 1000:>5.0f} ms {m['max'] * 1000:>5.0f} ms "
              f"{m['filtered'] * 1000:>9.0f} ms")
    print("\nGoal from the test plan: answer in under 5 seconds (with AI included).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
