"""Data packs: install, update, skip duplicates, remove; files that stay at their open library (remote.py)."""
from __future__ import annotations

import dataclasses
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from partsfinder import packs, remote
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder
from partsfinder.repository import Repository

DIM = 16
URL = "https://raw.githubusercontent.com/example/lib/0123abc/Resistor_SMD.3dshapes/R_0805_2012Metric.step"


def make_pack(root, name="test-pack", parts=None, version="2026-11-13"):
    folder = root / name
    (folder / "thumbnails").mkdir(parents=True)
    (folder / "files").mkdir()
    (folder / "files" / "bolt.step").write_text("ISO-10303-21; bolt")
    for pid in ("tp-bolt", "tp-resistor"):
        (folder / "thumbnails" / f"{pid}.png").write_bytes(b"\x89PNG fake")
    rows = parts or [
        {"id": "tp-bolt", "name": "Socket head bolt M8x30 ISO 4762", "description": "Socket head cap screw M8x30.",
         "category_path": "fasteners/bolt/socket-head-bolt", "tags": ["bolt", "m8"], "checksum": "c-bolt",
         "bbox_mm": [13, 13, 38], "volume_mm3": 1500, "license": "Apache-2.0", "source": "test-pack",
         "thumbnail_path": "thumbnails/tp-bolt.png", "files": [{"format": "step", "path": "files/bolt.step", "is_primary": True}]},
        {"id": "tp-resistor", "name": "SMD resistor R 0805 2012Metric", "description": "SMD resistor 0805.",
         "category_path": "electronics/component/resistor", "tags": ["resistor", "0805"], "checksum": "c-res",
         "bbox_mm": [2, 1.25, 0.5], "volume_mm3": 1.2, "license": "CC-BY-SA-4.0", "source": "test-pack",
         "source_ref": "https://github.com/example/lib/blob/0123abc/R_0805.step",
         "thumbnail_path": "thumbnails/tp-resistor.png", "files": [{"format": "step", "path": URL, "is_primary": True}]},
    ]
    (folder / "parts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (folder / "pack.json").write_text(json.dumps({"format": 1, "name": name, "title": "Test pack", "version": version,
                                                  "license": "mixed", "files": "remote", "parts": len(rows)}))
    (folder / "LICENSE.txt").write_text("licence")
    return folder


@pytest.fixture()
def lib(tmp_path):
    conn = connect(tmp_path / "lib.db", DIM)
    yield Repository(conn), tmp_path / "data"
    conn.close()


def test_install_update_and_remove(tmp_path, lib):
    repo, data = lib
    src = make_pack(tmp_path / "src")
    r = packs.install(src, repo, HashingEmbedder(DIM), data, log=lambda _: None)
    assert (r["added"], r["updated"], r["failed"]) == (2, 0, 0)
    bolt = repo.get_part("tp-bolt", None)
    assert bolt.license == "Apache-2.0" and bolt.thumbnail_path and bolt.files[0].path.endswith("packs/test-pack/files/bolt.step")
    assert repo.get_part("tp-resistor", None).files[0].path == URL           # stays at its library
    assert (data / "packs" / "test-pack" / "files" / "bolt.step").is_file()
    assert [p["name"] for p in packs.installed(repo)] == ["test-pack"]

    r = packs.install(src, repo, HashingEmbedder(DIM), data, log=lambda _: None)       # again: nothing to do
    assert (r["added"], r["updated"], r["unchanged"]) == (0, 0, 2)

    rows = [json.loads(x) for x in (src / "parts.jsonl").read_text().splitlines()]
    rows[0]["name"] = "Socket head bolt M8x30 ISO 4762 (corrected)"
    newer = make_pack(tmp_path / "src2", parts=rows, version="2026-12-01")
    r = packs.install(newer, repo, HashingEmbedder(DIM), data, log=lambda _: None)
    assert (r["added"], r["updated"], r["unchanged"]) == (0, 1, 1)
    assert repo.get_part("tp-bolt", None).name.endswith("(corrected)")

    out = packs.remove("test-pack", repo, data, log=lambda _: None)
    assert out["removed"] == 2 and repo.get_part("tp-bolt", None) is None and packs.installed(repo) == []
    assert not (data / "packs" / "test-pack").exists()


def test_a_file_already_in_the_library_is_not_added_twice(tmp_path, lib):
    repo, data = lib
    packs.install(make_pack(tmp_path / "a"), repo, HashingEmbedder(DIM), data, log=lambda _: None)
    rows = [json.loads(x) for x in (tmp_path / "a" / "test-pack" / "parts.jsonl").read_text().splitlines()]
    rows[0]["id"] = "other-id-same-file"
    r = packs.install(make_pack(tmp_path / "b", name="other-pack", parts=rows[:1]), repo, HashingEmbedder(DIM), data,
                      log=lambda _: None)
    assert r["duplicates"] == 1 and r["added"] == 0


