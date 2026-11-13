"""Tests for phase 5: the AI layer, with a fake Claude (no key or credit needed)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from partsfinder.ai import AIError, BudgetExceeded, PartFinder, search_without_ai
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.taxonomy import Taxonomy

DIM = 128


class FakeClaude:
    """Pretends to be the Anthropic client. interpret/judge are dicts or functions(payload)."""

    def __init__(self, interpret, judge, tokens=(1000, 200)):
        self.interpret, self.judge, self.tokens = interpret, judge, tokens
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        tool = kw["tools"][0]["name"]
        content = kw["messages"][0]["content"]
        if tool == "search_request":
            data = self.interpret(content) if callable(self.interpret) else self.interpret
        else:
            data = self.judge(json.loads(content)) if callable(self.judge) else self.judge
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name=tool, input=data)],
            usage=SimpleNamespace(input_tokens=self.tokens[0], output_tokens=self.tokens[1],
                                  cache_read_input_tokens=0, cache_creation_input_tokens=0))


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in [
        dict(id="chair-green", name="Garden chair green", category_path="furniture/seating/garden-chair",
             sectors=["horticulture"], material="steel", color="green", bbox_mm=(460, 520, 820)),
        dict(id="chair-white", name="Garden chair white", category_path="furniture/seating/garden-chair",
             sectors=["horticulture"], material="steel", color="white", bbox_mm=(460, 520, 820)),
        dict(id="workbench", name="Workbench steel 1500x750", category_path="furniture/tables/workbench",
             sectors=["industry"], material="steel", bbox_mm=(1500, 750, 900)),
        dict(id="bolt", name="Hex bolt M8x40", category_path="fasteners/bolt/hex-bolt",
             sectors=["industry"], standards=["DIN 933"], bbox_mm=(15, 13, 45)),
        dict(id="b-chair", name="Garden chair Lisse green", category_path="furniture/seating/garden-chair",
             sectors=["furniture"], color="green", bbox_mm=(450, 500, 800), company_id="company_b"),
    ]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb)
    conn.close()


def finder(engine, interpret, judge, **kw):
    return PartFinder(engine, Taxonomy.load(), "claude-haiku-5-5",
                      client=FakeClaude(interpret, judge, kw.pop("tokens", (1000, 200))), **kw)


def candidate_ids(payload):
    return [c["id"] for c in payload["candidates"]]


# ---- step 1: question -> requirements --------------------------------------------------------
def test_interpret_validates_and_cleans(engine):
    f = finder(engine, {"search_text": "garden chair green outdoor", "category": "Furniture/Seating/Garden-chair",
                        "sectors": ["horticulture", "space"], "max_dims_mm": [600, 600, 900],
                        "kind": "aircraft", "nice_to_have": ["green"]}, {})
    text, filters, req = f.interpret("green garden chair")
    assert text == "garden chair green outdoor"
    assert filters.category == "furniture/seating/garden-chair"
    assert filters.sectors == ["horticulture"]                 # unknown sector removed
    assert filters.max_dims_mm == (600, 600, 900)
    assert filters.kind is None and filters.color is None  # preference, not a hard filter
    assert req["nice_to_have"] == ["green"]


def test_interpret_unknown_type_falls_back_to_parent(engine):
    f = finder(engine, {"search_text": "sofa", "category": "furniture/seating/sofa"}, {})
    assert f.interpret("sofa")[1].category == "furniture/seating"


# ---- step 3: judging ------------------------------------------------------------
def test_find_filters_invented_and_rejected_ids(engine):
    def judge(payload):
        assert "b-chair" not in candidate_ids(payload)       # another company never as a candidate
        return {"status": "found", "message": "1 matching garden chair found.", "results": [
            {"id": "invented-id", "verdict": "fits"},
            {"id": "b-chair", "verdict": "fits"},
            {"id": "chair-green", "verdict": "fits", "match_reasons": ["green", "garden chair"]},
            {"id": "chair-white", "verdict": "close", "mismatch_reasons": ["white instead of green"]},
            {"id": "bolt", "verdict": "no_fit"},
            {"id": "chair-green", "verdict": "fits"},          # duplicate
        ]}
    r = finder(engine, {"search_text": "green garden chair"}, judge).find("green garden chair", "company_a")
    assert r.status == "found"
    assert [(j.hit.part.id, j.verdict) for j in r.results] == [("chair-green", "fits"), ("chair-white", "close")]
    assert r.results[0].match_reasons == ["green", "garden chair"]
    assert r.message == "1 matching garden chair found."


def test_company_sees_own_part_as_candidate(engine):
    seen = {}

    def judge(payload):
        seen["ids"] = candidate_ids(payload)
        return {"status": "found", "message": "ok", "results": [{"id": "b-chair", "verdict": "fits"}]}

    r = finder(engine, {"search_text": "green garden chair"}, judge).find("green garden chair", "company_b")
    assert "b-chair" in seen["ids"] and r.results[0].hit.part.company_id == "company_b"


def test_none_and_partial_status_follow_results(engine):
    none = finder(engine, {"search_text": "rocket engine"},
                  {"status": "found", "message": "Found!", "results": []}).find("rocket engine")
    assert none.status == "none" and none.results == [] and "No existing model found" in none.message

    partial = finder(engine, {"search_text": "red garden chair"},
                     {"status": "found", "message": "x", "results": [{"id": "chair-white", "verdict": "close"}]}
                     ).find("red garden chair")
    assert partial.status == "partial" and "starting point" in partial.message


def test_strict_filters_are_relaxed_to_find_candidates(engine):
    def judge(payload):
        assert "workbench" in candidate_ids(payload)
        return {"status": "found", "message": "ok", "results": [{"id": "workbench", "verdict": "fits"}]}
    # Claude accidentally chooses a category that is too strict: it is relaxed
    r = finder(engine, {"search_text": "workbench worktable", "category": "piping/flange"}, judge
               ).find("table for in the workshop")
    assert r.status == "found"
    assert r.requirements["search_steps"][0] != "all requirements"


# ---- costs and errors --------------------------------------------------------------
def test_usage_and_budget(engine):
    f = finder(engine, {"search_text": "chair"}, {"status": "none", "message": "", "results": []},
               tokens=(100_000, 10_000), max_spend_usd=0.02)
    f.find("chair")                                     # 2 requests: 200k in, 20k out (haiku)
    assert f.usage.calls == 2
    assert f.usage.cost_usd == pytest.approx(0.2 * 0.10 + 0.02 * 0.50)
    with pytest.raises(BudgetExceeded):
        f.find("chair")


def test_api_errors_are_explained(engine):
    class AuthenticationError(Exception):
        pass

    def boom(**kw):
        raise AuthenticationError("invalid x-api-key")

    client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    f = PartFinder(engine, Taxonomy.load(), "claude-haiku-5-5", client=client)
    with pytest.raises(AIError, match="API key is invalid"):
        f.find("chair")
    with pytest.raises(AIError, match="No API key"):
        PartFinder(engine, Taxonomy.load(), "claude-haiku-5-5", api_key=None)


def test_fallback_without_ai(engine):
    r = search_without_ai(engine, "green garden chair", "company_a", reason="no key")
    assert r.ai_used is False and r.status == "partial"
    assert "b-chair" not in [j.hit.part.id for j in r.results]


def test_result_dict_format(engine):
    r = finder(engine, {"search_text": "bolt M8"},
               {"status": "found", "message": "ok", "results": [{"id": "bolt", "verdict": "fits"}]}
               ).find("bolt M8x40 DIN 933")
    d = r.as_dict()
    assert d["status"] == "found" and d["ai_used"] is True
    res = d["results"][0]
    for key in ("id", "library", "name", "category_path", "dims_mm", "standards", "verdict",
                "match_reasons", "mismatch_reasons", "files", "score"):
        assert key in res
    assert res["standards"] == ["DIN 933"]
