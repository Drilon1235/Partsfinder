"""Generates the full set of standard parts with bd_warehouse (Apache-2.0): ~6,000 bolts, screws, nuts, washers,
bearings, O-rings, retaining rings, keys, flanges, gears and OpenBuilds parts, each as STEP + JSON.

The dimensions come from the standards as implemented in bd_warehouse; every thread size in coarse pitch and every
standard length between 1.5 and 12 times the diameter. Brand-specific parts (heat-set inserts of a named make) are left
out. The ~500 parts of the demo selection (scripts/demo/standard_parts.py) keep the same ids, so installing the pack
updates them instead of adding copies.

bd_warehouse needs its own environment (another OCP version than CadQuery):
    python -m venv .venv-bd && .venv-bd/bin/pip install bd_warehouse==0.4.0
    .venv-bd/bin/python scripts/datapacks/generate_standard_parts.py --out dist/standard-parts [--workers 2] [--count]
Then: python scripts/datapacks/build.py standard-parts --src dist/standard-parts
Safe to run again: parts whose STEP file exists are skipped.
"""
from __future__ import annotations

import argparse
import multiprocessing
import re
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from fractions import Fraction
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "demo"))

import standard_parts as demo  # noqa: E402  (Item, write, slug, std_label, thread, g, catalog)

Item, slug, std_label, thread, g = demo.Item, demo.slug, demo.std_label, demo.thread, demo.g
MACHINE = demo.MACHINE_SECTORS
FASTENER = demo.FASTENER_SECTORS

