"""KiCad 3D models: ~6,000 electronic components (resistors, ICs, connectors, ...), CC-BY-SA 4.0 with an exception.

Source: https://github.com/KiCad/kicad-packages3D (the archive of the official library; newer versions live at
gitlab.com/kicad/libraries/kicad-packages3D). Only the STEP files are used, linked at a pinned commit.
Names and properties come from KiCad's own naming convention (package, pitch, pins, orientation).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from common import Item, Source, git_commit, slug

REPO = "https://raw.githubusercontent.com/KiCad/kicad-packages3D"

# library folder -> (category_path, readable label, tags)
FAMILIES: dict[str, tuple[str, str, list[str]]] = {
    "Battery": ("electrical/power/battery-holder", "Battery holder", ["battery", "battery holder", "cell"]),
    "Button_Switch_SMD": ("electronics/component/switch", "SMD switch", ["switch", "button", "dip switch", "tactile"]),
    "Button_Switch_THT": ("electronics/component/switch", "Through-hole switch", ["switch", "push button", "tactile"]),
    "Buzzer_Beeper": ("electronics/component/buzzer", "Buzzer", ["buzzer", "beeper", "piezo", "sound"]),
    "Capacitor_SMD": ("electronics/component/capacitor", "SMD capacitor", ["capacitor", "ceramic", "chip capacitor"]),
    "Capacitor_THT": ("electronics/component/capacitor", "Through-hole capacitor", ["capacitor", "electrolytic", "film"]),
    "Capacitor_Tantalum_SMD": ("electronics/component/capacitor", "Tantalum capacitor", ["capacitor", "tantalum", "polarized"]),
    "Connector": ("electronics/component/connector", "Connector", ["connector", "header"]),
    "Connector_AMASS": ("electronics/component/connector", "Power connector", ["connector", "power", "xt60", "battery"]),
    "Connector_BarrelJack": ("electronics/component/connector", "Barrel jack", ["connector", "dc jack", "power jack", "barrel"]),
    "Connector_Card": ("electronics/component/connector", "Card socket", ["connector", "card", "sd card", "socket"]),
    "Connector_Coaxial": ("electronics/component/connector", "Coaxial connector", ["connector", "coaxial", "rf", "sma"]),
    "Connector_Dsub": ("electronics/component/connector", "D-sub connector", ["connector", "d-sub", "dsub", "serial"]),
    "Connector_FFC-FPC": ("electronics/component/connector", "FFC/FPC connector", ["connector", "ffc", "fpc", "flat cable"]),
    "Connector_IDC": ("electronics/component/connector", "IDC box header", ["connector", "idc", "box header", "ribbon cable"]),
    "Connector_JST": ("electronics/component/connector", "JST connector", ["connector", "jst", "wire to board"]),
    "Connector_Molex": ("electronics/component/connector", "Molex connector", ["connector", "molex", "wire to board"]),
    "Connector_Phoenix_GMSTB": ("electronics/component/terminal-block", "Pluggable terminal block", ["connector", "terminal block", "pluggable"]),
    "Connector_Phoenix_MC": ("electronics/component/terminal-block", "Pluggable terminal block", ["connector", "terminal block", "pluggable"]),
    "Connector_Phoenix_MC_HighVoltage": ("electronics/component/terminal-block", "Pluggable terminal block (high voltage)", ["connector", "terminal block", "high voltage"]),
    "Connector_Phoenix_MSTB": ("electronics/component/terminal-block", "Pluggable terminal block", ["connector", "terminal block", "pluggable"]),
    "Connector_Pin": ("electronics/component/connector", "Solder pin", ["connector", "pin", "solder pin"]),
    "Connector_PinHeader_1.00mm": ("electronics/component/pin-header", "Pin header 1.00 mm", ["pin header", "header", "male", "connector"]),
    "Connector_PinHeader_1.27mm": ("electronics/component/pin-header", "Pin header 1.27 mm", ["pin header", "header", "male", "connector"]),
    "Connector_PinHeader_2.00mm": ("electronics/component/pin-header", "Pin header 2.00 mm", ["pin header", "header", "male", "connector"]),
    "Connector_PinHeader_2.54mm": ("electronics/component/pin-header", "Pin header 2.54 mm", ["pin header", "header", "male", "connector"]),
    "Connector_PinSocket_1.00mm": ("electronics/component/pin-header", "Pin socket 1.00 mm", ["pin socket", "female header", "socket", "connector"]),
    "Connector_PinSocket_1.27mm": ("electronics/component/pin-header", "Pin socket 1.27 mm", ["pin socket", "female header", "socket", "connector"]),
    "Connector_PinSocket_2.00mm": ("electronics/component/pin-header", "Pin socket 2.00 mm", ["pin socket", "female header", "socket", "connector"]),
    "Connector_PinSocket_2.54mm": ("electronics/component/pin-header", "Pin socket 2.54 mm", ["pin socket", "female header", "socket", "connector"]),
    "Connector_RJ": ("electronics/component/connector", "RJ45 jack", ["connector", "rj45", "ethernet", "modular jack"]),
    "Connector_SATA_SAS": ("electronics/component/connector", "SATA connector", ["connector", "sata", "disk"]),
    "Connector_Samtec": ("electronics/component/connector", "Board-to-board connector", ["connector", "board to board", "mezzanine"]),
    "Connector_Stocko": ("electronics/component/connector", "Wire-to-board connector", ["connector", "wire to board"]),
    "Connector_USB": ("electronics/component/connector", "USB connector", ["connector", "usb"]),
    "Converter_ACDC": ("electronics/module/power-converter", "AC/DC converter", ["power supply", "ac dc", "converter", "module"]),
    "Converter_DCDC": ("electronics/module/power-converter", "DC/DC converter", ["power supply", "dc dc", "converter", "module"]),
    "Crystal": ("electronics/component/crystal", "Crystal", ["crystal", "quartz", "resonator", "clock"]),
    "Diode_SMD": ("electronics/component/diode", "SMD diode", ["diode", "rectifier", "schottky", "zener"]),
    "Diode_THT": ("electronics/component/diode", "Through-hole diode", ["diode", "rectifier", "axial"]),
    "Display": ("electronics/module/display", "Display", ["display", "lcd", "screen"]),
    "Display_7Segment": ("electronics/module/display", "7-segment display", ["display", "7 segment", "seven segment", "led"]),
    "Ferrite_THT": ("electronics/component/ferrite", "Ferrite", ["ferrite", "emi", "choke"]),
    "Filter": ("electronics/component/filter", "Filter", ["filter", "rf", "emi"]),
    "Fuse": ("electronics/component/fuse", "Fuse", ["fuse", "fuse holder", "protection"]),
    "Heatsink": ("electronics/component/heatsink", "Heatsink", ["heatsink", "cooling", "heat sink"]),
    "Inductor_SMD": ("electronics/component/inductor", "SMD inductor", ["inductor", "coil", "choke"]),
    "Inductor_THT": ("electronics/component/inductor", "Through-hole inductor", ["inductor", "coil", "choke"]),
    "LED_SMD": ("electronics/component/led", "SMD LED", ["led", "light", "indicator"]),
    "LED_THT": ("electronics/component/led", "Through-hole LED", ["led", "light", "indicator"]),
    "Module": ("electronics/module/development-board", "Module", ["module", "board", "development board"]),
    "MountingEquipment": ("electronics/component/mounting-hardware", "Mounting equipment", ["mounting", "din rail", "adapter"]),
    "Mounting_Wuerth": ("electronics/component/mounting-hardware", "PCB standoff", ["standoff", "spacer", "pcb mount", "smd nut", "threaded"]),
    "OptoDevice": ("electronics/component/optocoupler", "Opto device", ["optocoupler", "photo", "light sensor", "ir"]),
    "Oscillator": ("electronics/component/oscillator", "Oscillator", ["oscillator", "clock", "crystal oscillator"]),
    "Package_BGA": ("electronics/component/ic", "BGA package", ["ic", "chip", "bga", "ball grid array"]),
    "Package_DFN_QFN": ("electronics/component/ic", "DFN/QFN package", ["ic", "chip", "qfn", "dfn", "leadless"]),
    "Package_DIP": ("electronics/component/ic", "DIP package", ["ic", "chip", "dip", "dil", "through hole"]),
    "Package_DirectFET": ("electronics/component/transistor", "DirectFET package", ["transistor", "mosfet", "power"]),
    "Package_LGA": ("electronics/component/ic", "LGA package", ["ic", "chip", "lga", "land grid array"]),
    "Package_QFP": ("electronics/component/ic", "QFP package", ["ic", "chip", "qfp", "tqfp", "lqfp"]),
    "Package_SIP": ("electronics/component/ic", "SIP package", ["ic", "chip", "sip", "single in line"]),
    "Package_SO": ("electronics/component/ic", "SO package", ["ic", "chip", "soic", "ssop", "tssop", "small outline"]),
    "Package_SON": ("electronics/component/ic", "SON package", ["ic", "chip", "son", "leadless"]),
    "Package_TO_SOT_SMD": ("electronics/component/transistor", "TO/SOT package (SMD)", ["transistor", "regulator", "sot", "dpak", "mosfet"]),
    "Package_TO_SOT_THT": ("electronics/component/transistor", "TO package (through-hole)", ["transistor", "regulator", "to-220", "mosfet", "power"]),
    "Potentiometer_SMD": ("electronics/component/potentiometer", "SMD trimmer", ["potentiometer", "trimmer", "variable resistor"]),
    "Potentiometer_THT": ("electronics/component/potentiometer", "Potentiometer", ["potentiometer", "trimmer", "variable resistor"]),
    "RF_Antenna": ("electronics/module/antenna", "Chip antenna", ["antenna", "rf", "2.4 ghz"]),
    "RF_Converter": ("electronics/component/filter", "RF balun", ["balun", "rf", "transformer"]),
    "RF_Module": ("electronics/module/rf-module", "RF module", ["rf module", "wireless", "wifi", "radio"]),
    "Relay_SMD": ("electronics/component/relay", "SMD relay", ["relay", "switching"]),
    "Relay_THT": ("electronics/component/relay", "Relay", ["relay", "switching"]),
    "Resistor_SMD": ("electronics/component/resistor", "SMD resistor", ["resistor", "chip resistor"]),
    "Resistor_THT": ("electronics/component/resistor", "Through-hole resistor", ["resistor", "axial", "radial"]),
    "Sensor": ("electronics/component/sensor", "Sensor", ["sensor", "humidity", "temperature"]),
    "Sensor_Audio": ("electronics/component/sensor", "Microphone", ["sensor", "microphone", "mems", "audio"]),
    "Sensor_Current": ("electronics/component/sensor", "Current sensor", ["sensor", "current sensor", "transducer"]),
    "Sensor_Distance": ("electronics/component/sensor", "Distance sensor", ["sensor", "distance", "time of flight", "lidar"]),
    "Sensor_Pressure": ("electronics/component/sensor", "Pressure sensor", ["sensor", "pressure", "barometer"]),
    "TerminalBlock_Altech": ("electronics/component/terminal-block", "Terminal block", ["terminal block", "screw terminal", "connector"]),
    "TerminalBlock_Phoenix": ("electronics/component/terminal-block", "Terminal block", ["terminal block", "screw terminal", "connector"]),
    "TestPoint": ("electronics/component/test-point", "Test point", ["test point", "probe", "loop"]),
    "Transformer_SMD": ("electronics/component/transformer", "SMD transformer", ["transformer", "ethernet", "magnetics"]),
    "Transformer_THT": ("electronics/component/transformer", "Transformer", ["transformer", "mains", "power"]),
    "Valve": ("electronics/component/vacuum-tube", "Vacuum tube", ["vacuum tube", "valve", "tube"]),
    "Varistor": ("electronics/component/varistor", "Varistor", ["varistor", "mov", "surge protection"]),
}

LICENSE = "CC-BY-SA-4.0 WITH KiCad-libraries-exception"

ATTRIBUTION = """# KiCad 3D models

