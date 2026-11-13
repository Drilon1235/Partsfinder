"""Accounts and a company's own library (docs/10_COMPANY_LIBRARIES.md, 10 Nov 2026).

People sign in with a name and a password. The first admin account can only be made on the pc that runs
the library. Without signing in, a server with accounts shows only the general library. A company account
sees and changes only its own library: it uploads a folder from its own pc, updates it and removes it.
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from partsfinder.api import create_app, upload_path
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.repository import Repository

DIM = 32
PASSWORD = "correct horse 1"


def step_bytes(tmp: Path, size) -> bytes:
    p = tmp / f"box-{'x'.join(map(str, size))}.step"
    cq.exporters.export(cq.Workplane("XY").box(*size), str(p))
    return p.read_bytes()


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(tmp_path / "data"))
    db = tmp_path / "lib.db"
    conn = connect(db, embedding_dim=DIM, check_same_thread=False)
    repo, emb = Repository(conn), HashingEmbedder(DIM)
    for d in [dict(id="gen-bolt", name="Hex bolt M8x30", category_path="fasteners/bolt/hex-bolt"),
              dict(id="beta-bracket", name="Beta bracket 100", category_path="connections/bracket/angle-bracket",
                   company_id="beta")]:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    s = dataclasses.replace(get_settings(), api_keys=None, local_groups=None, data_dir=tmp_path / "data")
    app = create_app(s, conn=conn, embedder=emb, finder=None, enable_ai=False)
    yield app, conn, tmp_path
    conn.close()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def admin(c) -> str:
    r = c.post("/setup", json={"username": "owner_test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def company_user(c, token, name="anna", company="acme", groups=()):
    r = c.post("/users", json={"username": name, "password": PASSWORD, "company_id": company, "groups": list(groups)},
               headers=bearer(token))
    assert r.status_code == 200, r.text
    return c.post("/login", json={"username": name, "password": PASSWORD}).json()["token"]


# ---- the first account ---------------------------------------------------------------------------------
def test_without_accounts_nothing_changes_and_the_first_admin_is_made_on_this_pc(lib):
    app, conn, _ = lib
    c = TestClient(app)
    h = c.get("/health").json()
    assert h["setup_needed"] is True and h["accounts"] is False
    assert c.get("/me").json()["role"] == "local"
    far = TestClient(app, client=("10.0.0.7", 50000))
    assert far.post("/setup", json={"username": "x-admin", "password": PASSWORD}).status_code == 403
    token = admin(c)
    assert c.post("/setup", json={"username": "other", "password": PASSWORD}).status_code == 409
    me = c.get("/me", headers=bearer(token)).json()
    assert me["role"] == "admin" and me["username"] == "owner_test"
    h = c.get("/health").json()
    assert h["accounts"] is True and h["setup_needed"] is False
    # only a hash is stored; never the password or the token
    dump = "\n".join(conn.iterdump())
    assert PASSWORD not in dump and token not in dump and "scrypt$" in dump


def test_without_signing_in_only_the_general_library(lib):
    c = TestClient(lib[0])
    admin(c)
    assert c.get("/me").json()["role"] == "public"
    r = c.post("/search", json={"query": "hex bolt M8x30", "use_ai": False})
    assert r.status_code == 200 and r.json()["results"][0]["id"] == "gen-bolt"
    assert c.post("/search", json={"query": "bracket", "company_id": "beta", "use_ai": False}).status_code == 403
    for method, route in (("get", "/companies"), ("get", "/users"), ("get", "/library"), ("get", "/audit")):
        assert getattr(c, method)(route).status_code in (401, 403), route
    assert c.post("/ingest", json={"folder": "/"}).status_code == 403
    # a token that is not (or no longer) valid is refused, not quietly treated as "not signed in"
    assert c.post("/search", json={"query": "bolt", "use_ai": False}, headers=bearer("made-up")).status_code == 401


# ---- signing in -----------------------------------------------------------------------------------------
def test_a_company_account_sees_its_own_company_only(lib):
    c = TestClient(lib[0])
    token = company_user(c, admin(c))
    me = c.get("/me", headers=bearer(token)).json()
    assert me == {"keys_required": False, "username": "anna", "role": "company", "company_id": "acme",
                  "groups": [], "key": None}
    assert c.post("/search", json={"query": "bracket", "use_ai": False}, headers=bearer(token)).status_code == 200
    r = c.post("/search", json={"query": "bracket", "company_id": "beta", "use_ai": False}, headers=bearer(token))
    assert r.status_code == 403
    assert c.get("/users", headers=bearer(token)).status_code == 403
    assert c.get("/parts/beta-bracket", headers=bearer(token)).status_code == 404


def test_wrong_passwords_are_slowed_down_and_say_nothing_about_the_name(lib):
    c = TestClient(lib[0])
    company_user(c, admin(c))
    wrong = c.post("/login", json={"username": "anna", "password": "wrong-password"})
    unknown = c.post("/login", json={"username": "nobody", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    for _ in range(4):
        c.post("/login", json={"username": "anna", "password": "wrong-password"})
    r = c.post("/login", json={"username": "anna", "password": PASSWORD})
    assert r.status_code == 429                          # even the right password waits now


def test_admin_manages_people_and_a_change_signs_them_out(lib):
    app, conn, _ = lib
    c = TestClient(app)
    adm = admin(c)
    token = company_user(c, adm, groups=["nuclear"])
    users = c.get("/users", headers=bearer(adm)).json()
    assert {u["username"] for u in users} == {"owner_test", "anna"} and "password_hash" not in str(users)
    assert c.patch("/users/anna", json={"password": "a new one 22"}, headers=bearer(adm)).status_code == 200
    assert c.get("/me", headers=bearer(token)).status_code == 401           # signed out everywhere
    token = c.post("/login", json={"username": "anna", "password": "a new one 22"}).json()["token"]
    assert c.patch("/users/anna", json={"disabled": True}, headers=bearer(adm)).status_code == 200
    assert c.get("/me", headers=bearer(token)).status_code == 401
    assert c.post("/login", json={"username": "anna", "password": "a new one 22"}).status_code == 401
    assert c.delete("/users/owner_test", headers=bearer(adm)).status_code == 400       # the last admin stays
    assert c.post("/users", json={"username": "bad name!", "password": PASSWORD, "company_id": "acme"},
                  headers=bearer(adm)).status_code == 400
    assert c.post("/users", json={"username": "shorty", "password": "short", "company_id": "acme"},
                  headers=bearer(adm)).status_code == 400
    assert c.delete("/users/anna", headers=bearer(adm)).status_code == 200
    actors = {r["actor"] for r in c.get("/audit", headers=bearer(adm), params={"company_id": "acme"}).json()}
    assert "user:owner_test" in actors                                       # the log tells people apart
    assert c.post("/logout", headers=bearer(adm)).status_code == 200
    assert c.get("/users", headers=bearer(adm)).status_code == 401


# ---- a company's own library ----------------------------------------------------------------------------
def upload(c, token, name, files, company=None, access=None):
    q = {"company_id": company} if company else {}
    start = c.post(f"/uploads/{name}/start", params=q, headers=bearer(token))
    assert start.status_code == 200, start.text
    uid = start.json()["upload_id"]
    for path, data in files.items():
        r = c.put(f"/uploads/{name}/files", params={**q, "upload_id": uid, "path": path}, content=data,
                  headers=bearer(token))
        assert r.status_code == 200, (path, r.text)
    extra = {"access": access} if access else {}
    r = c.post(f"/uploads/{name}/finish", json={"upload_id": uid, "use_ai": False, **q, **extra}, headers=bearer(token))
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    for _ in range(200):
        st = c.get(f"/ingest/{job}", params=q, headers=bearer(token)).json()
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError(f"import did not finish: {st}")


def test_a_company_uploads_updates_and_removes_its_own_folder(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    anna = company_user(c, adm)
    nuc = company_user(c, adm, name="bert", groups=["nuclear"])
    files = {"brackets/wall bracket.step": step_bytes(tmp, (100, 40, 5)),
             "brackets/wall bracket.json": b'{"name": "Wall bracket acme 100", "category_path": "connections/bracket/wall-bracket"}',
             "reactor/.partsfinderaccess": b"nuclear\n",
             "reactor/vessel plate.step": step_bytes(tmp, (300, 300, 20))}
    st = upload(c, anna, "Main CAD", files)
    assert st["status"] == "done", st
    lib_ = c.get("/library", headers=bearer(anna)).json()
    assert lib_["parts"] == 2 and lib_["restricted_parts"] == 1
    assert [(f["name"], f["parts"]) for f in lib_["folders"]] == [("Main CAD", 2)]
    assert {t["path"]: t["access"] for t in lib_["folders"][0]["tree"]} == {"": "company", "brackets": "company",
                                                                           "reactor": "nuclear"}
    def found(tok, q):
        r = c.post("/search", json={"query": q, "use_ai": False, "limit": 20}, headers=bearer(tok))
        return {x["name"].lower() for x in r.json()["results"]}
    assert "wall bracket acme 100" in found(anna, "wall bracket")
    assert not any("vessel" in n for n in found(anna, "vessel plate"))       # restricted: only group nuclear
    assert any("vessel" in n for n in found(nuc, "vessel plate"))
    assert not any("acme" in n.lower() for n in {r["name"] for r in c.post(
        "/search", json={"query": "wall bracket acme", "use_ai": False}).json()["results"]})   # not public
    # the same folder again, without the vessel plate: it leaves the library completely
    st = upload(c, anna, "Main CAD", {k: v for k, v in files.items() if "reactor" not in k})
    assert st["status"] == "done" and st["report"]["removed"], st
    assert c.get("/library", headers=bearer(anna)).json()["parts"] == 1
    # another company's library: no
    assert c.post("/uploads/x/start", params={"company_id": "beta"}, headers=bearer(anna)).status_code == 403
    assert c.get("/library", params={"company_id": "beta"}, headers=bearer(anna)).status_code == 403
    # the admin names the company
    assert c.get("/library", params={"company_id": "acme"}, headers=bearer(adm)).json()["parts"] == 1
    r = c.delete("/uploads/Main CAD", headers=bearer(anna))
    assert r.status_code == 200 and r.json()["total"] == 1
    assert c.get("/library", headers=bearer(anna)).json()["parts"] == 0
    assert not (tmp / "data" / "companies" / "acme" / "uploads" / "Main CAD").exists()


def test_an_upload_accepts_only_cad_files_inside_the_folder(lib):
    app, _, tmp = lib
    c = TestClient(app)
    anna = company_user(c, admin(c))
    uid = c.post("/uploads/Parts/start", headers=bearer(anna)).json()["upload_id"]
    for bad in ("../escape.step", "/etc/x.step", "C:/x.step", "a/../../x.step", ".ssh/key.step", "tool.exe",
                "notes.txt", "a/ b.step", ".hidden.step"):
        r = c.put("/uploads/Parts/files", params={"upload_id": uid, "path": bad}, content=b"x", headers=bearer(anna))
        assert r.status_code in (400, 422), bad
    assert not list((tmp / "data").rglob("escape.step")) and not list(tmp.rglob("x.step"))
    r = c.post("/uploads/Parts/finish", json={"upload_id": uid}, headers=bearer(anna))
    assert r.status_code == 400 and "no CAD file" in r.json()["detail"]
    assert c.post("/uploads/..%2F..%2Fx/start", headers=bearer(anna)).status_code in (400, 404)
    assert upload_path("sub/part.STEP").as_posix() == "sub/part.STEP"
    assert upload_path("sub\\\\.partsfinderaccess".replace("\\\\\\\\", "\\\\")).name == ".partsfinderaccess"


def test_an_ai_client_or_someone_not_signed_in_cannot_change_a_library(lib):
    c = TestClient(lib[0])
    anna = company_user(c, admin(c))
    assert c.post("/uploads/x/start").status_code == 401
    assert c.post("/uploads/x/start", headers={**bearer(anna), "X-Partsfinder-AI": "1"}).status_code == 403


def test_the_admin_adds_a_company_by_name(lib):
    c = TestClient(lib[0])
    adm = admin(c)
    r = c.post("/companies", json={"name": "Janssen  Engineering B.V."}, headers=bearer(adm))
    assert r.status_code == 200 and r.json()["id"] == "janssen-engineering-b-v" and r.json()["name"] == "Janssen Engineering B.V."
    assert c.post("/companies", json={"name": "Janssen Engineering B.V."}, headers=bearer(adm)).status_code == 409
    assert c.post("/companies", json={"name": "!!!"}, headers=bearer(adm)).status_code == 400
    listed = {x["id"]: x for x in c.get("/companies", headers=bearer(adm)).json()}
    assert listed["janssen-engineering-b-v"]["people"] == 0
    company_user(c, adm, company="janssen-engineering-b-v")
    assert {x["id"]: x for x in c.get("/companies", headers=bearer(adm)).json()}["janssen-engineering-b-v"]["people"] == 1
    anna = c.post("/login", json={"username": "anna", "password": PASSWORD}).json()["token"]
    assert c.post("/companies", json={"name": "Other"}, headers=bearer(anna)).status_code == 403


# ---- restricted folders set in the app, and removing a company -----------------------------------------
def wait_job(c, token, job, q=None):
    for _ in range(200):
        st = c.get(f"/ingest/{job}", params=q or {}, headers=bearer(token)).json()
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError(st)


def test_the_admin_restricts_an_uploaded_folder_in_the_app_and_it_survives_an_update(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    anna = company_user(c, adm)
    bert = company_user(c, adm, name="bert", groups=["nuclear"])
    files = {"brackets/wall bracket.step": step_bytes(tmp, (100, 40, 5)),
             "reactor/vessel plate.step": step_bytes(tmp, (300, 300, 20)),
             "reactor/inner/pump base.step": step_bytes(tmp, (50, 50, 80))}
    assert upload(c, anna, "Main CAD", files)["status"] == "done"
    tree = c.get("/library", headers=bearer(anna)).json()["folders"][0]["tree"]
    assert [(t["path"], t["access"]) for t in tree] == [("", "company"), ("brackets", "company"), ("reactor", "company"),
                                                       ("reactor/inner", "company")]
    q = {"company_id": "acme"}
    # a company account cannot change it; the admin can
    assert c.put("/uploads/Main CAD/access", params=q, json={"path": "reactor", "access": "nuclear"},
                 headers=bearer(anna)).status_code == 403
    r = c.put("/uploads/Main CAD/access", params=q, json={"path": "reactor", "access": "nuclear"}, headers=bearer(adm))
    assert r.status_code == 200 and wait_job(c, adm, r.json()["job_id"])["status"] == "done"
    def names(tok):
        out = set()
        for q_ in ("vessel plate", "pump base"):
            out |= {x["name"].lower() for x in c.post("/search", json={"query": q_, "use_ai": False, "limit": 20},
                                                       headers=bearer(tok)).json()["results"]}
        return out
    assert not any("vessel" in n or "pump" in n for n in names(anna))
    assert any("vessel" in n for n in names(bert)) and any("pump" in n for n in names(bert))
    lib_ = c.get("/library", params=q, headers=bearer(adm)).json()
    assert lib_["restricted_parts"] == 2 and "nuclear" in lib_["groups"]
    assert {t["path"]: t["access"] for t in lib_["folders"][0]["tree"]}["reactor/inner"] == "nuclear"
    # anna sends the folder again from her pc (without any .partsfinderaccess): the setting stays
    assert upload(c, anna, "Main CAD", files)["status"] == "done"
    assert c.get("/library", params=q, headers=bearer(adm)).json()["restricted_parts"] == 2
    # back to everyone; a bad path or group is refused
    for bad in ({"path": "../x", "access": "company"}, {"path": "reactor", "access": "Not A Group"}):
        assert c.put("/uploads/Main CAD/access", params=q, json=bad, headers=bearer(adm)).status_code == 400
    assert c.put("/uploads/Main CAD/access", params=q, json={"path": "nope", "access": "company"},
                 headers=bearer(adm)).status_code == 404
    r = c.put("/uploads/Main CAD/access", params=q, json={"path": "reactor", "access": "inherit"}, headers=bearer(adm))
    wait_job(c, adm, r.json()["job_id"])
    assert c.get("/library", params=q, headers=bearer(adm)).json()["restricted_parts"] == 0
    groups = {x["id"]: x["groups"] for x in c.get("/companies", headers=bearer(adm)).json()}
    assert groups["acme"] == ["nuclear"]                  # still given to bert


def test_company_people_choose_who_sees_a_folder_within_their_own_groups(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    anna = company_user(c, adm)
    bert = company_user(c, adm, name="bert", groups=["nuclear"])
    files = {"plates/vessel plate.step": step_bytes(tmp, (300, 300, 20)),
             "brackets/wall bracket.step": step_bytes(tmp, (100, 40, 5))}

    def finds(tok, q_):
        return any(q_ in x["name"].lower() for x in c.post("/search", json={"query": q_, "use_ai": False, "limit": 20},
                                                           headers=bearer(tok)).json()["results"])
    assert c.get("/library", headers=bearer(bert)).json()["my_groups"] == ["nuclear"]
    assert c.get("/library", headers=bearer(anna)).json()["my_groups"] == []
    assert c.get("/library", params={"company_id": "acme"}, headers=bearer(adm)).json()["my_groups"] is None
    # bert uploads straight into the nuclear section
    assert upload(c, bert, "Reactor", files, access="nuclear")["status"] == "done"
    assert finds(bert, "vessel plate") and not finds(anna, "vessel plate")
    tree = c.get("/library", headers=bearer(bert)).json()["folders"][0]["tree"]
    assert {t["path"]: t["access"] for t in tree} == {"": "nuclear", "brackets": "nuclear", "plates": "nuclear"}
    # never a group he does not have, never 'inherit' for the whole upload
    put = lambda tok, path, access: c.put("/uploads/Reactor/access", json={"path": path, "access": access},
                                          headers=bearer(tok))
    assert put(bert, "plates", "aero").status_code == 403
    assert put(bert, "plates", "nuclear, aero").status_code == 403
    start = c.post("/uploads/x/start", headers=bearer(bert)).json()
    c.put("/uploads/x/files", params={"upload_id": start["upload_id"], "path": "a.step"}, content=files["plates/vessel plate.step"],
          headers=bearer(bert))
    assert c.post("/uploads/x/finish", json={"upload_id": start["upload_id"], "access": "aero"},
                  headers=bearer(bert)).status_code == 403
    assert c.post("/uploads/x/finish", json={"upload_id": start["upload_id"], "access": "inherit"},
                  headers=bearer(bert)).status_code == 400
    # anna cannot open a folder she cannot see
    assert put(anna, "", "company").status_code == 403
    # bert opens the brackets to the whole company
    r = put(bert, "brackets", "company")
    assert r.status_code == 200 and wait_job(c, bert, r.json()["job_id"])["status"] == "done"
    assert finds(anna, "wall bracket") and not finds(anna, "vessel plate")
    # a folder the administrator closed to a group bert does not have stays as it is
    r = c.put("/uploads/Reactor/access", params={"company_id": "acme"}, json={"path": "plates", "access": "aero"},
              headers=bearer(adm))
    wait_job(c, adm, r.json()["job_id"])
    assert put(bert, "plates", "nuclear").status_code == 403 and put(bert, "plates", "inherit").status_code == 403
    assert not finds(bert, "vessel plate")
    # an update that opens the whole folder: the subfolder the administrator closed stays closed
    assert upload(c, bert, "Reactor", files, access="company")["status"] == "done"
    assert finds(anna, "wall bracket") and not finds(anna, "vessel plate")       # plates stays aero


def test_the_admin_removes_a_company_completely(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    anna = company_user(c, adm)
    assert upload(c, anna, "Main CAD", {"a.step": step_bytes(tmp, (10, 20, 30))})["status"] == "done"
    assert c.delete("/companies/acme", headers=bearer(anna)).status_code == 403
    r = c.delete("/companies/acme", headers=bearer(adm))
    assert r.status_code == 200 and r.json() == {"removed_parts": 1, "removed_accounts": 1}
    assert c.get("/me", headers=bearer(anna)).status_code == 401              # her account went with it
    assert conn.execute("SELECT count(*) FROM parts WHERE company_id = 'acme'").fetchone()[0] == 0
    assert "acme" not in {x["id"] for x in c.get("/companies", headers=bearer(adm)).json()}
    assert not (tmp / "data" / "companies" / "acme" / "uploads").exists()
    assert c.delete("/companies/acme", headers=bearer(adm)).status_code == 404
    assert c.get("/parts/beta-bracket", params={"company_id": "beta"}, headers=bearer(adm)).status_code == 200


def test_a_folder_for_several_groups_and_searching_chosen_folders(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    anna = company_user(c, adm)
    aero = company_user(c, adm, name="erik", groups=["aero"])
    nuc = company_user(c, adm, name="bert", groups=["nuclear"])
    files = {"wall bracket.step": step_bytes(tmp, (100, 40, 5)),
             "secret/vessel plate.step": step_bytes(tmp, (300, 300, 20))}
    assert upload(c, anna, "Main CAD", files)["status"] == "done"
    assert upload(c, anna, "Old parts", {"old bracket.step": step_bytes(tmp, (90, 40, 5))})["status"] == "done"
    q = {"company_id": "acme"}
    r = c.put("/uploads/Main CAD/access", params=q, json={"path": "secret", "access": "nuclear, aero"}, headers=bearer(adm))
    assert r.status_code == 200 and wait_job(c, adm, r.json()["job_id"])["status"] == "done"
    seen = lambda tok, query, **kw: {x["name"].lower() for x in c.post(
        "/search", json={"query": query, "use_ai": False, "limit": 20, **kw}, headers=bearer(tok)).json()["results"]}
    assert any("vessel" in n for n in seen(aero, "vessel plate")) and any("vessel" in n for n in seen(nuc, "vessel plate"))
    assert not any("vessel" in n for n in seen(anna, "vessel plate"))
    lib_ = c.get("/library", headers=bearer(nuc)).json()
    assert lib_["coverage"]["dimensions"] == 100            # restricted parts count for whoever may see them
    main = next(f for f in lib_["folders"] if f["name"] == "Main CAD")
    assert {t["path"]: t["access"] for t in main["tree"]}["secret"] == "aero,nuclear"
    # the folder picker: only "Old parts", no general library
    only_old = seen(anna, "bracket", within={"general": False, "other": False, "folders": ["Old parts"]})
    assert only_old and all("old" in n for n in only_old)
    everything = seen(anna, "bracket")
    assert any("wall" in n for n in everything) and any("old" in n for n in everything)
    general_only = seen(anna, "bracket", within={"general": True, "other": False, "folders": []})
    assert not any("wall" in n or "old" in n for n in general_only)
    assert seen(anna, "bracket", within={"general": False, "other": False, "folders": []}) == set()


def test_a_removed_account_or_old_password_leaves_no_trace_in_the_database_files(lib):
    app, conn, tmp = lib
    c = TestClient(app)
    adm = admin(c)
    company_user(c, adm, name="oops")
    old = conn.execute("SELECT password_hash FROM users WHERE username = 'oops'").fetchone()[0]
    salt_and_hash = old.split("$", 4)[4].encode()
    assert c.patch("/users/oops", json={"password": "another one 2"}, headers=bearer(adm)).status_code == 200
    newer = conn.execute("SELECT password_hash FROM users WHERE username = 'oops'").fetchone()[0].split("$", 4)[4].encode()
    assert c.delete("/users/oops", headers=bearer(adm)).status_code == 200

    def raw():
        wal = tmp / "lib.db-wal"
        return (tmp / "lib.db").read_bytes() + (wal.read_bytes() if wal.exists() else b"")
    assert salt_and_hash not in raw() and newer not in raw()     # (the log keeps the name, never a password)


# ---- forgot the administrator password ------------------------------------------------------------------
def test_on_this_pc_the_admin_password_can_be_reset(lib):
    app, conn, _ = lib
    c = TestClient(app)
    old = admin(c)
    company_user(c, old)
    for _ in range(5):                                         # locked out by wrong tries
        c.post("/login", json={"username": "owner_test", "password": "wrong one!"})
    assert c.get("/setup/admins").json() == {"admins": [{"username": "owner_test", "disabled": False}]}
    r = c.post("/setup/reset", json={"username": "owner_test", "password": "a new password 2"})
    assert r.status_code == 200 and r.json()["me"]["role"] == "admin"
    assert c.get("/me", headers=bearer(r.json()["token"])).json()["role"] == "admin"
    assert c.get("/me", headers=bearer(old)).status_code == 401              # the old session is gone
    assert c.post("/login", json={"username": "owner_test", "password": "a new password 2"}).status_code == 200
    assert c.post("/login", json={"username": "owner_test", "password": PASSWORD}).status_code == 401
    assert "a new password 2" not in "\n".join(conn.iterdump())


def test_the_reset_is_only_for_admins_on_this_pc(lib):
    app, _, _ = lib
    c = TestClient(app)
    token = admin(c)
    anna = company_user(c, token)
    assert c.post("/setup/reset", json={"username": "anna", "password": "a new password 2"}).status_code == 404
    assert c.post("/setup/reset", json={"username": "nobody", "password": "a new password 2"}).status_code == 404
    assert c.post("/setup/reset", json={"username": "owner_test", "password": "short"}).status_code == 400
    assert c.post("/setup/reset", json={"username": "owner_test", "password": "a new password 2"},
                  headers=bearer(anna)).status_code == 403                     # a company account
    assert c.get("/setup/admins", headers=bearer(anna)).status_code == 403
    far = TestClient(app, client=("10.0.0.7", 50000))
    assert far.post("/setup/reset", json={"username": "owner_test", "password": "a new password 2"}).status_code == 403
    assert far.get("/setup/admins").status_code == 403
