"""Real standard parts for the demo library, generated with bd_warehouse (Apache-2.0).

Makes ~500 parts (bolts, screws, nuts, washers, retaining rings, keys, bearings, O-rings,
gears, sprockets, OpenBuilds parts) with the dimensions from the standard, each as STEP + JSON
with the metadata (standard, thread size, length, source and licence).

bd_warehouse uses build123d, which needs a different OCP version than CadQuery. So run this
in a separate environment:
    python -m venv .venv-bd && .venv-bd/bin/pip install bd_warehouse==0.4.0
    .venv-bd/bin/python scripts/demo/standard_parts.py [--out data/global/standard-parts] [--only text]

Threads are shown simplified (as in most CAD libraries): smaller
file, same outer dimensions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

warnings.filterwarnings("ignore")
PROJECT = Path(__file__).resolve().parents[2]
SOURCE = "bd_warehouse"
LICENSE = "Apache-2.0 (generated with bd_warehouse 0.4.0)"
FASTENER_SECTORS = ["industry", "machine-building", "construction"]
MACHINE_SECTORS = ["machine-building", "industry", "automotive"]


@dataclass
class Item:
    id: str
    make: Callable[[], Any]
    name: str
    description: str
    category_path: str
    tags: list[str]
    sectors: list[str] = field(default_factory=lambda: list(FASTENER_SECTORS))
    material: str | None = "steel"
    standards: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    source_ref: str = ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def std_label(code: str) -> str:
    """iso4762 -> ISO 4762, din6797 -> DIN 6797, iso7380_1 -> ISO 7380-1"""
    m = re.match(r"(iso|din)(\d+)(?:_(\d+))?$", code)
    if not m:
        return code
    return f"{m.group(1).upper()} {m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")


def thread(size: str) -> str:
    return size.split("-")[0]                       # "M8-1.25" -> "M8"


def g(x: float) -> str:
    return f"{x:g}"


# ---- catalogue -----------------------------------------------------------------------------------
def catalog() -> list[Item]:
    from bd_warehouse import bearing, fastener as f, gear, o_rings, open_builds as ob, retaining_ring as rr, \
        shaft_key, sprocket

    items: list[Item] = []
    metric = ["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]

    def sizes_for(cls, code, wanted):
        out, seen = [], set()
        for s in cls.sizes(code):                  # per thread size only the first (coarse pitch)
            if thread(s) in wanted and thread(s) not in seen:
                out.append(s)
                seen.add(thread(s))
        return out

    def screws(cls, code, cat, label, en, lengths_per_size, wanted=metric):
        lengths_all = f.Screw.nominal_length_range[code]
        for size in sizes_for(cls, code, wanted):
            d = float(thread(size)[1:])
            ls = [l for l in lengths_all if 1.5 * d <= l <= 12 * d]
            if len(ls) > lengths_per_size:                       # evenly distributed
                step = (len(ls) - 1) / (lengths_per_size - 1)
                ls = [ls[round(i * step)] for i in range(lengths_per_size)]
            for length in ls:
                t, lab = thread(size), std_label(code)
                items.append(Item(
                    id=f"bd-{slug(label)}-{slug(t)}x{g(length)}-{slug(lab)}",
                    make=lambda cls=cls, size=size, length=length, code=code: cls(size, length, code, simple=True),
                    name=f"{label} {t}x{g(length)} {lab}",
                    description=f"{label} {t}x{g(length)} mm according to {lab}, metric thread {size.replace('-', ' x ')}. "
                                f"{en.capitalize()}.",
                    category_path=cat, tags=[*label.lower().split(), *en.split(), t.lower(), f"{t.lower()}x{g(length)}"],
                    standards=[lab], properties={"thread": t, "pitch_mm": float(size.split("-")[1]), "length_mm": length},
                    source_ref=f"bd_warehouse.fastener.{cls.__name__}('{size}', {g(length)}, '{code}')"))

    screws(f.SocketHeadCapScrew, "iso4762", "fasteners/bolt/socket-head-bolt", "Socket head bolt", "socket head cap screw", 6)
    screws(f.HexHeadScrew, "iso4017", "fasteners/bolt/hex-bolt", "Hex bolt fully threaded", "hex head screw fully threaded", 5)
    screws(f.HexHeadScrew, "iso4014", "fasteners/bolt/hex-bolt", "Hex bolt partially threaded", "hex head bolt partially threaded", 4)
    screws(f.CounterSunkScrew, "iso10642", "fasteners/screw/countersunk-screw", "Countersunk socket screw", "countersunk socket screw", 4, metric[:7])
    screws(f.ButtonHeadScrew, "iso7380_1", "fasteners/screw/button-head-screw", "Button head screw", "button head socket screw", 4, metric[:7])
    screws(f.SetScrew, "iso4026", "fasteners/screw/set-screw", "Set screw", "set screw grub screw", 3, metric[:7])
    screws(f.PanHeadScrew, "iso14583", "fasteners/screw/machine-screw", "Pan head screw torx", "pan head screw torx", 3, metric[:6])

    def nuts(cls, code, cat, label, en, wanted=metric + ["M24"]):
        for size in sizes_for(cls, code, wanted):
            t, lab = thread(size), std_label(code)
            items.append(Item(
                id=f"bd-{slug(label)}-{slug(t)}-{slug(lab)}",
                make=lambda cls=cls, size=size, code=code: cls(size, code, simple=True),
                name=f"{label} {t} {lab}", description=f"{label} {t} according to {lab}, metric thread {size.replace('-', ' x ')}. {en.capitalize()}.",
                category_path=cat, tags=[*label.lower().split(), *en.split(), t.lower()], standards=[lab],
                properties={"thread": t, "pitch_mm": float(size.split("-")[1])},
                source_ref=f"bd_warehouse.fastener.{cls.__name__}('{size}', '{code}')"))

    nuts(f.HexNut, "iso4032", "fasteners/nut/hex-nut", "Hex nut", "hex nut")
    nuts(f.HexNut, "iso4035", "fasteners/nut/hex-nut", "Thin hex nut", "thin hex nut jam nut")
    nuts(f.HexNutWithFlange, "din1665", "fasteners/nut/flange-nut", "Flange nut", "hex flange nut")
    nuts(f.DomedCapNut, "din1587", "fasteners/nut/cap-nut", "Cap nut", "domed cap nut acorn nut")
    nuts(f.SquareNut, "din557", "fasteners/nut/square-nut", "Square nut", "square nut")

    def washers(cls, code, cat, label, en, wanted=metric + ["M24"]):
        for size in sizes_for(cls, code, wanted):
            t = thread(size)
            lab = std_label(code)
            items.append(Item(
                id=f"bd-{slug(label)}-{slug(t)}-{slug(lab)}",
                make=lambda cls=cls, size=size, code=code: cls(size, code),
                name=f"{label} {t} {lab}", description=f"{label} for {t} according to {lab}. {en.capitalize()}.",
                category_path=cat, tags=[*label.lower().split(), *en.split(), t.lower()], standards=[lab],
                properties={"for_thread": t}, source_ref=f"bd_warehouse.fastener.{cls.__name__}('{size}', '{code}')"))

    washers(f.PlainWasher, "iso7089", "fasteners/washer/flat-washer", "Flat washer", "plain washer flat washer")
    washers(f.PlainWasher, "iso7093", "fasteners/washer/flat-washer", "Large flat washer", "large plain washer fender washer")
    washers(f.InternalToothLockWasher, "din6797", "fasteners/washer/toothed-washer", "Internal tooth lock washer", "internal tooth lock washer")

    for size in ["8", "10", "12", "15", "17", "20", "25", "30", "35", "40"]:
        items.append(Item(
            id=f"bd-retaining-ring-shaft-{size}", make=lambda size=size: rr.ExternalSnapRing(size),
            name=f"Retaining ring for shaft {size} mm (circlip)", description=f"External retaining ring (circlip) for a {size} mm shaft.",
            category_path="fasteners/washer/lock-washer", tags=["retaining ring", "circlip", "snap ring", "shaft"],
            sectors=MACHINE_SECTORS, properties={"shaft_diameter_mm": float(size)}, source_ref=f"bd_warehouse.retaining_ring.ExternalSnapRing('{size}')"))
        items.append(Item(
            id=f"bd-retaining-ring-bore-{size}", make=lambda size=size: rr.InternalSnapRing(size),
            name=f"Retaining ring for bore {size} mm (circlip)", description=f"Internal retaining ring (circlip) for a {size} mm bore.",
            category_path="fasteners/washer/lock-washer", tags=["retaining ring", "circlip", "snap ring", "bore"],
            sectors=MACHINE_SECTORS, properties={"bore_mm": float(size)}, source_ref=f"bd_warehouse.retaining_ring.InternalSnapRing('{size}')"))

    for d, length in [(10, 20), (12, 25), (16, 32), (20, 40), (25, 45), (30, 50), (40, 63), (50, 80)]:
        items.append(Item(
            id=f"bd-key-shaft{d}-l{length}", make=lambda d=d, length=length: shaft_key.ShaftKey(d, length, "A"),
            name=f"Key form A for shaft {d} mm, length {length} mm", description=f"Parallel key (form A, round) for a {d} mm shaft, length {length} mm.",
            category_path="fasteners/pin/key", tags=["key", "keyway", "shaft", "parallel key"], sectors=MACHINE_SECTORS,
            properties={"shaft_diameter_mm": d, "length_mm": length, "form": "A"}, source_ref=f"bd_warehouse.shaft_key.ShaftKey({d}, {length}, 'A')"))

    bearings = [
        (bearing.SingleRowDeepGrooveBallBearing, "Deep groove ball bearing", "deep groove ball bearing", "drivetrain/bearing/ball-bearing", "open"),
        (bearing.SingleRowCappedDeepGrooveBallBearing, "Sealed deep groove ball bearing", "sealed deep groove ball bearing 2RS", "drivetrain/bearing/ball-bearing", "sealed"),
        (bearing.SingleRowAngularContactBallBearing, "Angular contact ball bearing", "angular contact ball bearing", "drivetrain/bearing/ball-bearing", "angular-contact"),
        (bearing.SingleRowCylindricalRollerBearing, "Cylindrical roller bearing", "cylindrical roller bearing", "drivetrain/bearing/roller-bearing", "cylindrical-roller"),
        (bearing.SingleRowTaperedRollerBearing, "Tapered roller bearing", "tapered roller bearing", "drivetrain/bearing/roller-bearing", "tapered-roller"),
    ]
    for cls, label, en, cat, kind in bearings:
        for size in cls.sizes("SKT"):
            m = re.match(r"M([\d.]+)-([\d.]+)-([\d.]+)", size)
            if not m:
                continue
            di, do, w = (float(x) for x in m.groups())
            items.append(Item(
                id=f"bd-{slug(label)}-{g(di)}x{g(do)}x{g(w)}".replace(".", "_"), make=lambda cls=cls, size=size: cls(size, "SKT"),
                name=f"{label} {g(di)}x{g(do)}x{g(w)} mm",
                description=f"{label} with inner diameter {g(di)} mm, outer diameter {g(do)} mm and width {g(w)} mm. {en.capitalize()}.",
                category_path=cat, tags=[*label.lower().split(), *en.split(), "bearing", f"{g(di)}mm"],
                sectors=MACHINE_SECTORS, material="steel",
                properties={"inner_diameter_mm": di, "outer_diameter_mm": do, "width_mm": w, "type": kind},
                source_ref=f"bd_warehouse.bearing.{cls.__name__}('{size}', 'SKT')"))

    for code in o_rings.ORing.sizes("iso3601")[::9][:40]:
        items.append(Item(
            id=f"bd-o-ring-iso3601-{code}", make=lambda code=code: o_rings.ORing(code, "iso3601"),
            name=f"O-ring ISO 3601 size {code}", description=f"O-ring according to ISO 3601, size {code}. Rubber sealing ring.",
            category_path="piping/sealing/o-ring", tags=["o-ring", "seal", "sealing ring", "rubber"],
            sectors=["industry", "machine-building", "food", "automotive"], material="rubber", standards=["ISO 3601"],
            properties={"size": code}, source_ref=f"bd_warehouse.o_rings.ORing('{code}', 'iso3601')"))

    for module in (1, 1.5, 2, 3):
        for teeth in (15, 20, 30, 40):
            items.append(Item(
                id=f"bd-spur-gear-m{g(module)}-z{teeth}".replace(".", "_"),
                make=lambda module=module, teeth=teeth: gear.SpurGear(module, teeth, 20, 10 * module),
                name=f"Spur gear module {g(module)}, {teeth} teeth",
                description=f"Spur gear module {g(module)} with {teeth} teeth, pressure angle 20°, "
                            f"pitch circle {g(module * teeth)} mm, width {g(10 * module)} mm.",
                category_path="drivetrain/gear/spur", tags=["gear", "spur", "spur gear", f"module {g(module)}", f"z{teeth}"],
                sectors=MACHINE_SECTORS, material=None,
                properties={"module": module, "teeth": teeth, "pressure_angle_deg": 20, "pitch_circle_mm": module * teeth},
                source_ref=f"bd_warehouse.gear.SpurGear({g(module)}, {teeth}, 20, {g(10 * module)})"))
    for module, teeth in [(2, 20), (2, 30), (3, 20)]:
        items.append(Item(
            id=f"bd-helical-gear-m{module}-z{teeth}", make=lambda module=module, teeth=teeth: gear.HelicalGear(module, teeth, 20, 15, 10 * module),
            name=f"Helical gear module {module}, {teeth} teeth", description=f"Helical gear module {module}, {teeth} teeth, helix angle 15°.",
            category_path="drivetrain/gear/helical", tags=["gear", "helical", "helical gear"], sectors=MACHINE_SECTORS, material=None,
            properties={"module": module, "teeth": teeth, "slope_deg": 15}, source_ref=f"bd_warehouse.gear.HelicalGear({module}, {teeth}, 20, 15, {10 * module})"))
    for module in (1, 2):
        items.append(Item(
            id=f"bd-gear-rack-m{module}", make=lambda module=module: gear.RackGear(module, 30, 20, 10 * module),
            name=f"Gear rack module {module}, 30 teeth", description=f"Gear rack module {module} with 30 teeth.",
            category_path="drivetrain/gear/gear-rack", tags=["gear rack", "rack", "gear"], sectors=MACHINE_SECTORS, material=None,
            properties={"module": module, "teeth": 30}, source_ref=f"bd_warehouse.gear.RackGear({module}, 30, 20, {10 * module})"))

    for teeth in (10, 12, 15, 18, 20, 25, 30, 40):
        items.append(Item(
            id=f"bd-sprocket-08b-z{teeth}", make=lambda teeth=teeth: sprocket.Sprocket(teeth, bore_diameter=10),
            name=f"Sprocket 1/2\" x 5/16\" (08B), {teeth} teeth",
            description=f"Sprocket for roller chain 1/2\" pitch (12.7 mm, 08B), {teeth} teeth, bore 10 mm.",
            category_path="drivetrain/transmission/sprocket", tags=["sprocket", "chain", "08b", "roller chain"],
            sectors=MACHINE_SECTORS, properties={"teeth": teeth, "spacing_mm": 12.7}, source_ref=f"bd_warehouse.sprocket.Sprocket({teeth}, bore_diameter=10)"))

    ob_sectors = ["machine-building", "electronics", "industry"]
    for size in ("20x20", "20x40", "20x60", "20x80", "40x40"):
        for length in (250, 500, 1000):
            items.append(Item(
                id=f"bd-vslot-{size}-l{length}", make=lambda size=size, length=length: ob.VSlotLinearRail(size, length),
                name=f"V-slot aluminium profile {size} mm, {length} mm long",
                description=f"OpenBuilds V-slot aluminium system profile {size} mm, length {length} mm, for CNC, 3D printers and frames.",
                category_path="profiles/aluminium/system-profile", tags=["v-slot", "vslot", "aluminium", "profiles", "openbuilds", "extrusion", size],
                sectors=ob_sectors, material="aluminium", properties={"profiles": size, "length_mm": length},
                source_ref=f"bd_warehouse.open_builds.VSlotLinearRail('{size}', {length})"))
    for length in (500, 1000):
        items.append(Item(
            id=f"bd-cbeam-l{length}", make=lambda length=length: ob.CBeamLinearRail(length),
            name=f"C-beam aluminium profile 40x80, {length} mm long", description=f"OpenBuilds C-beam aluminium profile 40x80 mm, length {length} mm.",
            category_path="profiles/aluminium/system-profile", tags=["c-beam", "aluminium", "profiles", "openbuilds", "extrusion"],
            sectors=ob_sectors, material="aluminium", properties={"length_mm": length}, source_ref=f"bd_warehouse.open_builds.CBeamLinearRail({length})"))
    singles = [
        ("bd-openbuilds-tnut", lambda: ob.TNut(), "T-nut for V-slot (OpenBuilds)", "T-nut (drop-in tee nut) for V-slot aluminium profile.", "fasteners/nut", ["t-nut", "tnut", "v-slot"], "steel"),
        ("bd-openbuilds-vwheel", lambda: ob.XtremeSolidVWheel(), "Xtreme Solid V-wheel (OpenBuilds)", "Plastic V-wheel for guiding over V-slot profile.", "machine-elements/guide/wheel", ["wheel", "v-wheel", "guide"], "plastic"),
        ("bd-openbuilds-angle-bracket", lambda: ob.LBracket(), "L angle bracket (OpenBuilds)", "Aluminium L-bracket to join V-slot profiles at right angles.", "connections/bracket/angle-bracket", ["angle bracket", "l-bracket", "bracket"], "aluminium"),
        ("bd-openbuilds-gantry-plate", lambda: ob.CBeamGantryPlate(), "C-beam gantry plate (OpenBuilds)", "Aluminium gantry plate for a carriage on C-beam.", "machine-elements/cnc/gantry-plate", ["gantry", "plate", "carriage", "cnc"], "aluminium"),
        ("bd-openbuilds-coupling-8mm", lambda: ob.FlexibleCoupler("8mm"), "Flexible shaft coupling 8 mm (OpenBuilds)", "Flexible shaft coupling for an 8 mm shaft (e.g. motor to lead screw).", "connections/coupling/shaft-coupling", ["shaft coupling", "coupling", "coupler", "flexible"], "aluminium"),
        ("bd-openbuilds-lock-collar-8mm", lambda: ob.LockCollar("8mm"), "Lock collar 8 mm (OpenBuilds)", "Lock collar for an 8 mm shaft.", "drivetrain/shaft", ["lock collar", "collar", "shaft"], "steel"),
        ("bd-openbuilds-lead-screw-500", lambda: ob.MetricLeadScrew(500), "Lead screw 8 mm, 500 mm long (OpenBuilds)", "Metric trapezoidal lead screw 8 mm, length 500 mm.", "drivetrain/shaft/spindle", ["lead screw", "trapezoidal", "threaded rod"], "steel"),
        ("bd-stepper-motor-nema17", lambda: ob.StepperMotor("Nema17"), "Stepper motor NEMA 17", "Stepper motor NEMA 17 (42 mm flange), for CNC and 3D printers.", "electrical/motor/stepper-motor", ["stepper motor", "stepper", "motor", "nema17", "nema 17"], None),
        ("bd-stepper-motor-nema23", lambda: ob.StepperMotor("Nema23"), "Stepper motor NEMA 23", "Stepper motor NEMA 23 (57 mm flange), for CNC machines.", "electrical/motor/stepper-motor", ["stepper motor", "stepper", "motor", "nema23", "nema 23"], None),
    ]
    for length in ("6mm", "10mm", "20mm", "40mm"):
        singles.append((f"bd-openbuilds-spacer-{length}", lambda length=length: ob.AluminumSpacer(length),
                        f"Aluminium spacer {length}", f"Aluminium spacer of {length} for OpenBuilds constructions.",
                        "machine-elements/cnc/spacer", ["spacer", "standoff"], "aluminium"))
    for id_, make, name, desc, cat, tags, mat in singles:
        items.append(Item(id=id_, make=make, name=name, description=desc, category_path=cat, tags=[*tags, "openbuilds"],
                          sectors=ob_sectors, material=mat, source_ref=f"bd_warehouse.open_builds ({name})"))
    return items


def write(item: Item, out: Path, geometry: bool = True) -> Path:
    from build123d import export_step

    folder = out / item.category_path.split("/")[0]
    folder.mkdir(parents=True, exist_ok=True)
    step = folder / f"{item.id}.step"
    is_oring = item.id.startswith("bd-o-ring-")
    shape = item.make() if (geometry or is_oring) else None    # O-ring names need the measured shape
    if geometry:
        export_step(shape, str(step))
    if is_oring:            # ISO 3601 only knows codes: take the dimensions from the model
        size = shape.bounding_box().size
        od, cs = round(max(size.X, size.Y), 2), round(size.Z, 2)
        inner = round(od - 2 * cs, 2)
        code = item.properties["size"]
        item.name = f"O-ring {g(inner)} x {g(cs)} mm (ISO 3601 size {code})"
        item.description = (f"O-ring according to ISO 3601 size {code}: inner diameter {g(inner)} mm, cross-section {g(cs)} mm, "
                            f"outer diameter {g(od)} mm. Rubber sealing ring.")
        item.properties.update(inner_diameter_mm=inner, chord_thickness_mm=cs, outer_diameter_mm=od)
        item.tags = [*item.tags, f"{g(round(inner))}mm"]
    meta = {
        "id": item.id, "kind": "part", "name": item.name, "description": item.description,
        "category_path": item.category_path, "sectors": item.sectors, "tags": sorted(set(item.tags)),
        "material": item.material, "standards": item.standards, "properties": item.properties,
        "source": SOURCE, "source_ref": item.source_ref, "license": LICENSE,
    }
    (folder / f"{item.id}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return step


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PROJECT / "data" / "global" / "standard-parts"))
    ap.add_argument("--only")
    ap.add_argument("--json-only", action="store_true", help="write only the JSON metadata (no STEP files)")
    args = ap.parse_args()
    items = catalog()
    ids = [i.id for i in items]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print("Duplicate ids:", sorted(dup)[:10])
        return 1
    if args.only:
        items = [i for i in items if args.only in i.id]
    out = Path(args.out)
    ok, failed = 0, []
    for n, item in enumerate(items, 1):
        try:
            write(item, out, geometry=not args.json_only)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - one broken part must not hold up the rest
            failed.append((item.id, f"{type(exc).__name__}: {exc}"[:150]))
        print(f"  {n}/{len(items)} {item.id:60}", end="\r", flush=True)
    print(f"\n{ok} standard parts made in {out}" + (f", {len(failed)} failed:" if failed else ""))
    for i, e in failed:
        print(f"  - {i}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
