"""Tests for the fixes of the 9 Nov 2026 audit (company env, re-import transaction,
mesh cache temp files)."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from partsfinder import preview
from partsfinder.db import connect
from partsfinder.models import PartCreate, PartFile
from partsfinder.repository import Repository


# ---- re-import: old version out and new version in, in one transaction --------------------------
@pytest.fixture
def repo():
    conn = connect(":memory:", embedding_dim=8)
    yield Repository(conn)
    conn.close()


def _part(**kw):
    base = dict(id="bracket-1", name="Bracket", category_path="connections/bracket/angle-bracket",
                checksum="abc", files=[PartFile(format="step", path="a.step", is_primary=True)])
    base.update(kw)
    return PartCreate(**base)


def test_replace_keeps_old_part_when_insert_fails(repo):
    repo.add_part(_part())
    # two files with the same path break the (part_id, path) key while inserting the new version
    broken = _part(name="Bracket v2", files=[PartFile(format="step", path="b.step", is_primary=True),
                                             PartFile(format="step", path="b.step")])
    with pytest.raises(Exception):
        repo.add_part(broken, replace_id="bracket-1")
    old = repo.get_part("bracket-1", None)
    assert old is not None and old.name == "Bracket"


def test_replace_swaps_the_part(repo):
    repo.add_part(_part())
    new = repo.add_part(_part(name="Bracket v2"), replace_id="bracket-1")
    assert new.name == "Bracket v2" and repo.count_parts(None) == 1


def test_replace_never_deletes_another_companys_part(repo):
    repo.add_part(_part(id="b-secret", company_id="company_b", checksum="zzz"))
    repo.add_part(_part(id="a-new", company_id="company_a", checksum="yyy"), replace_id="b-secret")
    assert repo.get_part("b-secret", "company_b") is not None


# ---- mesh cache: own temporary file per writer ---------------------------------------------
def test_parallel_mesh_writes_do_not_clash(tmp_path):
    out = tmp_path / "m.stl"
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    errors = []

    def write():
        try:
            for _ in range(20):
                preview._write_binary_stl(out, verts, [(0, 1, 2)])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert out.stat().st_size == 84 + 50
    assert not list(tmp_path.glob("*.tmp"))
