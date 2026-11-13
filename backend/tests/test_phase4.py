"""Tests for phase 4: the search engine (filters, keywords, meaning, separation)."""
from __future__ import annotations

import pytest

from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, SearchFilters, _fts_query

DIM = 128


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    parts = [
        dict(id="chair-green", name="Garden chair green", category_path="furniture/seating/garden-chair",
             sectors=["horticulture", "hospitality"], material="steel", color="green", bbox_mm=(460, 520, 820),
             tags=["chair", "outdoor"], kind="assembly"),
        dict(id="chair-red", name="Canteen chair red", category_path="furniture/seating/chair",
             sectors=["office"], material="pp", color="red", bbox_mm=(460, 500, 800), tags=["chair"]),
        dict(id="chair-leg", name="Garden chair leg", category_path="furniture/seating", sectors=["horticulture"],
             material="steel", bbox_mm=(22, 22, 435), tags=["leg", "garden chair"]),
        dict(id="bolt-m8x40", name="Hex bolt M8x40", category_path="fasteners/bolt/hex-bolt",
             sectors=["industry"], material="steel 8.8", standards=["DIN 933"], bbox_mm=(15, 13, 45),
             tags=["bolt", "M8"]),
        dict(id="socket-m8x40", name="Socket head bolt M8x40", category_path="fasteners/bolt/socket-head-bolt",
             sectors=["industry"], material="steel 12.9", standards=["ISO 4762"], bbox_mm=(13, 13, 48),
             tags=["socket", "M8"]),
        dict(id="bracket-stainless", name="Angle bracket 60x60 stainless", category_path="connections/bracket/angle-bracket",
             sectors=["food"], material="stainless steel 304", bbox_mm=(60, 40, 60), tags=["angle bracket"]),
        dict(id="a-tray", name="Growing tray TB-1000", category_path="horticulture/cultivation/tray", sectors=["horticulture"],
             material="pe", bbox_mm=(1000, 400, 180), tags=["growing tray"], company_id="company_a"),
        dict(id="b-chair", name="Garden chair Lisse green", category_path="furniture/seating/garden-chair",
             sectors=["furniture"], material="aluminium", color="green", bbox_mm=(450, 500, 800),
             tags=["garden chair"], company_id="company_b"),
    ]
    for d in parts:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    repo.add_component("chair-green", "chair-leg", 4, None)
    yield SearchEngine(repo, emb)
    conn.close()


def ids(hits):
    return [h.part.id for h in hits]


def test_fts_query_is_safe_and_english_aware():
    assert _fts_query('green "chair* AND') == '"green"* OR "chair"*'     # quotes/AND harmless
    assert '"m6x25"' in _fts_query("socket bolt m6 25mm")
    assert _fts_query("the a an") is None


def test_basic_ranking(engine):
    assert ids(engine.search("green garden chair"))[0] == "chair-green"
    assert ids(engine.search("angle bracket stainless"))[0] == "bracket-stainless"


def test_standard_and_thread_size(engine):
    hits = engine.search("bolt DIN 933")
    assert hits[0].part.id == "bolt-m8x40" and hits[0].matched_standard
    assert ids(engine.search("socket bolt m8 40mm"))[0] == "socket-m8x40"


def test_components_rank_below_full_assembly(engine):
    r = ids(engine.search("garden chair"))
    assert r.index("chair-green") < r.index("chair-leg")
    assert ids(engine.search("garden chair leg"))[0] == "chair-leg"   # on top if asked for


def test_isolation_in_search(engine):
    assert "b-chair" not in ids(engine.search("green garden chair", "company_a", limit=20))
    assert "b-chair" in ids(engine.search("green garden chair", "company_b", limit=20))
    assert "a-tray" not in ids(engine.search("growing tray", None, limit=20))
    assert ids(engine.search("growing tray", "company_a"))[0] == "a-tray"
    # filter-only search must not leak either
    assert "b-chair" not in ids(engine.search("", "company_a", SearchFilters(color="green")))


def test_filters(engine):
    f = SearchFilters(category="furniture/seating/garden-chair")
    assert set(ids(engine.search("chair", "company_b", f))) == {"chair-green", "b-chair"}
    assert ids(engine.search("chair", None, SearchFilters(sectors=["office"]))) == ["chair-red"]
    assert ids(engine.search("bracket", None, SearchFilters(material="STAINLESS"))) == ["bracket-stainless"]
    assert ids(engine.search("bracket", None, SearchFilters(material="stainless-steel"))) == ["bracket-stainless"]
    assert ids(engine.search("bolt", None, SearchFilters(standards=["iso4762"]))) == ["socket-m8x40"]
    assert ids(engine.search("chair", None, SearchFilters(kind="assembly"))) == ["chair-green"]
    lib = SearchFilters(library="company")
    assert ids(engine.search("chair", "company_b", lib)) == ["b-chair"]
    assert engine.search("chair", None, lib) == []


def test_dimension_filters_ignore_orientation(engine):
    # 820 x 460 x 520 in a different order: the green chair still fits
    f = SearchFilters(max_dims_mm=(830, 470, 530), category="furniture/seating/garden-chair")
    assert ids(engine.search("chair", None, f)) == ["chair-green"]
    assert engine.search("chair", None, SearchFilters(max_dims_mm=(100, 100, 100),
                                                      category="furniture")) == []
    small = ids(engine.search("", None, SearchFilters(max_dims_mm=(50, 50, 50))))
    assert set(small) == {"bolt-m8x40", "socket-m8x40"}
    assert "bracket-stainless" in ids(engine.search("", None, SearchFilters(min_dims_mm=(40, 60, 60))))


def test_nothing_found(engine):
    assert engine.search("rocket engine", None, SearchFilters(category="drivetrain")) == []
    assert engine.search("", None, SearchFilters(category="piping")) == []


def test_hit_as_dict(engine):
    d = engine.search("green garden chair")[0].as_dict()
    assert d["part"]["id"] == "chair-green" and d["library"] == "global" and d["score"] > 0