# (class name, type code) -> (label, category_path, english words); the demo labels are kept for the same ids
SCREWS = {
    ("SocketHeadCapScrew", "iso4762"): ("Socket head bolt", "fasteners/bolt/socket-head-bolt", "socket head cap screw allen bolt"),
    ("SocketHeadCapScrew", "asme_b18.3"): ("Socket head cap screw", "fasteners/bolt/socket-head-bolt", "socket head cap screw inch unc unf"),
    ("HexHeadScrew", "iso4017"): ("Hex bolt fully threaded", "fasteners/bolt/hex-bolt", "hex head screw fully threaded"),
    ("HexHeadScrew", "iso4014"): ("Hex bolt partially threaded", "fasteners/bolt/hex-bolt", "hex head bolt partially threaded"),
    ("HexHeadScrew", "din931"): ("Hex bolt partially threaded", "fasteners/bolt/hex-bolt", "hex head bolt partially threaded"),
    ("HexHeadWithFlangeScrew", "din1662"): ("Hex flange bolt", "fasteners/bolt/hex-bolt", "hex flange bolt flange screw"),
    ("HexHeadWithFlangeScrew", "din1665"): ("Hex flange bolt", "fasteners/bolt/hex-bolt", "hex flange bolt flange screw"),
    ("CounterSunkScrew", "iso10642"): ("Countersunk socket screw", "fasteners/screw/countersunk-screw", "countersunk socket screw flat head"),
    ("CounterSunkScrew", "iso2009"): ("Countersunk slotted screw", "fasteners/screw/countersunk-screw", "countersunk slotted screw flat head"),
    ("CounterSunkScrew", "iso7046"): ("Countersunk Phillips screw", "fasteners/screw/countersunk-screw", "countersunk phillips cross recess screw"),
    ("CounterSunkScrew", "iso14581"): ("Countersunk torx screw", "fasteners/screw/countersunk-screw", "countersunk torx hexalobular screw"),
    ("CounterSunkScrew", "iso14582"): ("Countersunk torx screw high head", "fasteners/screw/countersunk-screw", "countersunk torx high head screw"),
    ("RaisedCounterSunkOvalHeadScrew", "iso2010"): ("Raised countersunk slotted screw", "fasteners/screw/countersunk-screw", "raised countersunk oval head slotted screw"),
    ("RaisedCounterSunkOvalHeadScrew", "iso7047"): ("Raised countersunk Phillips screw", "fasteners/screw/countersunk-screw", "raised countersunk oval head phillips screw"),
    ("RaisedCounterSunkOvalHeadScrew", "iso14584"): ("Raised countersunk torx screw", "fasteners/screw/countersunk-screw", "raised countersunk oval head torx screw"),
    ("ButtonHeadScrew", "iso7380_1"): ("Button head screw", "fasteners/screw/button-head-screw", "button head socket screw"),
    ("ButtonHeadWithCollarScrew", "iso7380_2"): ("Button head screw with collar", "fasteners/screw/button-head-screw", "button head flange socket screw"),
    ("SetScrew", "iso4026"): ("Set screw", "fasteners/screw/set-screw", "set screw grub screw flat point"),
    ("PanHeadScrew", "iso14583"): ("Pan head screw torx", "fasteners/screw/machine-screw", "pan head screw torx"),
    ("PanHeadScrew", "iso1580"): ("Pan head slotted screw", "fasteners/screw/machine-screw", "pan head slotted screw"),
    ("PanHeadScrew", "asme_b_18.6.3"): ("Pan head screw", "fasteners/screw/machine-screw", "pan head machine screw inch"),
    ("PanHeadWithCollarScrew", "din967"): ("Pan head Phillips screw with collar", "fasteners/screw/machine-screw", "pan head flange phillips screw"),
    ("RaisedCheeseHeadScrew", "iso7045"): ("Pan head Phillips screw", "fasteners/screw/machine-screw", "pan head phillips cross recess screw"),
    ("CheeseHeadScrew", "iso1207"): ("Cheese head slotted screw", "fasteners/screw/machine-screw", "cheese head slotted screw"),
    ("CheeseHeadScrew", "iso14580"): ("Cheese head torx screw", "fasteners/screw/machine-screw", "cheese head torx screw"),
    ("CheeseHeadScrew", "iso7048"): ("Cheese head Phillips screw", "fasteners/screw/machine-screw", "cheese head phillips screw"),
    ("ShoulderScrew", "iso7379"): ("Shoulder screw", "fasteners/bolt/socket-head-bolt", "shoulder screw shoulder bolt"),
}
NUTS = {
    ("HexNut", "iso4032"): ("Hex nut", "fasteners/nut/hex-nut", "hex nut"),
    ("HexNut", "iso4033"): ("High hex nut", "fasteners/nut/hex-nut", "hex nut style 2 high"),
    ("HexNut", "iso4035"): ("Thin hex nut", "fasteners/nut/hex-nut", "thin hex nut jam nut"),
    ("UnchamferedHexagonNut", "iso4036"): ("Thin hex nut unchamfered", "fasteners/nut/hex-nut", "thin hex nut unchamfered"),
    ("HexNutWithFlange", "din1665"): ("Flange nut", "fasteners/nut/flange-nut", "hex flange nut"),
    ("DomedCapNut", "din1587"): ("Cap nut", "fasteners/nut/cap-nut", "domed cap nut acorn nut"),
    ("SquareNut", "din557"): ("Square nut", "fasteners/nut/square-nut", "square nut"),
}
WASHERS = {
    ("PlainWasher", "iso7089"): ("Flat washer", "fasteners/washer/flat-washer", "plain washer flat washer"),
    ("PlainWasher", "iso7091"): ("Flat washer product grade C", "fasteners/washer/flat-washer", "plain washer flat washer"),
    ("PlainWasher", "iso7093"): ("Large flat washer", "fasteners/washer/flat-washer", "large plain washer fender washer"),
    ("PlainWasher", "iso7094"): ("Extra large flat washer", "fasteners/washer/flat-washer", "extra large plain washer"),
    ("ChamferedWasher", "iso7090"): ("Chamfered flat washer", "fasteners/washer/flat-washer", "plain washer chamfered"),
    ("CheeseHeadWasher", "iso7092"): ("Small flat washer", "fasteners/washer/flat-washer", "small plain washer for cheese head screws"),
    ("InternalToothLockWasher", "din6797"): ("Internal tooth lock washer", "fasteners/washer/toothed-washer", "internal tooth lock washer"),
    ("InternalToothLockWasher", "asme_b18.21.1"): ("Internal tooth lock washer", "fasteners/washer/toothed-washer", "internal tooth lock washer inch"),
}


