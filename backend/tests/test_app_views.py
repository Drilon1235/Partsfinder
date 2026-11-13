"""Tests for the app views: card summary, 3D mesh, datasheet, search by image, previews of long parts."""
from __future__ import annotations

import base64
import json
import struct
from types import SimpleNamespace

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from partsfinder import preview
from partsfinder.ai import PartFinder
from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate, PartFile
from partsfinder.repository import Repository
from partsfinder.search import SearchEngine

DIM = 128
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def fake_client(seen=None):
    """Fake Claude for every tool the API uses."""
    calls = []

    def create(**kw):
        tool = kw["tools"][0]["name"]
        content = kw["messages"][0]["content"]
        calls.append((tool, content))
        if tool == "search_request":
            data = {"search_text": content.split(": ", 1)[1]}
        elif tool == "judgement":
            ids = [c["id"] for c in json.loads(content)["candidates"]]
            data = {"status": "found", "message": "Found.",
                    "results": [{"id": i, "verdict": "fits", "match_reasons": ["test"]} for i in ids[:2]]}
        elif tool == "identify_part":
            data = seen or {"is_mechanical_part": True, "part_type": "socket head cap screw",
                            "search_query": "socket head bolt M8x30", "markings": ["M8"], "confidence": "high"}
        else:
            raise AssertionError(tool)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=tool, input=data)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20))
    return SimpleNamespace(messages=SimpleNamespace(create=create), calls=calls)


@pytest.fixture
def setup(tmp_path):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    step = tmp_path / "bolt.step"
    cq.exporters.export(cq.Workplane("XY").box(13, 13, 38), str(step))
    rows = [
        dict(id="shcs-m8x30", name="Socket head bolt M8x30 ISO 4762", category_path="fasteners/bolt/socket-head-bolt",
             description="Socket head cap screw M8 x 30 mm, ISO 4762. Also known as: Allen bolt.",
             standards=["ISO 4762"], bbox_mm=(13, 13, 38), material="steel",
             properties={"thread": "M8", "length_mm": 30, "pitch_mm": 1.25, "original_name": "x"},
             files=[PartFile(format="step", path=str(step), is_primary=True)]),
        dict(id="profile-2020", name="T-slot aluminium profile 20x20 slot 6", category_path="profiles/aluminium/system-profile",
             description="T-slot aluminium profile 20x20 slot 6", bbox_mm=(20, 20, 500),
             properties={"profile_size": "20x20", "slot_width_mm": 6},
             files=[PartFile(format="sldprt", path=str(tmp_path / "p.sldprt"))]),
        dict(id="flange-dn50", name="Weld neck flange DN50 PN16 EN 1092-1", category_path="piping/flange",
             description="Weld neck flange DN50 PN16 with 4 bolt holes M16", properties={"dn": 50, "pn": 16}),
        dict(id="secret-bolt", name="Socket head bolt M8x30 company B", category_path="fasteners/bolt/socket-head-bolt",
             company_id="company_b", properties={"thread": "M8", "length_mm": 30},
             files=[PartFile(format="step", path=str(step))]),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    yield SimpleNamespace(conn=conn, repo=repo, emb=emb, tmp=tmp_path)
    conn.close()


def client_for(setup, monkeypatch, with_ai=True, **kw):
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(setup.tmp / "data"))
    finder = None
    fake = fake_client(**kw)
    if with_ai:
        finder = PartFinder(SearchEngine(setup.repo, setup.emb), setup.repo.taxonomy, "claude-haiku-5-5", client=fake)
    app = create_app(get_settings(), conn=setup.conn, embedder=setup.emb, finder=finder, enable_ai=with_ai)
    return TestClient(app), fake


# ---- summary and highlights -------------------------------------------------------------
def test_summary_and_highlights(setup):
    bolt = setup.repo.get_part("shcs-m8x30", None)
    assert preview.summary(bolt) == "Socket head cap screw M8 x 30 mm, ISO 4762"
    hl = preview.highlights(bolt)
    assert hl[:2] == [{"label": "Thread", "value": "M8"}, {"label": "Length", "value": "30 mm"}]
    assert len(hl) == 3 and all(h["label"] != "Original name" for h in hl)
    prof = setup.repo.get_part("profile-2020", None)
    assert preview.summary(prof) == "System profile"            # description = name: say the kind of part
    assert {"label": "Profile", "value": "20x20"} in preview.highlights(prof)


