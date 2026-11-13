"""Adafruit CAD parts: ~490 development boards, breakouts, displays, sensors and other parts, MIT licence.

Source: https://github.com/adafruit/Adafruit_CAD_Parts (STEP files only, linked at a pinned commit).
Every folder is "<product number> <name>"; the category comes from keywords in that name.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from common import Item, Source, git_commit, slug

REPO = "https://raw.githubusercontent.com/adafruit/Adafruit_CAD_Parts"
LICENSE = "MIT"

ATTRIBUTION = """# Adafruit CAD parts

The parts in this pack come from the Adafruit CAD parts repository (https://github.com/adafruit/Adafruit_CAD_Parts),
Copyright (c) 2016 Adafruit Industries, licensed under the MIT licence (see LICENSE.txt).
The models are not modified; each part links to its original file at the commit in pack.json.
Names and classification were added by Partsfinder from the folder names. Adafruit is a trademark of Adafruit
Industries; this pack is not made or endorsed by Adafruit.
"""

RULES: list[tuple[str, str, list[str]]] = [
    (r"extrusion", "profiles/aluminium/system-profile", ["aluminium extrusion", "2020", "t-slot"]),
    (r"pulley", "drivetrain/transmission/timing-pulley", ["timing pulley", "gt2"]),
    (r"servo", "electrical/motor/servo-motor", ["servo", "rc servo"]),
    (r"stepper", "electrical/motor/stepper-motor", ["stepper motor"]),
    (r"\bmotor\b(?!.*(shield|wing|driver|bonnet|hat))", "electrical/motor/electric-motor", ["motor", "dc motor"]),
    (r"arcade", "electrical/controls/arcade-button", ["arcade button", "push button"]),
    (r"joystick|thumbstick", "electrical/controls/joystick", ["joystick"]),
    (r"lipo|battery|\b18650\b", "electrical/power/battery", ["battery", "lipo"]),
    (r"speaker", "electrical/audio/speaker", ["speaker", "audio"]),
    (r"camera", "electronics/module/camera", ["camera"]),
    (r"tft|oled|lcd|e-?ink|epaper|e-paper|display|7[ -]segment|segment", "electronics/module/display", ["display", "screen"]),
    (r"matrix|neopixel|dotstar|led strip|ring", "electronics/module/led-matrix", ["led", "neopixel", "rgb led"]),
    (r"feather(?!wing)|qt py|itsybitsy|trinket|metro|circuit playground|kb2040|\bpico\b|macropad|gemma|flora|teensy|"
     r"fruit jam|esp32-?s[23]? (dev|feather)|grand central|pyportal|pybadge|pygamer|clue|funhouse|magtag|matrixportal",
     "electronics/module/development-board", ["development board", "microcontroller"]),
    (r"sensor|accelero|gyro|imu|temperature|humidity|pressure|altimeter|gps|light|lux|proximity|distance|tof|\bsht|bme|"
     r"bmp|lis3|mpu|thermocouple|gas|co2|\buv\b|magnetometer|compass|heart|color|spectral|touch|capacitive",
     "electronics/module/sensor", ["sensor", "breakout"]),
    (r"button|switch|tactile", "electrical/controls/push-button", ["button", "switch"]),
    (r"potentiometer|\bpot\b|rotary encoder|encoder", "electronics/component/potentiometer", ["potentiometer", "encoder"]),
    (r"connector|jack|cable|socket|terminal", "electronics/component/connector", ["connector"]),
    (r"\bled\b|laser", "electronics/component/led", ["led", "light"]),
    (r"featherwing|bonnet|\bhat\b|shield|wing|backpack|breakout|stemma|driver|extender|booster|amplifier|dac|adc|"
     r"charger|buck|boost|level|proto|adapter|multiplexer|expander|controller|rtc|clock|audio|radio|lora|wifi|bluetooth|"
     r"usb|i2c|spi|uart|can bus|relay", "electronics/module/breakout-board", ["breakout board", "add-on board"]),
]


def classify(name: str) -> tuple[str, list[str]]:
    low = name.lower()
    for pattern, cat, tags in RULES:
        if re.search(pattern, low):
            return cat, tags
    return "electronics/module/pcb", ["circuit board"]


def items(src: Path) -> list[Item]:
    commit = git_commit(src)
    out: list[Item] = []
    seen: set[str] = set()
    for f in sorted(src.rglob("*")):
        if f.suffix.lower() not in (".step", ".stp") or ".git" in f.parts or not f.is_file():
            continue
        rel = f.relative_to(src).as_posix()
        folder = f.parent.name
        m = re.match(r"(\d{2,5})\s+(.+)", folder)
        number, title = (m.group(1), m.group(2)) if m else (None, folder)
        variant = re.sub(rf"^{number}\s*" if number else r"^", "", f.stem).strip()
        name = title if (not variant or variant.lower() == title.lower()) else f"{title} ({variant})" \
            if variant.lower() not in title.lower() else title
        siblings = [s for s in f.parent.iterdir() if s.suffix.lower() in (".step", ".stp")]
        if len(siblings) > 1 and variant and variant.lower() != title.lower():
            name = f"{title}: {variant}" if variant.lower() not in title.lower() else variant
        cat, tags = classify(f"{title} {variant}")
        words = [w.lower() for w in re.split(r"[\s()\-,/]+", title) if len(w) > 1]
        props = {"original_name": f.name}
        if number:
            props["adafruit_product"] = int(number)
        pid = "ada-" + slug(f"{number or ''}-{f.stem}")[:100]
        if pid in seen:                                  # the same file name in two folders
            pid += "-" + hashlib.sha1(rel.encode()).hexdigest()[:6]
        seen.add(pid)
        out.append(Item(
            id=pid,
            file=f,
            url=f"{REPO}/{commit}/{quote(rel)}",
            meta={"name": f"Adafruit {name}"[:200],
                  "description": f"Adafruit {name}" + (f" (product {number})" if number else "")
                                 + ". 3D model of the board or part, for enclosures and fit checks.",
                  "category_path": cat, "sectors": ["electronics"],
                  "tags": list(dict.fromkeys([*tags, *words, "adafruit"]))[:14], "properties": props,
                  "source": "adafruit-cad-parts", "license": LICENSE,
                  "source_ref": f"https://github.com/adafruit/Adafruit_CAD_Parts/blob/{commit}/{quote(rel)}"},
        ))
    return out


SOURCE = Source(
    name="adafruit-cad-parts", title="Adafruit CAD parts (boards, breakouts, displays)", license=LICENSE,
    license_text="", attribution=ATTRIBUTION, homepage="https://github.com/adafruit/Adafruit_CAD_Parts",
    files="remote", items=items, license_file="LICENSE",
)
