"""Tests for phase 8: 'nothing found' without AI, valid test questions, robust import."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cadquery as cq
import pytest

from partsfinder.ai import search_without_ai
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, ingest_folder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine, looks_relevant
from partsfinder.taxonomy import Taxonomy

DIM = 128
BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    for d in [
        dict(id="chair", name="Garden chair green", category_path="furniture/seating/garden-chair", tags=["chair"]),
        dict(id="tray", name="Growing tray 600x400 mm", category_path="horticulture/cultivation/tray", tags=["growing tray"]),
    ]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb)
    conn.close()


# ---- 'nothing found' without AI -------------------------------------------------------------
def test_none_when_no_query_word_matches(engine):
    r = search_without_ai(engine, "titanium rocket engine", None)
    assert r.status == "none" and r.results == [] and "No existing model found" in r.message
    # a number that happens to occur (400 in 600x400) is not a real match
    assert search_without_ai(engine, "solar panel 400 watt", None).status == "none"


def test_results_when_a_word_matches(engine):
    r = search_without_ai(engine, "green garden chair", None)
    assert r.status == "partial" and r.results[0].hit.part.id == "chair"
    assert r.results[0].hit.word_coverage == pytest.approx(1.0)


def test_looks_relevant_edge_cases(engine):
    assert looks_relevant([]) is False
    assert looks_relevant(engine.search("400", None)) is True          # numbers only: do not reject


# ---- the test questions themselves are correct ---------------------------------------------------------------
def _catalog():
    spec = importlib.util.spec_from_file_location("gen", PROJECT / "scripts" / "generate_testdata.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen"] = mod                      # needed for the dataclasses in that script
    sys.path.insert(0, str(PROJECT / "scripts"))
    spec.loader.exec_module(mod)
    return mod.catalog()


def test_queries_yaml_is_valid():
    sys.path.insert(0, str(BACKEND))
    from eval_search import load_cases

    cases = load_cases()
    assert len(cases) == 50
    groups = {c["group"] for c in cases}
    assert groups == {"clear", "vague", "requirements", "none", "separation"}
    ids = {m.id for m in _catalog()}
    tax = Taxonomy.load()
    for c in cases:
        for i in c.get("ids", []):
            assert i in ids, f"unknown id in queries.yaml: {i}"
        if "category" in c:
            tax.validate_category(c["category"])
        if c.get("status") != "none":
            assert any(k in c for k in ("ids", "category", "material", "company_top")), c["q"]


# ---- robust import ---------------------------------------------------------------------------
def test_import_survives_messy_folders(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    lib = tmp_path / "messy folder"
    (lib / "sub folder" / "deeper").mkdir(parents=True)
    cq.exporters.export(cq.Workplane("XY").box(10, 10, 10), str(lib / "tmp1.step"))
    (lib / "tmp1.step").rename(lib / "Angle bracket 50X50.STEP")
    cq.exporters.export(cq.Workplane("XY").box(5, 5, 60), str(lib / "tmp2.step"))
    (lib / "tmp2.step").rename(lib / "sub folder" / "deeper" / "shaft_8mm.stp")
    (lib / "broken.step").write_text("this is not a STEP file", encoding="utf-8")
    (lib / "empty.stl").write_bytes(b"")
    (lib / "notes.txt").write_text("no CAD", encoding="utf-8")
    (lib / "drawing.sldprt").write_bytes(b"native without STEP")

    r = ingest_folder(lib, repo, HashingEmbedder(DIM), thumbnail_dir=tmp_path / "t", log=lambda s: None)
    names = {repo.get_part(i, None).name for i in r.added}
    assert {"Angle bracket 50X50", "Shaft 8mm", "Drawing"} <= names           # subfolders, capitals, spaces
    failed = {f for f, _ in r.failed}
    assert failed == {"broken.step", "empty.stl"}                          # broken files: reported cleanly
    native = next(repo.get_part(i, None) for i in r.added if repo.get_part(i, None).name == "Drawing")
    assert native.bbox_mm is None and native.files[0].format == "sldprt"  # stored, not measured
    assert repo.get_part(next(i for i in r.added if repo.get_part(i, None).name == "Shaft 8mm"), None) \
        .category_path.startswith("drivetrain/shaft")
    conn.close()


# ---- the AI judge sees which words of the question occur in a candidate ------------
def test_matched_query_words():
    from partsfinder.ai import _candidate_line
    from partsfinder.search import SearchHit, matched_query_words

    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    m8 = repo.add_part(PartCreate(id="m8", name="Hex nut galvanized", category_path="fasteners/nut/hex-nut",
                                  properties={"thread": "M8"}))
    m6 = repo.add_part(PartCreate(id="m6", name="Hex nut M6 galvanized", category_path="fasteners/nut/hex-nut"))
    assert matched_query_words("hex nut M8", m8) == ["hex", "nut", "m8"]          # also from the properties
    assert matched_query_words("hex nut M8", m6) == ["hex", "nut"]
    assert matched_query_words("green hex nuts", m6) == ["hex", "nuts"]
    assert _candidate_line(SearchHit(m8, 0, 0, None, None), "hex nut M8")["query_words_matched"] == ["hex", "nut", "m8"]
    conn.close()


def test_changed_json_is_reimported(tmp_path):
    """A changed JSON next to an already imported CAD file is applied on the next import."""
    import json

    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    lib = tmp_path / "lib"
    lib.mkdir()
    cq.exporters.export(cq.Workplane("XY").box(10, 20, 30), str(lib / "block.step"))
    meta = {"id": "block-1", "name": "Block old", "category_path": "other/unknown", "tags": ["block"]}
    (lib / "block.json").write_text(json.dumps(meta), encoding="utf-8")
    run = lambda: ingest_folder(lib, repo, HashingEmbedder(DIM), make_thumbnails=False, log=lambda s: None)  # noqa: E731
    assert run().added == ["block-1"]
    assert run().skipped == ["block-1"]                         # nothing changed: skip
    meta.update(name="Block new", category_path="enclosures/machine")
    (lib / "block.json").write_text(json.dumps(meta), encoding="utf-8")
    r = run()
    assert r.updated == ["block-1"] and not r.added
    part = repo.get_part("block-1", None)
    assert part.name == "Block new" and part.category_path == "enclosures/machine"
    assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 1
    hits = SearchEngine(repo, HashingEmbedder(DIM)).search("block new", None)
    assert hits and hits[0].part.name == "Block new"          # the search index is updated too
    assert run().skipped == ["block-1"]
    conn.close()


def test_failed_update_keeps_old_part(tmp_path):
    """An invalid changed JSON must not lose the already imported part."""
    import json

    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    lib = tmp_path / "lib"
    lib.mkdir()
    cq.exporters.export(cq.Workplane("XY").box(10, 20, 30), str(lib / "block.step"))
    meta = {"id": "block-1", "name": "Block old", "category_path": "other/unknown", "tags": ["block"]}
    (lib / "block.json").write_text(json.dumps(meta), encoding="utf-8")
    run = lambda: ingest_folder(lib, repo, HashingEmbedder(DIM), make_thumbnails=False, log=lambda s: None)  # noqa: E731
    assert run().added == ["block-1"]
    meta.update(name="Block new", properties="not a dictionary")        # invalid for the data model
    (lib / "block.json").write_text(json.dumps(meta), encoding="utf-8")
    r = run()
    assert not r.updated and len(r.failed) == 1
    part = repo.get_part("block-1", None)
    assert part is not None and part.name == "Block old"                 # old version still present
    hits = SearchEngine(repo, HashingEmbedder(DIM)).search("block old", None)
    assert hits and hits[0].part.id == "block-1"                          # and still findable
    conn.close()


def test_updated_component_stays_linked_to_assembly(tmp_path):
    """If a part that is in an assembly is updated, the link remains."""
    import json

    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    lib = tmp_path / "lib"
    lib.mkdir()
    cq.exporters.export(cq.Workplane("XY").box(5, 5, 40), str(lib / "leg.step"))
    cq.exporters.export(cq.Workplane("XY").box(40, 40, 5), str(lib / "table.step"))
    leg = {"id": "leg-1", "name": "Leg old", "category_path": "other/unknown"}
    table = {"id": "table-1", "name": "Table", "kind": "assembly", "category_path": "other/unknown",
             "components": [{"id": "leg-1", "quantity": 4}]}
    (lib / "leg.json").write_text(json.dumps(leg), encoding="utf-8")
    (lib / "table.json").write_text(json.dumps(table), encoding="utf-8")
    run = lambda: ingest_folder(lib, repo, HashingEmbedder(DIM), make_thumbnails=False, log=lambda s: None)  # noqa: E731
    assert run().components_linked == 1
    leg["name"] = "Leg new"
    (lib / "leg.json").write_text(json.dumps(leg), encoding="utf-8")
    r = run()
    assert r.updated == ["leg-1"] and r.skipped == ["table-1"]
    comps = repo.get_components("table-1", None)
    assert [(c.part.name, c.quantity) for c in comps] == [("Leg new", 4)]
    conn.close()