def test_payload_has_card_fields(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)
    p = c.get("/parts/shcs-m8x30").json()
    assert p["summary"] and p["highlights"] and p["mesh_url"].startswith("/parts/shcs-m8x30/mesh")
    assert p["datasheet_url"] == "/parts/shcs-m8x30/datasheet"
    # the card shows the envelope (largest first) and where the model comes from
    assert len(p["dims_mm"]) == 3 and all(d > 0 for d in p["dims_mm"])
    assert p["library"] == "global" and "source" in p
    secret = c.get("/parts/secret-bolt?company_id=company_b").json()
    assert secret["library"] == "company" and secret["company_id"] == "company_b"
    assert c.get("/parts/profile-2020").json()["mesh_url"] is None     # only a SolidWorks file
    assert c.get("/parts/secret-bolt?company_id=company_b").json()["mesh_url"].endswith("company_id=company_b")


# ---- 3D mesh ------------------------------------------------------------------------------
def test_mesh_from_step_is_binary_stl_and_cached(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)
    r = c.get("/parts/shcs-m8x30/mesh")
    assert r.status_code == 200 and r.headers["content-type"].startswith("model/stl")
    n = struct.unpack("<I", r.content[80:84])[0]
    assert n >= 12 and len(r.content) == 84 + 50 * n
    cached = list((setup.tmp / "data" / "meshes").glob("*.stl"))
    assert len(cached) == 1
    assert c.get("/parts/shcs-m8x30/mesh").content == r.content


def test_mesh_respects_company_and_format(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)
    assert c.get("/parts/secret-bolt/mesh").status_code == 404
    assert c.get("/parts/secret-bolt/mesh?company_id=company_a").status_code == 404
    assert c.get("/parts/secret-bolt/mesh?company_id=company_b").status_code == 200
    assert c.get("/parts/profile-2020/mesh").status_code == 404


# ---- datasheet ----------------------------------------------------------------------------
def test_datasheet(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)
    r = c.get("/parts/shcs-m8x30/datasheet")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    t = r.text
    assert "Socket head bolt M8x30 ISO 4762" in t and "ISO 4762" in t and "Thread" in t and "30 mm" in t
    assert "Original name" not in t and "Print / Save as PDF" in t
    assert c.get("/parts/secret-bolt/datasheet").status_code == 404


def test_datasheet_escapes_html(setup, monkeypatch):
    setup.repo.add_part(PartCreate(id="evil", name="<script>alert(1)</script>", category_path="fasteners/bolt"))
    c, _ = client_for(setup, monkeypatch)
    t = c.get("/parts/evil/datasheet").text
    assert "<script>alert(1)" not in t and "&lt;script&gt;" in t


# ---- search by image ----------------------------------------------------------------------
def test_image_search(setup, monkeypatch):
    c, fake = client_for(setup, monkeypatch)
    r = c.post("/search/image", json={"image_base64": PNG, "media_type": "image/png", "note": "stainless"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["identified"]["part_type"] == "socket head cap screw" and d["query"] == "socket head bolt M8x30"
    assert d["results"][0]["id"] == "shcs-m8x30"
    assert all(x["id"] != "secret-bolt" for x in d["results"])
    tool, content = fake.calls[0]
    assert tool == "identify_part" and content[0]["type"] == "image" and "stainless" in content[1]["text"]


def test_image_search_not_a_part(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch, seen={"is_mechanical_part": False, "part_type": "cat",
                                                 "search_query": "", "confidence": "high"})
    d = c.post("/search/image", json={"image_base64": PNG, "media_type": "image/png"}).json()
    assert d["status"] == "none" and d["results"] == []


def test_image_search_errors(setup, monkeypatch):
    c, _ = client_for(setup, monkeypatch)
    assert c.post("/search/image", json={"image_base64": "not base64 !!!!!!!!", "media_type": "image/png"}).status_code == 400
    assert c.post("/search/image", json={"image_base64": PNG, "media_type": "image/tiff"}).status_code == 422
    big = base64.b64encode(b"\x00" * (10 * 1024 * 1024 + 10)).decode()
    assert c.post("/search/image", json={"image_base64": big}).status_code == 413
    c2, _ = client_for(setup, monkeypatch, with_ai=False)
    assert c2.post("/search/image", json={"image_base64": PNG}).status_code == 503


# ---- previews of long parts --------------------------------------------------------------
def test_elongated_preview_is_shortened():
    import numpy as np
    from partsfinder.ingest.thumbnail import is_elongated, shorten
    v = np.array([[0, 0, 0], [30, 30, 0], [0, 30, 1000], [30, 0, 1000]], dtype=float)
    out = shorten(v)
    assert is_elongated((30, 30, 1000)) and not is_elongated((40, 47, 14))
    assert out[:, 2].max() == 90 and out[:, :2].tolist() == v[:, :2].tolist()      # 3 x 30 mm, same cross-section
    short = np.array([[0, 0, 0], [40, 47, 14]], dtype=float)
    assert shorten(short).tolist() == short.tolist()