def test_zip_and_unsafe_packs(tmp_path, lib):
    repo, data = lib
    src = make_pack(tmp_path / "src")
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as f:
        for p in src.rglob("*"):
            if p.is_file():
                f.write(p, p.relative_to(src).as_posix())
    assert packs.install(z, repo, HashingEmbedder(DIM), data, log=lambda _: None)["added"] == 2

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(packs.PackError):
        packs.install(bad, repo, HashingEmbedder(DIM), data, log=lambda _: None)

    rows = [{"id": "x", "name": "x", "description": "x", "category_path": "fasteners/bolt/hex-bolt",
             "files": [{"format": "step", "path": "https://evil.example.com/x.step", "is_primary": True}]}]
    r = packs.install(make_pack(tmp_path / "c", name="evil-pack", parts=rows), repo, HashingEmbedder(DIM), data,
                      log=lambda _: None)
    assert r["failed"] == 1 and repo.get_part("x", None) is None


def test_remote_files_are_fetched_once_and_only_from_open_libraries(tmp_path):
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(b"ISO-10303-21; resistor")

    p = remote.fetch(URL, tmp_path, opener=opener)
    assert p.read_bytes().startswith(b"ISO-10303-21") and p.name == "R_0805_2012Metric.step"
    assert remote.fetch(URL, tmp_path, opener=opener) == p and len(calls) == 1
    for bad in ("http://raw.githubusercontent.com/x/y.step", "https://example.com/x.step", "file:///etc/passwd"):
        with pytest.raises(remote.RemoteFileError):
            remote.fetch(bad, tmp_path, opener=opener)


def _client(tmp_path, **env):
    s = dataclasses.replace(get_settings(), db_path=tmp_path / "lib.db", embedding_dim=DIM,
                            data_dir=tmp_path / "data", anthropic_api_key=None, **env)
    conn = connect(s.db_path, DIM, check_same_thread=False)
    return TestClient(create_app(s, conn=conn, embedder=HashingEmbedder(DIM)))


def test_api_install_list_download_and_remove(tmp_path, monkeypatch):
    c = _client(tmp_path)
    src = make_pack(tmp_path / "src")
    job = c.post("/packs/install", json={"path": str(src)}).json()
    for _ in range(100):
        st = c.get(f"/ingest/{job['job_id']}").json()
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done" and st["report"]["added"] == 2
    assert c.get("/packs").json()["installed"][0]["name"] == "test-pack"
    found = c.post("/search", json={"query": "resistor 0805"}).json()["results"]
    assert found and found[0]["id"] == "tp-resistor" and found[0]["license"] == "CC-BY-SA-4.0"

    cached = tmp_path / "R_0805_2012Metric.step"
    cached.write_text("ISO-10303-21; resistor")
    monkeypatch.setattr(remote, "fetch", lambda url, cache_dir: cached)
    r = c.get("/parts/tp-resistor/file")
    assert r.status_code == 200 and r.content.startswith(b"ISO-10303-21")

    assert c.post("/packs/test-pack/remove").json()["removed"] == 2
    assert c.post("/packs/test-pack/remove").status_code == 404


def test_only_the_admin_installs_packs(tmp_path):
    c = _client(tmp_path, api_keys="k-admin=*,k-acme=acme")
    src = make_pack(tmp_path / "src")
    assert c.post("/packs/install", json={"path": str(src)}, headers={"Authorization": "Bearer k-acme"}).status_code == 403
    assert c.post("/packs/test-pack/remove", headers={"Authorization": "Bearer k-acme"}).status_code == 403


def test_command_line_installs_with_the_library_model(tmp_path, monkeypatch):
    """The command line uses the model of the vectors already in the library (not the hashing test embedder)."""
    from partsfinder import config, ingest

    used = []

    class FakeModel(HashingEmbedder):
        def __init__(self, name, dim):
            used.append((name, dim))
            super().__init__(dim)

    monkeypatch.setattr(ingest, "SentenceTransformerEmbedder", FakeModel)
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(tmp_path / "data"))
    db = tmp_path / "lib.db"
    conn = connect(db, get_settings().embedding_dim)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'intfloat/multilingual-e5-small')")
    conn.close()
    src = make_pack(tmp_path / "src")
    assert packs.main(["--db", str(db), "install", str(src)]) == 0
    assert used == [("intfloat/multilingual-e5-small", get_settings().embedding_dim)]
    assert packs.main(["--db", str(db), "list"]) == 0
    assert packs.main(["--db", str(db), "remove", "test-pack"]) == 0
