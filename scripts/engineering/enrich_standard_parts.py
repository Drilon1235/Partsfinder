"""Adds engineering metadata to the existing standard parts (data/global/standard-parts/*.json).

The bd_warehouse parts only said "steel". An engineer orders a DIN 912 M8x30 **12.9** or **A2-70**,
a 6204-**2RS** bearing. This script adds, without touching the geometry:
- property_classes / material_grades that the (identical) geometry is valid for
- the equivalent DIN number next to the ISO number (ISO 4762 = DIN 912), so both are found
- thread on washers ("for_thread" -> also "thread")
- designation + seal on deep groove ball bearings, found from d x D x B (ISO 15 table)
- a "designation" such as "ISO 4762 M8x30" for fasteners

Only standard library; safe to run twice. Afterwards import again: changed JSON files update the
existing parts under the same id (docs/03_DATAMODEL.md).
    python scripts/engineering/enrich_standard_parts.py [--dir data/global/standard-parts] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from catalog import BEARINGS  # noqa: E402

DIN_FOR = {"ISO 4762": "DIN 912", "ISO 4017": "DIN 933", "ISO 4014": "DIN 931", "ISO 4032": "DIN 934",
           "ISO 10511": "DIN 985", "ISO 7089": "DIN 125", "ISO 10642": "DIN 7991", "ISO 4026": "DIN 913",
           "ISO 7380-1": "DIN 7380", "ISO 4035": "DIN 439", "ISO 7092": "DIN 433", "ISO 7090": "DIN 125-B",
           "ISO 7093-1": "DIN 9021", "ISO 4028": "DIN 915", "ISO 4027": "DIN 914", "ISO 14583": "DIN 7985 (TX)"}
CLASSES = {  # standard -> (property classes, material text)
    "ISO 4762": (["8.8", "10.9", "12.9", "A2-70", "A4-80"], "steel 8.8 / 10.9 / 12.9 or stainless A2-70 / A4-80"),
    "ISO 4017": (["8.8", "10.9", "A2-70", "A4-70"], "steel 8.8 / 10.9 or stainless A2-70 / A4-70"),
    "ISO 4014": (["8.8", "10.9", "A2-70", "A4-70"], "steel 8.8 / 10.9 or stainless A2-70 / A4-70"),
    "ISO 10642": (["8.8", "10.9", "12.9", "A2-70"], "steel 8.8 / 10.9 / 12.9 or stainless A2-70"),
    "ISO 7380-1": (["10.9", "A2-70"], "steel 10.9 or stainless A2-70"),
    "ISO 14583": (["4.8", "A2-70"], "steel 4.8 or stainless A2-70"),
    "ISO 4026": (["45H", "A2"], "steel 45H or stainless A2"),
    "ISO 4032": (["8", "10", "A2-70", "A4-70"], "steel class 8 / 10 or stainless A2-70 / A4-70"),
    "ISO 10511": (["8", "10", "A2-70"], "steel class 8 / 10 or stainless A2-70 (nylon insert)"),
    "ISO 4035": (["04", "05", "A2-035"], "steel 04 / 05 or stainless A2"),
}
SYNONYMS = {  # what engineers call these parts, added as tags
    "ISO 4762": ["socket head cap screw", "shcs", "allen bolt", "cap screw"],
    "ISO 4017": ["hex head screw", "tap bolt", "hex cap screw"],
    "ISO 4014": ["hex head bolt", "hex cap screw", "partially threaded"],
    "ISO 10642": ["countersunk", "flat head socket screw", "csk"],
    "ISO 7380-1": ["button head", "button head cap screw", "bhcs"],
    "ISO 4026": ["grub screw", "set screw"],
    "ISO 4032": ["hex nut", "full nut"],
    "ISO 10511": ["nyloc", "lock nut", "self-locking nut", "nylon insert nut"],
    "ISO 4035": ["jam nut", "thin nut", "lock nut"],
    "ISO 7089": ["flat washer", "plain washer"],
}
WASHER_GRADES = (["200 HV", "300 HV", "A2", "A4"], "steel 200 HV / 300 HV or stainless A2 / A4")
# DIN 6885-1 parallel keys: shaft diameter (mm) -> key width b x height h (as in bd_warehouse.shaft_key)
KEY_SECTION = {**{d: (2, 2) for d in (6, 7, 8)}, **{d: (3, 3) for d in (9, 10)}, **{d: (4, 4) for d in (11, 12)},
               **{d: (5, 5) for d in range(13, 18)}, **{d: (6, 6) for d in range(18, 23)},
               **{d: (8, 7) for d in range(23, 31)}, **{d: (10, 8) for d in range(31, 39)},
               **{d: (12, 8) for d in range(39, 45)}, **{d: (14, 9) for d in range(45, 51)}}
BEARING_BY_DIMS = {(float(d), float(D), float(B)): code for code, (d, D, B) in BEARINGS.items()}


def enrich(meta: dict) -> bool:
    before = json.dumps(meta, sort_keys=True)
    props = meta.setdefault("properties", {})
    stds = list(meta.get("standards") or [])
    for s in list(stds):
        din = DIN_FOR.get(s)
        if din and din not in stds:
            stds.append(din)
        if s in CLASSES and meta.get("material") in (None, "steel"):
            classes, text = CLASSES[s]
            props.setdefault("property_classes", classes)
            meta["material"] = text
    meta["standards"] = stds
    tags = meta.setdefault("tags", [])
    for s in stds:
        for t in SYNONYMS.get(s, []):
            if t not in tags:
                tags.append(t)
    cat = meta.get("category_path", "")
    if cat.startswith("fasteners/washer") and meta.get("material") in (None, "steel"):
        props.setdefault("material_grades", WASHER_GRADES[0])
        meta["material"] = WASHER_GRADES[1]
    if "for_thread" in props and "thread" not in props:
        props["thread"] = props["for_thread"]
    if cat.startswith("fasteners/") and props.get("thread") and stds:
        size = props["thread"] + (f"x{props['length_mm']:g}" if isinstance(props.get("length_mm"), (int, float)) else "")
        props.setdefault("designation", f"{stds[0]} {size}")
    if cat == "fasteners/pin/key" and props.get("shaft_diameter_mm") in KEY_SECTION and props.get("length_mm"):
        # keys are ordered as b x h x l ("8x7x40"), not by the shaft they are for
        b, h = KEY_SECTION[props["shaft_diameter_mm"]]
        size = f"{b}x{h}x{props['length_mm']:g}"
        props.setdefault("width_mm", b)
        props.setdefault("height_mm", h)
        props.setdefault("designation", f"DIN 6885 A {size}")
        if size not in tags:
            tags.append(size)
        if not meta["name"].startswith("Parallel key"):
            meta["name"] = (f"Parallel key {size} mm DIN 6885 form {props.get('form', 'A')} "
                            f"(shaft {props['shaft_diameter_mm']:g} mm)")
    if cat == "drivetrain/bearing/ball-bearing" and props.get("type") in ("open", "sealed"):
        key = (float(props.get("inner_diameter_mm", 0)), float(props.get("outer_diameter_mm", 0)),
               float(props.get("width_mm", 0)))
        code = BEARING_BY_DIMS.get(key)
        if code:
            desig = code + ("-2RS" if props["type"] == "sealed" else "")
            props.setdefault("designation", desig)
            props.setdefault("seal", "2RS" if props["type"] == "sealed" else "open")
            if "ISO 15" not in stds:
                meta["standards"] = [*stds, "ISO 15"]
            for t in (code, desig.lower()):
                if t not in tags:
                    tags.append(t)
            if desig not in meta["name"]:
                meta["name"] = f"{meta['name'].split(' mm')[0]} mm ({desig})"
    return json.dumps(meta, sort_keys=True) != before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(PROJECT / "data" / "global" / "standard-parts"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 1
    changed = 0
    files = sorted(folder.rglob("*.json"))
    for f in files:
        meta = json.loads(f.read_text(encoding="utf-8"))
        if enrich(meta):
            changed += 1
            if not args.dry_run:
                f.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{changed} of {len(files)} standard parts enriched{' (dry run)' if args.dry_run else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
