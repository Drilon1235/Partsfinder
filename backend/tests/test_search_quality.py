"""13 Nov 2026: search bugs found with scripts/search_probe.py (123 engineering questions against 15,000 parts).

Ranges, inch threads, ASME flanges, O-rings, retaining rings for a shaft versus a bore, parallel keys by b x h x l,
sealed bearings, part names in Dutch/German/French, electrical values, input that asks for nothing, a designation
that is literally in the name, gear pairs for a ratio, and the same part from two sources shown once."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from partsfinder.api import create_app
from partsfinder.config import get_settings
from partsfinder.db import connect
from partsfinder.ingest import HashingEmbedder, part_text
from partsfinder.models import PartCreate
from partsfinder.query import drop_duplicates, gear_pair_request, gear_pairs, name_fits, prepare
from partsfinder.repository import Repository
from partsfinder.specs import check_specs, parse_specs, several_parts

DIM = 128


# ---- reading the question ----------------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("bolt M8 length between 25 and 40 mm", {"thread": "M8", "length_mm": {"min": 25.0, "max": 40.0}}),
    ("spur gear between 20 and 30 teeth module 1", {"teeth": {"min": 20, "max": 30}, "module": 1.0}),
    ("1/4-20 x 1 socket head cap screw", {"thread": "1/4-20", "length_mm": 25.4}),
    ("#10-32 screw", {"thread": "#10-32"}),
    ("3/8-16 UNC x 1 1/2 hex bolt", {"thread": "3/8-16", "length_mm": 38.1}),
    ("hex bolt M12 x 1.25 x 40", {"thread": "M12", "pitch_mm": 1.25, "length_mm": 40.0}),
    ("weld neck flange 2 inch class 300", {"nps": "2", "pressure_class": 300}),
    ("blind flange 1.5\" 150#", {"nps": "1 1/2", "pressure_class": 150}),
    ("slip-on flange NPS 1 1/4 class 600", {"nps": "1 1/4", "pressure_class": 600}),
    ("O-ring 20 x 2", {"inner_diameter_mm": 20.0, "chord_thickness_mm": 2.0}),
    ("o-ring ID 50 cross section 3", {"inner_diameter_mm": 50.0, "chord_thickness_mm": 3.0}),
    ("O-ring for 20 mm bore", {"outer_diameter_mm": 20.0}),
    ("retaining ring for 35 mm bore", {"bore_mm": 35.0}),
    ("circlip 20 mm shaft", {"shaft_diameter_mm": 20.0}),
    ("parallel key 8x7x40", {"width_mm": 8.0, "height_mm": 7.0, "length_mm": 40.0}),
    ("Bearing for a 25 mm shaft at 6000 rpm, sealed, under 15 mm wide",
     {"bore_mm": 25.0, "width_mm": {"max": 15.0}, "seal": "sealed"}),
    ("angular contact bearing 7205", {"designation": "7205"}),
    ("cylindrical roller bearing NU 205", {"designation": "NU205"}),
])
def test_parse_specs(query, expected):
    assert parse_specs(query) == expected


def test_a_range_is_one_part():
    assert not several_parts("bolt M8 length between 25 and 40 mm")
    assert several_parts("M8 bolt and M8 nut")


@pytest.mark.parametrize("query, read_as", [
    ("inbusbout M8x30", "socket head bolt M8x30"),
    ("zeskantbout M10x40", "hex bolt M10x40"),
    ("moer M10", "nut M10"),
    ("ring M8", "washer M8"),
    ("kogellager 10 mm as", "ball bearing 10 mm shaft"),
    ("Innensechskantschraube M6x16", "socket head bolt M6x16"),
    ("Flansch DN50 PN16", "flange DN50 PN16"),
    ("roulement à billes 6205", "ball bearing 6205"),
])
def test_other_languages(query, read_as):
    p = prepare(query)
    assert p.text == read_as
    assert p.notes and read_as in p.notes[0]


def test_english_is_left_alone():
    p = prepare("M8x30 socket head bolt, stainless")
    assert p.text == "M8x30 socket head bolt, stainless" and not p.notes and not p.empty


def test_electrical_values_are_set_aside():
    p = prepare("10k resistor 0603")
    assert p.text == "resistor 0603" and "10k" in p.notes[0]
    assert prepare("100nF capacitor 0805").text == "capacitor 0805"
    assert prepare("16MHz crystal HC49").text == "crystal HC49"
    assert prepare("M10 bolt 50 mm").text == "M10 bolt 50 mm"          # no passive part: nothing removed


@pytest.mark.parametrize("query", ["???", "a", "M", "x30", "!!", "the"])
def test_asks_for_nothing(query):
    assert prepare(query).empty


@pytest.mark.parametrize("query", ["608", "M8", "M8x", "bolt", "IPE 200", "Ø20 shaft", "😀 bolt"])
def test_asks_for_something(query):
    assert not prepare(query).empty


# ---- checking a part ---------------------------------------------------------------------------------------
def _part(name, category="other/unknown", tags=(), bbox=None, company=None, **props):
    return SimpleNamespace(name=name, category_path=category, tags=list(tags), properties=props, standards=[],
                           material=None, description="", bbox_mm=bbox, company_id=company, library="global")


def _status(query, part):
    return {c.key: c.status for c in check_specs(parse_specs(query), part)}


def test_ring_for_a_shaft_is_no_ring_for_a_bore():
    shaft = _part("Retaining ring for shaft 35 mm (circlip)", shaft_diameter_mm=35.0)
    bore = _part("Retaining ring for bore 35 mm (circlip)", bore_mm=35.0)
    assert _status("retaining ring for 35 mm bore", bore) == {"bore_mm": "match"}
    assert _status("retaining ring for 35 mm bore", shaft) == {"bore_mm": "mismatch"}
    assert _status("circlip 35 mm shaft", shaft) == {"shaft_diameter_mm": "match"}


def test_en_flange_is_no_asme_flange():
    en = _part("Weld neck flange EN 1092-1 DN50 PN16", dn=50, pn=16)
    asme = _part("Weld neck flange NPS 2\" class 300 ASME B16.5", nps="2", pressure_class=300)
    assert _status("weld neck flange 2 inch class 300", asme) == {"nps": "match", "pressure_class": "match"}
    assert _status("weld neck flange 2 inch class 300", en) == {"nps": "mismatch", "pressure_class": "mismatch"}
    assert _status("DN50 PN16 flange", asme) == {"dn": "mismatch", "pn": "mismatch"}


def test_ranges_and_sealed():
    bolt = _part("Hex bolt M8x30", thread="M8", length_mm=30)
    assert _status("M8 bolt between 25 and 40 mm", bolt) == {"thread": "match", "length_mm": "match"}
    assert _status("M8 bolt between 35 and 40 mm", bolt)["length_mm"] == "mismatch"
    open_ = _part("Deep groove ball bearing 6205", bore_mm=25, width_mm=15, seal="open")
    sealed = _part("Deep groove ball bearing 6205-2RS", bore_mm=25, width_mm=15, seal="2RS")
    q = "bearing 25 mm bore sealed under 15 mm wide"
    assert set(_status(q, sealed).values()) == {"match"}
    assert _status(q, open_)["seal"] == "mismatch"


def test_key_section_from_the_shaft():
    key = _part("Key form A for shaft 25 mm, length 38 mm", "fasteners/pin/key", shaft_diameter_mm=25, length_mm=38)
    assert _status("parallel key 8x7x38", key) == {"width_mm": "match", "height_mm": "match", "length_mm": "match"}
    assert _status("parallel key 10x8x38", key)["width_mm"] == "mismatch"


@pytest.mark.parametrize("query, name, fits", [
    ("IPE 200", "IPE-Profile 200 DIN1025-5 S235JR", True),
    ("IPE 200", "IPE-Profile 100 DIN1025-5 S235JR", False),
    ("SOIC-8", "SO package SOIC-8 3.9x4.9mm P1.27mm", True),
    ("TO-220", "TO package TO-220-3 Horizontal", True),
    ("angle 50x50x5", "Angle Bar L50x50x5 EN10056 S235JR", True),
    ("resistor 0603", "SMD resistor R 0603 1608Metric", True),
    ("resistor 0603", "SMD resistor R 0201 0603Metric", False),
    ("resistor 0603", "SMD resistor R Array Convex 4x0603", False),
    ("buzzer 12mm", "Buzzer MagneticBuzzer HMB-12", False),
    ("electrolytic capacitor 10 mm", "Capacitor CP Radial D10.0mm P5.00mm", True),
    ("round bar 20", "Round Bar 200 EN10060", False),
    ("lead screw 8mm", "Flange nut T8 lead screw 22 mm", False),
    ("lead screw 8mm", "T8 lead screw 150 mm", True),
])
def test_designation_in_the_name(query, name, fits):
    assert name_fits(query, _part(name)) is fits


def test_same_part_from_two_sources_once():
    hit = lambda part: SimpleNamespace(hit=SimpleNamespace(part=part))          # noqa: E731
    a = _part("Socket head bolt M8x30 ISO 4762", "fasteners/bolt/socket-head-bolt", bbox=(13.27, 13.27, 38),
              thread="M8", length_mm=30)
    b = _part("Socket head bolt M8x30 ISO 4762 (DIN 912)", "fasteners/bolt/socket-head-bolt", bbox=(13, 13, 38),
              thread="M8", length_mm=30.0)
    own = _part("Our M8x30 bolt", "fasteners/bolt/socket-head-bolt", bbox=(13, 13, 38), company="acme",
                thread="M8", length_mm=30)
    other = _part("Socket head bolt M8x35 ISO 4762", "fasteners/bolt/socket-head-bolt", bbox=(13, 13, 43),
                  thread="M8", length_mm=35)
    kept = drop_duplicates([hit(a), hit(b), hit(other)])
    assert [j.hit.part for j in kept] == [a, other]
    kept = drop_duplicates([hit(a), hit(own)])                                   # the company's own model wins
    assert [j.hit.part for j in kept] == [own]


# ---- gear pairs ----------------------------------------------------------------------------------------------
def test_gear_pair_request():
    assert gear_pair_request("give me a spur gear pair for 3:1 reduction") == {"ratio": 3.0, "type": "spur"}
    req = gear_pair_request("Spur gear pair for 3:1 reduction, centre distance 80 mm, module between 1.5 and 2")
    assert req == {"ratio": 3.0, "type": "spur", "centre_distance_mm": 80.0, "module": {"min": 1.5, "max": 2.0}}
    assert gear_pair_request("spur gear module 2 40 teeth") is None
    assert gear_pair_request("gear m1 z20") is None


def test_gear_pairs():
    gears = [SimpleNamespace(part=_part(f"Spur gear m{m} z{z}", module=m, teeth=z, pressure_angle_deg=20))
             for m in (1, 2) for z in (12, 15, 20, 36, 45, 60)]
    pairs = gear_pairs(gears, {"ratio": 3.0, "type": "spur"})
    teeth = {(p.part.properties["module"], p.part.properties["teeth"], w.part.properties["teeth"]) for p, w, _ in pairs}
    assert teeth == {(1, 12, 36), (1, 15, 45), (1, 20, 60), (2, 12, 36), (2, 15, 45), (2, 20, 60)}
    assert pairs[0][0].part.properties["teeth"] == 20                           # no undercut first
    only = gear_pairs(gears, {"ratio": 3.0, "type": "spur", "centre_distance_mm": 80.0, "module": {"min": 1.5, "max": 2}})
    assert [(p.part.properties["module"], p.part.properties["teeth"], a) for p, _, a in only] == [(2, 20, 80.0)]


# ---- the whole answer through the API -----------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    conn = connect(":memory:", embedding_dim=DIM, check_same_thread=False)
    repo = Repository(conn)
    emb = HashingEmbedder(DIM)
    rows = [dict(id=f"gear-m{m}-z{z}", name=f"Spur gear module {m}, {z} teeth", category_path="drivetrain/gear/spur",
                 description="Spur gear", properties={"module": m, "teeth": z, "pressure_angle_deg": 20})
            for m in (1, 2) for z in (20, 40, 60)]
    rows += [
        dict(id="shcs-a", name="Socket head bolt M8x30 ISO 4762", category_path="fasteners/bolt/socket-head-bolt",
             description="Socket head bolt", standards=["ISO 4762"], bbox_mm=(13.27, 13.27, 38),
             properties={"thread": "M8", "length_mm": 30}),
        dict(id="shcs-b", name="Socket head bolt M8x30 ISO 4762 (DIN 912)", category_path="fasteners/bolt/socket-head-bolt",
             description="Socket head bolt", standards=["ISO 4762", "DIN 912"], bbox_mm=(13, 13, 38),
             properties={"thread": "M8", "length_mm": 30}),
        dict(id="ipe-200", name="IPE-Profile 200 DIN1025-5 S235JR", category_path="profiles/steel/ipe",
             description="IPE beam", tags=["ipe", "i-beam"]),
        dict(id="ipe-100", name="IPE-Profile 100 DIN1025-5 S235JR", category_path="profiles/steel/ipe",
             description="IPE beam", tags=["ipe", "i-beam"]),
    ]
    for d in rows:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedder', 'hashing')")
    monkeypatch.setenv("PARTSFINDER_DATA_DIR", str(tmp_path / "data"))
    yield TestClient(create_app(get_settings(), conn=conn, embedder=emb, finder=None, enable_ai=False))
    conn.close()


def _search(client, query):
    r = client.post("/search", json={"query": query, "use_ai": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_api_gear_pair(client):
    d = _search(client, "spur gear pair for 3:1 reduction, centre distance 80 mm")
    assert d["status"] == "found"
    assert [g["request"] for g in d["groups"]] == ["m2, 20 + 60 teeth, centre distance 80 mm"]
    assert [r["id"] for r in d["results"]] == ["gear-m2-z20", "gear-m2-z60"]
    assert _search(client, "spur gear pair 7:1")["status"] == "none"


def test_api_nothing_asked(client):
    d = _search(client, "???")
    assert d["status"] == "none" and d["results"] == [] and "Type the part" in d["message"]


def test_api_translated_and_once(client):
    d = _search(client, "inbusbout M8x30")
    assert d["message"].startswith("Read as “socket head bolt M8x30”.")
    assert [r["verdict"] for r in d["results"]].count("fits") == 1               # one model, not the same twice


def test_api_designation_in_the_name(client):
    d = _search(client, "IPE 200")
    assert d["status"] == "found"
    assert d["results"][0]["id"] == "ipe-200" and d["results"][0]["verdict"] == "fits"
    assert all(r["verdict"] != "fits" for r in d["results"][1:])


# ---- a web page in a browser on this pc cannot reach the library ---------------------------------------------------
def test_dns_rebinding_and_web_pages_are_refused(client):
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers={"host": "127.0.0.1:8731"}).status_code == 200
    assert client.get("/health", headers={"host": "localhost:8731"}).status_code == 200
    r = client.get("/health", headers={"host": "evil.example:8731"})           # DNS rebinding
    assert r.status_code == 403 and "only answers to this computer" in r.json()["detail"]
    r = client.post("/search", json={"query": "IPE 200"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/settings/ai", json={"api_key": "sk-ant-x"}, headers={"origin": "null"})
    assert r.status_code == 403
    # a browser on /docs of this server itself: same origin
    r = client.post("/search", json={"query": "IPE 200", "use_ai": False}, headers={"origin": "http://testserver"})
    assert r.status_code == 200


def test_a_network_server_answers_to_its_own_name(client):
    client.app.state.loopback_only = False                                        # --host 0.0.0.0 with accounts
    assert client.get("/health", headers={"host": "parts.example.local:8000"}).status_code == 200
    r = client.get("/health", headers={"host": "parts.example.local:8000", "origin": "https://evil.example"})
    assert r.status_code == 403


def test_pack_files_never_leave_the_open_libraries(tmp_path):
    import urllib.request
    import zipfile

    from partsfinder import packs, remote
    handler = remote._SameHostsOnly()
    req = urllib.request.Request("https://raw.githubusercontent.com/a/b/c.step")
    with pytest.raises(remote.RemoteFileError):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/c.step")
    with pytest.raises(remote.RemoteFileError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://raw.githubusercontent.com/a/b/c.step")
    for bad in ("../outside.txt", "files\\\\..\\\\..\\\\outside.txt", "/etc/x", "C:/x"):
        z = tmp_path / "bad.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr(bad, "x")
        with pytest.raises(packs.PackError):
            packs._extract(z, tmp_path / "out")
