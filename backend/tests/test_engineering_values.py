"""Strength, load, tolerance and mass: shown per part, and checked when a question asks for them."""
from __future__ import annotations

import pytest

from partsfinder import engineering
from partsfinder.ai import search_without_ai
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.specs import parse_specs

BOLT = "fasteners/bolt/hex-bolt"
BRACKET = "connections/bracket/angle-bracket"
BEARING = "drivetrain/bearing/ball-bearing"


@pytest.fixture
def lib():
    conn = connect(":memory:", embedding_dim=64)
    repo, emb = Repository(conn), HashingEmbedder(64)
    rows = [
        dict(id="bolt-88", name="Hex bolt M8x30 ISO 4017", category_path=BOLT, material="steel 8.8",
             properties={"thread": "M8", "length_mm": 30}, standards=["ISO 4017"]),
        dict(id="bolt-109", name="Hex bolt M8x30 ISO 4017 10.9", category_path=BOLT, material="steel",
             properties={"thread": "M8", "length_mm": 30, "property_class": "10.9"}, standards=["ISO 4017"]),
        dict(id="bolt-a2", name="Hex bolt M8x30 stainless", category_path=BOLT, material="stainless steel A2-70",
             properties={"thread": "M8", "length_mm": 30}, standards=["ISO 4017"]),
        dict(id="bracket-80", name="Shelf bracket 200 mm", category_path=BRACKET, material="steel S235",
             properties={"max_load_kg": 80}, volume_mm3=23000, bbox_mm=(200, 150, 40)),
        dict(id="bracket-30", name="Shelf bracket 150 mm", category_path=BRACKET, material="steel",
             properties={"max_load_n": 294.3}),
        dict(id="bracket-none", name="Shelf bracket 100 mm", category_path=BRACKET, material="aluminium"),
        dict(id="bearing-6205", name="Deep groove ball bearing 6205-2RS", category_path=BEARING, material="steel",
             properties={"designation": "6205", "load_rating_kn": 14.8, "static_load_rating_kn": 7.8,
                         "inner_diameter_mm": 25, "outer_diameter_mm": 52, "width_mm": 15}),
        dict(id="plate", name="Mounting plate 120x80", category_path="connections/plate/base-plate",
             material="aluminium 6082-T6", properties={"tolerance": "ISO 2768-mK", "hardness_hb": 95}),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb), repo
    conn.close()


def ask(lib, q):
    return search_without_ai(lib[0], q, None, 6, reason="switched off in the request")


def by_key(part):
    return {v["key"]: v for v in engineering.values(part)}


def test_strength_follows_from_the_property_class_or_the_grade(lib):
    _, repo = lib
    v = by_key(repo.get_part("bolt-88", None))
    assert (v["yield_strength_mpa"]["value"], v["tensile_strength_mpa"]["value"]) == (640, 800)
    assert "ISO 898-1" in v["tensile_strength_mpa"]["source"] and v["tensile_strength_mpa"]["text"] == "≥ 800 MPa"
    assert by_key(repo.get_part("bolt-109", None))["tensile_strength_mpa"]["value"] == 1040
    a2 = by_key(repo.get_part("bolt-a2", None))
    assert a2["tensile_strength_mpa"]["value"] == 700 and "ISO 3506-1" in a2["tensile_strength_mpa"]["source"]
    s235 = by_key(repo.get_part("bracket-80", None))
    assert (s235["yield_strength_mpa"]["value"], s235["tensile_strength_mpa"]["value"]) == (235, 360)
    # a loose "steel" or "aluminium" says nothing certain about its strength: nothing is made up
    assert "tensile_strength_mpa" not in by_key(repo.get_part("bracket-30", None))
    assert "tensile_strength_mpa" not in by_key(repo.get_part("bracket-none", None))


def test_mass_is_estimated_and_load_ratings_come_only_from_the_part_itself(lib):
    _, repo = lib
    v = by_key(repo.get_part("bracket-80", None))
    assert v["mass_g"]["text"] in ("≈ 180 g", "≈ 181 g") and v["mass_g"]["source"].startswith("estimate")
    assert v["max_load_kg"]["value"] == 80 and v["max_load_kg"]["source"] == "part data"
    assert round(by_key(repo.get_part("bracket-30", None))["max_load_kg"]["value"]) == 30          # 294.3 N
    b = by_key(repo.get_part("bearing-6205", None))
    assert b["load_rating_kn"]["text"] == "14.8 kN" and b["static_load_rating_kn"]["value"] == 7.8
    p = by_key(repo.get_part("plate", None))
    assert p["tolerance"]["value"] == "ISO 2768-mK" and p["hardness"]["value"] == "95 HB"
    assert p["tensile_strength_mpa"]["value"] == 290                                               # EN 755-2


def test_questions_read_strength_load_and_tolerance():
    assert parse_specs("bolt M8x30 at least 800 MPa")["tensile_strength_mpa"] == 800
    assert parse_specs("bolt M8 yield 640 MPa")["yield_strength_mpa"] == 640
    assert parse_specs("shelf bracket that holds 50 kg") == {"max_load_kg": 50}
    assert parse_specs("bracket max load 500 N")["max_load_kg"] == 51.0
    assert parse_specs("bearing 6205 dynamic load rating 14 kN")["load_rating_kn"] == 14
    assert parse_specs("bearing static load rating 7 kN") == {"static_load_rating_kn": 7}
    assert parse_specs("plate ISO 2768-m") == {"tolerance": "ISO 2768-m"}       # not a standard the part must name
    assert parse_specs("load cell 50 kg") == {}                                  # a load cell is not a requirement


def test_a_stronger_bolt_fits_a_weaker_one_does_not(lib):
    r = ask(lib, "hex bolt M8x30 at least 1000 MPa")
    fits = [j.hit.part.id for j in r.results if j.verdict == "fits"]
    assert fits == ["bolt-109"]
    weak = next(j for j in r.results if j.hit.part.id == "bolt-88")
    assert any("tensile strength 800 MPa, less than 1000 MPa" in m for m in weak.mismatch_reasons)


def test_a_bracket_must_state_that_it_holds_the_load(lib):
    r = ask(lib, "shelf bracket that holds 50 kg")
    verdicts = {j.hit.part.id: j.verdict for j in r.results}
    assert verdicts.get("bracket-80") == "fits"
    assert verdicts.get("bracket-30") != "fits" and verdicts.get("bracket-none") != "fits"
    assert r.status != "none"


def test_a_tolerance_class_and_a_load_rating_are_checked(lib):
    r = ask(lib, "mounting plate ISO 2768-m")
    assert [j.hit.part.id for j in r.results if j.verdict == "fits"] == ["plate"]
    r = ask(lib, "deep groove ball bearing 6205 dynamic load rating 14 kN")
    assert [j.hit.part.id for j in r.results if j.verdict == "fits"] == ["bearing-6205"]
    r = ask(lib, "deep groove ball bearing 6205 dynamic load rating 20 kN")
    assert not any(j.verdict == "fits" for j in r.results)


def test_every_result_carries_its_engineering_data(lib):
    from partsfinder.api import part_payload
    _, repo = lib
    eng = part_payload(repo.get_part("bolt-88", None), None)["engineering"]
    assert [(v["label"], v["text"]) for v in eng][:2] == [("Yield strength", "≥ 640 MPa"), ("Tensile strength", "≥ 800 MPa")]
    assert all(v["source"] for v in eng)