def diameter_mm(t: str) -> float | None:
    """'M8' -> 8, '#10' -> 4.83, '1/4' -> 6.35, '1 1/8' -> 28.6."""
    if t.startswith("M"):
        try:
            return float(t[1:])
        except ValueError:
            return None
    if t.startswith("#"):
        return (0.060 + 0.013 * int(t[1:])) * 25.4
    try:
        return float(sum(Fraction(p) for p in t.split())) * 25.4
    except (ValueError, ZeroDivisionError):
        return None


def coarse(sizes: list[str]) -> list[str]:
    """Per thread diameter only the first size (coarse pitch / UNC)."""
    out, seen = [], set()
    for s in sizes:
        t = thread(s)
        if t not in seen:
            out.append(s)
            seen.add(t)
    return out


def inch_label(t: str) -> str:
    return f"{t}\"" if not t.startswith("#") else t


def catalog() -> list[Item]:
    from bd_warehouse import bearing, fastener as f, flange, gear, o_rings, retaining_ring as rr, shaft_key

    items: list[Item] = []
    seen: set[str] = set()

    def add(item: Item) -> None:
        if item.id not in seen:
            seen.add(item.id)
            items.append(item)

    # the demo parts first: same ids and texts as before
    for item in demo.catalog():
        add(item)

    classes = {c.__name__: c for base in (f.Screw, f.Nut, f.Washer) for c in base.__subclasses__()}
    for (cname, code), (label, cat, en) in SCREWS.items():
        cls = classes[cname]
        lengths_all = f.Screw.nominal_length_range[code]
        inch = code.startswith("asme")
        for size in coarse(cls.sizes(code)):
            t = thread(size)
            d = diameter_mm(t)
            if d is None:
                continue
            for length in [length for length in lengths_all if 1.5 * d <= length <= 12 * d]:
                lab = std_label(code) if not inch else code.upper().replace("_", " ").replace("ASME B ", "ASME B")
                if inch:
                    shown = f"{inch_label(t)} x {g(round(length / 25.4, 3))}\""
                    name = f"{label} {size} x {g(round(length / 25.4, 3))}\" {lab}"
                    pid = f"bd-{slug(label)}-{slug(size)}x{slug(g(round(length / 25.4, 3)))}in-{slug(lab)}"
                    props = {"thread": size, "length_mm": round(length, 2), "length_in": round(length / 25.4, 3),
                             "unit": "inch"}
                    desc = f"{label} {size} UNC, length {shown} ({g(round(length, 1))} mm), according to {lab}. {en.capitalize()}."
                else:
                    pitch = float(size.split("-")[1])
                    name = f"{label} {t}x{g(length)} {lab}"
                    pid = f"bd-{slug(label)}-{slug(t)}x{g(length)}-{slug(lab)}"
                    props = {"thread": t, "pitch_mm": pitch, "length_mm": length}
                    desc = (f"{label} {t}x{g(length)} mm according to {lab}, metric thread {size.replace('-', ' x ')}. "
                            f"{en.capitalize()}.")
                add(Item(
                    id=pid, make=lambda cls=cls, size=size, length=length, code=code: cls(size, length, code, simple=True),
                    name=name, description=desc, category_path=cat,
                    tags=[*label.lower().split(), *en.split(), t.lower(), f"{t.lower()}x{g(length)}"],
                    standards=[lab], properties=props,
                    source_ref=f"bd_warehouse.fastener.{cname}('{size}', {g(length)}, '{code}')"))

    for table, kind in ((NUTS, "nut"), (WASHERS, "washer")):
        for (cname, code), (label, cat, en) in table.items():
            cls = classes[cname]
            inch = code.startswith("asme")
            sizes = cls.sizes(code) if kind == "washer" else coarse(cls.sizes(code))
            for size in sizes:
                t = thread(size)
                lab = std_label(code) if not inch else code.upper().replace("_", " ")
                pid = f"bd-{slug(label)}-{slug(t)}-{slug(lab)}"
                make = (lambda cls=cls, size=size, code=code: cls(size, code, simple=True)) if kind == "nut" else \
                    (lambda cls=cls, size=size, code=code: cls(size, code))
                if kind == "nut":
                    desc = f"{label} {t} according to {lab}, thread {size.replace('-', ' x ')}. {en.capitalize()}."
                    props = {"thread": t, **({"pitch_mm": float(size.split("-")[1])} if not inch and "-" in size else {})}
                else:
                    desc = f"{label} for {inch_label(t) if inch else t} according to {lab}. {en.capitalize()}."
                    props = {"for_thread": t}
                add(Item(id=pid, make=make, name=f"{label} {inch_label(t) if inch else t} {lab}", description=desc,
                         category_path=cat, tags=[*label.lower().split(), *en.split(), t.lower()], standards=[lab],
                         properties=props, source_ref=f"bd_warehouse.fastener.{cname}('{size}', '{code}')"))

    # retaining rings: every size
    for size in rr.ExternalSnapRing.sizes():
        add(Item(id=f"bd-retaining-ring-shaft-{size}", make=lambda size=size: rr.ExternalSnapRing(size),
                 name=f"Retaining ring for shaft {size} mm (circlip)",
                 description=f"External retaining ring (circlip, DIN 471) for a {size} mm shaft.",
                 category_path="fasteners/washer/lock-washer", tags=["retaining ring", "circlip", "snap ring", "shaft", "din 471"],
                 sectors=MACHINE, standards=["DIN 471"], properties={"shaft_diameter_mm": float(size)},
                 source_ref=f"bd_warehouse.retaining_ring.ExternalSnapRing('{size}')"))
    for size in rr.InternalSnapRing.sizes():
        add(Item(id=f"bd-retaining-ring-bore-{size}", make=lambda size=size: rr.InternalSnapRing(size),
                 name=f"Retaining ring for bore {size} mm (circlip)",
                 description=f"Internal retaining ring (circlip, DIN 472) for a {size} mm bore.",
                 category_path="fasteners/washer/lock-washer", tags=["retaining ring", "circlip", "snap ring", "bore", "din 472"],
                 sectors=MACHINE, standards=["DIN 472"], properties={"bore_mm": float(size)},
                 source_ref=f"bd_warehouse.retaining_ring.InternalSnapRing('{size}')"))

    # parallel keys: per shaft size four standard lengths
    for d in shaft_key.ShaftKey.sizes():
        lengths = sorted({int(round(x)) for x in (d * 1.0, d * 1.5, d * 2.0, d * 3.0)})
        for length in lengths:
            add(Item(id=f"bd-key-shaft{d}-l{length}", make=lambda d=d, length=length: shaft_key.ShaftKey(d, length, "A"),
                     name=f"Key form A for shaft {d} mm, length {length} mm",
                     description=f"Parallel key (form A, round ends, DIN 6885) for a {d} mm shaft, length {length} mm.",
                     category_path="fasteners/pin/key", tags=["key", "keyway", "shaft", "parallel key", "din 6885"],
                     sectors=MACHINE, standards=["DIN 6885"], properties={"shaft_diameter_mm": d, "length_mm": length, "form": "A"},
                     source_ref=f"bd_warehouse.shaft_key.ShaftKey({d}, {length}, 'A')"))

    # every bearing size
    kinds = [
        (bearing.SingleRowDeepGrooveBallBearing, "Deep groove ball bearing", "deep groove ball bearing", "drivetrain/bearing/ball-bearing", "open"),
        (bearing.SingleRowCappedDeepGrooveBallBearing, "Sealed deep groove ball bearing", "sealed deep groove ball bearing 2RS", "drivetrain/bearing/ball-bearing", "sealed"),
        (bearing.SingleRowAngularContactBallBearing, "Angular contact ball bearing", "angular contact ball bearing", "drivetrain/bearing/ball-bearing", "angular-contact"),
        (bearing.SingleRowCylindricalRollerBearing, "Cylindrical roller bearing", "cylindrical roller bearing", "drivetrain/bearing/roller-bearing", "cylindrical-roller"),
        (bearing.SingleRowTaperedRollerBearing, "Tapered roller bearing", "tapered roller bearing", "drivetrain/bearing/roller-bearing", "tapered-roller"),
    ]
    for cls, label, en, cat, kind in kinds:
        for code in sorted(cls.types()):
            for size in cls.sizes(code):
                m = re.match(r"M([\d.]+)-([\d.]+)-([\d.]+)", size)
                if not m:
                    continue
                di, do, w = (float(x) for x in m.groups())
                add(Item(id=f"bd-{slug(label)}-{g(di)}x{g(do)}x{g(w)}".replace(".", "_"),
                         make=lambda cls=cls, size=size, code=code: cls(size, code),
                         name=f"{label} {g(di)}x{g(do)}x{g(w)} mm",
                         description=f"{label} with inner diameter {g(di)} mm, outer diameter {g(do)} mm and width {g(w)} mm. {en.capitalize()}.",
                         category_path=cat, tags=[*label.lower().split(), *en.split(), "bearing", f"{g(di)}mm"],
                         sectors=MACHINE, material="steel",
                         properties={"inner_diameter_mm": di, "outer_diameter_mm": do, "width_mm": w, "type": kind},
                         source_ref=f"bd_warehouse.bearing.{cls.__name__}('{size}', '{code}')"))

    # every ISO 3601 O-ring (names get the measured diameters in demo.write)
    for code in o_rings.ORing.sizes("iso3601"):
        add(Item(id=f"bd-o-ring-iso3601-{code}", make=lambda code=code: o_rings.ORing(code, "iso3601"),
                 name=f"O-ring ISO 3601 size {code}", description=f"O-ring according to ISO 3601, size {code}. Rubber sealing ring.",
                 category_path="piping/sealing/o-ring", tags=["o-ring", "seal", "sealing ring", "rubber"],
                 sectors=["industry", "machine-building", "food", "automotive"], material="rubber", standards=["ISO 3601"],
                 properties={"size": code}, source_ref=f"bd_warehouse.o_rings.ORing('{code}', 'iso3601')"))

    # ASME B16.5 flanges: five types, every size and pressure class
    nps_all = ['1/2', '3/4', '1', '1 1/4', '1 1/2', '2', '2 1/2', '3', '4', '5', '6', '8', '10', '12', '14', '16', '18',
               '20', '22', '24']
    ftypes = [(flange.WeldNeckFlange, "Weld neck flange", "piping/flange/weld-flange", "weld neck flange"),
              (flange.SlipOnFlange, "Slip-on flange", "piping/flange/weld-flange", "slip on flange"),
              (flange.BlindFlange, "Blind flange", "piping/flange/blind-flange", "blind flange"),
              (flange.LappedFlange, "Lap joint flange", "piping/flange/loose-flange", "lap joint flange loose flange"),
              (flange.SocketWeldFlange, "Socket weld flange", "piping/flange/weld-flange", "socket weld flange")]
    for cls, label, cat, en in ftypes:
        for nps in nps_all:
            for cl in (150, 300, 600, 900, 1500, 2500):
                add(Item(id=f"bd-{slug(label)}-nps{slug(nps)}-class{cl}",
                         make=lambda cls=cls, nps=nps, cl=cl: cls(nps, cl),
                         name=f"{label} NPS {nps}\" class {cl} ASME B16.5",
                         description=f"{label} NPS {nps}\" pressure class {cl}, raised face, according to ASME B16.5. {en.capitalize()}.",
                         category_path=cat, tags=[*en.split(), "flange", f"nps {nps}", f"class {cl}", "asme b16.5", "pipe"],
                         sectors=["industry", "energy", "construction"], material="steel", standards=["ASME B16.5"],
                         properties={"nps": nps, "pressure_class": cl, "face": "raised"},
                         source_ref=f"bd_warehouse.flange.{cls.__name__}('{nps}', {cl})"))

    # spur gears: common catalogue modules and tooth counts
    for module in (0.5, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5):
        for teeth in (12, 14, 15, 16, 18, 20, 22, 24, 25, 28, 30, 32, 35, 36, 40, 45, 48, 50, 60, 70, 80, 100):
            add(Item(id=f"bd-spur-gear-m{g(module)}-z{teeth}".replace(".", "_"),
                     make=lambda module=module, teeth=teeth: gear.SpurGear(module, teeth, 20, 10 * module),
                     name=f"Spur gear module {g(module)}, {teeth} teeth",
                     description=f"Spur gear module {g(module)} with {teeth} teeth, pressure angle 20°, "
                                 f"pitch circle {g(module * teeth)} mm, width {g(10 * module)} mm.",
                     category_path="drivetrain/gear/spur", tags=["gear", "spur", "spur gear", f"module {g(module)}", f"z{teeth}"],
                     sectors=MACHINE, properties={"module": module, "teeth": teeth, "pressure_angle_deg": 20,
                                                  "pitch_circle_mm": module * teeth},
                     source_ref=f"bd_warehouse.gear.SpurGear({g(module)}, {teeth}, 20, {g(10 * module)})"))
    return items


