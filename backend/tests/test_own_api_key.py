"""Bring your own key: the app hands the user's Anthropic key to the API at run time (POST /settings/ai), and a
library from before the rename (orlix_parts.db) keeps working as partsfinder.db."""
from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from partsfinder import config
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder

DIM = 16


def _app(tmp_path, **env):
    env = {"anthropic_api_key": None, "ai_backend": "auto", **env}
    s = dataclasses.replace(get_settings(), db_path=tmp_path / "lib.db", embedding_dim=DIM, **env)
    conn = connect(s.db_path, DIM, check_same_thread=False)
    return TestClient(create_app(s, conn=conn, embedder=HashingEmbedder(DIM)))


def test_without_a_key_the_ai_is_off_and_says_how_to_turn_it_on(tmp_path):
    h = _app(tmp_path).get("/health").json()
    assert h["ai_available"] is False and "Settings" in h["ai_note"]
    assert "ai_backend" not in h and "ai_gate" not in h and "orlix_demo_available" not in h


def test_the_key_is_set_and_cleared_at_run_time(tmp_path):
    c = _app(tmp_path)
    r = c.post("/settings/ai", json={"api_key": "  sk-ant-test-key  "}).json()
    assert r["ai_available"] is True and r["ai_model"]
    h = c.get("/health").json()
    assert h["ai_available"] is True and h["image_search_available"] is True
    assert "sk-ant-test-key" not in c.get("/health").text                    # never echoed back
    r = c.post("/settings/ai", json={"api_key": ""}).json()
    assert r["ai_available"] is False and c.get("/health").json()["ai_available"] is False


def test_only_the_admin_sets_the_key(tmp_path):
    c = _app(tmp_path, api_keys="k-admin=*,k-acme=acme")
    assert c.post("/settings/ai", json={"api_key": "sk"}, headers={"Authorization": "Bearer k-acme"}).status_code == 403
    assert c.post("/settings/ai", json={"api_key": "sk"}).status_code in (401, 403)
    ok = c.post("/settings/ai", json={"api_key": "sk"}, headers={"Authorization": "Bearer k-admin"})
    assert ok.status_code == 200 and ok.json()["ai_available"] is True


def test_the_owner_of_this_pc_sets_the_key_without_signing_in(tmp_path):
    """A library with accounts (made for sharing): on the pc of the search engine the key needs no sign-in."""
    c = _app(tmp_path)
    assert c.post("/setup", json={"username": "drilon", "password": "a-long-password"}).status_code == 200
    assert c.get("/health").json()["accounts"] is True
    r = c.post("/settings/ai", json={"api_key": "sk-ant-test"})          # not signed in, on this pc
    assert r.status_code == 200 and r.json()["ai_available"] is True


def test_ai_off_stays_off_with_a_key(tmp_path):
    c = _app(tmp_path, ai_backend="off")
    assert c.post("/settings/ai", json={"api_key": "sk"}).status_code == 400


def test_old_database_is_renamed_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKEND_DIR", tmp_path)
    (tmp_path / "orlix_parts.db").write_bytes(b"db")
    (tmp_path / "orlix_parts.db-wal").write_bytes(b"wal")
    assert config.default_db_path() == tmp_path / "partsfinder.db"
    assert (tmp_path / "partsfinder.db").read_bytes() == b"db" and (tmp_path / "partsfinder.db-wal").exists()
    assert not (tmp_path / "orlix_parts.db").exists()
    assert config.default_db_path() == tmp_path / "partsfinder.db"          # the second time: nothing to do
