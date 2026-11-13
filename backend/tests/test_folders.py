"""Folder rules, sync and removal (docs/10_COMPANY_LIBRARIES.md).

A company share is built on disk with .partsfinderignore and .partsfinderaccess files. Every function of the import
that reads a CAD or JSON file is watched, so "never read" is checked literally.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from partsfinder import api as api_mod
from partsfinder.access import full
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder
from partsfinder.ingest import __main__ as ingest_cli
from partsfinder.ingest import pipeline
from partsfinder.repository import Repository

DIM = 32


def box(path: Path, size=(10, 20, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane("XY").box(*size), str(path))
    return path


def text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def share(tmp_path):
    root = tmp_path / "nas"
    box(root / "std" / "bracket.step", (100, 40, 5))
    text(root / "reactor" / ".partsfinderaccess", "# reactor parts\nnuclear\n")
    box(root / "reactor" / "vessel.step", (300, 300, 20))
    box(root / "reactor" / "internals" / "pump.step", (50, 50, 80))
    text(root / "reactor" / "internals" / "open" / ".partsfinderaccess", "company")
    box(root / "reactor" / "internals" / "open" / "plate.step", (60, 60, 4))
    text(root / "secret" / ".partsfinderignore", "*")
    box(root / "secret" / "topsecret.step", (11, 11, 11))
    text(root / "old" / ".partsfinderignore", "*.stl\ndrafts/\nnotes.json\n")
    box(root / "old" / "a.step", (12, 12, 12))
    box(root / "old" / "drafts" / "d.step", (13, 13, 13))
    text(root / "old" / "notes.json", '{"name": "must never be read"}')
    box(root / "old" / "notes.step", (14, 14, 14))
    text(root / "bad" / ".partsfinderaccess", "Not A Group!")
    box(root / "bad" / "x.step", (15, 15, 15))
    text(root / "neg" / ".partsfinderignore", "!keep.step")
    box(root / "neg" / "keep.step", (16, 16, 16))
    (root / "old" / "a2.stl").write_bytes(b"solid x\nendsolid x\n")
    return root


@pytest.fixture
def repo(tmp_path):
    conn = connect(tmp_path / "lib.db", embedding_dim=DIM, check_same_thread=False)
    yield Repository(conn)
    conn.close()


@pytest.fixture
def opened(monkeypatch):
    """Every file the import reads (checksum, geometry, JSON)."""
    seen: list[Path] = []
    for name in ("file_checksum", "analyze", "load_sidecar"):
        real = getattr(pipeline, name)

        def spy(path, *a, _real=real, **k):
            seen.append(Path(path))
            return _real(path, *a, **k)
        monkeypatch.setattr(pipeline, name, spy)
    return seen


class Enricher:
    def __init__(self):
        self.files = []

    def enrich(self, path, geom, guess):
        self.files.append(Path(path).name)
        return guess


def ingest(repo, folder, company="acme", **kw):
    kw.setdefault("make_thumbnails", False)
    return pipeline.ingest_folder(folder, repo, HashingEmbedder(DIM), company_id=company, log=lambda _: None, **kw)


def parts(repo, company="acme"):
    """file name -> access group of every part of this library"""
    return {Path(path).stem: repo.get_part(pid, full(company)).access_group for pid, path in repo.primary_paths(company)}


# ---- what is read, and who may see it --------------------------------------------------------------------
def test_rules_decide_what_is_read_and_who_sees_it(share, repo, opened):
    ai = Enricher()
    report = ingest(repo, share, enricher=ai)
    assert parts(repo) == {"bracket": None, "vessel": "nuclear", "pump": "nuclear", "plate": None,
                           "a": None, "notes": None}
    read = {p.name for p in opened}
    for never in ("topsecret.step", "d.step", "a2.stl", "notes.json", "x.step", "keep.step"):
        assert never not in read, never
    failed = dict(report.failed)
    assert "bad/" in failed and "not a valid group name" in failed["bad/"]
    assert "neg/" in failed and "not supported" in failed["neg/"]
    assert any("left out by .partsfinderignore" in w for w in report.warnings)
    # restricted files never get an AI description; the others do
    assert "vessel.step" not in ai.files and "pump.step" not in ai.files and "bracket.step" in ai.files


def test_confidential_company_gets_no_ai_at_all(share, repo):
    repo.set_confidential("acme", True)
    ai = Enricher()
    ingest(repo, share, enricher=ai)
    assert ai.files == []


def test_restricted_folders_never_in_the_general_library(share, repo):
    report = ingest(repo, share, company=None)
    names = {Path(path).stem for _pid, path in repo.primary_paths(None)}
    assert "vessel" not in names and "pump" not in names and "bracket" in names and "plate" in names
    assert any("only be imported into a company library" in e for _f, e in report.failed)


def test_rules_above_the_imported_folder_count(share, repo, opened):
    ingest(repo, share / "secret")                         # its own "*": nothing in it is read
    assert repo.primary_paths("acme") == [] and not opened
    text(share / ".partsfinderignore", "customer-x/\n")           # excluded from the top of the share
    box(share / "customer-x" / "drawing.step")
    report = ingest(repo, share / "customer-x")            # importing it directly changes nothing
    assert repo.primary_paths("acme") == [] and not opened
    assert "excluded by an .partsfinderignore in a folder above" in dict(report.failed)["./"]
    ingest(repo, share / "reactor" / "internals")          # the group of the folder above counts
    assert parts(repo) == {"pump": "nuclear", "plate": None}


def test_a_json_cannot_set_the_group(share, repo):
    text(share / "std" / "bracket.json", '{"name": "Bracket", "category_path": "connections/bracket/angle-bracket", '
                                          '"access_group": "public", "company_id": "other"}')
    ingest(repo, share / "std")
    (pid, _), = repo.primary_paths("acme")
    part = repo.get_part(pid, full("acme"))
    assert part.access_group is None and part.company_id == "acme"


# ---- sync ------------------------------------------------------------------------------------------------------
def test_sync_follows_the_share(share, repo, tmp_path):
    ingest(repo, share, make_thumbnails=True, thumbnail_dir=tmp_path / "thumbs")
    ids = {Path(path).stem: pid for pid, path in repo.primary_paths("acme")}
    thumb_a = Path(repo.get_part(ids["a"], full("acme")).thumbnail_path)
    mesh_dir = tmp_path / "data" / "meshes"
    mesh_dir.mkdir(parents=True)
    cached = mesh_dir / f"{ids['a']}-abc.stl"
    cached.write_bytes(b"x")

    box(share / "reactor" / "internals" / "open" / "plate.step", (61, 61, 4))      # changed content
    (share / "old" / "a.step").unlink()                                              # file gone
    text(share / "std" / ".partsfinderignore", "bracket.step")                             # now excluded
    text(share / "reactor" / ".partsfinderaccess", "aero")                                 # other group
    report = ingest(repo, share, sync=True, data_dir=tmp_path / "data")

    now = {Path(path).stem: pid for pid, path in repo.primary_paths("acme")}
    assert set(report.removed) == {ids["a"], ids["bracket"]} and "a" not in now and "bracket" not in now
    assert now["plate"] == ids["plate"] and ids["plate"] in report.updated              # same part, new content
    assert repo.get_part(ids["plate"], full("acme")).bbox_mm[0] == pytest.approx(61, abs=0.5)
    assert repo.get_part(ids["vessel"], full("acme")).access_group == "aero"
    assert not thumb_a.exists() and not cached.exists()
    assert repo.conn.execute("SELECT count(*) FROM parts_vec").fetchone()[0] == len(now)


def test_sync_never_empties_the_library_by_accident(share, repo, monkeypatch, tmp_path):
    ingest(repo, share)
    before = len(repo.primary_paths("acme"))
    empty = tmp_path / "empty-share"
    empty.mkdir()
    # an unreachable share stops everything
    with pytest.raises(FileNotFoundError):
        ingest(repo, tmp_path / "not-mounted", sync=True)
    # many files gone at once: refused unless explicitly allowed
    monkeypatch.setattr(pipeline, "MASS_REMOVAL", (2, 0.5))
    for p in list(share.rglob("*.step")):
        if p.parent.name in ("std", "old", "open"):
            p.unlink()
    report = ingest(repo, share, sync=True)
    assert report.removed == [] and any("nothing removed" in w for w in report.warnings)
    assert len(repo.primary_paths("acme")) == before
    report = ingest(repo, share, sync=True, allow_mass_removal=True)
    assert len(report.removed) == 4                        # bracket, a, notes, plate


# ---- removal ---------------------------------------------------------------------------------------------------
def test_remove_folder_removes_everything(share, repo):
    ingest(repo, share)
    ids = {Path(path).stem: pid for pid, path in repo.primary_paths("acme")}
    repo.add_feedback(ids["vessel"], full("acme"), "up", "reactor vessel")
    removed = pipeline.remove_folder(repo, share / "reactor", "acme")
    assert set(removed) == {ids["vessel"], ids["pump"], ids["plate"]}
    assert set(Path(p).stem for _i, p in repo.primary_paths("acme")) == {"bracket", "a", "notes"}
    c = repo.conn
    assert c.execute("SELECT count(*) FROM feedback").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM parts_fts WHERE parts_fts MATCH 'vessel'").fetchone()[0] == 0
    assert c.execute("PRAGMA secure_delete").fetchone()[0] == 1
    # another company's parts in the same folder are never touched
    ingest(repo, share / "std", company="beta")
    pipeline.remove_folder(repo, share / "std", "acme")
    assert len(repo.primary_paths("beta")) == 1


# ---- command line and API ------------------------------------------------------------------------------------------
def test_command_line(share, tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    base = ["--db", db, "--offline", "--no-ai", "--no-thumbnails"]
    assert ingest_cli.main([str(share / "std"), "--company", "acme", *base]) == 0
    assert ingest_cli.main(["--company", "acme", "--confidential", *base]) == 0
    assert ingest_cli.main(["--remove", str(share / "std"), "--company", "acme", *base]) == 0
    out = capsys.readouterr().out
    assert "confidential" in out and "Removed 1 parts" in out
    conn = connect(db, embedding_dim=get_settings().embedding_dim)
    repo = Repository(conn)
    assert repo.is_confidential("acme") and repo.primary_paths("acme") == []
    assert [e["action"] for e in repo.audit_entries("acme")] == ["remove", "settings", "ingest"]
    conn.close()
    with pytest.raises(SystemExit):
        ingest_cli.main(["--remove", str(share), *base])                     # needs --company


def test_api_remove_and_sync_need_the_admin(share, tmp_path, monkeypatch):
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(tmp_path / "data"))
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    s = dataclasses.replace(get_settings(), api_keys="k=acme, admin=*")
    c = TestClient(create_app(s, conn=conn, embedder=HashingEmbedder(DIM), finder=None, enable_ai=False))
    admin, key = {"Authorization": "Bearer admin"}, {"Authorization": "Bearer k"}
    body = {"folder": str(share / "old"), "company_id": "acme", "use_ai": False, "thumbnails": False}
    assert c.post("/ingest", json=body, headers=key).status_code == 403
    assert c.post("/ingest", json=body, headers=admin).json()["added"]
    (share / "old" / "a.step").unlink()
    r = c.post("/ingest", json={**body, "sync": True}, headers=admin).json()
    assert len(r["removed"]) == 1
    assert c.post("/remove", json={"folder": str(share / "old"), "company_id": "acme"}, headers=key).status_code == 403
    assert c.post("/remove", json={"folder": str(share / "old"), "company_id": "acme"}, headers=admin).json()["total"] == 1
    actions = [e["action"] for e in Repository(conn).audit_entries("acme")]
    assert actions[:3] == ["remove", "ingest", "ingest"]
    assert all(e["actor"].startswith("key:") for e in Repository(conn).audit_entries("acme"))


def test_links_are_never_followed(share, repo, opened):
    import os
    try:
        os.symlink(share / "secret" / "topsecret.step", share / "std" / "link.step")
        os.symlink(share / "secret", share / "std" / "linked-folder", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make symbolic links")
    ingest(repo, share / "std")
    assert {Path(p).stem for _i, p in repo.primary_paths("acme")} == {"bracket"}
    assert "topsecret.step" not in {p.name for p in opened} and "link.step" not in {p.name for p in opened}
