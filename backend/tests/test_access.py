"""Restricted parts, outside AI and confidential companies (docs/10_COMPANY_LIBRARIES.md).

One library with: a general bolt, a normal bracket of acme, a restricted bracket of acme (group
"nuclear", with a word, a property and files nobody else may learn about), a bracket of acme in group
"aero", and a bracket of company beta. Every route that returns something about parts is asked by:
a key without groups, a key with the group, another company, an admin, and an AI client.
"""
from __future__ import annotations

import dataclasses
import json
import sys

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from partsfinder import api as api_mod
from partsfinder import auth
from partsfinder.access import Scope
from partsfinder.ai import PartFinder
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate, PartFile
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine

DIM = 64
SECRET = ("secret-reactor-bracket", "zirconium", "reactor_rating")       # nothing of this may leak
KEYS = "k-acme=acme, k-nuc=acme:nuclear, k-beta=beta, admin=*"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
IMAGE = {"image_base64": __import__("base64").b64encode(PNG).decode(), "media_type": "image/png"}


@pytest.fixture
def lib(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo, emb = Repository(conn), HashingEmbedder(DIM)
    step = tmp_path / "bracket.step"
    cq.exporters.export(cq.Workplane("XY").box(100, 40, 5), str(step))
    png = tmp_path / "secret.png"
    png.write_bytes(PNG)
    cat = "connections/bracket/angle-bracket"
    rows = [
        dict(id="gen-bolt", name="Hex bolt M8x30", category_path="fasteners/bolt/hex-bolt",
             properties={"thread": "M8", "length_mm": 30}),
        dict(id="acme-bracket", name="Mounting bracket 100", category_path=cat, company_id="acme",
             bbox_mm=(100, 40, 5), volume_mm3=20000, files=[PartFile(format="step", path=str(step), is_primary=True)]),
        dict(id="secret-reactor-bracket", name="Reactor vessel bracket zirconium 100", category_path=cat,
             company_id="acme", access_group="nuclear", bbox_mm=(100, 40, 5), volume_mm3=20000,
             properties={"reactor_rating": 99}, thumbnail_path=str(png),
             files=[PartFile(format="step", path=str(step), is_primary=True)]),
        dict(id="aero-bracket", name="Wing bracket 100", category_path=cat, company_id="acme",
             access_group="aero", bbox_mm=(100, 40, 5)),
        dict(id="beta-bracket", name="Beta bracket 100", category_path=cat, company_id="beta", bbox_mm=(100, 40, 5)),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    yield conn, repo, emb, tmp_path, step
    conn.close()


def client(lib, monkeypatch, keys=KEYS, local_groups=None, with_ai=False):
    conn, repo, emb, tmp_path, _ = lib
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(tmp_path / "data"))
    s = dataclasses.replace(get_settings(), api_keys=keys, local_groups=local_groups)
    finder = calls = None
    if with_ai:
        from test_app_views import fake_client
        fake = fake_client()
        calls = fake.calls
        finder = PartFinder(SearchEngine(repo, emb), repo.taxonomy, "claude-haiku-5-5", client=fake)
    return TestClient(create_app(s, conn=conn, embedder=emb, finder=finder, enable_ai=with_ai)), calls


def h(key=None, ai=False):
    out = {"Authorization": f"Bearer {key}"} if key else {}
    if ai:
        out["X-Partsfinder-AI"] = "1"
    return out


def leaks(text: str) -> bool:
    return any(s in text for s in SECRET)


def everything(c, headers, company="acme", step=None):
    """Every route that tells something about parts, as one text (plus the status codes of direct reads)."""
    q = {"company_id": company} if company else {}
    out = [
        # the questions never contain a secret word themselves (the answer repeats the question)
        c.post("/search", json={"query": "vessel bracket 100", "use_ai": False, "limit": 20, **q}, headers=headers).text,
        c.post("/search", json={"query": "reactor vessel bracket", "use_ai": False, "limit": 20, **q}, headers=headers).text,
        c.post("/search/batch", json={"searches": [{"query": "reactor vessel", "limit": 20}], **q}, headers=headers).text,
        c.get("/parts/acme-bracket/similar", params={**q, "limit": 20}, headers=headers).text,
        c.get("/properties", params=q, headers=headers).text,
        c.get("/quality", params=q, headers=headers).text,
        c.get("/duplicates", params=q, headers=headers).text,
    ]
    if step is not None:
        out.append(c.post("/search/shape", params={**q, "filename": "x.step", "limit": 20}, content=step.read_bytes(),
                          headers={**headers, "Content-Type": "application/octet-stream"}).text)
    direct = {route: c.get(f"/parts/secret-reactor-bracket{route}", params=q, headers=headers).status_code
              for route in ("", "/file", "/thumbnail", "/mesh", "/datasheet", "/similar")}
    fb = c.post("/feedback", json={"part_id": "secret-reactor-bracket", "rating": "up", **q}, headers=headers).status_code
    return "\n".join(out), direct, fb


# ---- who sees the restricted part ----------------------------------------------------------------------
def test_key_without_the_group_learns_nothing(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    text, direct, fb = everything(c, h("k-acme"), step=lib[4])
    assert not leaks(text), text[:500]
    assert "acme-bracket" in text                                  # the normal company part is there
    assert set(direct.values()) == {404} and fb == 404


def test_key_with_the_group_sees_it(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    r = c.post("/search", json={"query": "reactor vessel bracket", "use_ai": False, "limit": 20}, headers=h("k-nuc")).json()
    found = {x["id"]: x for x in r["results"]}
    assert found["secret-reactor-bracket"]["access_group"] == "nuclear"
    assert "aero-bracket" not in found                              # another group stays hidden
    for route in ("", "/file", "/thumbnail", "/mesh", "/datasheet"):
        assert c.get(f"/parts/secret-reactor-bracket{route}", headers=h("k-nuc")).status_code == 200, route


def test_other_company_and_general_learn_nothing(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    for headers, company in ((h("k-beta"), None), (h("admin"), None)):
        text, direct, fb = everything(c, headers, company=company)
        assert not leaks(text) and set(direct.values()) == {404} and fb == 404
    assert c.post("/search", json={"query": "bracket", "company_id": "acme"}, headers=h("k-beta")).status_code == 403


def test_admin_sees_everything_of_the_company(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    r = c.post("/search", json={"query": "bracket 100", "company_id": "acme", "use_ai": False, "limit": 20},
               headers=h("admin")).json()
    assert {"secret-reactor-bracket", "aero-bracket"} <= {x["id"] for x in r["results"]}
    companies = {x["id"]: x for x in c.get("/companies", headers=h("admin")).json()}
    assert companies["acme"]["restricted_parts"] == 2 and companies["acme"]["confidential"] is False


def test_an_ai_client_never_sees_it_even_with_the_group(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    for key in ("k-nuc", "admin"):
        text, direct, fb = everything(c, h(key, ai=True))
        assert not leaks(text) and set(direct.values()) == {404}, key


def test_remembered_answers_are_kept_per_right(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    body = {"query": "reactor vessel bracket", "use_ai": False, "limit": 20}
    assert not leaks(c.post("/search", json=body, headers=h("k-acme")).text)
    second = c.post("/search", json=body, headers=h("k-nuc")).json()
    assert second["cached"] is False and "secret-reactor-bracket" in {x["id"] for x in second["results"]}
    assert not leaks(c.post("/search", json=body, headers=h("k-nuc", ai=True)).text)


# ---- without keys (one pc) -------------------------------------------------------------------------------
def test_without_keys_restricted_is_hidden_unless_listed(lib, monkeypatch):
    c, _ = client(lib, monkeypatch, keys=None)
    text, direct, _ = everything(c, {})
    assert not leaks(text) and set(direct.values()) == {404}
    c, _ = client(lib, monkeypatch, keys=None, local_groups="nuclear")
    assert c.get("/parts/secret-reactor-bracket", params={"company_id": "acme"}).status_code == 200
    assert c.get("/parts/aero-bracket", params={"company_id": "acme"}).status_code == 404
    assert c.get("/parts/secret-reactor-bracket", params={"company_id": "acme"}, headers=h(ai=True)).status_code == 404


def test_network_address_without_keys_is_refused(monkeypatch):
    monkeypatch.delenv("PARTSFINDER_API_KEYS", raising=False)
    monkeypatch.setattr(sys, "argv", ["api", "--host", "0.0.0.0"])
    assert api_mod.main() == 2
    assert api_mod.is_local_host("127.0.0.1") and not api_mod.is_local_host("192.168.1.10")


# ---- outside AI: Claude never gets restricted or confidential data ---------------------------------------
def test_claude_judges_only_what_an_ai_may_see(lib, monkeypatch):
    c, calls = client(lib, monkeypatch, with_ai=True)
    r = c.post("/search", json={"query": "bracket 100", "limit": 20}, headers=h("k-acme")).json()
    assert r["ai_used"] is True and calls
    r = c.post("/search", json={"query": "reactor vessel bracket", "limit": 20}, headers=h("k-nuc")).json()
    assert r["ai_used"] is False and "AI is off" in r["message"]   # this caller could see more: code only
    assert "secret-reactor-bracket" in {x["id"] for x in r["results"]}
    assert not any(leaks(json.dumps(content)) for _tool, content in calls)


def test_confidential_company_never_reaches_an_ai(lib, monkeypatch):
    c, calls = client(lib, monkeypatch, with_ai=True)
    assert c.post("/companies/acme/settings", json={"confidential": True}, headers=h("k-acme")).status_code == 403
    assert c.post("/companies/acme/settings", json={"confidential": True}, headers=h("admin")).json()["confidential"]
    r = c.post("/search", json={"query": "mounting bracket 100", "limit": 20}, headers=h("k-acme")).json()
    assert r["ai_used"] is False and "acme-bracket" in {x["id"] for x in r["results"]}
    assert not any("acme-bracket" in json.dumps(content) for _tool, content in calls)
    # an AI client sees none of acme's parts, not even the normal ones
    ai = c.post("/search", json={"query": "mounting bracket 100", "use_ai": False, "limit": 20}, headers=h("k-acme", ai=True)).text
    assert "acme-bracket" not in ai and not leaks(ai)
    assert c.post("/search/image", json=IMAGE, headers=h("k-acme")).status_code == 403


def test_keys_with_groups_get_no_photo_search(lib, monkeypatch):
    c, _ = client(lib, monkeypatch, with_ai=True)
    assert c.post("/search/image", json=IMAGE, headers=h("k-nuc")).status_code == 403


# ---- rules in the data -------------------------------------------------------------------------------------
def test_groups_only_in_company_libraries(lib):
    repo = lib[1]
    with pytest.raises(ValueError, match="general library"):
        repo.add_part(PartCreate(name="x", category_path="fasteners/bolt/hex-bolt", access_group="nuclear"))
    with pytest.raises(ValueError, match="Invalid group"):
        repo.add_part(PartCreate(name="x", category_path="fasteners/bolt/hex-bolt", company_id="acme", access_group="Nu clear"))


def test_scope_rules():
    assert Scope("acme", all_groups=True, for_ai=True).all_groups is False      # an AI never sees more
    assert Scope("acme", ["nuclear"]) == "acme"                                  # still the company id
    with pytest.raises(ValueError):
        auth.parse_keys("k=*:nuclear")
    with pytest.raises(ValueError):
        auth.parse_keys("k=acme:Bad Group")
    assert auth.split_scope("acme:nuclear:aero") == ("acme", frozenset({"nuclear", "aero"}))
    assert auth.fingerprint("secret").startswith("key:") and "secret" not in auth.fingerprint("secret")


def test_old_database_gets_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = connect(path, embedding_dim=DIM)
    with conn:
        conn.execute("DROP INDEX idx_parts_group")
        conn.execute("ALTER TABLE parts DROP COLUMN access_group")
        conn.execute("ALTER TABLE companies DROP COLUMN confidential")
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    conn.close()
    conn = connect(path, embedding_dim=DIM)
    assert "access_group" in {r[1] for r in conn.execute("PRAGMA table_info(parts)")}
    assert "confidential" in {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    conn.close()


# ---- audit log ------------------------------------------------------------------------------------------------
def test_audit_log_records_who_did_what_without_keys_or_names(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    nuc = h("k-nuc")
    first = c.post("/search", json={"query": "reactor vessel bracket", "use_ai": False}, headers=nuc).json()
    again = c.post("/search", json={"query": "reactor vessel bracket", "use_ai": False}, headers=nuc).json()
    assert first["cached"] is False and again["cached"] is True              # logging does not clear the memory
    for route in ("/file", "/mesh", "/datasheet"):
        assert c.get(f"/parts/secret-reactor-bracket{route}", headers=nuc).status_code == 200
    assert c.get("/audit", params={"company_id": "acme"}, headers=nuc).status_code == 403   # admin only
    log = c.get("/audit", params={"company_id": "acme"}, headers=h("admin")).json()
    actions = [(e["action"], e["target"]) for e in log]
    assert actions[:5] == [("datasheet", "secret-reactor-bracket"), ("mesh", "secret-reactor-bracket"),
                           ("download", "secret-reactor-bracket"), ("search", ""), ("search", "")]
    assert log[3]["detail"] == "reactor vessel bracket"
    assert {e["actor"] for e in log} == {auth.fingerprint("k-nuc")}
    text = json.dumps(log)
    assert "k-nuc" not in text and "zirconium" not in text                   # never the key, never a part name
    downloads = c.get("/audit", params={"company_id": "acme", "action": "download"}, headers=h("admin")).json()
    assert [e["detail"] for e in downloads] == ["step"]


def test_audit_log_is_kept_per_company(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    c.post("/search", json={"query": "bracket", "use_ai": False}, headers=h("k-beta"))
    c.post("/search", json={"query": "bracket", "use_ai": False}, headers=h("k-acme"))
    beta = c.get("/audit", params={"company_id": "beta"}, headers=h("admin")).json()
    assert len(beta) == 1 and beta[0]["actor"] == auth.fingerprint("k-beta")


def test_feedback_on_a_restricted_part_stays_with_the_group(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    assert c.post("/feedback", json={"part_id": "secret-reactor-bracket", "rating": "up", "query": "vessel"},
                  headers=h("k-nuc")).status_code == 200
    assert not leaks(c.get("/feedback", headers=h("k-acme")).text)
    assert "secret-reactor-bracket" in c.get("/feedback", headers=h("k-nuc")).text


# ---- signing in from the app (E1) -------------------------------------------------------------------------
def test_me_tells_the_app_who_the_key_belongs_to_without_the_key(lib, monkeypatch):
    c, _ = client(lib, monkeypatch)
    assert c.get("/health").json()["keys_required"] is True
    assert c.get("/me").status_code == 401
    assert c.get("/me", headers=h("wrong")).status_code == 401
    me = c.get("/me", headers=h("k-nuc")).json()
    assert me == {"keys_required": True, "role": "company", "company_id": "acme", "groups": ["nuclear"],
                  "key": auth.fingerprint("k-nuc"), "username": None}
    assert "k-nuc" not in json.dumps(me).replace(auth.fingerprint("k-nuc"), "")
    assert c.get("/me", headers=h("admin")).json()["role"] == "admin"
    # the previews the app shows as <img> need the key too (the app adds it for every request to the API)
    assert c.get("/parts/acme-bracket/thumbnail", params={"company_id": "acme"}).status_code == 401

    c, _ = client(lib, monkeypatch, keys=None, local_groups="nuclear")
    assert c.get("/health").json()["keys_required"] is False
    assert c.get("/me").json() == {"keys_required": False, "role": "local", "company_id": None,
                                   "groups": ["nuclear"], "key": None, "username": None}
