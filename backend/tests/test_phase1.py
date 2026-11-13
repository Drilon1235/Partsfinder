"""Tests for phase 1: schema, taxonomy, storage and company separation.

Run:  python -m pytest   (in the backend/ folder)
"""
from __future__ import annotations

import sqlite_vec
import pytest

from partsfinder.db import SchemaMismatchError, connect
from partsfinder.models import PartCreate, PartFile
from partsfinder.repository import AccessError, DuplicatePartError, Repository
from partsfinder.taxonomy import Taxonomy, TaxonomyError

DIM = 8


@pytest.fixture
def repo():
    conn = connect(":memory:", embedding_dim=DIM)
    yield Repository(conn)
    conn.close()


def make(**kw) -> PartCreate:
    base = dict(name="Test part", category_path="connections/bracket/angle-bracket")
    base.update(kw)
    return PartCreate(**base)


# ---- taxonomy --------------------------------------------------------------
def test_taxonomy_loads():
    tax = Taxonomy.load()
    assert "furniture/seating/chair" in tax.all_category_paths()
    assert "horticulture" in tax.sectors


def test_taxonomy_normalizes_case_and_spaces():
    tax = Taxonomy.load()
    assert tax.validate_category(" Furniture/Seating/Chair ") == "furniture/seating/chair"
    assert tax.validate_category("connections/bracket") == "connections/bracket"


def test_taxonomy_rejects_unknown_with_hint():
    tax = Taxonomy.load()
    with pytest.raises(TaxonomyError, match="Did you mean"):
        tax.validate_category("furniture/seatin/chair")
    with pytest.raises(TaxonomyError):
        tax.validate_category("furniture")
    with pytest.raises(TaxonomyError):
        tax.validate_sectors(["space"])


# ---- store and retrieve -----------------------------------------------------
def test_add_and_get_roundtrip(repo):
    p = repo.add_part(make(
        name="Angle bracket 40x40 galvanized",
        sectors=["Construction", "industry", "construction"],
        tags=["angle", "galvanized"],
        material="steel S235",
        bbox_mm=(40, 40, 3),
        standards=["DIN 6917"],
        properties={"holes": 2, "hole_diameter_mm": 6.5},
        checksum="abc",
        files=[PartFile(format=".STEP", path="data/global/angle-bracket.step"),
               PartFile(format="sldprt", path="data/global/angle-bracket.sldprt")],
    ))
    got = repo.get_part(p.id, None)
    assert got is not None
    assert got.sectors == ["construction", "industry"]
    assert got.bbox_mm == (40, 40, 3)
    assert got.properties["holes"] == 2
    assert got.library == "global"
    primary = [f for f in got.files if f.is_primary]
    assert len(primary) == 1 and primary[0].format == "step"


def test_invalid_category_is_rejected(repo):
    with pytest.raises(TaxonomyError):
        repo.add_part(make(category_path="furniture/spaceship"))
    assert repo.count_parts(None) == 0


def test_list_by_category_prefix(repo):
    repo.add_part(make(name="Chair", category_path="furniture/seating/chair"))
    repo.add_part(make(name="Table", category_path="furniture/tables/dining-table"))
    repo.add_part(make(name="Bolt", category_path="fasteners/bolt/hex-bolt"))
    assert {p.name for p in repo.list_parts(None, "furniture")} == {"Chair", "Table"}
    assert [p.name for p in repo.list_parts(None, "furniture/seating")] == ["Chair"]


# ---- company separation (hard requirement) ------------------------------------------
def test_company_isolation(repo):
    g = repo.add_part(make(name="General"))
    a = repo.add_part(make(name="From A", company_id="company_a"))
    b = repo.add_part(make(name="From B", company_id="company_b"))

    assert {p.name for p in repo.list_parts("company_a")} == {"General", "From A"}
    assert {p.name for p in repo.list_parts("company_b")} == {"General", "From B"}
    assert {p.name for p in repo.list_parts(None)} == {"General"}

    assert repo.get_part(b.id, "company_a") is None
    assert repo.get_part(a.id, None) is None
    assert repo.get_part(g.id, "company_b") is not None


