"""What the library's own code says before any AI (without an API key, or when another AI calls the library with
use_ai false). The app asks the code first, so the code must be honest by itself: "none" when the part is not there, a material only from the stated
material, and a value no part states is not "close"."""
from __future__ import annotations

import pytest

from partsfinder.ai import NOT_JUDGED, head_noun, missing_words, only_named, search_without_ai
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.specs import parse_specs

NUT = "fasteners/nut/hex-nut"
BRACKET = "connections/bracket/angle-bracket"


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=64)
    repo, emb = Repository(conn), HashingEmbedder(64)
    rows = [
        dict(id="servo-sg90", name="Servo motor SG90", category_path="electrical/motor/servo-motor"),
        dict(id="dc-motor-750", name="DC motor 750 W 24 V", category_path="electrical/motor/electric-motor"),
        dict(id="chain", name="Cable chain link 25 x 16 mm", category_path="electronics/component/connector"),
        dict(id="nut-m8", name="Hex nut M8 ISO 4032", category_path=NUT, material="steel 8",
             properties={"thread": "M8"}),
        dict(id="nut-m8-brass", name="Hex nut M8", category_path=NUT, material="brass CuZn39Pb3",
             properties={"thread": "M8"}),
        dict(id="nut-m10-insert", name="Hex nut M10", description="For brass inserts in aluminium profiles.",
             category_path=NUT, material="steel 8", properties={"thread": "M10"}),
        dict(id="bracket-alu", name="Corner bracket 40x40", category_path=BRACKET, material="die-cast aluminium"),
        dict(id="bracket-steel", name="Angle bracket 60x60", description="For aluminium profiles.",
             category_path=BRACKET, material="steel galvanized"),
        dict(id="b-table", name="Table Nora 1200", category_path="furniture/tables/dining-table", company_id="b"),
        dict(id="table", name="Dining table oak 1600x900", category_path="furniture/tables/dining-table"),
        dict(id="battery", name="Li-ion battery pack 24 V for DC motor drives", category_path="electrical/power/battery"),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb), repo
    conn.close()


def ask(engine, q, company=None):
    return search_without_ai(engine[0], q, company, 6, reason="switched off in the request")


def test_power_is_read_as_a_spec():
    assert parse_specs("servo motor 400 W") == {"power_w": 400.0}
    assert parse_specs("heater 0.75 kW")["power_w"] == 750.0
    assert parse_specs("400 watt motor")["power_w"] == 400.0
    assert "power_w" not in parse_specs("washer M8 w")


def test_a_power_no_part_states_is_none_not_a_tiny_servo(engine):
    r = ask(engine, "servo motor 400 W")
    assert r.status == "none" and not r.results and r.decided
    assert "states its power" in r.message
    r = ask(engine, "DC motor 750 W")
    assert r.status == "found" and r.results[0].hit.part.id == "dc-motor-750"


def test_a_part_the_library_does_not_have_is_none(engine):
    for q in ("cable gland", "Cable gland M20", "a cable gland"):
        r = ask(engine, q)
        assert r.status == "none" and not r.results, q
        assert "no part in the library is a gland" in r.message


def test_the_head_noun_is_never_a_product_name_or_a_sentence():
    assert head_noun("cable gland") == "gland"
    assert head_noun("servo motor 400 W") == "motor"
    assert head_noun("dining table Nora") == "table"
    assert head_noun("something to hang a shelf on") is None
    assert head_noun("green bracket") == "bracket"


def test_the_request_around_the_part_is_not_the_part():
    for q in ("make me a battery", "Make me a battery", "can you give me a battery", "I need a battery",
              "please draw a battery", "battery"):
        assert head_noun(q) == "battery", q
    assert head_noun("make me something to hang a shelf on") is None


def test_make_me_a_battery_shows_the_battery_not_the_motor(engine):
    r = ask(engine, "make me a battery")
    assert r.status != "none" and [j.hit.part.id for j in r.results] == ["battery"]
    hits = engine[0].search("make me a battery", limit=10)       # what the AI gets to judge: only batteries
    assert any(h.part.id == "dc-motor-750" for h in hits)
    assert [h.part.id for h in only_named("make me a battery", hits)] == ["battery"]
    r = ask(engine, "make me a gearbox")                          # none in the library: say so
    assert r.status == "none" and "is a gearbox" in r.message


def test_a_product_name_of_another_company_still_finds_the_kind(engine):
    r = ask(engine, "dining table Nora", company="a")
    assert r.status != "none" and "table" in {j.hit.part.id for j in r.results}
    assert "b-table" not in {j.hit.part.id for j in r.results}


def test_a_material_counts_only_in_the_stated_material(engine):
    _, repo = engine
    assert missing_words("aluminium bracket", repo.get_part("bracket-alu", None)) == []
    assert missing_words("aluminium bracket", repo.get_part("bracket-steel", None)) == ["aluminium"]
    assert missing_words("aluminum bracket", repo.get_part("bracket-alu", None)) == []      # US spelling
    r = ask(engine, "brass nut M8")
    assert [j.hit.part.id for j in r.results if j.verdict == "fits"] == ["nut-m8-brass"]
    r = ask(engine, "brass nut M10")                    # "brass inserts" in a description is no brass nut
    assert r.status == "partial" and not any(j.verdict == "fits" for j in r.results)
    assert all("brass: not stated" in j.mismatch_reasons for j in r.results if j.hit.part.id == "nut-m10-insert")


def test_without_ai_the_message_is_not_an_error(engine):
    r = ask(engine, "flux capacitor bracket")
    assert "AI not available" not in r.message
    r = search_without_ai(engine[0], "corner bracket", None, 6)
    assert r.message == NOT_JUDGED



def test_a_material_stays_hard_when_the_ai_judges(engine):
    from partsfinder.ai import enforce_material
    from partsfinder.search import SearchHit
    _, repo = engine
    steel = SearchHit(repo.get_part("nut-m8", None), 1.0, None, None, None)
    brass = SearchHit(repo.get_part("nut-m8-brass", None), 1.0, None, None, None)
    assert enforce_material("brass nut M8", steel, "fits", []) == ("close", ["brass: not stated"])
    assert enforce_material("brass nut M8", brass, "fits", []) == ("fits", [])
    assert enforce_material("nut M8, preferably brass", steel, "fits", []) == ("fits", [])   # only preferred


def test_a_word_in_the_description_does_not_make_a_part_that_thing():
    conn = connect(":memory:", embedding_dim=64)
    repo, emb = Repository(conn), HashingEmbedder(64)
    for d in [dict(id="shield", name="Nano expansion shield 59 x 54 mm", category_path="electronics/component/connector"),
              dict(id="bearing", name="Deep groove ball bearing 6000-2Z, 10x26x8 mm",
                   description="Single-row deep groove ball bearing with two metal shields (2Z), nano grease.",
                   category_path="drivetrain/bearing/ball-bearing")]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    r = search_without_ai(SearchEngine(repo, emb), "nano expansion shield", None, 6, reason="switched off in the request")
    assert [j.hit.part.id for j in r.results] == ["shield"]
    hits = SearchEngine(repo, emb).search("nano expansion shield", limit=10)
    assert [h.part.id for h in only_named("nano expansion shield", hits)] == ["shield"]
    conn.close()
