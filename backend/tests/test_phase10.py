"""Tests for phase 10: property filters and their overview."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from partsfinder.api import create_app
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, SearchFilters, merge_filters, property_clauses

DIM = 128


def _parts():
    return [
        dict(id="bolt-m8x40", name="Hex bolt M8x40", category_path="fasteners/bolt/hex-bolt",
             bbox_mm=(15, 13, 45), tags=["bolt"], properties={"thread": "M8", "length_mm": 40, "galvanized": True}),
        dict(id="bolt-m8x60", name="Hex bolt M8x60", category_path="fasteners/bolt/hex-bolt",
             bbox_mm=(15, 13, 65), tags=["bolt"], properties={"thread": "M8", "length_mm": 60, "galvanized": False}),
        dict(id="bolt-m6x25", name="Hex bolt M6x25", category_path="fasteners/bolt/hex-bolt",
             bbox_mm=(11, 10, 30), tags=["bolt"], properties={"thread": "M6", "length_mm": 25}),
        dict(id="a-bolt", name="Hex bolt M8x80 internal", category_path="fasteners/bolt/hex-bolt",
             bbox_mm=(15, 13, 85), tags=["bolt"], properties={"thread": "M8", "length_mm": 80},
             company_id="company_a"),
        dict(id="b-bolt", name="Hex bolt M8x100 secret", category_path="fasteners/bolt/hex-bolt",
             bbox_mm=(15, 13, 105), tags=["bolt"], properties={"thread": "M8", "length_mm": 100, "secret_b": "yes"},
             company_id="company_b"),
    ]


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in _parts():
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb)
    conn.close()


def ids(hits):
    return sorted(h.part.id for h in hits)


def test_exact_text_is_case_insensitive(engine):
    f = SearchFilters(properties={"thread": "m8"})
    assert ids(engine.search("bolt", None, f, limit=20)) == ["bolt-m8x40", "bolt-m8x60"]


def test_numeric_range_and_exact_number(engine):
    f = SearchFilters(properties={"length_mm": {"min": 30, "max": 50}})
    assert ids(engine.search("bolt", None, f, limit=20)) == ["bolt-m8x40"]
    f = SearchFilters(properties={"length_mm": 60})
    assert ids(engine.search("bolt", None, f, limit=20)) == ["bolt-m8x60"]
    # a text value never matches a numeric range
    f = SearchFilters(properties={"thread": {"min": 0}})
    assert engine.search("bolt", None, f, limit=20) == []


def test_bool_and_missing_property(engine):
    assert ids(engine.search("bolt", None, SearchFilters(properties={"galvanized": True}), limit=20)) == ["bolt-m8x40"]
    assert ids(engine.search("bolt", None, SearchFilters(properties={"galvanized": False}), limit=20)) == ["bolt-m8x60"]
    assert engine.search("bolt", None, SearchFilters(properties={"does_not_exist": "x"}), limit=20) == []


def test_filters_combine(engine):
    f = SearchFilters(properties={"thread": "M8", "length_mm": {"max": 50}})
    assert ids(engine.search("bolt", None, f, limit=20)) == ["bolt-m8x40"]


def test_company_separation_holds_with_property_filter(engine):
    f = SearchFilters(properties={"thread": "M8"})
    assert "b-bolt" not in ids(engine.search("bolt", "company_a", f, limit=20))
    assert "a-bolt" in ids(engine.search("bolt", "company_a", f, limit=20))
    assert "a-bolt" not in ids(engine.search("bolt", None, f, limit=20))
    # a property of company B is invisible to A
    assert engine.search("bolt", "company_a", SearchFilters(properties={"secret_b": "yes"}), limit=20) == []


def test_invalid_key_is_rejected_and_never_reaches_sql():
    for bad in ("a'); DROP TABLE parts;--", "a.b", "", "A B", 'x"y'):
        with pytest.raises(ValueError):
            property_clauses({bad: "x"})
    with pytest.raises(ValueError):
        property_clauses({"length_mm": {"minimum": 3}})
    with pytest.raises(ValueError):
        property_clauses({"length_mm": {}})


def test_merge_keeps_both_property_sets():
    base = SearchFilters(properties={"thread": "M8", "length_mm": 40})
    extra = SearchFilters(properties={"length_mm": 60})
    assert merge_filters(base, extra).properties == {"thread": "M8", "length_mm": 60}
    assert merge_filters(base, SearchFilters()).properties == {"thread": "M8", "length_mm": 40}


@pytest.fixture
def client():
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in _parts():
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    app = create_app(conn=conn, embedder=emb, finder=None)
    return TestClient(app)


def test_api_properties_overview_is_scoped(client):
    keys = {p["key"]: p for p in client.get("/properties").json()}
    assert "secret_b" not in keys and keys["length_mm"]["max"] == 60 and keys["length_mm"]["type"] == "number"
    assert keys["thread"]["values"][0] == "M8"
    own = {p["key"]: p for p in client.get("/properties", params={"company_id": "company_b"}).json()}
    assert "secret_b" in own and own["length_mm"]["max"] == 100
    other = {p["key"] for p in client.get("/properties", params={"company_id": "company_a"}).json()}
    assert "secret_b" not in other


def test_api_search_filters_on_properties(client):
    r = client.post("/search", json={"query": "bolt", "use_ai": False, "limit": 20,
                                     "filters": {"properties": {"length_mm": {"min": 50}}}}).json()
    got = sorted(x["id"] for x in r["results"])
    assert got == ["bolt-m8x60"]
    assert client.post("/search", json={"query": "bolt", "filters": {"properties": {"a b": 1}}}).status_code == 422


# ---- mass estimate ------------------------------------------------------------------------
def test_mass_estimate_table():
    from partsfinder.mass import density_for, estimate_mass_g
    assert density_for("stainless steel 1.4301") == 7.9 and density_for("Steel 8.8") == 7.85
    assert density_for("PP") == 0.91 and density_for("aluminium 6061") == 2.7
    assert density_for("unknown stuff") is None and density_for(None) is None
    assert density_for("pp") != density_for("polycarbonate")           # short keys only as a whole word
    assert estimate_mass_g(10_000, "steel") == 78.5                    # 10 cm³ × 7,85
    assert estimate_mass_g(None, "steel") is None and estimate_mass_g(0, "steel") is None
    assert estimate_mass_g(10_000, "unknown") is None


def test_api_marks_estimated_mass(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in [
        dict(id="block", name="Steel block", material="steel", category_path="other/unknown", volume_mm3=10_000, bbox_mm=(10, 10, 100)),
        dict(id="real", name="Weighed block", material="steel", category_path="other/unknown", volume_mm3=10_000, mass_g=99.0, bbox_mm=(10, 10, 100)),
        dict(id="no-material", name="Block without material", category_path="other/unknown", volume_mm3=10_000, bbox_mm=(10, 10, 100)),
        dict(id="asm", name="Assembly", kind="assembly", material="steel", category_path="other/unknown", volume_mm3=10_000, bbox_mm=(10, 10, 100)),
    ]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    c = TestClient(create_app(conn=conn, embedder=emb, finder=None))
    got = {i: c.get(f"/parts/{i}").json() for i in ("block", "real", "no-material", "asm")}
    assert (got["block"]["mass_g"], got["block"]["mass_estimated"]) == (78.5, True)
    assert (got["real"]["mass_g"], got["real"]["mass_estimated"]) == (99.0, False)
    assert (got["no-material"]["mass_g"], got["no-material"]["mass_estimated"]) == (None, False)
    assert got["asm"]["mass_g"] is None                                # assemblies are not estimated
    assert repo.get_part("block", None).mass_g is None                  # nothing stored in the database


# ---- API keys ---------------------------------------------------------------------------
def _keyed_client(keys="ka-key=company_a,kb-key=company_b,admin-key=*"):
    import dataclasses
    from partsfinder.config import get_settings
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in _parts():
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    s = dataclasses.replace(get_settings(), api_keys=keys)
    return TestClient(create_app(s, conn=conn, embedder=emb, finder=None, enable_ai=False))


def _bearer(key):
    return {"Authorization": f"Bearer {key}"}


def test_keys_are_required_when_enabled():
    c = _keyed_client()
    assert c.get("/health").status_code == 200                       # health stays open
    assert c.get("/taxonomy").status_code == 401
    assert c.get("/properties", headers=_bearer("wrong")).status_code == 401
    assert c.get("/taxonomy", headers=_bearer("ka-key")).status_code == 200
    assert c.get("/taxonomy", headers={"X-API-Key": "ka-key"}).status_code == 200


def test_company_key_is_pinned_to_its_company():
    c = _keyed_client()
    a = _bearer("ka-key")
    # own part visible, even without company_id (the key decides the company)
    assert c.get("/parts/a-bolt", headers=a).status_code == 200
    assert c.get("/parts/a-bolt", params={"company_id": "company_a"}, headers=a).status_code == 200
    # naming another company or requesting B parts is never possible
    assert c.get("/parts/b-bolt", params={"company_id": "company_b"}, headers=a).status_code == 403
    assert c.get("/parts/b-bolt", headers=a).status_code == 404
    r = c.post("/search", json={"query": "bolt", "use_ai": False, "limit": 20, "company_id": "company_b"}, headers=a)
    assert r.status_code == 403
    r = c.post("/search", json={"query": "bolt", "use_ai": False, "limit": 20}, headers=a).json()
    ids_ = {x["id"] for x in r["results"]}
    assert "a-bolt" in ids_ and "b-bolt" not in ids_
    keys = {p["key"] for p in c.get("/properties", headers=a).json()}
    assert "secret_b" not in keys
    assert c.get("/parts/b-bolt/file", params={"company_id": "company_b"}, headers=a).status_code == 403
    assert c.get("/parts/b-bolt/thumbnail", params={"company_id": "company_b"}, headers=a).status_code == 403


def test_admin_only_endpoints():
    c = _keyed_client()
    assert c.get("/companies", headers=_bearer("ka-key")).status_code == 403
    assert c.post("/ingest", json={"folder": "."}, headers=_bearer("ka-key")).status_code == 403
    assert c.get("/companies", headers=_bearer("admin-key")).status_code == 200
    # the admin picks the company
    assert c.get("/parts/b-bolt", params={"company_id": "company_b"}, headers=_bearer("admin-key")).status_code == 200


def test_no_keys_means_open_api_as_before():
    c = _keyed_client(keys="")
    assert c.get("/taxonomy").status_code == 200 and c.get("/companies").status_code == 200


def test_key_parsing_rejects_bad_format():
    from partsfinder.auth import lookup, parse_keys
    assert parse_keys("a=b, c=*") == {"a": "b", "c": "*"} and parse_keys(None) == {}
    for bad in ("no-equals-sign", "=company", "k=", "k=a,k=b"):
        with pytest.raises(ValueError):
            parse_keys(bad)
    assert lookup({"k": "x"}, "k") == "x" and lookup({"k": "x"}, "kk") is None and lookup({"k": "x"}, None) is None


# ---- similar parts and shape search --------------------------------------------------
def _shape_client(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in [
        dict(id="block-a", name="Block 50x30x20", category_path="other/unknown", bbox_mm=(50, 30, 20), volume_mm3=30000),
        dict(id="block-b", name="Block lying 20x50x30", category_path="other/unknown", bbox_mm=(20, 50, 30), volume_mm3=29500),
        dict(id="block-large", name="Large block", category_path="other/unknown", bbox_mm=(500, 300, 200), volume_mm3=3e7),
        dict(id="a-block", name="Block of A", category_path="other/unknown", bbox_mm=(50, 30, 21),
             volume_mm3=31000, company_id="company_a"),
        dict(id="b-block", name="Block of B", category_path="other/unknown", bbox_mm=(50, 30, 20),
             volume_mm3=30000, company_id="company_b"),
        dict(id="empty", name="No dimensions", category_path="other/unknown"),
    ]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    return TestClient(create_app(conn=conn, embedder=emb, finder=None, enable_ai=False))


def test_similar_ignores_orientation_and_scale_and_company(tmp_path):
    c = _shape_client(tmp_path)
    r = c.get("/parts/block-a/similar", params={"limit": 10}).json()
    got = [x["id"] for x in r["results"]]
    assert got[0] == "block-b" and "block-a" not in got           # not itself; rotation does not matter
    assert "block-large" not in got and "b-block" not in got and "a-block" not in got   # too large / other companies
    assert r["results"][0]["similarity"] > 0.9
    ra = c.get("/parts/block-a/similar", params={"company_id": "company_a", "limit": 10}).json()
    ids_a = [x["id"] for x in ra["results"]]
    assert "a-block" in ids_a and "b-block" not in ids_a
    assert c.get("/parts/b-block/similar", params={"company_id": "company_a"}).status_code == 404
    assert c.get("/parts/empty/similar").status_code == 400


def test_shape_search_measures_uploaded_step(tmp_path):
    import cadquery as cq
    c = _shape_client(tmp_path)
    step = tmp_path / "search.step"
    cq.exporters.export(cq.Workplane("XY").box(30, 20, 50), str(step))      # same block, other orientation
    r = c.post("/search/shape", params={"filename": "mine.step", "limit": 10},
               content=step.read_bytes(), headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    body = r.json()
    assert sorted(body["measured"]["dims_mm"]) == [20.0, 30.0, 50.0]
    ids_ = [x["id"] for x in body["results"]]
    assert {"block-a", "block-b"} <= set(ids_) and "b-block" not in ids_ and "a-block" not in ids_
    own = c.post("/search/shape", params={"filename": "m.step", "company_id": "company_b", "limit": 10},
                 content=step.read_bytes()).json()
    assert "b-block" in [x["id"] for x in own["results"]]


def test_shape_search_rejects_bad_input(tmp_path):
    c = _shape_client(tmp_path)
    assert c.post("/search/shape", params={"filename": "x.sldprt"}, content=b"abc").status_code == 400
    assert c.post("/search/shape", params={"filename": "x.step"}, content=b"").status_code == 400
    assert c.post("/search/shape", params={"filename": "x.step"}, content=b"not cad").status_code == 400
    bad_len = c.post("/search/shape", params={"filename": "x.step"}, content=b"abc",
                     headers={"content-length": "abc"})
    assert bad_len.status_code == 400 and "Content-Length" in bad_len.json()["detail"]


def test_shape_search_needs_key_when_enabled(tmp_path):
    c = _keyed_client()
    assert c.post("/search/shape", content=b"x").status_code == 401
    assert c.get("/parts/a-bolt/similar").status_code == 401


# ---- feedback --------------------------------------------------------------------------------
def test_feedback_is_scoped_per_company():
    c = _keyed_client(keys="")
    ok = c.post("/feedback", json={"part_id": "bolt-m8x40", "rating": "up", "query": "m8 bolt"})
    assert ok.status_code == 200
    assert c.post("/feedback", json={"part_id": "a-bolt", "rating": "down", "company_id": "company_a",
                                     "note": "too long"}).status_code == 200
    # part of another company: cannot be rated
    assert c.post("/feedback", json={"part_id": "b-bolt", "rating": "up", "company_id": "company_a"}).status_code == 404
    assert c.post("/feedback", json={"part_id": "bolt-m8x40", "rating": "good"}).status_code == 422
    glob = c.get("/feedback").json()
    own = c.get("/feedback", params={"company_id": "company_a"}).json()
    assert [f["part_id"] for f in glob] == ["bolt-m8x40"] and glob[0]["query"] == "m8 bolt"
    assert [f["part_id"] for f in own] == ["a-bolt"] and own[0]["rating"] == "down"
    assert c.get("/feedback", params={"company_id": "company_b"}).json() == []


def test_feedback_follows_api_keys():
    c = _keyed_client()
    a = _bearer("ka-key")
    assert c.post("/feedback", json={"part_id": "a-bolt", "rating": "up"}, headers=a).status_code == 200
    assert c.post("/feedback", json={"part_id": "a-bolt", "rating": "up", "company_id": "company_b"}, headers=a).status_code == 403
    assert c.get("/feedback", params={"company_id": "company_b"}, headers=a).status_code == 403
    assert len(c.get("/feedback", headers=a).json()) == 1
    assert c.get("/feedback").status_code == 401


# ---- background import ----------------------------------------------------------------
def _cad_folder(tmp_path, names=("block",)):
    import cadquery as cq
    folder = tmp_path / "cad"
    folder.mkdir()
    for i, n in enumerate(names):
        cq.exporters.export(cq.Workplane("XY").box(10 + i, 20, 30), str(folder / f"{n}.step"))
    return folder


def test_background_import_uses_own_connection_and_reports(tmp_path):
    import time
    folder = _cad_folder(tmp_path, ("block", "block two"))
    conn = connect(tmp_path / "bg.db", embedding_dim=DIM, check_same_thread=False)
    emb = HashingEmbedder(DIM)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    c = TestClient(create_app(conn=conn, embedder=emb, finder=None, enable_ai=False))
    r = c.post("/ingest", json={"folder": str(folder), "use_ai": False, "thumbnails": False, "background": True})
    assert r.status_code == 200 and r.json()["status"] == "running"
    job_id = r.json()["job_id"]
    status = {}
    for _ in range(200):                                   # max ~20 s
        assert c.get("/health").status_code == 200         # the API stays reachable during the import
        status = c.get(f"/ingest/{job_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.1)
    assert status["status"] == "done", status.get("error")
    assert len(status["report"]["added"]) == 2 and status["report"]["failed"] == []
    assert c.get("/health").json()["parts"] == 2           # the main connection sees the result
    assert c.get("/ingest/does-not-exist").status_code == 404


def test_background_import_reports_errors_and_falls_back_inline_in_memory(tmp_path):
    c = _shape_client(tmp_path)                            # :memory: database
    folder = _cad_folder(tmp_path)
    r = c.post("/ingest", json={"folder": str(folder), "use_ai": False, "thumbnails": False, "background": True}).json()
    assert "job_id" not in r and len(r["added"]) == 1      # without a database file: simply inline
    assert c.post("/ingest", json={"folder": str(tmp_path / "no"), "background": True}).status_code == 400


def test_ingest_status_is_admin_only():
    c = _keyed_client()
    assert c.get("/ingest/x", headers=_bearer("ka-key")).status_code == 404       # a company sees only its own imports
    assert c.get("/ingest/x", headers=_bearer("admin-key")).status_code == 404


# ---- real data: yes/no properties and noise in the overview ------------------------------------
def test_bool_property_matches_text_yes_no_and_overview_says_boolean(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in [dict(id="a", name="Garden chair", category_path="other/unknown", properties={"outdoor": True, "folder_in_freecad_library": "x"}),
              dict(id="b", name="Office chair", category_path="other/unknown", properties={"outdoor": False, "needs_review": True})]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    eng = SearchEngine(repo, emb)
    for yes in (True, "true", "Yes"):
        assert ids(eng.search("chair", None, SearchFilters(properties={"outdoor": yes}))) == ["a"]
    for no in (False, "false", "no"):
        assert ids(eng.search("chair", None, SearchFilters(properties={"outdoor": no}))) == ["b"]
    ov = {o["key"]: o for o in repo.property_overview(None)}
    assert ov["outdoor"]["type"] == "boolean" and set(ov) == {"outdoor"}     # noise (origin) is absent


def test_mass_estimate_refuses_impossible_volume():
    from partsfinder.mass import estimate_mass_g
    assert estimate_mass_g(10_000, "steel", (10, 10, 100)) == 78.5          # fits the box exactly
    assert estimate_mass_g(10_500, "steel", (10, 10, 100)) is not None      # 5 % margin
    assert estimate_mass_g(50_000, "steel", (10, 10, 100)) is None          # larger than the box: volume is wrong
    assert estimate_mass_g(10_000, "steel", None) == 78.5


# ---- AI layer uses properties (fake Claude) -------------------------------------------
class _FakeClaude:
    def __init__(self, interpret, judge):
        from types import SimpleNamespace
        self.interpret, self.judge, self.calls = interpret, judge, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        from types import SimpleNamespace
        self.calls.append(kw)
        tool = kw["tools"][0]["name"]
        data = self.interpret if tool == "search_request" else self.judge(json.loads(kw["messages"][0]["content"]))
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=tool, input=data)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _ai_finder(interpret):
    from partsfinder.ai import PartFinder
    from partsfinder.taxonomy import Taxonomy
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    rows = [dict(id=f"alg-{i}", name=f"Hex bolt M{d}x{i}", category_path="fasteners/bolt/hex-bolt",
                 properties={"thread": f"M{d}", "length_mm": i}) for i, d in ((20, 6), (40, 8), (60, 8), (80, 10))]
    rows.append(dict(id="b-x", name="Hex bolt secret", category_path="fasteners/bolt/hex-bolt",
                     properties={"only_company_b": "x", "thread": "M8"}, company_id="company_b"))
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    judge = lambda payload: {"status": "found", "message": "ok",   # noqa: E731
                             "results": [{"id": c["id"], "verdict": "fits", "match_reasons": [], "mismatch_reasons": []}
                                         for c in payload["candidates"]]}
    client = _FakeClaude(interpret, judge)
    # `thread` has several values in the general library; company properties are not in the list
    f = PartFinder(SearchEngine(repo, emb), Taxonomy.load(), "claude-haiku-5-5", client=client)
    return f, client


def test_ai_gets_general_property_list_only_and_filters_with_it():
    f, client = _ai_finder({"search_text": "hex bolt",
                            "properties": {"thread": "M8", "length_mm": {"min": 30, "max": 50}, "does_not_exist": 5}})
    res = f.find("hex bolt M8 rond 40 mm", "company_b", 5)
    system = client.calls[0]["system"][0]["text"]
    assert "Available properties" in system and "thread" in system and "length_mm" in system
    assert "only_company_b" not in system                         # company data never goes to Claude
    assert res.requirements["properties"] == {"thread": "M8", "length_mm": {"min": 30.0, "max": 50.0}}   # unknown key dropped
    ids_ = [r.hit.part.id for r in res.results]
    assert "alg-40" in ids_                                          # fits thread M8 and length 30-50
    # step 1 (all requirements) searches with the filter first: only M8 with length 30-50
    first = f.engine.search("hex bolt", "company_b", res_filters(res), limit=10)
    assert [h.part.id for h in first] == ["alg-40"]


def res_filters(res):
    from partsfinder.search import SearchFilters
    return SearchFilters(properties=res.requirements["properties"])


def test_ai_property_filter_is_relaxed_when_nothing_matches():
    f, _ = _ai_finder({"search_text": "hex bolt", "properties": {"thread": "M99"}})
    res = f.find("hex bolt M99", None, 5)
    assert res.results, "the filter must be relaxed when nothing fits"


def test_clean_properties_rejects_bad_values():
    from partsfinder.ai import clean_properties
    known = {"thread", "length_mm"}
    assert clean_properties({"thread": "M8", "length_mm": {"min": "x"}, "foo": 1}, known) == {"thread": "M8"}
    assert clean_properties({"length_mm": {"min": 1, "extra": 2}}, known) == {"length_mm": {"min": 1.0}}
    assert clean_properties("rubbish", known) == {} and clean_properties({"thread": ""}, known) == {}


# ---- quality report ------------------------------------------------------------------------
def test_quality_report_counts_only_own_library():
    c = _keyed_client(keys="")
    own = c.get("/quality", params={"company_id": "company_a"}).json()
    assert own["total"] == 1 and own["coverage"]["properties"] == 100       # a-bolt has properties
    assert own["coverage"]["description"] == 0 and own["coverage"]["preview_image"] == 0
    assert own["needs_attention"][0]["id"] == "a-bolt" and "material" in own["needs_attention"][0]["missing"]
    glob = c.get("/quality").json()
    assert glob["total"] == 3 and "a-bolt" not in [x["id"] for x in glob["needs_attention"]]
    assert c.get("/quality", params={"company_id": "empty"}).json() == {
        "total": 0, "coverage": {k: 0 for k in own["coverage"]}, "needs_attention": [], "incomplete_total": 0}


def test_quality_follows_api_keys():
    c = _keyed_client()
    assert c.get("/quality").status_code == 401
    assert c.get("/quality", params={"company_id": "company_b"}, headers=_bearer("ka-key")).status_code == 403
    assert c.get("/quality", headers=_bearer("ka-key")).json()["total"] == 1


# ---- batch search -------------------------------------------------------------------------------
def test_batch_search_runs_each_query_and_keeps_companies_apart():
    c = _keyed_client(keys="")
    body = {"searches": [
        {"query": "bolt", "limit": 20, "filters": {"properties": {"thread": "M6"}}},
        {"query": "bolt", "limit": 20, "filters": {"properties": {"thread": "M8"}}},
        {"query": "titanium rocket engine"},
    ]}
    r = c.post("/search/batch", json=body).json()["searches"]
    assert [s["query"] for s in r] == ["bolt", "bolt", "titanium rocket engine"]
    assert [x["id"] for x in r[0]["results"]] == ["bolt-m6x25"]
    assert {x["id"] for x in r[1]["results"]} == {"bolt-m8x40", "bolt-m8x60"}      # no company parts
    assert r[2]["status"] == "none" and r[2]["results"] == []
    own = c.post("/search/batch", json={**body, "company_id": "company_a"}).json()["searches"]
    assert "a-bolt" in {x["id"] for x in own[1]["results"]} and "b-bolt" not in {x["id"] for x in own[1]["results"]}
    assert c.post("/search/batch", json={"searches": []}).status_code == 422
    assert c.post("/search/batch", json={"searches": [{"query": "x"}] * 11}).status_code == 422


def test_batch_search_follows_api_keys():
    c = _keyed_client()
    assert c.post("/search/batch", json={"searches": [{"query": "bolt"}]}).status_code == 401
    r = c.post("/search/batch", json={"searches": [{"query": "bolt", "limit": 20}]}, headers=_bearer("ka-key"))
    assert "b-bolt" not in {x["id"] for x in r.json()["searches"][0]["results"]}
    assert c.post("/search/batch", json={"searches": [{"query": "x"}], "company_id": "company_b"},
                  headers=_bearer("ka-key")).status_code == 403


# ---- found with weird input ----------------------------------------------------------------
def test_weird_property_values_give_422_not_500():
    c = _keyed_client(keys="")
    for cond in ({"min": None}, {"min": "x"}, {"max": True}, {"min": [1]}):
        r = c.post("/search", json={"query": "bolt", "use_ai": False, "filters": {"properties": {"length_mm": cond}}})
        assert r.status_code == 422, cond
    r = c.post("/search", content=b'{"query":"bolt","use_ai":false,"filters":{"properties":{"length_mm":1e999}}}',
               headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_zero_vector_query_does_not_crash_search(tmp_path):
    c = _shape_client(tmp_path)
    for q in ("\x00", "???", "é" * 3):
        assert c.post("/search", json={"query": q, "use_ai": False}).status_code == 200


# ---- duplicates ---------------------------------------------------------------------------------
def test_duplicates_groups_same_shape_in_own_library_only():
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    for i, (box, comp) in enumerate([((10, 20, 30), "company_a"), ((30, 10, 20), "company_a"),
                                     ((10, 20, 30.1), "company_a"), ((50, 50, 50), "company_a"),
                                     ((10, 20, 30), "company_b"), ((10, 20, 30), None)]):
        repo.add_part(PartCreate(id=f"p{i}", name=f"Block {i}", category_path="other/unknown",
                                 bbox_mm=box, company_id=comp))
    s = __import__("dataclasses").replace(__import__("partsfinder.config", fromlist=["x"]).get_settings(), api_keys="")
    c = TestClient(create_app(s, conn=conn, embedder=HashingEmbedder(DIM), finder=None, enable_ai=False))
    a = c.get("/duplicates", params={"company_id": "company_a"}).json()
    assert a["total"] == 1 and sorted(x["id"] for x in a["groups"][0]["parts"]) == ["p0", "p1", "p2"]
    assert c.get("/duplicates", params={"company_id": "company_b"}).json()["total"] == 0   # own parts only
    assert c.get("/duplicates").json()["total"] == 0                                         # general: 1 part
    assert c.get("/duplicates", params={"limit": "x"}).status_code == 422


# ---- learning from feedback ---------------------------------------------------------------
def test_feedback_nudges_ranking_for_same_query_and_company_only(engine):
    repo = engine.repo
    base = [h.part.id for h in engine.search("hex bolt", "company_a", limit=20)]
    last = base[-1]
    repo.add_feedback(last, "company_a", "up", "Hex bolt ")          # case/whitespace does not matter
    after = [h.part.id for h in engine.search("hex bolt", "company_a", limit=20)]
    assert sorted(after) == sorted(base) and after.index(last) < base.index(last)   # moved up, nothing disappeared
    # other company, other question or the general library notice nothing
    assert [h.part.id for h in engine.search("hex bolt", "company_b", limit=20)] == \
        [h.part.id for h in engine.search("hex bolt", "company_b", limit=20)]
    assert repo.feedback_scores("hex bolt", "company_b") == {} and repo.feedback_scores("hex bolt", None) == {}
    assert repo.feedback_scores("other question", "company_a") == {}
    repo.add_feedback(last, "company_a", "down", "hex bolt")          # the last one counts
    assert repo.feedback_scores("hex bolt", "company_a") == {last: -1}
    down = [h.part.id for h in engine.search("hex bolt", "company_a", limit=20)]
    assert sorted(down) == sorted(base) and down.index(last) >= base.index(last)


# ---- search statistics never use another company's parts ------------------------------------
def test_word_weights_ignore_other_companies(engine):
    def scores():
        return {h.part.id: (round(h.score, 9), h.word_coverage) for h in engine.search("hex bolt secret", "company_a", limit=20)}
    before = scores()
    emb = HashingEmbedder(DIM)
    for i in range(30):                                  # company B suddenly has many "secret" parts
        p = engine.repo.add_part(PartCreate(id=f"b-extra-{i}", name=f"Secret thing {i}", category_path="other/unknown",
                                            company_id="company_b"))
        engine.repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    assert scores() == before