def test_company_cannot_delete_others_or_global(repo):
    g = repo.add_part(make(name="General"))
    b = repo.add_part(make(name="From B", company_id="company_b"))
    assert repo.delete_part(b.id, "company_a") is False
    assert repo.delete_part(g.id, "company_a") is False
    assert repo.delete_part(b.id, "company_b") is True
    assert repo.get_part(b.id, "company_b") is None


def test_checksum_duplicates_per_library(repo):
    repo.add_part(make(name="Original", checksum="x1"))
    with pytest.raises(DuplicatePartError):
        repo.add_part(make(name="Copy", checksum="x1"))
    # the same file is allowed in a company library
    a = repo.add_part(make(name="Copy A", checksum="x1", company_id="company_a"))
    assert repo.find_by_checksum("x1", "company_a").id == a.id
    assert repo.find_by_checksum("x1", "company_b") is None


# ---- search indexes -------------------------------------------------------------
def test_fulltext_index_follows_changes(repo):
    p = repo.add_part(make(name="Hex bolt M8x40", standards=["DIN 933"],
                           category_path="fasteners/bolt/hex-bolt"))
    hit = repo.conn.execute(
        "SELECT p.id FROM parts_fts f JOIN parts p ON p.pk = f.rowid WHERE parts_fts MATCH ?",
        ('"din 933"',),
    ).fetchall()
    assert [r["id"] for r in hit] == [p.id]
    repo.delete_part(p.id, None)
    assert repo.conn.execute("SELECT count(*) FROM parts_fts").fetchone()[0] == 0


def test_vector_index(repo):
    p1 = repo.add_part(make(name="One"))
    p2 = repo.add_part(make(name="Two"))
    repo.set_embedding(p1.id, [1, 0, 0, 0, 0, 0, 0, 0])
    repo.set_embedding(p2.id, [0, 1, 0, 0, 0, 0, 0, 0])
    repo.set_embedding(p2.id, [0, 0, 1, 0, 0, 0, 0, 0])  # overwriting is allowed
    rows = repo.conn.execute(
        """SELECT p.name FROM parts_vec v JOIN parts p ON p.pk = v.rowid
           WHERE v.embedding MATCH ? AND k = 1""",
        (sqlite_vec.serialize_float32([0.9, 0, 0.1, 0, 0, 0, 0, 0]),),
    ).fetchall()
    assert rows[0]["name"] == "One"
    with pytest.raises(ValueError):
        repo.set_embedding(p1.id, [1, 2, 3])
    repo.delete_part(p1.id, None)
    assert repo.conn.execute("SELECT count(*) FROM parts_vec").fetchone()[0] == 1


# ---- assemblies --------------------------------------------------------------
def test_assembly_components_respect_isolation(repo):
    leg = repo.add_part(make(name="Chair leg", category_path="furniture/seating"))
    seat_b = repo.add_part(make(name="Seat B", company_id="company_b",
                                   category_path="furniture/seating"))
    chair = repo.add_part(make(name="Chair A", kind="assembly", company_id="company_a",
                               category_path="furniture/seating/chair"))

    repo.add_component(chair.id, leg.id, 4, "company_a")       # general part: ok
    with pytest.raises(AccessError):
        repo.add_component(chair.id, seat_b.id, 1, "company_a")  # from another company
    with pytest.raises(AccessError):
        repo.add_component(chair.id, leg.id, 1, "company_b")       # not your assembly

    comps = repo.get_components(chair.id, "company_a")
    assert [(c.part.name, c.quantity) for c in comps] == [("Chair leg", 4)]
    assert repo.get_components(chair.id, "company_b") == []


# ---- database file --------------------------------------------------------
def test_reopen_file_db_and_dim_mismatch(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path, embedding_dim=DIM)
    Repository(conn).add_part(make(name="Is kept"))
    conn.close()

    conn = connect(path, embedding_dim=DIM)
    assert Repository(conn).count_parts(None) == 1
    conn.close()

    with pytest.raises(SchemaMismatchError):
        connect(path, embedding_dim=DIM * 2)
