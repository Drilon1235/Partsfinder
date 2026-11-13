"""Tests for phase 6: the HTTP API (with a fake Claude and a test database)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from partsfinder.ai import PartFinder
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate, PartFile
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine

DIM = 128


def fake_client(judge_ids=None, fail=None):
    """Fake Claude: search text = the question; approves judge_ids as 'fits' (or all candidates)."""
    def create(**kw):
        if fail:
            raise fail
        tool = kw["tools"][0]["name"]
        content = kw["messages"][0]["content"]
        if tool == "search_request":
            data = {"search_text": content.split(": ", 1)[1]}
        else:
            ids = [c["id"] for c in json.loads(content)["candidates"]]
            keep = [i for i in ids if judge_ids is None or i in judge_ids]
            data = {"status": "found", "message": "Found.",
                    "results": [{"id": i, "verdict": "fits", "match_reasons": ["test"]} for i in keep]}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=tool, input=data)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20))
    return SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.fixture
def setup(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    step = tmp_path / "chair.step"
    cq.exporters.export(cq.Workplane("XY").box(10, 10, 10), str(step))
    thumb = tmp_path / "chair.png"
    thumb.write_bytes(b"\x89PNG\r\n\x1a\n")
    for d in [
        dict(id="chair-green", name="Garden chair green", category_path="furniture/seating/garden-chair",
             sectors=["horticulture"], color="green", bbox_mm=(460, 520, 820), kind="assembly",
             thumbnail_path=str(thumb), files=[PartFile(format="step", path=str(step)),
                                               PartFile(format="sldprt", path=str(tmp_path / "gone.sldprt"))]),
        dict(id="leg", name="Garden chair leg", category_path="furniture/seating", bbox_mm=(22, 22, 435)),
        dict(id="bolt", name="Hex bolt M8x40", category_path="fasteners/bolt/hex-bolt",
             standards=["DIN 933"], bbox_mm=(15, 13, 45)),
        dict(id="b-chair", name="Garden chair Lisse green", category_path="furniture/seating/garden-chair",
             color="green", bbox_mm=(450, 500, 800), company_id="company_b",
             files=[PartFile(format="step", path=str(step))]),
    ]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    repo.add_component("chair-green", "leg", 4, None)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    yield SimpleNamespace(conn=conn, repo=repo, emb=emb, tmp=tmp_path)
    conn.close()


def make_client(setup, finder="fake", **fake_kw) -> TestClient:
    if finder == "fake":
        engine = SearchEngine(setup.repo, setup.emb)
        finder = PartFinder(engine, setup.repo.taxonomy, "claude-haiku-5-5", client=fake_client(**fake_kw))
    app = create_app(get_settings(), conn=setup.conn, embedder=setup.emb, finder=finder,
                     enable_ai=finder is not None)
    return TestClient(app)


# ---- basics -----------------------------------------------------------------------------
def test_health(setup):
    h = make_client(setup).get("/health").json()
    assert h["status"] == "ok" and h["parts"] == 4 and h["ai_available"] and h["embedder"] == "hashing"
    h2 = make_client(setup, finder=None).get("/health").json()
    assert h2["ai_available"] is False and h2["ai_note"]


def test_search_with_ai(setup):
    r = make_client(setup, judge_ids={"chair-green"}).post(
        "/search", json={"query": "green garden chair"}).json()
    assert r["status"] == "found" and r["ai_used"] is True
    first = r["results"][0]
    assert first["id"] == "chair-green" and first["verdict"] == "fits"
    assert first["dims_mm"] == [460, 520, 820] and first["match_reasons"] == ["test"]
    assert first["files"][0]["url"].startswith("/parts/chair-green/file?format=")
    assert first["thumbnail_url"].startswith("/parts/chair-green/thumbnail?v=")      # version against stale caches


def test_search_isolation(setup):
    c = make_client(setup)                         # approves everything it sees
    ids_a = [x["id"] for x in c.post("/search", json={"query": "garden chair green", "company_id": "company_a"}).json()["results"]]
    ids_b = [x["id"] for x in c.post("/search", json={"query": "garden chair green", "company_id": "company_b"}).json()["results"]]
    assert "b-chair" not in ids_a and "b-chair" in ids_b
    b = next(x for x in c.post("/search", json={"query": "garden chair green", "company_id": "company_b"}).json()["results"]
             if x["id"] == "b-chair")
    assert "company_id=company_b" in b["files"][0]["url"]


def test_search_fallback_without_ai(setup):
    r = make_client(setup, finder=None).post("/search", json={"query": "hex bolt DIN 933"}).json()
    assert r["ai_used"] is False and r["results"][0]["id"] == "bolt"
    r2 = make_client(setup).post("/search", json={"query": "hex bolt", "use_ai": False}).json()
    assert r2["ai_used"] is False


def test_search_ai_error_falls_back(setup):
    class APIConnectionError(Exception):
        pass
    r = make_client(setup, fail=APIConnectionError("down")).post("/search", json={"query": "hex bolt"}).json()
    assert r["ai_used"] is False and "No connection" in r["message"] and r["results"]


def test_fixed_filters_are_never_relaxed(setup):
    c = make_client(setup)
    r = c.post("/search", json={"query": "garden chair", "filters": {"max_dims_mm": [100, 100, 500]}}).json()
    ids = [x["id"] for x in r["results"]]
    assert "leg" in ids and "chair-green" not in ids        # chair is too big, even after relaxing
    assert all(a <= b for x in r["results"] for a, b in zip(sorted(x["dims_mm"]), [100, 100, 500]))
    assert r["interpreted_requirements"]["fixed_filters"] == {"max_dims_mm": [100, 100, 500]}
    r2 = c.post("/search", json={"query": "chair", "filters": {"category": "piping"}}).json()
    assert r2["status"] == "none" and r2["results"] == []


def test_search_validation(setup):
    c = make_client(setup)
    assert c.post("/search", json={"query": ""}).status_code == 422
    assert c.post("/search", json={"query": "x", "limit": 99}).status_code == 422
    assert c.post("/search", json={"query": "x", "filters": {"max_dims_mm": [1, 2]}}).status_code == 422


# ---- parts and files ------------------------------------------------------------
def test_get_part_and_components(setup):
    c = make_client(setup)
    p = c.get("/parts/chair-green").json()
    assert p["name"] == "Garden chair green" and p["components"] == [{"id": "leg", "name": "Garden chair leg", "quantity": 4}]
    assert c.get("/parts/b-chair").status_code == 404
    assert c.get("/parts/b-chair", params={"company_id": "company_a"}).status_code == 404
    assert c.get("/parts/b-chair", params={"company_id": "company_b"}).status_code == 200
    assert c.get("/parts/does-not-exist").status_code == 404


def test_file_and_thumbnail(setup):
    c = make_client(setup)
    r = c.get("/parts/chair-green/file")
    assert r.status_code == 200 and b"ISO-10303" in r.content[:200]
    assert c.get("/parts/chair-green/file", params={"format": "STEP"}).status_code == 200
    assert c.get("/parts/chair-green/file", params={"format": "stl"}).status_code == 404
    assert c.get("/parts/chair-green/file", params={"format": "sldprt"}).status_code == 410
    assert c.get("/parts/b-chair/file").status_code == 404                     # another company
    assert c.get("/parts/b-chair/file", params={"company_id": "company_b"}).status_code == 200
    t = c.get("/parts/chair-green/thumbnail")
    assert t.status_code == 200 and t.headers["content-type"] == "image/png"
    assert c.get("/parts/bolt/thumbnail").status_code == 404


# ---- import, taxonomy, companies ----------------------------------------------------------
def test_ingest_endpoint(setup):
    folder = setup.tmp / "import"
    folder.mkdir()
    cq.exporters.export(cq.Workplane("XY").box(5, 5, 50), str(folder / "levelling_foot_m8.step"))
    c = make_client(setup, finder=None)
    r = c.post("/ingest", json={"folder": str(folder), "company_id": "company_c", "thumbnails": False}).json()
    assert len(r["added"]) == 1 and r["needs_review"] == r["added"] and not r["failed"]
    pid = r["added"][0]
    assert c.get(f"/parts/{pid}").status_code == 404
    assert c.get(f"/parts/{pid}", params={"company_id": "company_c"}).json()["needs_review"] is True
    again = c.post("/ingest", json={"folder": str(folder), "company_id": "company_c", "thumbnails": False}).json()
    assert again["skipped"] == [pid]
    assert c.post("/ingest", json={"folder": str(setup.tmp / "nope")}).status_code == 400
    assert {x["id"] for x in c.get("/companies").json()} == {"company_b", "company_c"}


def test_taxonomy(setup):
    t = make_client(setup).get("/taxonomy").json()
    assert "furniture/seating/garden-chair" in t["category_paths"] and "horticulture" in t["sectors"]


def test_slow_ai_does_not_block_other_requests(setup):
    """A slow AI question (Claude) must not hold up other requests."""
    import threading
    import time

    base = fake_client()

    def slow_create(**kw):
        time.sleep(1.5)
        return base.messages.create(**kw)

    engine = SearchEngine(setup.repo, setup.emb)
    finder = PartFinder(engine, setup.repo.taxonomy, "claude-haiku-5-5",
                        client=SimpleNamespace(messages=SimpleNamespace(create=slow_create)))
    client = TestClient(create_app(get_settings(), conn=setup.conn, embedder=setup.emb, finder=finder))
    slow = threading.Thread(target=lambda: client.post("/search", json={"query": "green garden chair"}))
    slow.start()
    time.sleep(0.3)                                    # the AI question is now running
    t0 = time.perf_counter()
    r = client.post("/search", json={"query": "chair", "use_ai": False})
    h = client.get("/health")
    fast = time.perf_counter() - t0
    slow.join()
    assert r.status_code == 200 and h.status_code == 200
    assert fast < 1.0, f"other requests waited {fast:.1f} s for the AI question"
