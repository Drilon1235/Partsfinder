"""11 Nov 2026: several parts in one question, the Filters panel (engineering filters, filters without a
question, GET /filters), where used, and the guard against "not specified" as a deviation."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from partsfinder import engineering
from partsfinder.ai import JUDGE_SYSTEM, drop_unasked
from partsfinder.ai import PartFinder, search_several, split_request
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import Part, PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, SearchFilters

DIM = 128


@pytest.fixture
def lib(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    rows = [
        dict(id="bolt-m8x30-88", name="Hex bolt M8x30 ISO 4017", category_path="fasteners/bolt/hex-bolt",
             description="Hex bolt M8 x 30 mm, property class 8.8", standards=["ISO 4017"], material="steel 8.8",
             bbox_mm=(13, 14, 35), volume_mm3=2200, properties={"thread": "M8", "length_mm": 30, "property_class": "8.8"}),
        dict(id="bolt-m8x40-46", name="Hex bolt M8x40 ISO 4017 class 4.6", category_path="fasteners/bolt/hex-bolt",
             description="Hex bolt M8 x 40 mm, property class 4.6", standards=["ISO 4017"], material="steel 4.6",
             bbox_mm=(13, 14, 45), properties={"thread": "M8", "length_mm": 40, "property_class": "4.6"}),
        dict(id="nut-m8", name="Hex nut M8 ISO 4032", category_path="fasteners/nut/hex-nut",
             description="Hex nut M8", standards=["ISO 4032"], material="steel 8", properties={"thread": "M8"}),
        dict(id="arduino-uno", name="Arduino Uno R3 board", category_path="electronics/module/single-board-computer",
             description="Arduino Uno single board computer", kind="assembly", bbox_mm=(68.6, 53.4, 15)),
        dict(id="frame-1", name="Machine frame 1000", category_path="construction/structure/beam", kind="assembly",
             description="Welded frame with bolts", bbox_mm=(1000, 600, 400)),
        dict(id="bracket-load", name="Shelf bracket 200", category_path="connections/bracket",
             description="Shelf bracket", material="steel S235", properties={"max_load_kg": 80, "tolerance": "ISO 2768-mK",
                                                                              "hardness_hrc": 30}),
        dict(id="secret-frame", name="Company B frame", category_path="construction/structure/beam", kind="assembly",
             company_id="company_b", material="titanium grade 5", description="Secret frame"),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    repo.add_component("frame-1", "bolt-m8x30-88", 24, None)
    repo.add_component("frame-1", "nut-m8", 24, None)
    repo.ensure_company("company_b")
    repo.add_component("secret-frame", "bolt-m8x30-88", 6, "company_b")
    yield SimpleNamespace(conn=conn, repo=repo, emb=emb, tmp=tmp_path)
    conn.close()


def client(lib, monkeypatch, finder=None):
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(lib.tmp / "data"))
    app = create_app(get_settings(), conn=lib.conn, embedder=lib.emb, finder=finder, enable_ai=finder is not None)
    return TestClient(app)


# ---- several parts in one question -------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("give me 1 M8 bolt and 1 arduino", [("M8 bolt", 1), ("arduino", 1)]),
    ("M8 bolt, nut and washer", [("M8 bolt", None), ("M8 nut", None), ("M8 washer", None)]),
    ("hex bolt M8x30 with nut", [("hex bolt M8x30", None), ("M8 nut", None)]),
    ("2x 608 bearing and a pillow block", [("608 bearing", 2), ("pillow block", None)]),
])
def test_a_question_for_several_parts_is_split(query, expected):
    assert [(p["request"], p["quantity"]) for p in split_request(query)] == expected


@pytest.mark.parametrize("query", [
    "bearing 6204 with two shields",          # a feature, not a second part
    "M8x30 bolt, preferably A4",              # a preference of the bolt
    "stainless steel and brass bolt",         # materials, one part
    "608 bearing",                            # a designation is no quantity
    "garden chair green and red",
])
def test_one_part_stays_one_question(query):
    assert split_request(query) == []


def test_every_requested_part_is_answered_on_its_own(lib):
    r = search_several(SearchEngine(lib.repo, lib.emb), "give me 1 M8 bolt and 1 arduino", None, 5)
    assert [g["request"] for g, _ in r.groups] == ["M8 bolt", "arduino"]
    bolt, board = (res for _, res in r.groups)
    assert bolt.results and all("bolt" in j.hit.part.name.lower() for j in bolt.results)
    # the bolt is never judged against "arduino", and the board never against "M8"
    assert not any("arduino" in " ".join(j.mismatch_reasons).lower() for j in bolt.results)
    assert [j.hit.part.id for j in board.results][:1] == ["arduino-uno"]
    assert not any("m8" in " ".join(j.mismatch_reasons).lower() for j in board.results)


def test_a_word_of_one_name_is_no_part_of_its_own(lib):
    # "pick and place head": "pick" names no part, so this stays one question (as before)
    assert split_request("pick and place head")
    assert search_several(SearchEngine(lib.repo, lib.emb), "pick and place head", None, 5) is None


def test_the_api_answers_per_requested_part(lib, monkeypatch):
    c = client(lib, monkeypatch)
    d = c.post("/search", json={"query": "an M8 bolt and an arduino", "use_ai": False}).json()
    assert [g["request"] for g in d["groups"]] == ["M8 bolt", "arduino"]
    assert d["groups"][0]["results"] and d["groups"][0]["results"][0]["id"].startswith("bolt-m8")
    assert d["groups"][1]["results"][0]["id"] == "arduino-uno"
    # results = every part of every group, in order (for clients that do not read groups)
    assert [r["id"] for r in d["results"]] == [r["id"] for g in d["groups"] for r in g["results"]]


def test_the_ai_only_judges_the_parts_the_code_cannot_settle(lib, monkeypatch):
    calls = []

    def create(**kw):
        tool = kw["tools"][0]["name"]
        content = kw["messages"][0]["content"]
        calls.append((tool, content))
        if tool == "search_request":
            data = {"search_text": content.split(": ", 1)[1]}
        else:
            ids = [cand["id"] for cand in json.loads(content)["candidates"]]
            data = {"status": "found", "message": "Found.", "results": [{"id": ids[0], "verdict": "fits"}]}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=tool, input=data)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    finder = PartFinder(SearchEngine(lib.repo, lib.emb), lib.repo.taxonomy, "claude-haiku-5-5", client=fake)
    d = client(lib, monkeypatch, finder).post("/search", json={"query": "M8x30 bolt and arduino"}).json()
    asked = [content for tool, content in calls if tool == "search_request"]
    assert asked == ["User question: arduino"]           # the bolt was settled by the library's own checks
    assert [g["request"] for g in d["groups"]] == ["M8x30 bolt", "arduino"]
    assert d["groups"][1]["ai_used"] is True and d["groups"][0]["ai_used"] is False


# ---- something the engineer did not ask is no deviation ----------------------------------------------------
@pytest.mark.parametrize("reasons, expected", [
    (["the Arduino model was not specified"], "fits"),
    (["length and class were not specified"], "fits"),
    (["you did not specify the length"], "fits"),
    (["length 40 mm instead of 30 mm"], "close"),
    (["other colour"], "close"),
    (["the part does not state a colour"], "close"),                 # about the part, not the request
    (["colour not stated"], "close"),
    (["the Arduino model was not specified", "other colour"], "close"),
])
def test_unasked_values_are_no_deviation(reasons, expected):
    verdict, _ = drop_unasked("close", reasons)
    assert verdict == expected


def test_the_unasked_remark_is_dropped_from_the_reasons():
    _, kept = drop_unasked("close", ["assembly, 108 x 53 mm", "the Arduino model was not specified"])
    assert kept == ["assembly, 108 x 53 mm"]


def test_the_prompt_says_unasked_values_are_open():
    assert "every value fits it" in JUDGE_SYSTEM


# ---- engineering filters ---------------------------------------------------------------------------------
def test_engineering_filter_uses_what_follows_from_the_property_class(lib):
    engine = SearchEngine(lib.repo, lib.emb)
    hits = engine.search("hex bolt M8", None, SearchFilters(engineering={"tensile_strength_mpa": {"min": 800}}), limit=10)
    assert [h.part.id for h in hits] == ["bolt-m8x30-88"]               # 8.8 = 800 MPa; 4.6 = 400 MPa drops out
    hits = engine.search("", None, SearchFilters(engineering={"max_load_kg": {"min": 50}}), limit=10)
    assert [h.part.id for h in hits] == ["bracket-load"]
    hits = engine.search("", None, SearchFilters(engineering={"tolerance": "2768-m", "hardness_hrc": {"min": 25}}), limit=10)
    assert [h.part.id for h in hits] == ["bracket-load"]
    assert engine.search("", None, SearchFilters(engineering={"max_load_kg": {"min": 100}}), limit=10) == []


def test_a_part_that_states_nothing_never_passes_an_engineering_filter():
    p = Part(id="x", name="Thing", category_path="misc", created_at="", updated_at="")
    assert not engineering.meets(p, {"tensile_strength_mpa": {"max": 99999}})


@pytest.mark.parametrize("bad", [{"price": {"min": 1}}, {"mass_g": 5}, {"mass_g": {"min": "a"}}, {"mass_g": {"low": 1}},
                                 {"tolerance": ""}])
def test_invalid_engineering_filters_are_refused(lib, monkeypatch, bad):
    r = client(lib, monkeypatch).post("/search", json={"query": "bolt", "use_ai": False, "filters": {"engineering": bad}})
    assert r.status_code == 422


# ---- filters without a question, and what the panel can offer ----------------------------------------------
def test_filters_without_a_question_list_the_parts_that_meet_them(lib, monkeypatch):
    c = client(lib, monkeypatch)
    d = c.post("/search", json={"query": "", "filters": {"category": "fasteners/bolt"}}).json()
    assert d["browse"] is True and d["ai_used"] is False
    assert sorted(r["id"] for r in d["results"]) == ["bolt-m8x30-88", "bolt-m8x40-46"]
    d = c.post("/search", json={"query": "", "filters": {"properties": {"property_class": "8.8"}}}).json()
    assert [r["id"] for r in d["results"]] == ["bolt-m8x30-88"]
    assert c.post("/search", json={"query": ""}).status_code == 422
    assert c.post("/search", json={"query": "  ", "filters": {}}).status_code == 422


def test_filter_options_only_show_what_this_company_may_see(lib, monkeypatch):
    c = client(lib, monkeypatch)
    f = c.get("/filters").json()
    assert f["total"] == 6                                              # the general library
    assert "titanium grade 5" not in [m["value"] for m in f["materials"]]
    cats = {x["value"]: x["count"] for x in f["categories"]}
    assert cats["fasteners"] == 3 and cats["fasteners/bolt"] == 2      # every level counts its parts
    eng = {e["key"]: e["count"] for e in f["engineering"]}
    assert eng["tensile_strength_mpa"] == 3 and eng["max_load_kg"] == 1   # 8.8, 4.6, S235; one bracket
    assert {"key": "thread"} .items() <= next(p for p in f["properties"] if p["key"] == "thread").items()
    b = c.get("/filters", params={"company_id": "company_b"}).json()
    assert b["total"] == 7 and "titanium grade 5" in [m["value"] for m in b["materials"]]
    bolts = c.get("/filters", params={"category": "fasteners/bolt"}).json()
    assert bolts["total"] == 2 and {p["key"] for p in bolts["properties"]} == {"thread", "length_mm", "property_class"}


# ---- where used ----------------------------------------------------------------------------------------
def test_used_in_shows_only_assemblies_this_company_may_see(lib, monkeypatch):
    c = client(lib, monkeypatch)
    assert c.get("/parts/bolt-m8x30-88").json()["used_in"] == [{"id": "frame-1", "name": "Machine frame 1000", "quantity": 24}]
    b = c.get("/parts/bolt-m8x30-88", params={"company_id": "company_b"}).json()["used_in"]
    assert {u["id"] for u in b} == {"frame-1", "secret-frame"}
    assert c.get("/parts/arduino-uno").json()["used_in"] == []


# ---- 12 Nov 2026: review fixes ---------------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("100 M8 bolts and 100 nuts", [("M8 bolts", 100), ("M8 nuts", 100)]),     # fasteners come by the hundred
    ("a 608 bearing and a pillow block", [("608 bearing", None), ("pillow block", None)]),   # a designation
    ("250 washers and 2 brackets", [("washers", 250), ("brackets", 2)]),
])
def test_large_quantities_only_for_fasteners(query, expected):
    assert [(p["request"], p["quantity"]) for p in split_request(query)] == expected


def test_percent_and_underscore_in_a_filter_are_ordinary_characters(lib, monkeypatch):
    c = client(lib, monkeypatch)
    for filters in ({"material": "%"}, {"material": "st__l"}, {"color": "%"}, {"category": "fasteners/b_lt"}):
        d = c.post("/search", json={"query": "", "filters": filters}).json()
        assert d["results"] == [], filters
    assert len(c.post("/search", json={"query": "", "filters": {"material": "steel 8.8"}}).json()["results"]) == 1


def test_photo_search_keeps_the_filters(lib, monkeypatch):
    seen = {}

    class Finder:
        model, backend, client = "m", "api", None
        engine = SearchEngine(lib.repo, lib.emb)
        usage = SimpleNamespace(cost_usd=0.0, billed=False)

        def identify_image(self, *_a):
            return {"is_mechanical_part": True, "part_type": "hex bolt", "search_query": "hex bolt M8",
                    "visible_features": [], "markings": [], "confidence": "high"}

        def find(self, query, company_id, limit, fixed_filters=None):
            seen["fixed"] = fixed_filters
            from partsfinder.ai import search_without_ai
            return search_without_ai(self.engine, query, company_id, limit, filters=fixed_filters)
    c = client(lib, monkeypatch, Finder())
    d = c.post("/search/image", json={"image_base64": "aGVsbG8gd29ybGQgaGVsbG8=", "media_type": "image/png",
                                      "filters": {"properties": {"property_class": "4.6"}}}).json()
    assert seen["fixed"].properties == {"property_class": "4.6"}
    assert [r["id"] for r in d["results"]] == ["bolt-m8x40-46"]


def test_filter_options_follow_the_library(lib, monkeypatch):
    c = client(lib, monkeypatch)
    assert c.get("/filters").json()["total"] == 6
    lib.repo.add_part(PartCreate(id="new-pin", name="Dowel pin 6x20", category_path="fasteners/bolt/hex-bolt"))
    out = c.get("/filters").json()
    assert out["total"] == 7 and "cached" not in out       # remembered per library version, never stale


def test_a_company_id_is_checked_before_an_import(lib, monkeypatch):
    c = client(lib, monkeypatch)
    r = c.post("/ingest", json={"folder": str(lib.tmp), "company_id": "../../elsewhere"})
    assert r.status_code == 400
