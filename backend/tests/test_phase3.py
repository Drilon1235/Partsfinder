"""Tests for phase 3: geometry, metadata, embeddings and the import pipeline.

Uses a fake Claude and the simple HashingEmbedder: no API key or download needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cadquery as cq
import pytest

from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, ingest_folder, part_text
from partsfinder.ingest.geometry import analyze, file_checksum
from partsfinder.ingest.metadata import REVIEW_TAG, ClaudeEnricher, guess_from_filename
from partsfinder.repository import Repository
from partsfinder.taxonomy import Taxonomy

DIM = 64


def step_box(path: Path, x=10, y=20, z=30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane("XY").box(x, y, z), str(path))
    return path


def sidecar(path: Path, **meta) -> None:
    path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture
def repo():
    conn = connect(":memory:", embedding_dim=DIM)
    yield Repository(conn)
    conn.close()


def run(folder, repo, **kw):
    kw.setdefault("thumbnail_dir", folder / "_thumbs")
    return ingest_folder(folder, repo, HashingEmbedder(DIM), log=lambda s: None, **kw)


# ---- geometry -----------------------------------------------------------------
def test_analyze_step_and_stl(tmp_path):
    g = analyze(step_box(tmp_path / "block.step", 10, 20, 30))
    assert g.bbox_mm == pytest.approx((10, 20, 30), abs=0.01)
    assert g.volume_mm3 == pytest.approx(6000, rel=1e-3)
    assert g.triangles

    import trimesh
    trimesh.creation.box(extents=(5, 6, 7)).export(tmp_path / "block.stl")
    s = analyze(tmp_path / "block.stl")
    assert s.bbox_mm == pytest.approx((5, 6, 7), abs=0.01)
    assert s.volume_mm3 == pytest.approx(210, rel=1e-3)

    (tmp_path / "x.sldprt").write_bytes(b"native")
    assert analyze(tmp_path / "x.sldprt") is None


def test_step_checksum_ignores_header(tmp_path):
    a = step_box(tmp_path / "a.step")
    b = tmp_path / "b.step"
    b.write_bytes(a.read_bytes().replace(b"HEADER;", b"HEADER;\n/* other time */", 1))
    assert file_checksum(a) == file_checksum(b)


# ---- metadata -------------------------------------------------------------------
def test_guess_from_filename():
    tax = Taxonomy.load()
    assert guess_from_filename(Path("angle-bracket_50x50.step"), None, tax)["category_path"] == \
        "connections/bracket/angle-bracket"
    assert guess_from_filename(Path("greenhouse-bracket-large.step"), None, tax)["category_path"].startswith(
        "connections/bracket")
    assert guess_from_filename(Path("Garden chair red.step"), None, tax)["category_path"] == \
        "furniture/seating/garden-chair"
    unknown = guess_from_filename(Path("xq-7781.step"), None, tax)
    assert unknown["category_path"] == "other/unknown"
    assert REVIEW_TAG in unknown["tags"]


def test_claude_enricher_with_fake_client():
    answer = json.dumps({"name": "Mounting bracket", "description": "Bracket to mount something.",
                         "category_path": "connections/bracket/mounting-bracket",
                         "sectors": ["industry", "space"], "material": "steel",
                         "tags": ["bracket", "mounting"]})
    fake = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(content=[SimpleNamespace(text="Here: " + answer)])))
    tax = Taxonomy.load()
    enr = ClaudeEnricher("x", "model", tax, client=fake)
    guess = guess_from_filename(Path("mb-12.step"), None, tax)
    out = enr.enrich(Path("mb-12.step"), None, guess)
    assert out["name"] == "Mounting bracket"
    assert out["category_path"] == "connections/bracket/mounting-bracket"
    assert out["sectors"] == ["industry"]            # unknown sector filtered out
    assert REVIEW_TAG in out["tags"] and out["properties"]["ai_metadata"]


# ---- embeddings -----------------------------------------------------------------
def test_hashing_embedder_prefers_shared_words():
    e = HashingEmbedder(DIM * 4)
    q = e.embed_query("green garden chair")
    a, b = e.embed_passages(["Garden chair green. keywords: green garden chair", "Hex bolt M8 steel"])
    dot = lambda u, v: sum(x * y for x, y in zip(u, v))  # noqa: E731
    assert dot(q, a) > dot(q, b)


# ---- pipeline -------------------------------------------------------------------
def test_ingest_with_sidecar_thumbnail_and_embedding(tmp_path, repo):
    f = step_box(tmp_path / "lib" / "bracket.step", 40, 40, 3)
    (tmp_path / "lib" / "bracket.sldprt").write_bytes(b"native solidworks")
    sidecar(f, id="bracket-1", name="Angle bracket 40", category_path="connections/bracket/angle-bracket",
            sectors=["construction"], material="steel", company_id="company_hack")
    r = run(tmp_path / "lib", repo)
    assert r.added == ["bracket-1"] and not r.failed
    p = repo.get_part("bracket-1", None)
    assert p.company_id is None                       # JSON may not choose the library
    assert p.bbox_mm == pytest.approx((40, 40, 3), abs=0.01)
    assert {x.format for x in p.files} == {"step", "sldprt"}
    assert [x.format for x in p.files if x.is_primary] == ["step"]
    assert p.thumbnail_path and Path(p.thumbnail_path).exists()
    assert repo.conn.execute("SELECT count(*) FROM parts_vec").fetchone()[0] == 1
    assert "Angle bracket 40" in part_text(p)


def test_reimport_skips_and_changed_file_updates(tmp_path, repo):
    f = step_box(tmp_path / "lib" / "block.step")
    sidecar(f, id="block", name="Block", category_path="other/unknown")
    run(tmp_path / "lib", repo)
    assert run(tmp_path / "lib", repo).skipped == ["block"]
    step_box(f, 11, 20, 30)                            # model changed
    r = run(tmp_path / "lib", repo)
    assert r.updated == ["block"]
    assert repo.get_part("block", None).bbox_mm[0] == pytest.approx(11, abs=0.01)
    assert repo.count_parts(None) == 1


def test_changed_id_in_json_renames_the_part(tmp_path, repo):
    f = step_box(tmp_path / "lib" / "old_name.step")
    sidecar(f, id="bd-groefkogellager-20x47x14", name="Ball bearing", category_path="drivetrain/bearing/ball-bearing")
    run(tmp_path / "lib", repo)
    repo.add_feedback("bd-groefkogellager-20x47x14", None, "up", query="bearing")
    f.with_suffix(".json").unlink()
    f = f.rename(tmp_path / "lib" / "new_name.step")
    sidecar(f, id="bd-deep-groove-ball-bearing-20x47x14", name="Deep groove ball bearing 20x47x14 mm",
            category_path="drivetrain/bearing/ball-bearing")
    r = run(tmp_path / "lib", repo)
    assert r.updated == ["bd-deep-groove-ball-bearing-20x47x14"] and not r.failed
    assert repo.get_part("bd-groefkogellager-20x47x14", None) is None
    p = repo.get_part("bd-deep-groove-ball-bearing-20x47x14", None)
    assert p.name.startswith("Deep groove") and p.files[0].path.endswith("new_name.step")
    assert [f["part_id"] for f in repo.list_feedback(None)] == ["bd-deep-groove-ball-bearing-20x47x14"]
    assert repo.count_parts(None) == 1


def test_company_import_is_isolated(tmp_path, repo):
    step_box(tmp_path / "a" / "secret_part.step")
    r = run(tmp_path / "a", repo, company_id="company_a")
    pid = r.added[0]
    assert repo.get_part(pid, "company_a").company_id == "company_a"
    assert repo.get_part(pid, "company_b") is None
    assert repo.get_part(pid, None) is None


def test_id_from_other_library_is_refused(tmp_path, repo):
    f = step_box(tmp_path / "g" / "x.step")
    sidecar(f, id="same-id", name="X", category_path="other/unknown")
    run(tmp_path / "g", repo)
    f2 = step_box(tmp_path / "b" / "y.step", 5, 5, 5)
    sidecar(f2, id="same-id", name="Y", category_path="other/unknown")
    r = run(tmp_path / "b", repo, company_id="company_b")
    assert r.failed and "another library" in r.failed[0][1]
    assert repo.get_part("same-id", None).name == "X"


def test_without_sidecar_guess_and_enricher(tmp_path, repo):
    step_box(tmp_path / "lib" / "swivel_caster_75.step")
    r = run(tmp_path / "lib", repo)
    p = repo.get_part(r.added[0], None)
    assert p.category_path == "machine-elements/foot/swivel-caster"
    assert r.needs_review == [p.id]

    class Fake:
        def enrich(self, path, geom, guess):
            return {**guess, "name": "Smartly named", "sectors": ["logistics"]}

    step_box(tmp_path / "lib2" / "something.step", 7, 7, 7)
    r2 = run(tmp_path / "lib2", repo, enricher=Fake())
    assert repo.get_part(r2.added[0], None).name == "Smartly named"


def test_broken_enricher_falls_back(tmp_path, repo):
    class Broken:
        def enrich(self, *a):
            raise RuntimeError("no internet")

    step_box(tmp_path / "lib" / "levelling-foot-m10.step")
    r = run(tmp_path / "lib", repo, enricher=Broken())
    assert len(r.added) == 1 and r.warnings


def test_assembly_components_linked(tmp_path, repo):
    lib = tmp_path / "lib"
    for pid in ("leg", "seat"):
        sidecar(step_box(lib / f"{pid}.step", 5, 5, 40 if pid == "leg" else 2),
                id=pid, name=pid, category_path="furniture/seating")
    sidecar(step_box(lib / "chair.step", 40, 40, 80), id="chair", name="Chair", kind="assembly",
            category_path="furniture/seating/chair",
            components=[{"id": "leg", "quantity": 4}, {"id": "seat", "quantity": 1},
                        {"id": "does-not-exist", "quantity": 1}])
    r = run(lib, repo)
    assert r.components_linked == 2
    assert any("does-not-exist" in err for _, err in r.failed)
    comps = {c.part.id: c.quantity for c in repo.get_components("chair", None)}
    assert comps == {"leg": 4, "seat": 1}


def test_bad_category_in_sidecar_fails_cleanly(tmp_path, repo):
    sidecar(step_box(tmp_path / "lib" / "a.step"), name="A", category_path="spaceship/engine")
    step_box(tmp_path / "lib" / "b_bolt.step", 8, 8, 40)
    r = run(tmp_path / "lib", repo)
    assert len(r.failed) == 1 and len(r.added) == 1


def test_hints_from_filename():
    from partsfinder.ingest.metadata import hints_from_name
    h = hints_from_name("Hex_bolt_M8x40_DIN933_stainless")
    assert h["standards"] == ["DIN 933"] and h["properties"] == {"thread": "M8", "length_mm": 40}
    assert h["material"] == "stainless steel"
    assert hints_from_name("Nut M10 ISO 4032 steel")["properties"] == {"thread": "M10"}
    assert hints_from_name("Nut M10 ISO 4032 steel")["standards"] == ["ISO 4032"]
    h = hints_from_name("Bolt M6x12,5 alu")
    assert h["properties"] == {"thread": "M6", "length_mm": 12.5} and h["material"] == "aluminium"
    assert hints_from_name("xq-7781") == {"standards": [], "properties": {}}
    assert hints_from_name("Motor MM2 enclosure")["properties"] == {}             # no false thread
    tax = Taxonomy.load()
    g = guess_from_filename(Path("Bolt_M8x40_DIN933_stainless.step"), None, tax)
    assert g["standards"] == ["DIN 933"] and g["material"] == "stainless steel"
    assert g["properties"]["thread"] == "M8" and g["properties"]["needs_review"] is True
