"""Vague and extremely specific questions (10 Nov 2026): the library names the defining value a question
leaves open (with the values it really has), shows requirements it can only check in text as "not checked",
checks upper limits, and lets preferences change only the order."""
from __future__ import annotations

import pytest

from partsfinder.ai import search_without_ai
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine
from partsfinder.specs import parse_preferences, parse_specs

BOLT = "fasteners/bolt/hex-bolt"


@pytest.fixture
def engine():
    conn = connect(":memory:", embedding_dim=64)
    repo, emb = Repository(conn), HashingEmbedder(64)
    rows = [
        dict(id=f"bolt-m{t}x{l}", name=f"Hex bolt M{t}x{l}", category_path=BOLT, properties={"thread": f"M{t}", "length_mm": l},
             bbox_mm=(1.6 * t, 1.6 * t, l + 0.7 * t), material="steel 8.8")
        for t, l in [(6, 20), (8, 20), (8, 30), (8, 40)]
    ] + [
        dict(id="bolt-m8x30-a4", name="Hex bolt M8x30 stainless", category_path=BOLT, material="stainless steel A4",
             properties={"thread": "M8", "length_mm": 30}, bbox_mm=(13, 13, 35.3)),
        dict(id="bolt-m8x30-black", name="Hex bolt M8x30", description="Black oxide finish.", category_path=BOLT,
             properties={"thread": "M8", "length_mm": 30}, bbox_mm=(13, 13, 35.3), material="steel 8.8"),
        dict(id="nut-m12", name="Hex nut M12", category_path="fasteners/nut/hex-nut", properties={"thread": "M12"}),
        dict(id="bracket", name="Angle bracket 120x80", category_path="connections/bracket/angle-bracket",
             bbox_mm=(120, 80, 6)),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    yield SearchEngine(repo, emb)
    conn.close()


def need(engine, q):
    return {n["spec"]: n["choices"] for n in search_without_ai(engine, q, None, 6).requirements.get("need", [])}


# ---- vague: name what is open, offer what exists ------------------------------------------------------
def test_a_bolt_asks_thread_and_length_from_real_values(engine):
    open_specs = need(engine, "a bolt")
    assert list(open_specs) == ["thread", "length_mm"]
    assert open_specs["thread"] == ["M6", "M8"]                 # the M12 nut is no bolt: not offered
    assert "40 mm" in open_specs["length_mm"]


def test_choosing_a_value_closes_it(engine):
    assert list(need(engine, "a bolt M8")) == ["length_mm"]
    assert need(engine, "bolt M8x30") == {}


def test_choice_is_read_back_by_the_parser():
    assert parse_specs("a bolt M8 30 mm") == {"thread": "M8", "length_mm": 30.0}
    assert parse_specs("ball bearing 20 mm bore")["bore_mm"] == 20.0


def test_api_returns_need(engine):
    r = search_without_ai(engine, "a bolt", None, 6)
    assert r.status == "partial" and r.message.startswith("Which thread?")


# ---- extreme: everything shown, nothing forced ----------------------------------------------------------
def verdicts(engine, q):
    return {j.hit.part.id: j for j in search_without_ai(engine, q, None, 10).results}


def test_text_requirement_is_not_checked_until_the_part_states_it(engine):
    got = verdicts(engine, "hex bolt M8x30 black oxide")
    assert got["bolt-m8x30-black"].verdict == "fits"
    plain = got.get("bolt-m8x30")
    assert plain is None or plain.verdict == "close"
    if plain:
        assert any("not checked" in m for m in plain.mismatch_reasons)


def test_upper_limit_is_checked_against_the_envelope(engine):
    assert parse_specs("bracket max 100 mm") == {"max_size_mm": 100.0}
    checks = {c.key: c for c in verdicts(engine, "angle bracket max 100 mm")["bracket"].hit.specs.checks}
    assert checks["max_size_mm"].status == "mismatch" and checks["max_size_mm"].as_dict()["requested"] == "≤ 100 mm"
    checks = {c.key: c for c in verdicts(engine, "angle bracket max 150 mm")["bracket"].hit.specs.checks}
    assert checks["max_size_mm"].status == "match"


# ---- preferences: order only ----------------------------------------------------------------------------
def test_preference_orders_but_does_not_require(engine):
    q = "hex bolt M8x30, preferably A4"
    assert parse_preferences(q) == {"material_grade": "A4"} and "material_grade" not in parse_specs(q)
    results = search_without_ai(engine, q, None, 10).results
    fits = [j.hit.part.id for j in results if j.verdict == "fits"]
    assert fits[0] == "bolt-m8x30-a4" and "bolt-m8x30" in fits      # the steel one still fits


# ---- settled in code: the app answers without AI when the library's own checks decide ----------------------
@pytest.mark.parametrize("query, decided", [
    ("hex bolt M8x30", True),                         # a part meets every requirement
    ("a bolt", True),                                  # a defining value is open: only the engineer can choose it
    ("hex bolt M8x30, preferably A4", True),
    ("hex bolt M8x30 with a nut", False),              # several parts: one search cannot settle it
    ("hex bolt M8x30 and washer", False),
    ("angle bracket", False),                          # no requirement to check: the AI judges
])
def test_decided(engine, query, decided):
    assert search_without_ai(engine, query, None, 6).decided is decided


# ---- every word counts: "green bolt" is not settled by thread and length (10 Nov, Drilon's screenshot) ------
def test_a_word_the_part_lacks_is_never_a_fit(engine):
    got = verdicts(engine, "galvanized hex bolt M8x30")
    assert not any(j.verdict == "fits" for j in got.values())     # thread and length fit, "galvanized" not


def test_a_bolt_is_no_answer_to_a_nut_question(engine):
    got = verdicts(engine, "hex nut M8x30")
    assert not any(j.verdict == "fits" and "bolt" in j.hit.part.id for j in got.values())


def test_green_bolt_goes_to_the_ai_and_shows_only_bolts(engine):
    r = search_without_ai(engine, "make me a green bolt", None, 6)
    assert all("bolt" in j.hit.part.id for j in r.results)        # no buttons, tables or hooks
    if r.results:                                                 # the code says itself that no bolt is green
        assert r.decided and "No bolt in the library is stated as green" in r.message
    plain = search_without_ai(engine, "a bolt", None, 6)
    assert plain.decided is True and all("bolt" in j.hit.part.id for j in plain.results)


def test_a_word_no_part_has_does_not_change_the_answer(engine):
    """'a red bolt' and 'a green bolt' give the same bolts and choices as 'a bolt', each with the word it lacks."""
    plain = search_without_ai(engine, "a bolt", None, 6)
    for colour in ("red", "green"):
        r = search_without_ai(engine, f"a {colour} bolt", None, 6)
        if not r.results:
            continue
        assert [j.hit.part.id for j in r.results] == [j.hit.part.id for j in plain.results]
        assert r.requirements["need"] == plain.requirements["need"]
        assert all(f"{colour}: not stated" in j.mismatch_reasons for j in r.results)


def test_colour_is_a_whole_word():
    """'green' is not in 'greenhouse': a greenhouse profile is not a green profile."""
    from partsfinder.ai import missing_words
    from partsfinder.models import Part
    p = Part(id="gh", name="Greenhouse profile T 60 mm", category_path="profiles/aluminium/system-profile",
             created_at="", updated_at="")
    assert missing_words("green aluminium profile", p) == ["green", "aluminium"]


def test_pillow_block_bearing_is_one_part():
    from partsfinder.specs import several_parts
    assert not several_parts("pillow block bearing") and not several_parts("linear bearing LM12UU")
    assert several_parts("bearing and pillow block") and several_parts("M10 bolt with nut")
