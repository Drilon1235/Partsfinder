"""Generates test models (STEP + JSON metadata) for Partsfinder.

Usage (from the project folder):
    backend\\.venv\\Scripts\\python scripts\\generate_testdata.py          (Windows)
    backend/.venv/bin/python scripts/generate_testdata.py                (Mac)

Options:
    --check        only check the metadata (CadQuery not needed)
    --only TEXT   only models whose id contains this text
    --clean        first remove previously generated test data

Two files are written per model:
    data/<library>/<category>/<id>.step   the 3D model
    data/<library>/<category>/<id>.json   the metadata (see docs/03_DATAMODEL.md)
The import pipeline (phase 3) reads that JSON along. There is also an overview in
data/testdata_manifest.json, which the test questions (phase 8) use as "right answers".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
sys.path.insert(0, str(PROJECT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from partsfinder.taxonomy import Taxonomy  # noqa: E402

LICENSE = "Partsfinder test data (free to use)"


@dataclass
class Model:
    id: str
    shape: tuple[str, dict[str, Any]]          # (function name in shapes.py, arguments)
    name: str
    description: str
    category_path: str
    sectors: list[str]
    material: str
    tags: list[str] = field(default_factory=list)
    color: str | None = None
    standards: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    kind: str = "part"
    components: list[dict[str, Any]] = field(default_factory=list)  # [{"id":..., "quantity":...}]
    company_id: str | None = None

    def metadata(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("shape")
        d["tags"] = list(dict.fromkeys(d["tags"]))      # no duplicates after translation
        d.update(source="generated", license=LICENSE)
        return d

    def folder(self) -> Path:
        lib = "global" if self.company_id is None else f"companies/{self.company_id}"
        return DATA / lib / self.category_path.split("/")[0]


def S(fn: str, **kw) -> tuple[str, dict[str, Any]]:
    return fn, kw


def fmt(x: float) -> str:
    return f"{x:g}".replace(".", "_")


# =============================================================================
# Catalogue
# =============================================================================
def fasteners() -> list[Model]:
    out: list[Model] = []
    # DIN 933 hex bolts: d -> (wrench size s, head height k, lengths)
    bolts = {4: (7, 2.8, [10, 20, 30]), 5: (8, 3.5, [12, 20, 30]), 6: (10, 4, [16, 25, 40]),
             8: (13, 5.3, [20, 40, 60]), 10: (17, 6.4, [30, 50, 80]), 12: (19, 7.5, [40, 60, 100]),
             16: (24, 10, [50, 80]), 20: (30, 12.5, [60, 100])}
    for d, (s, k, lengths) in bolts.items():
        variants = [("88", "steel 8.8 galvanized", "steel")]
        if d in (6, 8):
            variants.append(("a2", "stainless steel A2", "stainless steel"))
        for L in lengths:
            for code, mat, short in variants:
                out.append(Model(
                    f"bolt-din933-m{d}x{L}-{code}", S("hex_bolt", d=d, L=L, s=s, k=k),
                    f"Hex bolt M{d}x{L} {mat}",
                    f"Hex bolt with full thread, M{d}, length {L} mm, wrench size {s} mm, {mat}.",
                    "fasteners/bolt/hex-bolt", ["industry", "machine-building", "construction"], mat,
                    tags=["bolt", "hex", "hex bolt", "thread", f"M{d}", short],
                    standards=["DIN 933", "ISO 4017"],
                    properties={"thread": f"M{d}", "length_mm": L, "wrench_size_mm": s,
                                "strength_class": "8.8" if code == "88" else "A2-70"}))
    # DIN 934 hex nuts and DIN 985 lock nuts
    nuts = {4: (7, 3.2), 5: (8, 4), 6: (10, 5), 8: (13, 6.5), 10: (17, 8), 12: (19, 10),
            16: (24, 13), 20: (30, 16)}
    for d, (s, m) in nuts.items():
        out.append(Model(
            f"nut-din934-m{d}", S("hex_nut", d=d, s=s, m=m), f"Hex nut M{d} galvanized",
            f"Standard hex nut M{d}, height {m} mm, steel class 8 galvanized.",
            "fasteners/nut/hex-nut", ["industry", "machine-building", "construction"], "steel galvanized",
            tags=["nut", "nut", "hex", f"M{d}"], standards=["DIN 934", "ISO 4032"],
            properties={"thread": f"M{d}", "wrench_size_mm": s, "height_mm": m}))
        if d in (6, 8, 10, 12):
            out.append(Model(
                f"locknut-din985-m{d}", S("hex_nut", d=d, s=s, m=d), f"Lock nut M{d} with nylon insert",
                f"Self-locking hex nut M{d} with nylon ring, does not vibrate loose.",
                "fasteners/nut/lock-nut", ["machine-building", "automotive", "industry"], "steel galvanized",
                tags=["lock nut", "nyloc", "lock nut", "self-locking", f"M{d}"],
                standards=["DIN 985", "ISO 10511"], properties={"thread": f"M{d}", "wrench_size_mm": s}))
    # DIN 125 washers
    washers = {4: (4.3, 9, 0.8), 5: (5.3, 10, 1), 6: (6.4, 12, 1.6), 8: (8.4, 16, 1.6),
               10: (10.5, 20, 2), 12: (13, 24, 2.5), 16: (17, 30, 3), 20: (21, 37, 3)}
    for d, (d1, d2, h) in washers.items():
        out.append(Model(
            f"washer-din125-m{d}", S("washer", d1=d1, d2=d2, h=h), f"Washer M{d} flat",
            f"Flat washer for M{d}, inner {d1} mm, outer {d2} mm, thickness {h} mm.",
            "fasteners/washer/flat-washer", ["industry", "machine-building", "construction"], "steel galvanized",
            tags=["washer", "washer", "washer", f"M{d}"], standards=["DIN 125", "ISO 7089"],
            properties={"inner_diameter_mm": d1, "outer_diameter_mm": d2, "thickness_mm": h}))
    # ISO 4762 socket head bolts
    cap = {3: (5.5, 3, 2.5, [8, 12, 20]), 4: (7, 4, 3, [10, 16, 25]), 5: (8.5, 5, 4, [12, 20, 30]),
           6: (10, 6, 5, [16, 25, 40]), 8: (13, 8, 6, [20, 30, 50]), 10: (16, 10, 8, [25, 40, 60])}
    for d, (dk, k, sock, lengths) in cap.items():
        for L in lengths:
            out.append(Model(
                f"socket-iso4762-m{d}x{L}", S("socket_screw", d=d, L=L, dk=dk, k=k, socket=sock),
                f"Socket head bolt M{d}x{L} 12.9 black",
                f"Socket head cap screw M{d}x{L}, strength class 12.9, black oxide.",
                "fasteners/bolt/socket-head-bolt", ["machine-building", "industry", "automotive"], "steel 12.9",
                tags=["hex socket", "socket head cap screw", "cylinder head", f"M{d}"],
                standards=["ISO 4762", "DIN 912"],
                properties={"thread": f"M{d}", "length_mm": L, "hex_socket_mm": sock}))
    # wedge anchors (construction)
    for d, L in ((8, 75), (10, 90), (12, 110)):
        out.append(Model(
            f"wedge-anchor-m{d}x{L}", S("wedge_anchor", d=d, L=L), f"Wedge anchor M{d}x{L} for concrete",
            f"Through-bolt anchor M{d}x{L} for fixing in concrete, with nut and washer.",
            "fasteners/anchor/wedge-anchor", ["construction"], "steel galvanized",
            tags=["anchor", "wedge anchor", "wedge anchor", "concrete", "through-bolt anchor", f"M{d}"],
            standards=["ETA Option 7"], properties={"thread": f"M{d}", "length_mm": L}))
    return out


def connections() -> list[Model]:
    out: list[Model] = []
    brackets = [(30, 30, 25, 2), (40, 40, 30, 2.5), (50, 50, 35, 2.5), (60, 60, 40, 3),
                (70, 70, 55, 3), (90, 90, 65, 3), (100, 100, 90, 4), (40, 60, 40, 2.5),
                (60, 90, 50, 3), (80, 120, 60, 4)]
    for a, b, w, t in brackets:
        hole = 5 if a <= 40 else 6.5 if a <= 70 else 8.5
        for code, mat, sectors in (("zn", "steel galvanized", ["construction", "furniture", "industry"]),
                                   ("stainless-steel", "stainless steel 304", ["food", "maritime", "industry"])):
            out.append(Model(
                f"angle-bracket-{a}x{b}x{w}-{code}", S("angle_bracket", a=a, b=b, w=w, t=t, hole=hole),
                f"Angle bracket {a}x{b}x{w} mm {mat}",
                f"Equal or unequal angle connector {a}x{b} mm, width {w} mm, "
                f"thickness {t} mm, holes {hole} mm, {mat}.",
                "connections/bracket/angle-bracket", sectors, mat,
                tags=["angle bracket", "angle iron", "angle bracket", "angle connector", "L-bracket"],
                properties={"thickness_mm": t, "hole_diameter_mm": hole}))
    for a, b, t in ((150, 120, 3), (200, 150, 3), (250, 200, 4), (300, 250, 5)):
        out.append(Model(
            f"shelf-bracket-{a}x{b}", S("wall_bracket", a=a, b=b, t=t), f"Shelf bracket {a}x{b} mm with brace",
            f"Wall bracket to hang a shelf on the wall, {a}x{b} mm, with reinforcement.",
            "connections/bracket/wall-bracket", ["construction", "furniture", "consumer-products"], "steel powder-coated",
            tags=["shelf bracket", "wall bracket", "shelf bracket", "shelf", "wall"], color="white",
            properties={"max_load_kg": int(a / 5)}))
    for pipe_d in (20, 32, 50, 76):
        out.append(Model(
            f"pipe-bracket-{pipe_d}", S("pipe_clamp", pipe_d=pipe_d, t=2, w=20),
            f"Pipe bracket for pipe {pipe_d} mm",
            f"Omega pipe clamp with two feet for pipe with diameter {pipe_d} mm.",
            "connections/bracket/u-bracket", ["industry", "construction", "horticulture", "energy"], "stainless steel 304",
            tags=["pipe bracket", "omega bracket", "pipe clamp", "u bracket"],
            properties={"tube_diameter_mm": pipe_d}))
    for a, t in ((150, 10), (200, 15), (250, 20)):
        out.append(Model(
            f"base-plate-{a}x{a}x{t}", S("plate_with_holes", a=a, b=a, t=t, hole=18, inset=30),
            f"Column base plate {a}x{a}x{t} mm",
            f"Steel base plate {a}x{a} mm, thickness {t} mm, 4 anchor holes 18 mm, for steel columns.",
            "connections/plate/base-plate", ["construction", "industry"], "steel S235",
            tags=["base plate", "column base", "base plate", "anchor plate"], standards=["EN 10025"],
            properties={"thickness_mm": t, "holes": 4}))
    for L, w in ((60, 40), (100, 60)):
        out.append(Model(
            f"door-hinge-{L}x{w}", S("hinge", length=L, width=w / 2, t=2, knuckle_d=8),
            f"Door hinge {L}x{w} mm", f"Ball bearing hinge {L} mm for doors and cabinets.",
            "connections/hinge/door-hinge", ["construction", "furniture"], "stainless steel 304",
            tags=["hinge", "door hinge", "door", "lift-off hinge"]))
    out.append(Model(
        "piano-hinge-1000", S("hinge", length=1000, width=16, t=1, knuckle_d=4),
        "Piano hinge 1000 mm", "Continuous piano hinge 1000 x 32 mm for flaps and lids.",
        "connections/hinge/piano-hinge", ["furniture", "machine-building"], "steel nickel-plated",
        tags=["piano hinge", "piano hinge", "continuous hinge"]))
    return out


def profiles() -> list[Model]:
    out: list[Model] = []
    for a, t in ((20, 2), (30, 2), (40, 2), (40, 3), (50, 3), (60, 3), (80, 4), (100, 4)):
        out.append(Model(
            f"tube-{a}x{a}x{fmt(t)}", S("rect_tube", a=a, b=a, t=t, L=1000),
            f"Square tube {a}x{a}x{t} mm steel",
            f"Cold-formed square tube {a}x{a} mm, wall thickness {t} mm, length 1000 mm.",
            "profiles/steel/box-section", ["construction", "industry", "machine-building", "furniture"], "steel S235",
            tags=["box section", "square tube", "square tube", "box section profile"], standards=["EN 10219"],
            properties={"wall_thickness_mm": t, "length_mm": 1000}))
    for a, b, t in ((60, 40, 3), (80, 40, 3), (100, 50, 4)):
        out.append(Model(
            f"tube-{a}x{b}x{t}", S("rect_tube", a=a, b=b, t=t, L=1000),
            f"Rectangular tube {a}x{b}x{t} mm steel",
            f"Rectangular tube {a}x{b} mm, wall thickness {t} mm, length 1000 mm.",
            "profiles/steel/box-section", ["construction", "industry", "machine-building"], "steel S235",
            tags=["box section", "rectangular tube", "rectangular tube"], standards=["EN 10219"],
            properties={"wall_thickness_mm": t, "length_mm": 1000}))
    for a, t in ((20, 3), (30, 3), (40, 4), (50, 5), (60, 6)):
        out.append(Model(
            f"angle-profile-{a}x{t}", S("angle_profile", a=a, t=t, L=1000),
            f"Equal angle profile {a}x{a}x{t} mm",
            f"L-profile {a}x{a} mm, thickness {t} mm, length 1000 mm, hot-rolled steel.",
            "profiles/steel/angle-profile", ["construction", "industry", "agriculture"], "steel S235",
            tags=["angle profile", "angle steel", "L-profile", "angle iron"], standards=["EN 10056"],
            properties={"thickness_mm": t, "length_mm": 1000}))
    for h, b, tw, tf in ((80, 45, 6, 8), (100, 50, 6, 8.5), (120, 55, 7, 9)):
        out.append(Model(
            f"unp-{h}", S("u_profile", h=h, b=b, tw=tw, tf=tf, L=2000),
            f"UNP {h} profile", f"U-profile UNP {h} (height {h} mm, flange {b} mm), length 2000 mm.",
            "profiles/steel/u-profile", ["construction", "industry"], "steel S235",
            tags=["UNP", "U-profile", "U-beam", "channel"], standards=["DIN 1026"],
            properties={"height_mm": h, "flange_width_mm": b, "length_mm": 2000}))
    ipe = {80: (46, 3.8, 5.2), 100: (55, 4.1, 5.7), 120: (64, 4.4, 6.3), 140: (73, 4.7, 6.9),
           160: (82, 5, 7.4), 180: (91, 5.3, 8), 200: (100, 5.6, 8.5)}
    for h, (b, tw, tf) in ipe.items():
        out.append(Model(
            f"ipe-{h}", S("i_profile", h=h, b=b, tw=tw, tf=tf, L=2000), f"IPE {h} beam",
            f"I-profile IPE {h} (height {h} mm, width {b} mm), length 2000 mm, for load-bearing structures.",
            "profiles/steel/ipe", ["construction", "industry"], "steel S235",
            tags=["IPE", "I-beam", "I-profile", "steel beam", "girder", "I-beam"], standards=["EN 10365"],
            properties={"height_mm": h, "width_mm": b, "length_mm": 2000}))
    for a, b in ((20, 20), (30, 30), (40, 40), (45, 45), (40, 80)):
        out.append(Model(
            f"alu-system-profile-{a}x{b}", S("alu_slot_profile", a=a, b=b, L=1000),
            f"Aluminium system profile {a}x{b} slot", f"Anodised aluminium construction profile "
            f"{a}x{b} mm with T-slots, length 1000 mm, for frames and machine building.",
            "profiles/aluminium/system-profile", ["machine-building", "industry", "logistics"], "aluminium 6063",
            tags=["aluminium profile", "item profile", "T-slot", "extrusion", "bosch profile"],
            color="silver", properties={"length_mm": 1000}))
    for d, t in ((20, 2), (30, 2), (40, 3)):
        out.append(Model(
            f"alu-tube-{d}x{t}", S("round_tube", d=d, t=t, L=1000), f"Aluminium round tube {d}x{t} mm",
            f"Round aluminium tube, diameter {d} mm, wall {t} mm, length 1000 mm.",
            "profiles/aluminium/tube", ["industry", "furniture", "consumer-products"], "aluminium 6060",
            tags=["aluminium tube", "round tube", "tube"], properties={"wall_thickness_mm": t}))
    for d in (32, 40, 50):
        out.append(Model(
            f"pvc-pipe-{d}", S("round_tube", d=d, t=2.4 if d < 50 else 3, L=1000),
            f"PVC pipe {d} mm", f"PVC pipe diameter {d} mm, length 1000 mm, for drainage and irrigation.",
            "profiles/plastic/tube", ["construction", "horticulture", "agriculture"], "PVC",
            tags=["pvc pipe", "drain pipe", "plastic pipe", "irrigation"], color="grey"))
    return out


def drive() -> list[Model]:
    out: list[Model] = []
    bearings = {"6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10),
                "6004": (20, 42, 12), "6005": (25, 47, 12), "6200": (10, 30, 9), "6201": (12, 32, 10),
                "6202": (15, 35, 11), "6203": (17, 40, 12), "6204": (20, 47, 14), "6205": (25, 52, 15),
                "6206": (30, 62, 16), "6300": (10, 35, 11), "6301": (12, 37, 12), "6302": (15, 42, 13),
                "6303": (17, 47, 14), "6304": (20, 52, 15)}
    for code, (d, D, B) in bearings.items():
        out.append(Model(
            f"ball-bearing-{code}-2rs", S("ball_bearing", d=d, D=D, B=B), f"Ball bearing {code}-2RS",
            f"Deep groove ball bearing {code} with rubber seal, shaft {d} mm, outer {D} mm, width {B} mm.",
            "drivetrain/bearing/ball-bearing", ["machine-building", "industry", "automotive", "agriculture"],
            "bearing steel 100Cr6", tags=["ball bearing", "bearing", "ball bearing", "deep groove ball bearing", code],
            standards=["ISO 15", "DIN 625"],
            properties={"inner_diameter_mm": d, "outer_diameter_mm": D, "width_mm": B,
                        "seal": "2RS"}))
    for code, d, H in (("ucp204", 20, 33), ("ucp205", 25, 36), ("ucp206", 30, 42)):
        out.append(Model(
            f"pillow-block-{code}", S("pillow_block", d=d, H=H * 2, L=H * 4), f"Pillow block bearing {code.upper()}",
            f"Cast iron pillow block housing with bearing for shaft {d} mm.", "drivetrain/bearing/pillow-block",
            ["machine-building", "agriculture", "logistics"], "cast-iron",
            tags=["pillow block", "pillow block", "pillow block housing", "UCP"], properties={"shaft_diameter_mm": d}))
    for d in (8, 10, 12, 16, 20, 25):
        out.append(Model(
            f"shaft-{d}x300", S("shaft", d=d, L=300), f"Ground shaft {d} mm x 300 mm",
            f"Hardened and ground shaft, diameter {d} mm h6, length 300 mm, C45.",
            "drivetrain/shaft/shaft", ["machine-building", "industry"], "steel C45",
            tags=["as", "shaft", "guide shaft", "ground"], properties={"tolerance": "h6", "length_mm": 300}))
    for d in (8, 10, 12):
        out.append(Model(
            f"threaded-rod-m{d}x1000", S("shaft", d=d, L=1000), f"Threaded rod M{d} x 1000 mm",
            f"Fully threaded rod M{d}, length 1 metre, galvanized.", "drivetrain/shaft/threaded-rod",
            ["construction", "industry"], "steel 4.8 galvanized",
            tags=["threaded rod", "threaded rod", "threaded stud", f"M{d}"], standards=["DIN 976"],
            properties={"thread": f"M{d}", "length_mm": 1000}))
    for wire, D, L, coils in ((0.8, 6, 20, 8), (1, 8, 25, 8), (1.5, 12, 30, 7), (2, 16, 40, 7),
                              (2.5, 20, 50, 6), (3, 25, 60, 6)):
        out.append(Model(
            f"compression-spring-{fmt(wire)}x{D}x{L}", S("compression_spring", wire_d=wire, D=D, L=L, coils=coils),
            f"Compression spring {wire}x{D}x{L} mm", f"Cylindrical compression spring, wire {wire} mm, outer diameter {D} mm, "
            f"free length {L} mm, spring steel.", "drivetrain/spring/compression-spring",
            ["machine-building", "automotive", "consumer-products"], "spring steel",
            tags=["compression spring", "spring", "compression spring", "coil spring"], standards=["DIN 2098"],
            properties={"wire_diameter_mm": wire, "outer_diameter_mm": D, "free_length_mm": L}))
    for mod, z in ((1, 20), (1, 40), (1.5, 20), (1.5, 30), (2, 20), (2, 30)):
        out.append(Model(
            f"spur-gear-m{fmt(mod)}-z{z}", S("spur_gear", module=mod, z=z, b=mod * 10, bore=max(6, mod * 5)),
            f"Spur gear module {mod} z={z}", f"Straight-cut spur gear, module {mod}, {z} teeth, "
            f"pitch diameter {mod * z:g} mm.", "drivetrain/gear/spur",
            ["machine-building", "industry"], "steel C45",
            tags=["gear", "gear", "spur gear", "pinion"],
            properties={"module": mod, "teeth": z, "pitch_diameter_mm": mod * z}))
    for d in (50, 80, 120):
        out.append(Model(
            f"pulley-v-{d}", S("pulley", d=d, b=16, bore=12 if d < 100 else 20),
            f"V-belt pulley {d} mm", f"Pulley for V-belt profile SPZ, diameter {d} mm.",
            "drivetrain/transmission/pulley", ["machine-building", "agriculture"], "cast-iron",
            tags=["pulley", "sheave", "pulley", "V-belt"], properties={"belt_profile": "SPZ"}))
    return out


def furniture() -> list[Model]:
    out: list[Model] = []
    styles = [
        # style, name, w, d, h, seat height, leg, backrest, round legs, material, colours, sectors, type
        ("garden-chair", "Garden chair", 460, 520, 820, 450, 22, True, True, "steel powder-coated",
         ["green", "anthracite", "white"], ["horticulture", "hospitality", "consumer-products"], "garden-chair"),
        ("hospitality-chair", "Hospitality chair", 440, 500, 850, 460, 35, True, False, "wood",
         ["oak", "beech", "walnut"], ["hospitality", "furniture"], "chair"),
        ("canteen-chair", "Canteen chair stackable", 460, 500, 800, 450, 20, True, True, "PP plastic",
         ["blue", "red", "grey", "black"], ["office", "hospitality", "furniture"], "chair"),
        ("child-chair", "Child chair", 320, 320, 550, 300, 20, True, True, "PP plastic",
         ["yellow", "green"], ["consumer-products", "furniture"], "chair"),
    ]
    for key, label, w, d, h, sh, leg, back, rnd, mat, colors, sectors, typ in styles:
        args = dict(w=w, d=d, h=h, seat_h=sh, leg=leg, back=back, round_legs=rnd)
        comp_ids = []
        for part, part_label, qty in (("leg", "leg", 4), ("seat", "seat", 1),
                                      ("backrest", "backrest", 1)):
            cid = f"{key}-{part}"
            comp_ids.append({"id": cid, "quantity": qty})
            out.append(Model(
                cid, S("chair_part", which=part, **args), f"{label} {part_label}",
                f"Part ({part_label}) of the {label.lower()}, {mat}.", "furniture/seating",
                sectors, mat, tags=[part_label, "chair part", key]))
        for color in colors:
            out.append(Model(
                f"{key}-{color}", S("chair_part", which="full", **args), f"{label} {color}",
                f"{label} in {color}, {mat}, seat height {sh} mm, total height {h} mm.",
                f"furniture/seating/{typ}", sectors, mat, color=color, kind="assembly",
                components=comp_ids, tags=["chair", "chair", key, color],
                properties={"seat_height_mm": sh, "stackable": key == "canteen-chair",
                            "outdoor": key == "garden-chair"}))
    # bar stools
    for sh in (650, 750):
        args = dict(w=380, d=380, h=sh, seat_h=sh, leg=25, back=False, round_legs=True)
        out.append(Model(
            f"bar-stool-{sh}", S("chair_part", which="full", **args), f"Bar stool stainless steel seat height {sh} mm",
            f"Bar stool without backrest, stainless steel frame, seat height {sh} mm.", "furniture/seating/stool",
            ["hospitality"], "stainless steel 304", tags=["stool", "bar stool", "bar stool"], properties={"seat_height_mm": sh}))
    # garden benches
    for L in (1200, 1500, 1800):
        out.append(Model(
            f"garden-bench-{L}", S("bench_part", which="full", length=L, d=550, h=850, seat_h=450),
            f"Garden bench wood {L} mm", f"Wooden garden bench with backrest, length {L} mm, hardwood.",
            "furniture/seating/bench", ["horticulture", "hospitality", "consumer-products"], "wood",
            color="teak", tags=["bench", "garden bench", "bench", "outdoor"], properties={"seats": L // 600}))
    tables = [
        ("dining-table-1600x900", "Dining table oak 1600x900", 1600, 900, 750, 30, 70, "wood", "oak",
         "furniture/tables/dining-table", ["furniture", "hospitality"]),
        ("dining-table-2000x1000", "Dining table oak 2000x1000", 2000, 1000, 750, 30, 80, "wood", "oak",
         "furniture/tables/dining-table", ["furniture", "hospitality"]),
        ("garden-table-green", "Garden table steel green", 900, 900, 740, 20, 30, "steel powder-coated", "green",
         "furniture/tables/garden-table", ["horticulture", "hospitality", "consumer-products"]),
        ("garden-table-anthracite", "Garden table steel anthracite", 900, 900, 740, 20, 30, "steel powder-coated",
         "anthracite", "furniture/tables/garden-table", ["horticulture", "hospitality", "consumer-products"]),
        ("workbench-1500x750", "Workbench steel 1500x750", 1500, 750, 900, 40, 50, "steel + plywood",
         "grey", "furniture/tables/workbench", ["industry", "machine-building"]),
        ("workbench-2000x800", "Workbench steel 2000x800", 2000, 800, 900, 40, 50, "steel + plywood",
         "grey", "furniture/tables/workbench", ["industry", "machine-building"]),
        ("side-table-500", "Side table 500x500", 500, 500, 450, 18, 30, "wood", "white",
         "furniture/tables/side-table", ["furniture", "consumer-products"]),
        ("desk-1200x600", "Desk 1200x600", 1200, 600, 740, 25, 40, "particle board + steel", "white",
         "furniture/tables/desk", ["office", "furniture"]),
        ("desk-1600x800", "Desk 1600x800", 1600, 800, 740, 25, 40, "particle board + steel", "white",
         "furniture/tables/desk", ["office", "furniture"]),
    ]
    for tid, label, w, d, h, top, leg, mat, color, cat, sectors in tables:
        out.append(Model(
            tid, S("table", w=w, d=d, h=h, top_t=top, leg=leg), label,
            f"{label}, height {h} mm, top {top} mm thick, {mat}.", cat, sectors, mat, color=color,
            tags=["table", cat.split("/")[-1]] + (["workshop table", "workshop"] if "workbench" in cat else []),
            properties={"height_mm": h}))
    for w, h in ((800, 1950), (1000, 1950)):
        out.append(Model(
            f"filing-cabinet-{w}", S("cabinet", w=w, d=420, h=h, t=1), f"Steel filing cabinet {w} mm",
            f"Steel cabinet with shelves, {w}x420x{h} mm.", "furniture/storage/cabinet",
            ["office", "industry"], "steel powder-coated", color="light-grey",
            tags=["cabinet", "filing cabinet", "cabinet", "storage cabinet"]))
    for w in (1000, 1500):
        out.append(Model(
            f"shelving-rack-{w}", S("shelving", w=w, d=500, h=2000, shelves=5), f"Shelving rack {w} mm 5 shelves",
            f"Warehouse rack {w}x500x2000 mm with 5 shelves.", "furniture/storage/rack",
            ["logistics", "industry"], "steel galvanized",
            tags=["rack", "rack", "warehouse rack", "shelving"], properties={"shelves": 5}))
    return out


def enclosures() -> list[Model]:
    out: list[Model] = []
    boxes = [(100, 68, 50, "ABS", "IP65", "light-grey"), (120, 80, 55, "ABS", "IP65", "light-grey"),
             (160, 110, 70, "ABS", "IP65", "light-grey"), (200, 120, 75, "ABS", "IP65", "light-grey"),
             (120, 80, 60, "PC", "IP67", "transparent"), (180, 130, 80, "PC", "IP67", "transparent"),
             (100, 100, 60, "aluminium", "IP66", "silver"), (160, 160, 90, "aluminium", "IP66", "silver")]
    for L, W_, H, mat, ip, color in boxes:
        out.append(Model(
            f"enclosure-{mat.lower()}-{L}x{W_}x{H}", S("enclosure", L=L, W_=W_, H=H, t=2.5 if mat != "aluminium" else 3),
            f"Electronics enclosure {L}x{W_}x{H} {mat} {ip}",
            f"Enclosure for electronics {L}x{W_}x{H} mm, {mat}, protection rating {ip}.",
            "enclosures/electronics/cabinet", ["electronics", "industry", "energy"], mat, color=color,
            tags=["enclosures", "enclosure", "electronics cabinet", "junction box", ip],
            standards=["EN 60529"], properties={"ip_rating": ip}))
    for L, W_, H in ((400, 300, 300), (600, 400, 400), (800, 600, 500)):
        out.append(Model(
            f"machine-guard-{L}x{W_}x{H}", S("guard", L=L, W_=W_, H=H, t=3), f"Machine guard {L}x{W_}x{H}",
            f"Guard for moving machine parts, {L}x{W_}x{H} mm, polycarbonate.",
            "enclosures/machine/guard", ["machine-building", "industry", "food"], "PC",
            color="transparent", tags=["guard", "guard cover", "machine guard"],
            standards=["EN ISO 14120"]))
    return out


def horticulture_and_construction() -> list[Model]:
    out: list[Model] = []
    for w, dpt in ((150, 80), (200, 100), (300, 120)):
        out.append(Model(
            f"greenhouse-gutter-{w}", S("gutter", width=w, depth=dpt, t=2, L=3000), f"Greenhouse gutter {w} mm aluminium",
            f"Roof gutter for horticultural greenhouses, width {w} mm, depth {dpt} mm, length 3 m.",
            "horticulture/greenhouse/gutter", ["horticulture"], "aluminium", tags=["gutter", "greenhouse gutter", "gutter", "greenhouse"]))
    for h in (60, 90):
        out.append(Model(
            f"greenhouse-profile-{h}", S("greenhouse_profile", h=h, b=50, t=3, L=3000), f"Greenhouse profile T {h} mm",
            f"Aluminium T-profile for glass retention in greenhouses, height {h} mm.", "horticulture/greenhouse/greenhouse-profile",
            ["horticulture"], "aluminium", tags=["greenhouse profile", "glazing bar", "greenhouse profile"]))
    for L, W_, H in ((600, 400, 200), (800, 600, 250), (1200, 800, 300)):
        out.append(Model(
            f"growing-tray-{L}x{W_}", S("tray", L=L, W_=W_, H=H, t=4), f"Growing tray {L}x{W_} mm black",
            f"Plastic growing tray {L}x{W_}x{H} mm for horticulture.", "horticulture/cultivation/tray",
            ["horticulture", "agriculture"], "PP", color="black", tags=["growing tray", "growing tray", "planter", "tray"]))
    for L in (2000, 4000):
        out.append(Model(
            f"ebb-flow-table-{L}", S("tray", L=L, W_=1200, H=80, t=3), f"Ebb-and-flow table {L}x1200 mm",
            f"Growing table with raised edge for ebb-and-flow irrigation, {L}x1200 mm.",
            "horticulture/cultivation/growing-table", ["horticulture"], "ABS", color="white",
            tags=["growing table", "ebb and flow", "rolling container", "growing table"]))
    for d in (90, 120, 170):
        out.append(Model(
            f"pot-{d}", S("pot", top_d=d, H=d * 0.85, t=1.2), f"Grow pot {d} mm",
            f"Round plastic grow pot, diameter {d} mm.", "horticulture/cultivation/pot", ["horticulture"], "PP",
            color="black", tags=["pot", "flower pot", "grow pot", "plant pot"]))
    for L in (100, 200):
        out.append(Model(
            f"hanging-hook-{L}", S("hook", wire_d=4, L=L), f"Hanging hook for crop wire {L} mm",
            f"Wire hook to hang plants or crop wire in the greenhouse, length {L} mm.",
            "horticulture/cultivation/hanging-system", ["horticulture"], "stainless steel", tags=["hook", "hanging hook", "hook"]))
    for b, h in ((70, 220), (100, 300)):
        out.append(Model(
            f"timber-beam-{b}x{h}", S("shaft_box", x=b, y=h, z=4000), f"Timber beam {b}x{h} mm C24",
            f"Sawn load-bearing beam {b}x{h} mm, strength class C24, length 4 m.",
            "construction/structure/beam", ["construction"], "wood", tags=["beam", "timber beam", "beam", "C24"],
            standards=["EN 338"]))
    return out


def piping_and_machine() -> list[Model]:
    out: list[Model] = []
    for dn, od, t in ((15, 21.3, 2), (25, 33.7, 2), (50, 60.3, 2.9)):
        out.append(Model(
            f"elbow-90-dn{dn}", S("pipe_bend", od=od, t=t, R=od * 1.5), f"Welded elbow 90° DN{dn}",
            f"Stainless steel welded elbow 90 degrees, DN{dn} ({od} mm).", "piping/pipe/elbow",
            ["food", "industry", "energy"], "stainless steel 316", tags=["bend", "elbow", "welded elbow", f"DN{dn}"],
            standards=["EN 10253"]))
    for dn, od, t in ((25, 33.7, 2), (50, 60.3, 2.9)):
        out.append(Model(
            f"tee-dn{dn}", S("tee", od=od, t=t, L=od * 2.5), f"Tee DN{dn}",
            f"Stainless steel equal tee DN{dn}.", "piping/pipe/tee", ["food", "industry"], "stainless steel 316",
            tags=["tee", "tee", "branch", f"DN{dn}"], standards=["EN 10253"]))
    for dn, D, bore, t, k, n, hole in ((25, 115, 34, 18, 85, 4, 14), (50, 165, 61, 20, 125, 4, 18),
                                       (80, 200, 90, 20, 160, 8, 18)):
        out.append(Model(
            f"weld-flange-dn{dn}-pn16", S("flange", D=D, bore=bore, t=t, k=k, n=n, hole=hole),
            f"Flat weld flange DN{dn} PN16", f"Flat weld flange DN{dn} PN16, {n} bolt holes.",
            "piping/flange/weld-flange", ["industry", "energy", "food"], "steel P250GH",
            tags=["flange", "weld flange", "flange", f"DN{dn}", "PN16"], standards=["EN 1092-1"],
            properties={"dn": dn, "pn": 16, "bolt_holes": n}))
    out.append(Model(
        "blind-flange-dn50-pn16", S("flange", D=165, bore=0, t=20, k=125, n=4, hole=18),
        "Blind flange DN50 PN16", "Blind flange to close off a pipe DN50.", "piping/flange/blind-flange",
        ["industry", "energy"], "steel P250GH", tags=["blind flange", "blind flange", "DN50"],
        standards=["EN 1092-1"]))
    for id_, cs in ((10, 2), (20, 2.5), (30, 3), (50, 3.5)):
        out.append(Model(
            f"o-ring-{id_}x{fmt(cs)}", S("o_ring", id_=id_, cs=cs), f"O-ring {id_}x{cs} NBR",
            f"Sealing ring inner diameter {id_} mm, cross-section {cs} mm, NBR 70.",
            "piping/sealing/o-ring", ["machine-building", "automotive", "food"], "rubber NBR",
            color="black", tags=["o-ring", "seal", "seal"], standards=["ISO 3601"]))
    for c in (96, 128, 160):
        out.append(Model(
            f"bar-handle-{c}", S("bow_handle", centers=c, d=10, h=35), f"Bar handle {c} mm centre-to-centre",
            f"Round bar handle, hole spacing {c} mm, for cabinets and machines.",
            "machine-elements/handle/bar-handle", ["furniture", "machine-building"], "stainless steel 304",
            tags=["handle", "handle", "handle", "cabinet handle"], properties={"center_distance_mm": c}))
    for d in (25, 40):
        out.append(Model(
            f"knob-{d}", S("knob", d=d, h=d, stud_d=8 if d < 40 else 10), f"Control knob {d} mm",
            f"Domed control knob diameter {d} mm with threaded stud.", "machine-elements/handle/knob",
            ["machine-building", "industry"], "PA", color="black", tags=["knob", "knob", "rotary knob"]))
    for t in (8, 10, 12):
        out.append(Model(
            f"levelling-foot-m{t}", S("leveling_foot", base_d=t * 5, thread_d=t, L=t * 6), f"Levelling foot M{t}",
            f"Adjustable foot with threaded stud M{t}, foot diameter {t * 5} mm.", "machine-elements/foot/leveling-foot",
            ["machine-building", "furniture", "industry"], "steel + nylon", tags=["levelling foot", "leveling foot", "foot"],
            properties={"thread": f"M{t}"}))
    for d in (50, 75, 100):
        out.append(Model(
            f"swivel-caster-{d}", S("castor", wheel_d=d, width=d * 0.35), f"Swivel caster {d} mm",
            f"Swivel caster with mounting plate for carts and trolleys, wheel diameter {d} mm, rubber tread.",
            "machine-elements/foot/swivel-caster", ["logistics", "furniture", "industry"], "steel + rubber",
            tags=["swivel caster", "wheel", "castor", "caster wheel", "cart wheel"], properties={"wheel_diameter_mm": d}))
    return out


def company_a() -> list[Model]:
    """Company A: horticulture company with its own designs."""
    c, out = "company_a", []
    for L, W_, H in ((1000, 400, 180), (1400, 400, 180), (1800, 600, 220), (2400, 600, 220),
                     (700, 350, 150), (1200, 1000, 300)):
        out.append(Model(
            f"a-growing-tray-tb{L}", S("tray", L=L, W_=W_, H=H, t=5), f"Growing tray TB-{L} (own design)",
            f"Own growing tray {L}x{W_}x{H} mm, reinforced bottom, for tomato growing.", "horticulture/cultivation/tray",
            ["horticulture"], "PE", color="black", company_id=c,
            tags=["growing tray", "tomato", "own design"]))
    for a in (60, 80, 100, 120, 150):
        out.append(Model(
            f"a-greenhouse-bracket-{a}", S("angle_bracket", a=a, b=a, w=40, t=4, hole=8.5), f"Greenhouse bracket KB-{a}",
            f"Own angle bracket {a} mm for fixing growing gutters to greenhouse posts.",
            "connections/bracket/angle-bracket", ["horticulture"], "steel hot-dip galvanized", company_id=c,
            tags=["greenhouse bracket", "angle bracket", "growing gutter", "own design"]))
    for w in (250, 350, 450):
        out.append(Model(
            f"a-growing-gutter-{w}", S("gutter", width=w, depth=60, t=1.5, L=6000), f"Growing gutter TG-{w}",
            f"Own growing gutter width {w} mm, length 6 m, for substrate growing.", "horticulture/greenhouse/gutter",
            ["horticulture"], "steel galvanized", company_id=c, tags=["growing gutter", "gutter", "substrate"]))
    for t in (10, 12, 16):
        out.append(Model(
            f"a-levelling-foot-m{t}", S("leveling_foot", base_d=t * 6, thread_d=t, L=t * 10),
            f"Levelling foot growing table M{t}", f"Own levelling foot M{t} for growing tables on an uneven greenhouse floor.",
            "machine-elements/foot/leveling-foot", ["horticulture"], "stainless steel", company_id=c,
            tags=["levelling foot", "growing table"]))
    for L in (150, 250, 350):
        out.append(Model(
            f"a-crop-hook-{L}", S("hook", wire_d=5, L=L), f"Crop hook GH-{L}",
            f"Own hook to tie up tomato plants, length {L} mm.", "horticulture/cultivation/hanging-system",
            ["horticulture"], "stainless steel", company_id=c, tags=["hook", "tomato", "tie up"]))
    return out


def company_b() -> list[Model]:
    """Company B: furniture maker with its own collection."""
    c, out = "company_b", []
    for color in ("green", "terracotta", "sand"):
        out.append(Model(
            f"b-garden-chair-lisse-{color}", S("chair_part", which="full", w=450, d=500, h=800, seat_h=440,
                                            leg=20, back=True, round_legs=True),
            f"Garden chair Lisse {color}", f"Own garden chair Lisse, compact and stackable, aluminium, {color}.",
            "furniture/seating/garden-chair", ["furniture", "hospitality", "horticulture"], "aluminium powder-coated",
            color=color, company_id=c, kind="part",
            tags=["garden chair", "chair", "lisse", "outdoor", "own collection"]))
    for color in ("oak", "black"):
        out.append(Model(
            f"b-dining-chair-otto-{color}", S("chair_part", which="full", w=430, d=510, h=830, seat_h=460,
                                          leg=30, back=True, round_legs=False),
            f"Dining chair Otto {color}", f"Own dining chair Otto, solid wood, {color}.",
            "furniture/seating/chair", ["furniture"], "wood", color=color, company_id=c,
            tags=["chair", "dining chair", "otto", "own collection"]))
    for w, d in ((1800, 900), (2200, 1000), (2600, 1000), (1200, 1200), (900, 900), (1400, 700)):
        out.append(Model(
            f"b-table-nora-{w}x{d}", S("table", w=w, d=d, h=750, top_t=40, leg=90), f"Table Nora {w}x{d}",
            f"Own solid oak table Nora {w}x{d} mm with thick legs.", "furniture/tables/dining-table",
            ["furniture", "hospitality"], "wood", color="oak", company_id=c,
            tags=["table", "dining table", "nora", "own collection"]))
    for L in (35, 50, 70, 90):
        out.append(Model(
            f"b-hinge-{L}", S("hinge", length=L, width=L * 0.3, t=1.5, knuckle_d=6),
            f"Cabinet hinge brass {L} mm", f"Own brass cabinet hinge {L} mm for the cabinet collection.",
            "connections/hinge/door-hinge", ["furniture"], "brass", company_id=c,
            tags=["hinge", "brass", "cabinet"]))
    for c_ in (64, 96, 128, 192, 256):
        out.append(Model(
            f"b-handle-{c_}", S("bow_handle", centers=c_, d=12, h=30), f"Furniture handle black {c_} mm",
            f"Own black furniture handle, hole spacing {c_} mm.", "machine-elements/handle/bar-handle",
            ["furniture"], "steel powder-coated", color="black", company_id=c,
            tags=["handle", "handle", "furniture handle", "black"]))
    return out


def catalog() -> list[Model]:
    return [*fasteners(), *connections(), *profiles(), *drive(), *furniture(),
            *enclosures(), *horticulture_and_construction(), *piping_and_machine(), *company_a(), *company_b()]


# =============================================================================
# Check and write out
# =============================================================================
def check(models: list[Model]) -> list[str]:
    tax = Taxonomy.load()
    errors, ids = [], set()
    for m in models:
        if m.id in ids:
            errors.append(f"{m.id}: duplicate id")
        ids.add(m.id)
        try:
            tax.validate_category(m.category_path)
            tax.validate_sectors(m.sectors)
        except ValueError as exc:
            errors.append(f"{m.id}: {exc}")
    for m in models:
        for comp in m.components:
            if comp["id"] not in ids:
                errors.append(f"{m.id}: component {comp['id']} does not exist")
    return errors


def build(model: Model):
    from testdata import shapes

    fn, kw = model.shape
    if fn == "chair_part":
        kw = dict(kw)
        which = kw.pop("which")
        leg, seat, back, full = shapes.chair_parts(**kw)
        return {"leg": leg, "seat": seat, "backrest": back, "full": full}[which]
    if fn == "bench_part":
        kw = dict(kw)
        kw.pop("which")
        return shapes.bench_parts(**kw)[3]
    if fn == "shaft_box":
        return shapes._box(kw["x"], kw["y"], kw["z"])
    return getattr(shapes, fn)(**kw)


def write(model: Model) -> Path:
    import cadquery as cq

    folder = model.folder()
    folder.mkdir(parents=True, exist_ok=True)
    step = folder / f"{model.id}.step"
    cq.exporters.export(build(model), str(step))
    meta = model.metadata()
    meta["files"] = [{"format": "step", "path": step.relative_to(PROJECT).as_posix(), "is_primary": True}]
    (folder / f"{model.id}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return step


def clean() -> int:
    removed = 0
    for meta_file in DATA.rglob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(meta, dict) and meta.get("source") == "generated":
            for f in (meta_file, meta_file.with_suffix(".step")):
                if f.exists():
                    f.unlink()
                    removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check metadata")
    ap.add_argument("--only", help="only ids that contain this text")
    ap.add_argument("--clean", action="store_true", help="first remove old test data")
    args = ap.parse_args()

    models = catalog()
    errors = check(models)
    libs: dict[str, int] = {}
    for m in models:
        key = m.company_id or "general"
        libs[key] = libs.get(key, 0) + 1
    print(f"{len(models)} models in the catalogue: " + ", ".join(f"{k} {v}" for k, v in libs.items()))
    if errors:
        print("ERRORS in the metadata:")
        for e in errors:
            print("  -", e)
        return 1
    if args.check:
        print("Metadata OK.")
        return 0

    if args.clean:
        print(f"{clean()} old files removed")
    selected = [m for m in models if not args.only or args.only in m.id]
    failed, start = [], time.time()
    for i, m in enumerate(selected, 1):
        try:
            write(m)
            print(f"[{i}/{len(selected)}] {m.id}")
        except Exception as exc:  # noqa: BLE001 - one failed model must not stop the rest
            failed.append(m.id)
            print(f"[{i}/{len(selected)}] ERROR {m.id}: {type(exc).__name__}: {exc}")

    manifest = [{"id": m.id, "name": m.name, "company_id": m.company_id, "category_path": m.category_path,
                 "kind": m.kind} for m in models if m.id not in failed]
    DATA.mkdir(exist_ok=True)
    (DATA / "testdata_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                                 encoding="utf-8")
    print(f"\nDone in {time.time() - start:.0f} s: {len(selected) - len(failed)} succeeded, {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