def _one(item: Item, out: str) -> tuple[str, str | None]:
    folder = Path(out) / item.category_path.split("/")[0]
    if (folder / f"{item.id}.step").exists() and (folder / f"{item.id}.json").exists():
        return item.id, None
    try:
        demo.write(item, Path(out))
        return item.id, None
    except Exception as exc:  # noqa: BLE001 - one broken size must not stop the rest
        for ext in (".step", ".json"):
            (folder / f"{item.id}{ext}").unlink(missing_ok=True)
        return item.id, f"{type(exc).__name__}: {exc}"[:200]


def _run(chunk: list[Item], out: str) -> list[tuple[str, str | None]]:
    return [_one(i, out) for i in chunk]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--count", action="store_true", help="only count the parts")
    ap.add_argument("--only")
    args = ap.parse_args()
    items = catalog()
    if args.only:
        items = [i for i in items if args.only in i.id]
    print(f"{len(items)} standard parts", flush=True)
    if args.count:
        return 0
    # lambdas cannot be pickled: each worker rebuilds the catalogue and takes its own share by index
    n = len(items)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(_worker, k, args.workers, args.out, args.only) for k in range(args.workers)]
        failed = []
        for fut in as_completed(futures):
            failed += [r for r in fut.result() if r[1]]
    print(f"done: {n - len(failed)} made, {len(failed)} failed", flush=True)
    for pid, err in failed[:50]:
        print(f"  - {pid}: {err}")
    return 0


def _worker(k: int, workers: int, out: str, only: str | None) -> list[tuple[str, str | None]]:
    items = catalog()
    if only:
        items = [i for i in items if only in i.id]
    mine = items[k::workers]
    results = []
    for j, item in enumerate(mine, 1):
        results.append(_one(item, out))
        if j % 200 == 0:
            print(f"  worker {k}: {j}/{len(mine)}", flush=True)
    return results


if __name__ == "__main__":
    sys.exit(main())
