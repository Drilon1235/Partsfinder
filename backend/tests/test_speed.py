"""Tests for the speed work (10 Nov 2026): the vector index gives the same parts as comparing every part."""
from __future__ import annotations

import math
import random

import pytest
import sqlite_vec

from partsfinder import search as search_mod
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, SearchFilters

DIM = 8
CATEGORY = "connections/bracket/angle-bracket"


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    rnd = random.Random(7)
    for company in ("company_a", "company_b"):
        repo.ensure_company(company)
    # company_b has many parts right next to the question: they fill the KNN set but company_a may not see them
    owners = [None] * 120 + ["company_b"] * 120 + ["company_a"] * 5
    for i, owner in enumerate(owners):
        repo.add_part(PartCreate(id=f"p{i}", name=f"Part {i}", category_path=CATEGORY, company_id=owner))
        base = [1.0] * DIM if owner == "company_b" else [rnd.uniform(-1, 1) for _ in range(DIM)]
        repo.set_embedding(f"p{i}", _unit([x + rnd.uniform(-0.05, 0.05) for x in base]))
    yield SearchEngine(repo, HashingEmbedder(DIM))
    conn.close()


def _scan(engine, qvec, company_id, candidates):
    where, args = engine._filter_sql(company_id, SearchFilters())
    rows = engine.repo.conn.execute(
        f"""SELECT v.rowid AS pk FROM parts_vec v JOIN parts p ON p.pk = v.rowid
            WHERE {where} ORDER BY vec_distance_cosine(v.embedding, ?) LIMIT ?""",
        [*args, sqlite_vec.serialize_float32(qvec), candidates]).fetchall()
    return [r["pk"] for r in rows]


@pytest.mark.parametrize("company_id", [None, "company_a", "company_b"])
def test_vector_index_equals_full_scan(engine, monkeypatch, company_id):
    monkeypatch.setattr(search_mod, "SCAN_BELOW", 0)   # use the index even for this small library
    monkeypatch.setattr(search_mod, "KNN_MIN", 1)      # small KNN set: company_b fills it, so None/company_a fall back
    monkeypatch.setattr(search_mod, "KNN_FACTOR", 2)
    qvec = _unit([1.0] * DIM)
    where, args = engine._filter_sql(company_id, SearchFilters())
    got = [r["pk"] for r in engine._vector_rows(qvec, where, args, 10)]
    assert got == _scan(engine, qvec, company_id, 10)
    owners = {r["pk"]: r["company_id"] for r in engine.repo.conn.execute("SELECT pk, company_id FROM parts")}
    assert all(owners[pk] in (None, company_id) for pk in got)          # never another company's part


def test_zero_vector_still_works(engine, monkeypatch):
    monkeypatch.setattr(search_mod, "SCAN_BELOW", 0)
    where, args = engine._filter_sql(None, SearchFilters())
    assert len(engine._vector_rows([0.0] * DIM, where, args, 5)) == 5


# ---- remembered answers: same question + same library = same answer, without a new search or AI call ----
from test_app_views import client_for, setup  # noqa: E402,F401  (setup is a fixture)

from partsfinder.ai import AIError  # noqa: E402

BOLT = {"query": "socket head bolt M8x30", "limit": 3}


def test_same_question_comes_from_memory(setup, monkeypatch):
    c, fake = client_for(setup, monkeypatch)
    first = c.post("/search", json=BOLT).json()
    calls = len(fake.calls)
    second = c.post("/search", json=BOLT).json()
    assert first["cached"] is False and second["cached"] is True
    assert len(fake.calls) == calls                                      # no new Claude call
    assert [r["id"] for r in second["results"]] == [r["id"] for r in first["results"]]
    assert first["seconds"] >= 0


def test_a_write_to_the_library_clears_the_memory(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch, with_ai=False)
    c.post("/search", json=BOLT)
    c.post("/feedback", json={"part_id": "shcs-m8x30", "rating": "up", "query": BOLT["query"]})
    assert c.post("/search", json=BOLT).json()["cached"] is False


def test_memory_is_kept_per_company(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch, with_ai=False)
    asked = {**BOLT, "query": "socket head bolt M8x30 company B", "limit": 5}
    as_b = c.post("/search", json={**asked, "company_id": "company_b"}).json()
    general = c.post("/search", json=asked).json()
    assert "secret-bolt" in [r["id"] for r in as_b["results"]]
    assert general["cached"] is False and "secret-bolt" not in [r["id"] for r in general["results"]]


def test_an_ai_failure_is_not_remembered(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)

    def down(*_a, **_k):
        raise AIError("Claude is down")
    monkeypatch.setattr(c.app.state.finder, "find", down)
    assert c.post("/search", json=BOLT).json()["ai_used"] is False
    assert c.post("/search", json=BOLT).json()["cached"] is False       # tried again, the AI may be back


