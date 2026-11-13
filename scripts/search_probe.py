"""Runs a large set of real engineering questions through the search (no AI) and writes a readable report.

For finding bugs and for comparing before/after a change. It only reads the library.
    backend/.venv/bin/python scripts/search_probe.py [--db FILE] [--out report.txt] [--only TEXT] [--ai]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend"))

QUERIES = [
    # fasteners: designations, units, languages, typing variants
    "M8x30 socket head cap screw", "socket head bolt M8 x 30 12.9", "M8×30 ISO 4762", "m8x30 din 912",
    "DIN 933 M10x50", "hex bolt M12 x 1.25 x 40", "bolt M8 length between 25 and 40 mm", "M8 bolt",
    "stainless steel M6 countersunk screw 20mm", "A4-80 M10 bolt", "1/4-20 x 1 socket head cap screw", "#10-32 screw",
    "grub screw M5", "nyloc nut M8", "M8 nut", "washer for M8", "large washer M10", "spring washer M12",
    "circlip 20 mm shaft", "retaining ring for 35 mm bore", "parallel key 8x7x40", "dowel pin 6 x 20",
    "inbusbout M8x30", "zeskantbout M10x40", "moer M10", "ring M8", "Innensechskantschraube M6x16",
    # bearings and seals
    "6205-2RS", "6205 bearing", "bearing 25x52x15", "bearing 20 mm bore sealed", "608 bearing", "608zz",
    "angular contact bearing 7205", "tapered roller bearing 30205", "needle bearing", "kogellager 10 mm as",
    "O-ring 20 x 2", "O-ring for 20 mm bore", "o-ring ID 50 cross section 3",
    # piping
    "weld neck flange 2 inch class 300", "DN50 PN16 flange", "blind flange 4 inch 150#", "slip-on flange NPS 1 class 600",
    "flens DN50",
    # gears
    "spur gear module 2 40 teeth", "gear m1 z20", "spur gear 60 teeth module 1.5", "tandwiel module 2",
    "give me a spur gear pair for 3:1 reduction",
    # profiles
    "square hollow section 40x40x3", "SHS 50x50x4", "RHS 100x50x5", "IPE 200", "HEA 160", "flat bar 40x10",
    "round bar 20 mm", "angle 50x50x5", "2020 aluminium profile 500 mm", "v-slot 20x40", "T-slot profile 40x40",
    # electronics
    "0805 resistor", "10k resistor 0603", "SOIC-8", "TSSOP-20", "QFN-32 5x5", "TO-220", "SOT-23",
    "electrolytic capacitor 10 mm diameter", "pin header 2x20 2.54mm", "female header 1x6", "JST XH 4 pin",
    "USB-C connector", "micro USB connector", "RJ45 jack", "DC barrel jack", "screw terminal 2 pin 5.08",
    "crystal HC49", "SMD LED 0603", "5mm LED", "tactile switch 6x6", "relay", "buzzer 12mm", "Arduino Uno",
    "Raspberry Pi", "Feather RP2040", "OLED display 128x64", "ESP32 module", "NeoPixel ring",
    # machine parts
    "NEMA 17 stepper motor", "servo motor", "40mm fan 12V", "shaft coupling 5 to 8 mm", "GT2 pulley 20 teeth",
    "linear bearing 8mm", "lead screw 8mm",
    # the hard ones
    "Stainless bolt to hold a 40 kg motor bracket to an aluminium plate, outdoors near the sea",
    "Bearing for a 25 mm shaft at 6000 rpm, sealed, under 15 mm wide",
    "Something like a 6205-2RS but food-safe",
    "M12 fine-pitch nut that won't come loose under vibration up to 200 °C",
    "Flange to connect a DN80 PN16 pipe to a 3 inch ASME class 150 valve",
    "Spur gear pair for 3:1 reduction, centre distance 80 mm, module between 1.5 and 2",
    "Aluminium profile frame for a 1200 x 800 mm table carrying 150 kg",
    "O-ring for a 20 mm bore hydraulic piston, 200 bar",
    "Connector for a sensor on a moving robot arm, 4 pins, IP67",
    "all parts made of 1.4301 thinner than 3 mm",
    # odd input
    "", "   ", "???", "a", "M", "M8x", "x30", "'; DROP TABLE parts; --", "<script>alert(1)</script>",
    "bolt " * 200, "😀 bolt", "Ø20 shaft", "something to hang a shelf on", "quantum flux capacitor",
    "M8 bolt and M8 nut and M8 washer", "3 x M8x30 bolt", "bolt not stainless M8",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--out", default=str(PROJECT / "data" / "search_probe.txt"))
    ap.add_argument("--only")
    ap.add_argument("--ai", action="store_true", help="also let the AI judge (needs a key)")
    args = ap.parse_args()
    if args.db:
        import os
        os.environ["PARTSFINDER_DB_PATH"] = str(Path(args.db).resolve())
    from fastapi.testclient import TestClient

    from partsfinder.api import create_app
    from partsfinder.config import get_settings
    s = get_settings()
    if not args.ai:
        s = dataclasses.replace(s, anthropic_api_key=None)
    client = TestClient(create_app(s), raise_server_exceptions=False)
    lines, problems = [], []
    queries = [q for q in QUERIES if not args.only or args.only.lower() in q.lower()]
    total = 0.0
    for q in queries:
        t = time.perf_counter()
        r = client.post("/search", json={"query": q, "use_ai": args.ai})
        ms = (time.perf_counter() - t) * 1000
        total += ms
        shown = q if len(q) < 90 else q[:60] + f"... ({len(q)} chars)"
        if r.status_code != 200:
            problems.append(f"{shown!r}: HTTP {r.status_code} {r.text[:200]}")
            lines.append(f"\n### {shown!r}  HTTP {r.status_code}  {r.text[:300]}")
            continue
        d = r.json()
        lines.append(f"\n### {shown!r}  [{d.get('status')}] {ms:.0f} ms  — {d.get('message', '')[:160]}")
        if d.get("groups"):
            for g in d["groups"]:
                lines.append(f"   group {g.get('request')!r}: {g.get('status')} — {g.get('message', '')[:120]}")
        for res in d.get("results", [])[:5]:
            checks = "; ".join(f"{c.get('label')}: {c.get('requested')} vs {c.get('found')} ({c.get('status')})"
                               for c in (res.get("spec_checks") or [])[:4])
            lines.append(f"   - {res.get('verdict', '')[:6]:6} {res['name'][:80]}  | {res.get('category_path')}"
                         + (f"\n       checks: {checks}" if checks else ""))
        if ms > 2000:
            problems.append(f"{shown!r}: slow ({ms:.0f} ms)")
    head = [f"{len(queries)} questions, {total / max(len(queries), 1):.0f} ms on average", *(f"PROBLEM {p}" for p in problems)]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head))
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
