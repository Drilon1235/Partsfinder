"""Engineering specs: parsing questions as an engineer asks them, checking them per part,
and the search engine / no-AI judge using them (specs.py, search.py, ai.py).

Run:  python -m pytest tests/test_engineering.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from partsfinder.ai import enforce_specs, search_without_ai
from partsfinder.db import connect
from partsfinder.ingest.embeddings import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.specs import check_specs, parse_specs, summarize

DIM = 384


# ---- 1. parsing ------------------------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("DIN 912 M8x30 A2-70", {"standard": ["DIN 912"], "thread": "M8", "length_mm": 30, "property_class": "A2-70"}),
    ("hex bolt M10 60 mm 8.8", {"thread": "M10", "length_mm": 60, "property_class": "8.8"}),
    ("socket head bolt m6 25mm", {"thread": "M6", "length_mm": 25}),
    ("M8x1.25 nut", {"thread": "M8", "pitch_mm": 1.25}),
    ("deep groove ball bearing 6204-2RS", {"designation": "6204", "seal": "2RS"}),
    ("608zz bearing", {"designation": "608", "seal": "2Z"}),
    ("bearing 20x47x14", {"inner_diameter_mm": 20, "outer_diameter_mm": 47, "width_mm": 14}),
    ("NEMA 23 stepper motor 2 Nm 8 mm shaft", {"frame_size": 23, "holding_torque_nm": 2, "shaft_diameter_mm": 8}),
    ("GT2 pulley 20 teeth 5 mm bore", {"belt_profile": "GT2", "teeth": 20, "bore_mm": 5}),
    ("spur gear module 1.5 z40", {"module": 1.5, "teeth": 40}),
    ("aluminium profile 40x40 slot 8 length 1000", {"profile_size": "40x40", "slot_width_mm": 8, "length_mm": 1000}),
    ("pneumatic cylinder ISO 15552 bore 50 stroke 100",
     {"standard": ["ISO 15552"], "piston_diameter_mm": 50, "stroke_mm": 100}),
    ("weld neck flange DN50 PN16", {"dn": 50, "pn": 16}),
    ("linear guide rail size 20", {"rail_size": 20}),
    ("pillow block bearing for 25 mm shaft", {"bore_mm": 25}),
    ("linear shaft 12 mm h6 500 mm", {"shaft_diameter_mm": 12, "tolerance": "h6", "length_mm": 500}),
    ("dowel pin 6 x 30 m6", {"diameter_mm": 6, "length_mm": 30, "tolerance": "m6"}),
    ("threaded rod M10 1000 mm", {"thread": "M10", "length_mm": 1000}),
    ("t-nut slot 8 M5", {"thread": "M5", "slot_width_mm": 8}),
])
def test_parse_engineering_questions(query, expected):
    assert parse_specs(query) == expected


@pytest.mark.parametrize("query", ["green garden chair", "IPE 200 beam",
                                   "table for in a workshop", "espresso machine"])
def test_parse_consumer_questions_has_no_specs(query):
    assert parse_specs(query) == {}


def test_module_is_not_a_thread():
    s = parse_specs("spur gear module 2 with 20 teeth")
    assert s == {"module": 2, "teeth": 20}


# ---- 2. checking ----------------------------------------------------------------------------------
def part(**kw):
    from partsfinder.models import Part
    base = dict(id="x", name="x", category_path="fasteners/bolt/socket-head-bolt", created_at="", updated_at="")
    base.update(kw)
    return Part(**base)


def test_equivalent_standard_and_property_class_list():
    p = part(standards=["ISO 4762"], properties={"thread": "M8", "length_mm": 30,
                                                 "property_classes": ["8.8", "10.9", "12.9", "A2-70"]})
    checks = {c.key: c.status for c in check_specs(parse_specs("DIN 912 M8x30 A2-70"), p)}
    assert checks == {"standard": "match", "thread": "match", "length_mm": "match", "property_class": "match"}


def test_wrong_thread_is_key_mismatch_and_reported_in_numbers():
    p = part(standards=["ISO 4762"], properties={"thread": "M6", "length_mm": 30})
    s = summarize(parse_specs("ISO 4762 M8x30"), p)
    assert s.key_mismatch and not s.all_match
    assert "thread M6 instead of M8" in [c.sentence() for c in s.mismatched]


def test_plain_steel_bolt_does_not_meet_stainless_class():
    p = part(material="steel", standards=["ISO 4762"], properties={"thread": "M8", "length_mm": 30})
    c = {c.key: c for c in check_specs({"property_class": "A2-70"}, p)}["property_class"]
    assert c.status == "mismatch"


def test_holding_torque_is_at_least():
    p = part(category_path="electrical/motor/stepper-motor", properties={"frame_size": 34, "holding_torque_nm": 8.5})
    assert summarize(parse_specs("NEMA 34 stepper motor at least 8 Nm"), p).all_match
    assert not summarize(parse_specs("NEMA 34 stepper 12 Nm"), p).all_match


def test_bearing_designation_with_seal():
    p = part(category_path="drivetrain/bearing/ball-bearing",
             properties={"designation": "6204-2RS", "seal": "2RS", "inner_diameter_mm": 20})
    assert summarize(parse_specs("6204-2RS"), p).all_match
    s = summarize(parse_specs("6204 ZZ bearing"), p)
    assert [c.key for c in s.mismatched] == ["seal"] and not s.key_mismatch
    assert summarize(parse_specs("62042RS bearing 62041"), p).checks   # no crash on odd input


def test_unknown_when_part_does_not_state_it():
    p = part(properties={"thread": "M8"})
    s = summarize(parse_specs("M8x30 12.9"), p)
    assert {c.key: c.status for c in s.checks} == {"thread": "match", "length_mm": "unknown",
                                                    "property_class": "unknown"}


def test_enforce_specs_downgrades_a_wrong_fit():
    class Hit:
        pass
    h = Hit()
    h.specs = summarize(parse_specs("ISO 4762 M8x30"), part(standards=["ISO 4762"],
                                                           properties={"thread": "M10", "length_mm": 30}))
    verdict, match, mismatch = enforce_specs(h, "fits", [], [])
    assert verdict == "close" and any("M10 instead of M8" in m for m in mismatch)


# ---- 3. search + judge without AI -------------------------------------------------------------------
@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=DIM)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    rows = [
        ("eng-b-6204-2rs", "Deep groove ball bearing 6204-2RS, 20x47x14 mm", "drivetrain/bearing/ball-bearing",
         ["ISO 15"], {"designation": "6204-2RS", "seal": "2RS", "inner_diameter_mm": 20, "outer_diameter_mm": 47,
                      "width_mm": 14}, ["ball bearing", "6204"]),
        ("eng-b-6205-2rs", "Deep groove ball bearing 6205-2RS, 25x52x15 mm", "drivetrain/bearing/ball-bearing",
         ["ISO 15"], {"designation": "6205-2RS", "seal": "2RS", "inner_diameter_mm": 25, "outer_diameter_mm": 52,
                      "width_mm": 15}, ["ball bearing", "6205"]),
        ("shcs-m8x30", "Socket head bolt M8x30 ISO 4762", "fasteners/bolt/socket-head-bolt", ["ISO 4762", "DIN 912"],
         {"thread": "M8", "length_mm": 30, "property_classes": ["8.8", "10.9", "12.9", "A2-70"]},
         ["socket head", "m8", "m8x30"]),
        ("shcs-m8x35", "Socket head bolt M8x35 ISO 4762", "fasteners/bolt/socket-head-bolt", ["ISO 4762", "DIN 912"],
         {"thread": "M8", "length_mm": 35, "property_classes": ["8.8", "10.9", "12.9", "A2-70"]},
         ["socket head", "m8", "m8x35"]),
        ("stepper-23", "Stepper motor NEMA 23, 76 mm body, 1.89 Nm", "electrical/motor/stepper-motor", [],
         {"frame_size": 23, "holding_torque_nm": 1.89, "shaft_diameter_mm": 8}, ["stepper motor", "nema 23"]),
    ]
    for pid, name, cat, stds, props, tags in rows:
        p = repo.add_part(PartCreate(id=pid, name=name, description=name, category_path=cat, standards=stds,
                                     properties=props, tags=tags, material="steel", sectors=["industry"]))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb)
    conn.close()


def test_exact_spec_ranks_first_and_fits(engine):
    r = search_without_ai(engine, "DIN 912 M8x30 12.9", None)
    assert r.status == "found"
    assert r.results[0].hit.part.id == "shcs-m8x30" and r.results[0].verdict == "fits"
    assert all(j.verdict != "fits" for j in r.results[1:] if j.hit.part.id == "shcs-m8x35")


def test_bearing_found_by_dimensions_only(engine):
    r = search_without_ai(engine, "bearing 20x47x14", None)
    assert r.results[0].hit.part.id == "eng-b-6204-2rs" and r.results[0].verdict == "fits"


def test_missing_size_is_partial_with_deviation(engine):
    r = search_without_ai(engine, "deep groove ball bearing 6206-2RS", None)
    assert r.status == "partial"
    assert r.results and r.results[0].verdict == "close"
    assert any("designation" in m for m in r.results[0].mismatch_reasons)


@pytest.mark.parametrize("query", ["make me a M8 bolt 30mm", "can you give me an M8x30 socket head bolt please",
                                   "I'd like a ISO 4762 M8x30"])
def test_request_phrasing_does_not_hide_the_part(engine, query):
    r = search_without_ai(engine, query, None)
    assert r.status == "found" and r.results[0].hit.part.id == "shcs-m8x30"


def test_specs_alone_do_not_make_a_fit(engine):
    r = search_without_ai(engine, "planetary gearbox ratio 10 NEMA 23", None)
    assert all(j.verdict != "fits" for j in r.results)


def test_spec_checks_in_hit_dict(engine):
    hit = engine.search("6204-2RS", None, limit=1)[0]
    d = hit.as_dict()
    assert {c["spec"] for c in d["spec_checks"]} == {"designation", "seal"}
    assert all(c["status"] == "match" for c in d["spec_checks"])


# ---- 4. catalogue -----------------------------------------------------------------------------------
def test_engineering_catalogue_is_valid():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "engineering"))
    from catalog import catalog
    from partsfinder.taxonomy import Taxonomy

    tax = Taxonomy.load()
    items = catalog()
    assert len(items) >= 250
    for i in items:
        tax.validate_category(i.category_path)
        assert i.properties, i.id
        meta = i.metadata()
        assert meta["source"] == "partsfinder-engineering" and "manufacturer" not in meta["properties"]
    # every bearing name carries its designation and d x D x B
    b = next(i for i in items if i.id == "eng-bearing-6204-2rs")
    assert "6204-2RS" in b.name and "20x47x14" in b.name
