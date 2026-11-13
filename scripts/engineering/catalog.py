"""Engineering catalogue for the Partsfinder demo library: what a mechanical engineer actually searches for.

Every item has exact, structured specs (designation, standard, dimensions, property class, ...) taken
from the public standards (ISO 15, EN 1092-1, ISO 15552, ISO 6432, NEMA ICS 16) or from the
conventional sizes of generic components (GT2 pulleys, T-slot profiles, profile rails, LMxUU bushings).

These are generic demo models made for Partsfinder itself; they carry no manufacturer and no manufacturer
part numbers. Ratings that differ per manufacturer (motor torque, current) are "typical" values for
that frame/length and are labelled as such in the description.

This file contains only data (no CadQuery), so it can be checked and used without CAD libraries.
The geometry is built in build.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SOURCE = "partsfinder-engineering"
LICENSE = "Partsfinder demo library (generic models, free to use)"
MECH = ["machine-building", "industry"]


@dataclass
class Item:
    id: str
    shape: str                                  # function name in build.py
    args: dict[str, Any]
    name: str
    description: str
    category_path: str
    material: str
    tags: list[str]
    properties: dict[str, Any]
    standards: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=lambda: list(MECH))

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": "part", "name": self.name, "description": self.description,
            "category_path": self.category_path, "sectors": self.sectors,
            "tags": list(dict.fromkeys(t.lower() for t in self.tags)),
            "material": self.material, "standards": self.standards, "properties": self.properties,
            "source": SOURCE, "source_ref": f"scripts/engineering ({self.shape})", "license": LICENSE,
        }


def g(x: float) -> str:
    return f"{x:g}"


def slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---- 1. deep groove ball bearings, ISO 15 (d, D, B) ---------------------------------------------
BEARINGS = {
    "623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6), "608": (8, 22, 7),
    "627": (7, 22, 7), "629": (9, 26, 8),
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10),
    "6004": (20, 42, 12), "6005": (25, 47, 12), "6006": (30, 55, 13), "6007": (35, 62, 14),
    "6008": (40, 68, 15), "6010": (50, 80, 16),
    "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12),
    "6204": (20, 47, 14), "6205": (25, 52, 15), "6206": (30, 62, 16), "6207": (35, 72, 17),
    "6208": (40, 80, 18), "6209": (45, 85, 19), "6210": (50, 90, 20),
    "6300": (10, 35, 11), "6301": (12, 37, 12), "6302": (15, 42, 13), "6303": (17, 47, 14),
    "6304": (20, 52, 15), "6305": (25, 62, 17), "6306": (30, 72, 19), "6308": (40, 90, 23),
}
SEALS = {"open": ("open", "no seals, for oil-bath or grease lubrication by the user"),
         "2RS": ("2RS", "rubber contact seals on both sides, greased for life"),
         "2Z": ("2Z", "metal shields on both sides (also called ZZ), greased for life")}


def bearings() -> list[Item]:
    out = []
    for code, (d, D, B) in BEARINGS.items():
        series = code[:2] if len(code) == 4 else code[:2]
        for seal, (label, seal_txt) in SEALS.items():
            desig = code if seal == "open" else f"{code}-{seal}"
            alt = [desig.lower().replace("-", ""), desig.lower()]
            if seal == "2Z":
                alt += [f"{code}zz", f"{code}-zz", "zz"]
            if seal == "2RS":
                alt += [f"{code}2rs", "2rs", "rs"]
            out.append(Item(
                id=f"eng-bearing-{slug(desig)}", shape="ball_bearing", args={"d": d, "D": D, "B": B, "seal": seal},
                name=f"Deep groove ball bearing {desig}, {g(d)}x{g(D)}x{g(B)} mm",
                description=(f"Single-row deep groove ball bearing {desig} according to ISO 15: bore d {g(d)} mm, "
                             f"outer diameter D {g(D)} mm, width B {g(B)} mm; {seal_txt}. Radial ball bearing "
                             f"for shafts of {g(d)} mm."),
                category_path="drivetrain/bearing/ball-bearing", material="bearing steel 100Cr6",
                tags=["ball bearing", "deep groove", "radial bearing", "rolling bearing", *alt, code,
                      f"{g(d)}x{g(D)}x{g(B)}"],
                standards=["ISO 15"],
                properties={"designation": desig, "bearing_type": "deep groove ball bearing", "series": series,
                            "inner_diameter_mm": d, "outer_diameter_mm": D, "width_mm": B,
                            "seal": label, "material_grade": "100Cr6"}))
    return out


# ---- 2. linear ball bushings LMxUU and linear shafts h6 -------------------------------------------
BUSHINGS = {6: (12, 19), 8: (15, 24), 10: (19, 29), 12: (21, 30), 16: (28, 37), 20: (32, 42),
            25: (40, 59), 30: (45, 64)}


def linear() -> list[Item]:
    out = []
    for d, (D, L) in BUSHINGS.items():
        desig = f"LM{d}UU"
        out.append(Item(
            id=f"eng-linear-bushing-lm{d}uu", shape="linear_bushing", args={"d": d, "D": D, "L": L},
            name=f"Linear ball bushing {desig}, {d}x{D}x{L} mm",
            description=(f"Linear ball bushing {desig} for a {d} mm h6 shaft: inner diameter {d} mm, outer diameter "
                         f"{D} mm, length {L} mm, with retaining ring grooves. Recirculating ball linear bearing."),
            category_path="drivetrain/bearing/linear-bushing", material="bearing steel 100Cr6",
            tags=["linear bearing", "linear bushing", "ball bushing", desig, f"lm{d}uu", "linear motion"],
            properties={"designation": desig, "bearing_type": "linear ball bushing", "inner_diameter_mm": d,
                        "outer_diameter_mm": D, "width_mm": L, "shaft_diameter_mm": d, "material_grade": "100Cr6"}))
    for d in (6, 8, 10, 12, 16, 20, 25):
        for L in (300, 500, 1000):
            out.append(Item(
                id=f"eng-linear-shaft-d{d}-l{L}", shape="shaft", args={"d": d, "L": L},
                name=f"Linear shaft Ø{d} h6 x {L} mm, hardened",
                description=(f"Precision linear shaft diameter {d} mm, tolerance h6, length {L} mm, induction hardened "
                             f"(approx. 60 HRC) and ground, steel Cf53 (1.1213). For linear ball bushings LM{d}UU."),
                category_path="drivetrain/shaft/shaft", material="steel Cf53 (1.1213), hardened",
                tags=["linear shaft", "guide shaft", "precision shaft", "hardened shaft", "h6", f"{d}mm", f"lm{d}uu"],
                properties={"shaft_diameter_mm": d, "length_mm": L, "tolerance": "h6", "hardness": "60 HRC",
                            "material_grade": "Cf53"}))
    return out


# ---- 3. pillow block bearings UCP2xx ----------------------------------------------------------------
PILLOW = {  # code: (bore, centre height H, total height, length L, bolt spacing J, base width A, bolt)
    "UCP204": (20, 33.3, 65, 127, 95, 38, "M10"), "UCP205": (25, 36.5, 71, 140, 105, 38, "M10"),
    "UCP206": (30, 42.9, 83, 165, 121, 48, "M14"), "UCP207": (35, 47.6, 93, 167, 127, 48, "M14"),
    "UCP208": (40, 49.2, 98, 184, 137, 54, "M14"), "UCP209": (45, 54.0, 106, 190, 146, 54, "M14"),
    "UCP210": (50, 57.2, 114, 206, 159, 60, "M16"),
}


def pillow_blocks() -> list[Item]:
    out = []
    for code, (bore, H, Ht, L, J, A, bolt) in PILLOW.items():
        insert = "UC" + code[3:]
        out.append(Item(
            id=f"eng-pillow-block-{code.lower()}", shape="pillow_block",
            args={"bore": bore, "H": H, "Ht": Ht, "L": L, "J": J, "A": A},
            name=f"Pillow block bearing {code}, bore {bore} mm",
            description=(f"Pillow block bearing unit {code}: cast iron housing with insert bearing {insert} and set "
                         f"screws, bore {bore} mm, shaft centre height {g(H)} mm, length {L} mm, bolt spacing {J} mm, "
                         f"fixing bolts {bolt}. Plummer block for a {bore} mm shaft."),
            category_path="drivetrain/bearing/pillow-block", material="cast iron EN-GJL-200 housing, 100Cr6 insert",
            tags=["pillow block", "plummer block", "bearing unit", "ucp", code, insert, f"{bore}mm shaft"],
            properties={"designation": code, "bore_mm": bore, "shaft_diameter_mm": bore, "centre_height_mm": H,
                        "bolt_spacing_mm": J, "fixing_bolt": bolt, "insert_bearing": insert,
                        "material_grade": "EN-GJL-200"}))
    return out


# ---- 4. hybrid stepper motors NEMA 17/23/34 (typical ratings, 1.8°) --------------------------------
NEMA = {  # frame: (flange mm, hole spacing mm, pilot dia, pilot height, mount hole thread/dia)
    17: (42.3, 31.0, 22.0, 2.0, "M3"), 23: (56.4, 47.14, 38.1, 1.6, "Ø5.1"), 34: (86.0, 69.6, 73.0, 2.0, "Ø6.5"),
}
STEPPERS = [  # frame, body length, typical holding torque Nm, rated current A, shaft dia, shaft length
    (17, 34, 0.28, 1.0, 5, 24), (17, 40, 0.42, 1.5, 5, 24), (17, 48, 0.55, 1.7, 5, 24), (17, 60, 0.65, 2.0, 5, 24),
    (23, 41, 0.55, 2.8, 6.35, 21), (23, 56, 1.26, 2.8, 6.35, 21), (23, 76, 1.89, 3.0, 8, 21), (23, 100, 3.0, 4.2, 8, 21),
    (34, 66, 3.5, 4.0, 14, 32), (34, 98, 8.5, 6.0, 14, 32), (34, 114, 12.0, 6.0, 14, 32),
]


def steppers() -> list[Item]:
    out = []
    for frame, length, torque, amps, shaft, sl in STEPPERS:
        flange, holes, pilot, ph, mount = NEMA[frame]
        out.append(Item(
            id=f"eng-stepper-nema{frame}-{length}", shape="stepper",
            args={"flange": flange, "length": length, "holes": holes, "pilot": pilot, "ph": ph,
                  "shaft": shaft, "shaft_len": sl},
            name=f"Stepper motor NEMA {frame}, {length} mm body, {g(torque)} Nm, shaft Ø{g(shaft)} mm",
            description=(f"Two-phase hybrid stepper motor NEMA {frame} (flange {g(flange)} mm square, mounting holes "
                         f"{g(holes)} mm apart, {mount}), body length {length} mm, typical holding torque {g(torque)} Nm, "
                         f"rated current {g(amps)} A per phase, step angle 1.8° (200 steps/rev), round shaft "
                         f"Ø{g(shaft)} x {sl} mm, pilot Ø{g(pilot)} mm. Ratings are typical for this frame size."),
            category_path="electrical/motor/stepper-motor", material="steel, aluminium end caps",
            tags=["stepper motor", "step motor", "hybrid stepper", f"nema {frame}", f"nema{frame}", "1.8 degree",
                  "cnc", "3d printer", "motion control"],
            standards=["NEMA ICS 16"],
            properties={"frame_size": frame, "body_length_mm": length, "holding_torque_nm": torque,
                        "rated_current_a": amps, "step_angle_deg": 1.8, "shaft_diameter_mm": shaft,
                        "shaft_length_mm": sl, "flange_mm": flange, "mounting_hole_spacing_mm": holes,
                        "pilot_diameter_mm": pilot, "phases": 2}))
    return out


# ---- 5. timing pulleys GT2 and HTD 5M ----------------------------------------------------------------
def pulleys() -> list[Item]:
    out = []
    combos = [(z, b, w) for z in (16, 20, 40, 60) for b in (5, 8) for w in (6, 10)] + [(20, 6.35, 6), (36, 8, 6)]
    for z, bore, w in combos:
        pd = z * 2.0 / math.pi
        od = pd - 0.508
        out.append(Item(
            id=f"eng-pulley-gt2-{z}t-b{g(bore).replace('.', '_')}-w{w}", shape="timing_pulley",
            args={"z": z, "od": od, "bore": bore, "width": w + 1, "pitch": 2.0},
            name=f"Timing pulley GT2 {z}T, bore {g(bore)} mm, for {w} mm belt",
            description=(f"GT2 (2GT) timing pulley with {z} teeth, pitch 2 mm, pitch diameter {pd:.2f} mm, outer "
                         f"diameter {od:.2f} mm, bore {g(bore)} mm, for a {w} mm wide GT2 belt; flanged, hub with "
                         f"two M3 set screws. Aluminium."),
            category_path="drivetrain/transmission/timing-pulley", material="aluminium 6061-T6",
            tags=["timing pulley", "gt2", "2gt", "belt pulley", "toothed pulley", f"{z}t", f"{z} teeth", "3d printer", "cnc"],
            properties={"belt_profile": "GT2", "teeth": z, "pitch_mm": 2.0, "pitch_diameter_mm": round(pd, 2),
                        "outer_diameter_mm": round(od, 2), "bore_mm": bore, "belt_width_mm": w,
                        "material_grade": "6061-T6"}))
    for z in (15, 20, 30, 40):
        for bore in (8, 12):
            pd = z * 5.0 / math.pi
            od = pd - 1.14
            out.append(Item(
                id=f"eng-pulley-htd5m-{z}t-b{bore}", shape="timing_pulley",
                args={"z": z, "od": od, "bore": bore, "width": 17, "pitch": 5.0},
                name=f"Timing pulley HTD 5M {z}T, bore {bore} mm, for 15 mm belt",
                description=(f"HTD 5M timing pulley with {z} teeth, pitch 5 mm, pitch diameter {pd:.2f} mm, outer "
                             f"diameter {od:.2f} mm, pilot bore finished to {bore} mm H7, for 15 mm wide HTD 5M belts; "
                             f"flanged. Aluminium."),
                category_path="drivetrain/transmission/timing-pulley", material="aluminium 6082-T6",
                tags=["timing pulley", "htd", "htd 5m", "5m", "belt pulley", f"{z}t", f"{z} teeth"],
                properties={"belt_profile": "HTD 5M", "teeth": z, "pitch_mm": 5.0, "pitch_diameter_mm": round(pd, 2),
                            "outer_diameter_mm": round(od, 2), "bore_mm": bore, "belt_width_mm": 15,
                            "material_grade": "6082-T6"}))
    return out


# ---- 6. spur gears, module 1 - 3, 20° pressure angle -----------------------------------------------
def gears() -> list[Item]:
    out = []
    for m in (1, 1.5, 2, 3):
        for z in (15, 20, 30, 40, 60):
            pd = m * z
            b = 10 * m
            bore = max(5, min(round(pd * 0.3 / 2) * 2, 40))
            out.append(Item(
                id=f"eng-spur-gear-m{g(m).replace('.', '_')}-z{z}", shape="spur_gear",
                args={"m": m, "z": z, "b": b, "bore": bore},
                name=f"Spur gear module {g(m)}, {z} teeth, bore {bore} mm",
                description=(f"Straight spur gear module {g(m)} (m{g(m)}), {z} teeth, pressure angle 20°, pitch diameter "
                             f"{g(pd)} mm, tip diameter {g(pd + 2 * m)} mm, face width {g(b)} mm, pilot bore {bore} mm. "
                             f"Steel C45, quality 8 according to DIN 3961."),
                category_path="drivetrain/gear/spur", material="steel C45",
                tags=["spur gear", "gear wheel", "cog", "straight tooth", f"module {g(m)}", f"m{g(m)}", f"z{z}",
                      f"{z} teeth", "gearing"],
                standards=["DIN 867", "DIN 3961"],
                properties={"module": m, "teeth": z, "pressure_angle_deg": 20, "pitch_diameter_mm": pd,
                            "tip_diameter_mm": pd + 2 * m, "face_width_mm": b, "bore_mm": bore,
                            "material_grade": "C45"}))
    return out


# ---- 7. aluminium T-slot profiles -----------------------------------------------------------------
PROFILES = [  # (w, h, slot, core bore)
    (20, 20, 6, 4.2), (30, 30, 8, 6.8), (40, 40, 8, 8.5), (40, 80, 8, 8.5), (45, 45, 10, 10.2), (80, 80, 8, 8.5),
]


def profiles() -> list[Item]:
    out = []
    for w, h, slot, core in PROFILES:
        for L in (500, 1000):
            size = f"{w}x{h}"
            out.append(Item(
                id=f"eng-tslot-{size}-s{slot}-l{L}", shape="tslot_profile",
                args={"w": w, "h": h, "slot": slot, "core": core, "L": L},
                name=f"Aluminium T-slot profile {size} slot {slot}, length {L} mm",
                description=(f"Aluminium T-slot extrusion {size} mm with {slot} mm slots on all sides, centre bore "
                             f"Ø{g(core)} mm for M{int(core + 1.5) if core < 9 else 12} tapping, length {L} mm, cut "
                             f"square. Aluminium EN AW-6063 T5, clear anodised. System profile for machine frames."),
                category_path="profiles/aluminium/system-profile", material="aluminium EN AW-6063 T5, anodised",
                tags=["t-slot profile", "aluminium profile", "extrusion", "system profile", "machine frame",
                      size, f"slot {slot}", f"slot{slot}", "t-slot"],
                properties={"profile_size": size, "slot_width_mm": slot, "length_mm": L, "core_bore_mm": core,
                            "material_grade": "6063-T5"}))
    return out


# ---- 8. pneumatic cylinders ISO 15552 and ISO 6432 ------------------------------------------------
ISO15552 = {32: (12, "G1/8", "M10x1.25", 45), 40: (16, "G1/4", "M12x1.25", 52), 50: (20, "G1/4", "M16x1.5", 64),
            63: (20, "G3/8", "M16x1.5", 75), 80: (25, "G3/8", "M20x1.5", 93), 100: (25, "G1/2", "M20x1.5", 110)}
ISO6432 = {12: (6, "M5", "M6"), 16: (6, "M5", "M6"), 20: (8, "G1/8", "M8"), 25: (10, "G1/8", "M10x1.25")}


def cylinders() -> list[Item]:
    out = []
    for bore, (rod, port, rodthr, sq) in ISO15552.items():
        for stroke in (50, 100, 200):
            out.append(Item(
                id=f"eng-cylinder-iso15552-d{bore}-s{stroke}", shape="cylinder_iso15552",
                args={"bore": bore, "rod": rod, "stroke": stroke, "sq": sq},
                name=f"Pneumatic cylinder ISO 15552 Ø{bore} x {stroke} mm stroke",
                description=(f"Double-acting pneumatic profile cylinder according to ISO 15552, piston diameter {bore} mm, "
                             f"stroke {stroke} mm, piston rod Ø{rod} mm with thread {rodthr}, ports {port}, adjustable "
                             f"end-position cushioning, magnetic piston for sensors; max. 10 bar."),
                category_path="pneumatics/cylinder/pneumatic-cylinder", material="aluminium barrel, stainless rod 1.4301",
                tags=["pneumatic cylinder", "air cylinder", "profile cylinder", "double acting", "iso 15552",
                      "vdma", f"ø{bore}", f"{bore}x{stroke}"],
                standards=["ISO 15552"],
                properties={"piston_diameter_mm": bore, "stroke_mm": stroke, "rod_diameter_mm": rod,
                            "rod_thread": rodthr, "port_thread": port, "action": "double acting",
                            "max_pressure_bar": 10, "magnetic_piston": True}))
    for bore, (rod, port, rodthr) in ISO6432.items():
        for stroke in (25, 50, 100):
            out.append(Item(
                id=f"eng-cylinder-iso6432-d{bore}-s{stroke}", shape="cylinder_round",
                args={"bore": bore, "rod": rod, "stroke": stroke},
                name=f"Mini pneumatic cylinder ISO 6432 Ø{bore} x {stroke} mm stroke",
                description=(f"Double-acting round mini cylinder according to ISO 6432, piston diameter {bore} mm, stroke "
                             f"{stroke} mm, piston rod Ø{rod} mm with thread {rodthr}, ports {port}, elastic cushioning, "
                             f"magnetic piston; stainless steel barrel; max. 10 bar."),
                category_path="pneumatics/cylinder/pneumatic-cylinder", material="stainless steel 1.4301",
                tags=["pneumatic cylinder", "mini cylinder", "round cylinder", "double acting", "iso 6432",
                      f"ø{bore}", f"{bore}x{stroke}"],
                standards=["ISO 6432"],
                properties={"piston_diameter_mm": bore, "stroke_mm": stroke, "rod_diameter_mm": rod,
                            "rod_thread": rodthr, "port_thread": port, "action": "double acting",
                            "max_pressure_bar": 10, "magnetic_piston": True}))
    return out


# ---- 9. flanges EN 1092-1 PN16 ---------------------------------------------------------------------
FLANGES = {  # DN: (pipe OD, D, k, holes, hole dia, bolt, thickness)
    15: (21.3, 95, 65, 4, 14, "M12", 16), 20: (26.9, 105, 75, 4, 14, "M12", 18), 25: (33.7, 115, 85, 4, 14, "M12", 18),
    32: (42.4, 140, 100, 4, 18, "M16", 18), 40: (48.3, 150, 110, 4, 18, "M16", 18), 50: (60.3, 165, 125, 4, 18, "M16", 18),
    65: (76.1, 185, 145, 8, 18, "M16", 18), 80: (88.9, 200, 160, 8, 18, "M16", 20), 100: (114.3, 220, 180, 8, 18, "M16", 20),
    125: (139.7, 250, 210, 8, 18, "M16", 22), 150: (168.3, 285, 240, 8, 22, "M20", 22),
}
FLANGE_TYPES = {"01": ("plate flange (slip-on)", "piping/flange/loose-flange", "type 01 plate flange"),
                "05": ("blind flange", "piping/flange/blind-flange", "type 05 blind flange"),
                "11": ("weld neck flange", "piping/flange/weld-flange", "type 11 weld neck flange")}


def flanges() -> list[Item]:
    out = []
    for dn, (pod, D, k, n, hd, bolt, t) in FLANGES.items():
        for typ, (label, cat, long) in FLANGE_TYPES.items():
            out.append(Item(
                id=f"eng-flange-en1092-t{typ}-dn{dn}-pn16", shape="flange",
                args={"typ": typ, "pod": pod, "D": D, "k": k, "n": n, "hd": hd, "t": t},
                name=f"{label.capitalize()} EN 1092-1 type {typ} DN{dn} PN16",
                description=(f"Steel {long} according to EN 1092-1, DN{dn} PN16, for pipe OD {g(pod)} mm: outer diameter "
                             f"{D} mm, bolt circle {k} mm, {n} holes Ø{hd} mm for {n}x {bolt} bolts, flange thickness "
                             f"{t} mm, raised face (form B1). Available in P250GH and stainless 1.4404 (same geometry)."),
                category_path=cat, material="steel P250GH or stainless 1.4404",
                tags=["flange", label, "pipe flange", "en 1092-1", f"dn{dn}", "pn16", f"type {typ}", "din 2501"],
                standards=["EN 1092-1"], sectors=["industry", "machine-building", "energy", "food"],
                properties={"dn": dn, "pn": 16, "flange_type": f"Type {typ} ({label})", "pipe_od_mm": pod,
                            "outer_diameter_mm": D, "bolt_circle_mm": k, "bolt_holes": n, "hole_diameter_mm": hd,
                            "bolts": f"{n}x {bolt}", "thickness_mm": t, "face": "B1 raised face",
                            "material_grades": ["P250GH", "1.4404"]}))
    return out


# ---- 10. profile rail linear guides (size 15/20/25) --------------------------------------------------
RAILS = {15: (15, 15, 34, 61.4, 28, 60), 20: (20, 17.5, 44, 77.5, 30, 60), 25: (23, 22, 48, 84, 40, 60)}


def rails() -> list[Item]:
    out = []
    for size, (rw, rh, cw, cl, ch, pitch) in RAILS.items():
        for L in (300, 500, 1000):
            out.append(Item(
                id=f"eng-rail-size{size}-l{L}", shape="rail", args={"rw": rw, "rh": rh, "L": L, "pitch": pitch},
                name=f"Profile rail size {size}, length {L} mm",
                description=(f"Ball-type profile rail (linear guide rail) size {size}: rail width {rw} mm, height {g(rh)} mm, "
                             f"length {L} mm, counterbored mounting holes every {pitch} mm. Hardened bearing steel. "
                             f"Mates with size {size} blocks."),
                category_path="machine-elements/guide/rail", material="bearing steel, hardened",
                tags=["linear guide", "profile rail", "guide rail", "linear rail", f"size {size}", f"{size}mm rail",
                      "linear motion"],
                properties={"rail_size": size, "rail_width_mm": rw, "rail_height_mm": rh, "length_mm": L,
                            "hole_pitch_mm": pitch}))
        out.append(Item(
            id=f"eng-carriage-size{size}", shape="carriage", args={"cw": cw, "cl": cl, "ch": ch, "rw": rw, "rh": rh},
            name=f"Linear guide carriage for profile rail size {size}, standard block",
            description=(f"Ball-type carriage (block) for profile rail size {size}: width {cw} mm, length {g(cl)} mm, "
                         f"assembly height {ch} mm, four threaded mounting holes, preload class light, with end seals "
                         f"and grease nipple."),
            category_path="machine-elements/guide/linear-guide", material="bearing steel, hardened",
            tags=["linear guide", "carriage", "block", "linear bearing block", f"size {size}", "linear motion"],
            properties={"rail_size": size, "width_mm": cw, "length_mm": cl, "assembly_height_mm": ch,
                        "preload": "light"}))
    return out


# ---- 11. jaw couplings ------------------------------------------------------------------------------
COUPLINGS = [(19, 25, 5, 8), (19, 25, 6.35, 8), (19, 25, 8, 8), (25, 30, 8, 10), (25, 30, 10, 12), (30, 35, 12, 14)]


def couplings() -> list[Item]:
    out = []
    for od, length, b1, b2 in COUPLINGS:
        out.append(Item(
            id=f"eng-coupling-jaw-d{od}-{g(b1).replace('.', '_')}-{g(b2)}", shape="coupling",
            args={"od": od, "L": length, "b1": b1, "b2": b2},
            name=f"Jaw coupling D{od} L{length}, bores {g(b1)} - {g(b2)} mm",
            description=(f"Flexible jaw coupling (spider coupling) outer diameter {od} mm, length {length} mm, bores "
                         f"{g(b1)} mm and {g(b2)} mm with set screws, polyurethane spider 92 Shore A. Connects a motor "
                         f"shaft of {g(b1)} mm to a {g(b2)} mm shaft, compensates misalignment."),
            category_path="connections/coupling/shaft-coupling", material="aluminium 7075, PU spider",
            tags=["shaft coupling", "jaw coupling", "spider coupling", "flexible coupling", "motor coupling",
                  f"{g(b1)}mm", f"{g(b2)}mm"],
            properties={"outer_diameter_mm": od, "length_mm": length, "bore_mm": [b1, b2], "bore_1_mm": b1,
                        "bore_2_mm": b2, "material_grade": "7075"}))
    return out


# ---- 12. common bolt lengths missing from the bd_warehouse set, and nyloc nuts --------------------
# head dimensions: ISO 4762 (dk, k, s socket) and ISO 4017 (s across flats, k)
SHCS = {"M3": (5.5, 3, 2.5), "M4": (7, 4, 3), "M5": (8.5, 5, 4), "M6": (10, 6, 5), "M8": (13, 8, 6),
        "M10": (16, 10, 8), "M12": (18, 12, 10), "M16": (24, 16, 14)}
HEX = {"M5": (8, 3.5), "M6": (10, 4), "M8": (13, 5.3), "M10": (16, 6.4), "M12": (18, 7.5), "M16": (24, 10),
       "M20": (30, 12.5)}
PITCH = {"M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75, "M16": 2.0, "M20": 2.5}
SHCS_LENGTHS = {"M3": [10, 20], "M4": [12, 20], "M5": [10, 16, 20, 30], "M6": [12, 16, 25, 35, 40, 50, 60],
                "M8": [16, 20, 30, 35, 45, 60, 70, 80], "M10": [20, 25, 35, 40, 50, 60, 80, 100],
                "M12": [25, 30, 40, 45, 50, 60, 80, 100], "M16": [30, 35, 40, 50, 60, 80, 100]}
HEX_LENGTHS = {"M5": [10, 12, 20, 25], "M6": [12, 16, 25, 30, 40, 50], "M8": [16, 20, 25, 35, 40, 50, 70, 80],
               "M10": [20, 25, 30, 40, 45, 50, 60, 70], "M12": [25, 30, 35, 45, 50, 70, 80],
               "M16": [30, 35, 40, 45, 60, 70, 100], "M20": [40, 50, 60, 70, 80, 100]}
NYLOC = {"M3": (5.5, 4), "M4": (7, 5), "M5": (8, 5), "M6": (10, 6), "M8": (13, 8), "M10": (16, 10),
         "M12": (18, 12), "M16": (24, 16), "M20": (30, 20)}


def fasteners() -> list[Item]:
    out = []
    for t, lengths in SHCS_LENGTHS.items():
        dk, k, sw = SHCS[t]
        d = float(t[1:])
        for L in lengths:
            out.append(Item(
                id=f"eng-shcs-iso4762-{t.lower()}x{L}", shape="socket_head_bolt",
                args={"d": d, "L": L, "dk": dk, "k": k, "s": sw},
                name=f"Socket head bolt {t}x{L} ISO 4762 (DIN 912)",
                description=(f"Hexagon socket head cap screw {t}x{L} mm according to ISO 4762 / DIN 912, metric coarse "
                             f"thread {t} x {PITCH[t]:g}, head diameter {g(dk)} mm, head height {g(k)} mm, socket "
                             f"{g(sw)} mm. Valid for property class 8.8, 10.9, 12.9 and stainless A2-70 / A4-80 "
                             f"(same geometry). Thread shown simplified."),
                category_path="fasteners/bolt/socket-head-bolt",
                material="steel 8.8 / 10.9 / 12.9 or stainless A2-70 / A4-80",
                tags=["socket head", "cap screw", "shcs", "allen bolt", "socket head cap screw", t.lower(),
                      f"{t.lower()}x{L}"],
                standards=["ISO 4762", "DIN 912"], sectors=["industry", "machine-building", "construction"],
                properties={"designation": f"ISO 4762 {t}x{L}", "thread": t, "pitch_mm": PITCH[t], "length_mm": L,
                            "head_diameter_mm": dk, "head_height_mm": k, "drive": f"hex socket {g(sw)} mm",
                            "property_classes": ["8.8", "10.9", "12.9", "A2-70", "A4-80"]}))
    for t, lengths in HEX_LENGTHS.items():
        sw, k = HEX[t]
        d = float(t[1:])
        for L in lengths:
            out.append(Item(
                id=f"eng-hex-iso4017-{t.lower()}x{L}", shape="hex_bolt", args={"d": d, "L": L, "s": sw, "k": k},
                name=f"Hex bolt fully threaded {t}x{L} ISO 4017 (DIN 933)",
                description=(f"Hexagon head screw {t}x{L} mm, thread to head, according to ISO 4017 / DIN 933, metric "
                             f"coarse thread {t} x {PITCH[t]:g}, width across flats {g(sw)} mm, head height {g(k)} mm. "
                             f"Valid for property class 8.8, 10.9 and stainless A2-70 / A4-70 (same geometry)."),
                category_path="fasteners/bolt/hex-bolt", material="steel 8.8 / 10.9 or stainless A2-70 / A4-70",
                tags=["hex bolt", "hex head screw", "tap bolt", "set screw (uk)", t.lower(), f"{t.lower()}x{L}"],
                standards=["ISO 4017", "DIN 933"], sectors=["industry", "machine-building", "construction"],
                properties={"designation": f"ISO 4017 {t}x{L}", "thread": t, "pitch_mm": PITCH[t], "length_mm": L,
                            "width_across_flats_mm": sw, "head_height_mm": k,
                            "property_classes": ["8.8", "10.9", "A2-70", "A4-70"]}))
    for t, (sw, h) in NYLOC.items():
        out.append(Item(
            id=f"eng-nyloc-iso10511-{t.lower()}", shape="nyloc_nut", args={"d": float(t[1:]), "s": sw, "h": h},
            name=f"Nyloc nut {t} ISO 10511 (DIN 985)",
            description=(f"Prevailing torque hexagon lock nut with nylon insert {t} according to ISO 10511 / DIN 985 "
                         f"(thin type), width across flats {g(sw)} mm, height {g(h)} mm, thread {t} x {PITCH[t]:g}. "
                         f"Property class 8 / 10 or stainless A2-70."),
            category_path="fasteners/nut/lock-nut", material="steel class 8 / 10 or stainless A2-70, PA insert",
            tags=["nyloc", "lock nut", "self-locking nut", "nylon insert nut", "locknut", t.lower()],
            standards=["ISO 10511", "DIN 985"], sectors=["industry", "machine-building", "construction"],
            properties={"designation": f"ISO 10511 {t}", "thread": t, "pitch_mm": PITCH[t],
                        "width_across_flats_mm": sw, "height_mm": h, "property_classes": ["8", "10", "A2-70"]}))
    return out


# ---- 13. dowel pins, threaded rod, T-slot nuts, profile corner brackets, shaft collars ------------
DOWELS = {3: [10, 16, 20], 4: [12, 20, 30], 5: [12, 20, 30], 6: [16, 20, 30, 40], 8: [20, 30, 40], 10: [30, 40, 60]}
RODS = ["M6", "M8", "M10", "M12", "M16"]
TNUTS = [(6, "M4"), (6, "M5"), (8, "M4"), (8, "M5"), (8, "M6"), (8, "M8"), (10, "M5"), (10, "M6"), (10, "M8")]
CORNERS = {"20x20": (20, 6, 18, "M5"), "30x30": (30, 8, 28, "M6"), "40x40": (40, 8, 38, "M8"),
           "45x45": (45, 10, 43, "M8")}
COLLARS = {6: (12, 8, "M4"), 8: (16, 8, "M5"), 10: (20, 10, "M6"), 12: (22, 12, "M6"), 16: (28, 12, "M6"),
           20: (32, 14, "M8"), 25: (40, 16, "M8")}


def small_parts() -> list[Item]:
    out = []
    for d, lengths in DOWELS.items():
        for L in lengths:
            out.append(Item(
                id=f"eng-dowel-iso8734-{d}x{L}", shape="dowel_pin", args={"d": d, "L": L},
                name=f"Dowel pin {d}x{L} mm ISO 8734 (DIN 6325), m6",
                description=(f"Hardened parallel dowel pin {d} x {L} mm according to ISO 8734 / DIN 6325, tolerance m6, "
                             f"one end chamfered and one end rounded, steel 100Cr6 hardened 58-62 HRC. For exact "
                             f"location of parts; hole H7."),
                category_path="fasteners/pin/dowel-pin", material="steel 100Cr6, hardened",
                tags=["dowel pin", "parallel pin", "locating pin", "cylindrical pin", f"{d}x{L}", "m6"],
                standards=["ISO 8734", "DIN 6325"],
                properties={"designation": f"ISO 8734 {d}x{L}", "diameter_mm": d, "length_mm": L,
                            "tolerance": "m6", "hardness": "58-62 HRC", "material_grade": "100Cr6"}))
    for t in RODS:
        d = float(t[1:])
        out.append(Item(
            id=f"eng-threaded-rod-din976-{t.lower()}-l1000", shape="threaded_rod", args={"d": d, "L": 1000},
            name=f"Threaded rod {t} x 1000 mm DIN 976-1",
            description=(f"Fully threaded rod (stud bar) {t} x 1000 mm according to DIN 976-1, metric coarse thread "
                         f"{t} x {PITCH[t]:g}. Property class 8.8, also in 4.8 and stainless A2-70 / A4-70 "
                         f"(same geometry). Thread shown simplified."),
            category_path="drivetrain/shaft/threaded-rod", material="steel 8.8 or stainless A2-70 / A4-70",
            tags=["threaded rod", "studding", "stud bar", "all-thread", "allthread", t.lower()],
            standards=["DIN 976-1"], sectors=["industry", "machine-building", "construction"],
            properties={"designation": f"DIN 976-1 {t}x1000", "thread": t, "pitch_mm": PITCH[t], "length_mm": 1000,
                        "property_classes": ["4.8", "8.8", "A2-70", "A4-70"]}))
    for slot, t in TNUTS:
        out.append(Item(
            id=f"eng-tnut-slot{slot}-{t.lower()}", shape="t_nut", args={"slot": slot, "d": float(t[1:])},
            name=f"T-slot nut slot {slot} {t}, drop-in",
            description=(f"Drop-in T-slot nut (sliding nut) for aluminium profiles with {slot} mm slot, thread {t}, "
                         f"with spring ball so it stays in place; can be inserted after assembly. Steel, zinc plated."),
            category_path="fasteners/nut/insert-nut", material="steel, zinc plated",
            tags=["t-nut", "t-slot nut", "slot nut", "sliding nut", "drop-in nut", f"slot {slot}", t.lower()],
            sectors=["machine-building", "industry"],
            properties={"designation": f"T-nut slot {slot} {t}", "slot_width_mm": slot, "thread": t}))
    for size, (w, slot, leg, bolt) in CORNERS.items():
        out.append(Item(
            id=f"eng-corner-bracket-{size}", shape="corner_bracket", args={"leg": leg, "w": w, "t": max(3, w / 8)},
            name=f"Corner bracket for T-slot profile {size} slot {slot}",
            description=(f"Die-cast angle bracket (corner bracket) for T-slot profiles {size} with {slot} mm slot: legs "
                         f"{leg} mm, width {w} mm, holes for {bolt} bolts with T-slot nuts. Joins two profiles at "
                         f"a right angle. Aluminium, anodised."),
            category_path="connections/bracket/angle-bracket", material="die-cast aluminium, anodised",
            tags=["corner bracket", "angle bracket", "profile connector", "t-slot bracket", "right angle", size,
                  f"slot {slot}"],
            sectors=["machine-building", "industry"],
            properties={"profile_size": size, "slot_width_mm": slot, "leg_mm": leg, "fixing_bolt": bolt}))
    for d, (od, b, screw) in COLLARS.items():
        out.append(Item(
            id=f"eng-shaft-collar-din705-{d}", shape="shaft_collar", args={"d": d, "od": od, "b": b},
            name=f"Shaft collar {d} mm DIN 705 with set screw",
            description=(f"Set collar (shaft collar) for a {d} mm shaft according to DIN 705 form A: bore {d} mm, "
                         f"outer diameter {od} mm, width {b} mm, one {screw} set screw (ISO 4027). Steel, "
                         f"zinc plated. Axial stop on a shaft."),
            category_path="drivetrain/shaft/shaft", material="steel, zinc plated",
            tags=["shaft collar", "set collar", "adjusting ring", "stop collar", f"{d}mm"],
            standards=["DIN 705"],
            properties={"designation": f"DIN 705 A {d}", "bore_mm": d, "shaft_diameter_mm": d, "outer_diameter_mm": od,
                        "width_mm": b, "set_screw": screw}))
    return out


def catalog() -> list[Item]:
    items = (bearings() + linear() + pillow_blocks() + steppers() + pulleys() + gears() + profiles()
             + cylinders() + flanges() + rails() + couplings() + fasteners() + small_parts())
    ids = [i.id for i in items]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate ids: {sorted(dup)[:5]}")
    return items


if __name__ == "__main__":
    from collections import Counter

    items = catalog()
    print(len(items), "items")
    print(Counter(i.category_path for i in items))
