"""The FreeCAD parts library: ~2,500 mechanical, electrical and architectural parts, CC-BY 3.0.

Source: https://github.com/FreeCAD/FreeCAD-library (STEP files only, linked at a pinned commit). The ~520 parts of
the demo selection keep their hand-checked metadata (scripts/demo/freecad_metadata.json); the rest is named and
classified from the folder and the file name (sizes, standards, threads). Clearance-hole cylinders (modelling aids,
not parts) are left out.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from common import Item, Source, git_commit, slug

REPO = "https://raw.githubusercontent.com/FreeCAD/FreeCAD-library"
LICENSE = "CC-BY-3.0"
CURATED = Path(__file__).resolve().parents[2] / "demo" / "freecad_metadata.json"
SKIP = ("Bolt Clearance Hole Cylinders/",)

ATTRIBUTION = """# FreeCAD parts library

The parts in this pack come from the FreeCAD parts library (https://github.com/FreeCAD/FreeCAD-library), made by the
FreeCAD-library contributors and licensed under Creative Commons Attribution 3.0 (CC-BY 3.0, see LICENSE.txt).
Each part is copyrighted by its own author; the authors are recorded in the git history of that repository.
The models are not modified; each part links to its original file at the commit in pack.json.
Names, descriptions and classification were added by Partsfinder (from the folder and file name, and for about 520
parts proposed by an AI and reviewed).
"""

# (pattern on "folder/file name" in lower case, category_path, extra tags); the first match wins
RULES: list[tuple[str, str, list[str]]] = [
    (r"iso ?4762|din ?912|socket head cap", "fasteners/bolt/socket-head-bolt", ["socket head cap screw", "allen bolt"]),
    (r"iso ?4017|iso ?4014|din ?93[13]|hex(agon)? head", "fasteners/bolt/hex-bolt", ["hex bolt"]),
    (r"iso ?10642|iso ?7046|iso ?2009|din ?7991|countersunk|flat head", "fasteners/screw/countersunk-screw", ["countersunk"]),
    (r"iso ?7380|button head", "fasteners/screw/button-head-screw", ["button head"]),
    (r"iso ?402[6-9]|set ?screw|grub", "fasteners/screw/set-screw", ["set screw"]),
    (r"grower|din ?12[78]|spring washer", "fasteners/washer/spring-washer", ["spring washer", "lock washer"]),
    (r"din ?679[78]|tooth", "fasteners/washer/toothed-washer", ["toothed washer"]),
    (r"washer", "fasteners/washer/flat-washer", ["washer"]),
    (r"retaining ?ring|circlip|din ?47[12]|din ?6799", "fasteners/washer/lock-washer", ["retaining ring", "circlip"]),
    (r"nyloc|lock ?nut|din ?985", "fasteners/nut/lock-nut", ["lock nut", "nylon insert"]),
    (r"t-?nut|tnut", "fasteners/nut/insert-nut", ["t-nut", "t-slot nut"]),
    (r"\bnut\b|tuerca|hex_nut|hex nut", "fasteners/nut/hex-nut", ["nut"]),
    (r"standoff", "electronics/component/mounting-hardware", ["standoff", "spacer"]),
    (r"dowel", "fasteners/pin/dowel-pin", ["dowel pin"]),
    (r"coupler|coupling", "connections/coupling/shaft-coupling", ["shaft coupling"]),
    (r"screw|bolt|tornillo", "fasteners/screw/machine-screw", ["screw"]),
    (r"shaft support|sc8uu|linear", "machine-elements/guide/linear-guide", ["linear", "shaft support"]),
    (r"threaded|tr8x|zaxis", "drivetrain/shaft/threaded-rod", ["lead screw", "threaded rod"]),
    (r"sprocket", "drivetrain/transmission/sprocket", ["sprocket", "chain wheel", "roller chain"]),
    (r"chain", "drivetrain/transmission/chain", ["chain"]),
    (r"pulley", "drivetrain/transmission/pulley", ["pulley"]),
    (r"bearing", "drivetrain/bearing/ball-bearing", ["bearing"]),
    (r"square hollow", "profiles/steel/box-section", ["square hollow section", "shs", "box section"]),
    (r"rectangular hollow", "profiles/steel/box-section", ["rectangular hollow section", "rhs", "box section"]),
    (r"equal angle|angle bar", "profiles/steel/angle-profile", ["angle", "l-profile"]),
    (r"flat (steel )?bar", "profiles/steel/flat-bar", ["flat bar", "strip"]),
    (r"round (steel )?bar", "profiles/steel/round-bar", ["round bar", "rod"]),
    (r"square (steel )?bar", "profiles/steel/square-bar", ["square bar"]),
    (r"he-?m|hem ", "profiles/steel/hem", ["hem", "h-beam", "wide flange beam"]),
    (r"he-?a|hea ", "profiles/steel/hea", ["hea", "h-beam", "wide flange beam"]),
    (r"he-?b|heb ", "profiles/steel/heb", ["heb", "h-beam", "wide flange beam"]),
    (r"ipe", "profiles/steel/ipe", ["ipe", "i-beam"]),
    (r"upe", "profiles/steel/upe", ["upe", "u-channel"]),
    (r"makerbeam|v-slot|openbuilds|t-slot|misumi|item_compatible|profile-\d|slot\d", "profiles/aluminium/system-profile",
     ["aluminium profile", "t-slot", "extrusion"]),
    (r"sigma profiles|carpentry iron", "profiles/steel/strip", ["profile"]),
    (r"servo", "electrical/motor/servo-motor", ["servo"]),
    (r"stepper|nema", "electrical/motor/stepper-motor", ["stepper motor"]),
    (r"motor driver", "electronics/module/breakout-board", ["motor driver"]),
    (r"motor", "electrical/motor/electric-motor", ["motor"]),
    (r"hotend", "machine-elements/3d-printer/hotend", ["3d printer", "hotend"]),
    (r"endstop", "electrical/controls/limit-switch", ["endstop", "limit switch"]),
    (r"push buttons?", "electrical/controls/push-button", ["push button"]),
    (r"batter", "electrical/power/battery", ["battery"]),
    (r"power suppl|dcdc", "electrical/power/power-supply", ["power supply"]),
    (r"breaker", "electrical/controls/switch", ["circuit breaker"]),
    (r"electrical switch", "electrical/controls/switch", ["switch"]),
    (r"\bfans?\b", "electrical/cooling/fan", ["fan"]),
    (r"singleboardcomputer|raspberry|arduino|beaglebone", "electronics/module/single-board-computer", ["single board computer"]),
    (r"computing/storage", "electronics/module/storage-device", ["storage"]),
    (r"headers?/|jumper", "electronics/component/pin-header", ["header"]),
    (r"connector", "electronics/component/connector", ["connector"]),
    (r"/ic/", "electronics/component/ic", ["ic", "chip"]),
    (r"/leds?/", "electronics/component/led", ["led"]),
    (r"capacitor", "electronics/component/capacitor", ["capacitor"]),
    (r"resistor|photoresistor", "electronics/component/resistor", ["resistor"]),
    (r"potentiometer|rotary resistor|encoder", "electronics/component/potentiometer", ["potentiometer"]),
    (r"inductor", "electronics/component/inductor", ["inductor"]),
    (r"transistor", "electronics/component/transistor", ["transistor"]),
    (r"diode", "electronics/component/diode", ["diode"]),
    (r"crystal", "electronics/component/crystal", ["crystal"]),
    (r"fuse", "electronics/component/fuse", ["fuse"]),
    (r"heatsink", "electronics/component/heatsink", ["heatsink"]),
    (r"buzzer", "electronics/component/buzzer", ["buzzer"]),
    (r"antenna", "electronics/module/antenna", ["antenna"]),
    (r"display", "electronics/module/display", ["display"]),
    (r"optical", "electronics/component/optocoupler", ["optical"]),
    (r"electronics parts/(switch|buttons)", "electronics/component/switch", ["switch", "button"]),
    (r"sensor|camera", "electronics/module/sensor", ["sensor"]),
    (r"cylinder", "pneumatics/cylinder/pneumatic-cylinder", ["pneumatic cylinder"]),
    (r"manifold|electro-pneumatic", "pneumatics/valve/valve", ["pneumatics"]),
    (r"/doors?/", "construction/finishing/door", ["door"]),
    (r"/windows?/", "construction/finishing/window", ["window"]),
    (r"construction blocks|foundation|wikihouse", "construction/element/building-block", ["building block"]),
    (r"roof|scaffold|building construction", "construction/structure/beam", ["construction"]),
    (r"hydro equipment|toilet|washbasin|shower", "construction/sanitary/washbasin", ["sanitary"]),
    (r"hvac|duct", "hvac/duct/air-duct", ["duct", "hvac"]),
    (r"flange", "piping/flange/weld-flange", ["flange"]),
    (r"elbow", "piping/pipe/elbow", ["elbow"]),
    (r"\btee\b", "piping/pipe/tee", ["tee"]),
    (r"tank", "tanks/tank/water-tank", ["tank"]),
    (r"pipes|tubes|pipe", "piping/pipe/straight-pipe", ["pipe"]),
    (r"container|logistics", "logistics/load/container", ["container"]),
    (r"chairs?/", "furniture/seating/chair", ["chair"]),
    (r"tables?/", "furniture/tables/side-table", ["table"]),
    (r"shelf|storage", "furniture/storage/rack", ["shelf"]),
    (r"beds?/", "furniture/bedroom/bed", ["bed"]),
    (r"hinge", "connections/hinge/door-hinge", ["hinge"]),
    (r"mountings?/|bracket", "connections/bracket/mounting-bracket", ["bracket", "mount"]),
    (r"wheels?/", "machine-elements/foot/wheel", ["wheel"]),
    (r"hand tools", "tools/hand-tools/wrench", ["tool"]),
    (r"medical", "medical/device/aid", ["medical"]),
    (r"appliance", "consumer-products/household/appliance", ["appliance"]),
    (r"capsule|cup|bottle|can\b|cans/", "consumer-products/packaging/bottle", ["packaging"]),
    (r"keychain|key-?ring|coin|recycling|jewel|lego|sport|archery|scale models|pushpin|lock", "consumer-products/miscellaneous/toy", []),
]
TOP_SECTORS = {
    "Architectural Parts": ["construction"], "Computing": ["electronics"], "Electrical Parts": ["electronics", "industry"],
    "Electro-pneumatic": ["industry", "machine-building"], "Electronics Parts": ["electronics"],
    "Generic objects": ["consumer-products"], "HVAC": ["construction"], "Industrial Design": ["consumer-products"],
    "Logistics": ["logistics"], "Mechanical Parts": ["machine-building", "industry"], "Medical Parts": ["medical"],
    "Pipes and tubes": ["construction", "industry"], "Robots": ["machine-building"], "Sensors": ["electronics"],
    "Sports": ["consumer-products"], "Symbols": ["consumer-products"], "DummiesAndSculptures": ["consumer-products"],
}


def readable(stem: str) -> str:
    s = stem.replace("_", " ")
    s = re.sub(r"(?<=\d)(?=(ISO|DIN|EN)\d)", " ", s)                       # ISO7093DIN9021 -> ISO7093 DIN9021
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z][a-z])", " ", s)                      # M10FlatWasher -> M10 Flat Washer
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1].upper() + s[1:]


def properties(text: str) -> dict:
    from partsfinder.ingest.metadata import hints_from_name
    hints = hints_from_name(text)
    props = dict(hints["properties"])
    m = re.search(r"\bM(\d+(?:[.,]\d+)?)(?:x(\d+(?:[.,]\d+)?))?\b", text)
    if m:
        props.setdefault("thread", f"M{m.group(1).replace(',', '.')}")
        if m.group(2):
            props.setdefault("length_mm", float(m.group(2).replace(",", ".")))
    m = re.search(r"\bz(\d{1,3})\b", text)
    if m and "sprocket" in text.lower():
        props["teeth"] = int(m.group(1))
    m = re.search(r"\b(\d+(?:[.,]\d+)?)x(\d+(?:[.,]\d+)?)(?:x(\d+(?:[.,]\d+)?))?\b", text)
    if m and "thread" not in props:
        props["size"] = m.group(0).replace(",", ".")
    return {"properties": props, "standards": hints["standards"], "material": hints.get("material")}


def classify(rel: str, name: str) -> tuple[str, list[str]]:
    hay = f"{rel}/{name}".lower()
    for pattern, cat, tags in RULES:
        if re.search(pattern, hay):
            return cat, tags
    top = rel.split("/")[0]
    return {"Architectural Parts": "construction/finishing", "Robots": "machine-elements/cnc",
            "DummiesAndSculptures": "consumer-products/miscellaneous/toy"}.get(top, "other/unknown"), []


def items(src: Path) -> list[Item]:
    commit = git_commit(src)
    curated = json.loads(CURATED.read_text(encoding="utf-8")) if CURATED.exists() else {}
    out: list[Item] = []
    for f in sorted(src.rglob("*")):
        if f.suffix.lower() not in (".step", ".stp") or ".git" in f.parts or not f.is_file():
            continue
        rel = f.relative_to(src).as_posix()
        if any(s in rel for s in SKIP):
            continue
        top = rel.split("/")[0]
        folder = str(Path(rel).parent)
        pid = f"fc-{slug(f.stem)}-{hashlib.sha1(rel.encode()).hexdigest()[:6]}"
        base = {"source": "freecad-library", "license": LICENSE,
                "source_ref": f"https://github.com/FreeCAD/FreeCAD-library/blob/{commit}/{quote(rel)}"}
        if rel in curated:
            m = curated[rel]
            meta = {"name": m["name"], "description": m["description"], "category_path": m["category_path"],
                    "sectors": m.get("sectors", []), "tags": sorted({t.lower() for t in m.get("tags", [])}),
                    "properties": {"original_name": f.name, "folder_in_freecad_library": folder}, **base}
            if m.get("material"):
                meta["material"] = m["material"]
            if m.get("kind"):
                meta["kind"] = m["kind"]
        else:
            name = readable(f.stem)
            cat, tags = classify(rel, name)
            hints = properties(name)
            words = [w.lower() for w in re.split(r"[\s/&,]+", folder) if len(w) > 2 and not w.isdigit()]
            meta = {"name": name[:200],
                    "description": f"{name}. From the FreeCAD parts library ({folder}).",
                    "category_path": cat, "sectors": TOP_SECTORS.get(top, []),
                    "tags": list(dict.fromkeys([*tags, *words]))[:14],
                    "standards": hints["standards"],
                    "properties": {**hints["properties"], "original_name": f.name, "folder_in_freecad_library": folder},
                    **base}
            if hints["material"]:
                meta["material"] = hints["material"]
        out.append(Item(id=pid, file=f, url=f"{REPO}/{commit}/{quote(rel)}", meta=meta))
    return out


SOURCE = Source(
    name="freecad-library", title="FreeCAD parts library", license=LICENSE, license_text="",
    attribution=ATTRIBUTION, homepage="https://github.com/FreeCAD/FreeCAD-library", files="remote", items=items,
    license_file="LICENSE-Assets",
)
