"""Required standards and materials (10 Nov 2026): strict standard, material families, exclusions,
and no "fits" while a material requirement is not confirmed by the part's own data."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from partsfinder.ai import enforce_specs
from partsfinder.models import Part
from partsfinder.specs import parse_specs, summarize


def part(**kw) -> Part:
    base = dict(id="p", name="Socket head bolt M8x30", category_path="fasteners/bolt/socket-head-bolt",
                created_at="", updated_at="", properties={"thread": "M8", "length_mm": 30})
    base.update(kw)
    return Part(**base)


def status(query: str, p: Part, key: str) -> tuple[str, object]:
    check = next(c for c in summarize(parse_specs(query), p).checks if c.key == key)
    return check.status, check.found


# ---- reading the question ------------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("M8x30 bolt A4", {"material_grade": "A4"}),
    ("hex bolt M10x40 stainless", {"material_grade": "stainless"}),
    ("plate 1.0038", {"material_grade": "S235JR"}),
    ("profile EN AW-6082 40x40", {"material_grade": "6082-T6", "profile_size": "40x40"}),
    ("exactly ISO 4762 M8x30", {"standard_exact": ["ISO 4762"]}),
    ("washer M8 not galvanized", {"excluded": ["galvanized"]}),
    ("bracket without zinc, no plastic", {"excluded": ["galvanized", "plastic"]}),
])
def test_parse(query, expected):
    specs = parse_specs(query)
    assert {k: specs.get(k) for k in expected} == expected


def test_what_is_ruled_out_is_not_also_required():
    specs = parse_specs("bolt M8x30 not stainless")
    assert specs["excluded"] == ["stainless"] and "material_grade" not in specs


def test_a_bearing_number_stays_a_bearing():
    assert parse_specs("6082 bearing") == {"designation": "6082"}
    assert parse_specs("bearing 6205-2RS")["designation"] == "6205"


# ---- materials -----------------------------------------------------------------------------------
def test_family_accepts_every_member():
    assert status("M8x30 bolt A4", part(properties={"material_grades": ["1.4404"]}), "material_grade")[0] == "match"
    assert status("M8x30 bolt A4", part(material="stainless steel 1.4571"), "material_grade")[0] == "match"
    assert status("M8x30 bolt A2", part(material="stainless steel 1.4404"), "material_grade")[0] == "mismatch"


def test_precise_number_on_a_family_part_is_unknown():
    assert status("bolt M8x30 1.4404", part(material="stainless steel A4"), "material_grade")[0] == "unknown"


def test_stainless_must_be_stated():
    assert status("M8x30 bolt stainless", part(material="stainless steel"), "material_grade")[0] == "match"
    assert status("M8x30 bolt stainless", part(material="steel 8.8"), "material_grade")[0] == "mismatch"
    assert status("M8x30 bolt stainless", part(), "material_grade")[0] == "unknown"


def test_en_numbers_are_the_same_grade():
    assert status("plate 1.0038", part(material="S235JR"), "material_grade")[0] == "match"


# ---- standards -----------------------------------------------------------------------------------
def test_equivalent_standard_counts_unless_exact_is_asked():
    din = part(standards=["DIN 912"])
    assert status("M8x30 ISO 4762", din, "standard")[0] == "match"
    state, found = status("M8x30 exactly ISO 4762", din, "standard_exact")
    assert state == "mismatch" and "equivalent" in found
    assert status("M8x30 exactly ISO 4762", part(standards=["ISO 4762"]), "standard_exact")[0] == "match"


# ---- exclusions ----------------------------------------------------------------------------------
def test_exclusion():
    q = "washer M8 not galvanized"
    assert status(q, part(material="steel, zinc plated"), "excluded") == ("mismatch", "zinc plated")
    assert status(q, part(material="stainless steel A2"), "excluded")[0] == "match"
    assert status(q, part(), "excluded")[0] == "unknown"                     # nothing stated: not confirmed
    assert status("bolt M8 no plastic", part(name="Nylon bolt M8"), "excluded")[0] == "mismatch"


def test_exclusion_shown_as_not():
    check = summarize(parse_specs("washer M8 not galvanized"), part(material="zinc plated")).checks[-1].as_dict()
    assert check["requested"] == "not galvanized" and check["found"] == "zinc plated"


# ---- never a forced fit, also when the AI says so ----------------------------------------------------
@pytest.mark.parametrize("query, p", [
    ("M8x30 bolt stainless", part()),                              # material not stated
    ("washer M8 not galvanized", part(name="Washer M8")),          # exclusion not confirmed
    ("M8x30 exactly ISO 4762", part(standards=["DIN 912"])),       # equivalent, not the asked number
])
def test_ai_fits_becomes_close(query, p):
    hit = SimpleNamespace(specs=summarize(parse_specs(query), p))
    verdict, _match, mismatch = enforce_specs(hit, "fits", ["looks right"], [])
    assert verdict == "close" and mismatch