The parts in this pack are the STEP models of the KiCad library (https://github.com/KiCad/kicad-packages3D,
now https://gitlab.com/kicad/libraries/kicad-packages3D), made by the KiCad library contributors and licensed under
Creative Commons Attribution-ShareAlike 4.0 with the KiCad libraries exception (see LICENSE.txt).
The models themselves are not modified; each part links to its original file at the commit in pack.json.
Names, descriptions and classification were added by Partsfinder from KiCad's naming convention.
This collection is shared under the same licence (CC-BY-SA 4.0 with the KiCad libraries exception).
Using a model in your own design does not require you to share that design.
"""


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def describe(stem: str) -> tuple[str, dict, list[str]]:
    """KiCad naming convention -> readable words, properties and tags."""
    props: dict = {}
    words: list[str] = []
    tags: list[str] = []
    m = re.search(r"(?:^|_)P(\d+(?:[.,]\d+)?)(?:x(\d+(?:[.,]\d+)?))?mm", stem)
    if m:
        props["pitch_mm"] = _num(m.group(1))
        words.append(f"pitch {m.group(1)} mm")
    m = re.search(r"(?:^|_)(\d{1,2})x(\d{1,3})(?:[-_]|$)", stem)
    if m:
        rows, per_row = int(m.group(1)), int(m.group(2))
        props.update({"rows": rows, "pins_per_row": per_row, "pins": rows * per_row})
        words.append(f"{rows * per_row} pins ({rows} x {per_row})")
        tags += [f"{rows}x{per_row:02d}", f"{rows * per_row} pin"]
    m = re.match(r"([A-Za-z]+(?:-\d+[A-Za-z]*)?)-(\d+)(?:[-_]|$)", stem)          # SOIC-8, QFN-40-1EP, DIP-24
    if m and "pins" not in props:
        props["pins"] = int(m.group(2))
        props["package"] = f"{m.group(1)}-{m.group(2)}"
        words.append(f"{m.group(2)} pins")
        tags += [m.group(1).lower(), props["package"].lower()]
    m = re.match(r"(?:R|C|L|D|LED|CP)_(\d{4})_(\d{4})Metric", stem)                  # chip size codes
    if m:
        props.update({"size_code": m.group(1), "size_code_metric": m.group(2)})
        words.append(f"chip size {m.group(1)} (metric {m.group(2)})")
        tags += [m.group(1), f"{m.group(2)} metric"]
    for key, label in (("D", "diameter"), ("L", "length"), ("W", "width"), ("H", "height")):
        mm = re.search(rf"(?:^|_){key}(\d+(?:[.,]\d+)?)mm", stem)
        if mm:
            props[f"{label}_mm"] = _num(mm.group(1))
            words.append(f"{label} {mm.group(1)} mm")
    m = re.search(r"(?:^|_)(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?mm", stem)
    if m:
        words.append(f"body {m.group(0).strip('_')}")
    for word, prop in (("Vertical", "vertical"), ("Horizontal", "horizontal"), ("Angled", "angled")):
        if re.search(rf"(?:^|_){word}(?:_|$)", stem):
            props["orientation"] = prop
            words.append(prop)
            tags.append(prop)
    if re.search(r"(?:^|_)SMD(?:_|$)", stem):
        props["mounting"] = "SMD"
    m = re.search(r"M(\d(?:\.\d)?)(?:_|$|-)", stem)
    if m and ("Mounting" in stem or "Heatsink" in stem):
        props["thread"] = f"M{m.group(1)}"
        tags.append(props["thread"].lower())
    return ", ".join(words), props, tags


def _raw_base(src: Path) -> tuple[str, str]:
    """(raw file URL base, page URL base) of the clone: the GitHub archive or the current library on GitLab."""
    try:
        origin = subprocess.run(["git", "-C", str(src), "remote", "get-url", "origin"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - not a clone: assume the GitHub archive
        origin = ""
    if "gitlab.com" in origin:
        repo = "https://gitlab.com/kicad/libraries/kicad-packages3D"
        return f"{repo}/-/raw", f"{repo}/-/blob"
    return REPO, "https://github.com/KiCad/kicad-packages3D/blob"


def items(src: Path) -> list[Item]:
    commit = git_commit(src)
    raw, page = _raw_base(src)
    out: list[Item] = []
    for folder in sorted(src.glob("*.3dshapes")):
        family = folder.name[: -len(".3dshapes")]
        if family in FAMILIES:
            cat, label, base_tags = FAMILIES[family]
        else:                       # a library newer than this table: still in, under electronic components
            print(f"  kicad: no mapping for {family}, filed under electronics/component")
            words = family.replace("_", " ")
            cat, label, base_tags = "electronics/component", words, [w.lower() for w in words.split() if len(w) > 2]
        mount = "SMD" if family.endswith("_SMD") else "THT" if family.endswith("_THT") else None
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in (".step", ".stp"):
                continue
            stem = f.stem
            readable = stem.replace("_", " ").replace(",", ".")
            detail, props, extra = describe(stem)
            if mount and "mounting" not in props:
                props["mounting"] = mount
            props["kicad_model"] = stem
            name = f"{label} {readable}"
            desc = f"{label}: {readable}"
            if detail:
                desc += f" ({detail})"
            desc += ". 3D model from the KiCad library, for mechanical fit checks and enclosures."
            tags = list(dict.fromkeys([*base_tags, *extra, *(["smd"] if props.get("mounting") == "SMD" else []),
                                       *(["through hole", "tht"] if props.get("mounting") == "THT" else []), "kicad"]))
            rel = f"{folder.name}/{f.name}"
            out.append(Item(
                id="kicad-" + slug(f"{family}-{stem}")[:110],
                file=f,
                url=f"{raw}/{commit}/{quote(rel)}",
                meta={"name": name[:200], "description": desc, "category_path": cat, "sectors": ["electronics"],
                      "tags": tags[:16], "properties": props, "source": "kicad-3d",
                      "source_ref": f"{page}/{commit}/{quote(rel)}",
                      "license": LICENSE},
            ))
    return out


SOURCE = Source(
    name="kicad-3d", title="KiCad 3D models (electronic components)", license=LICENSE,
    license_text="", attribution=ATTRIBUTION, homepage="https://gitlab.com/kicad/libraries/kicad-packages3D",
    files="remote", items=items, license_file="LICENSE.md",
)

