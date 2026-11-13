"""Geometry for the engineering catalogue (CadQuery). Simplified but dimensionally correct models:
outer dimensions, bores, hole patterns and mating features are exact; internal details
(balls, windings, thread flanks) are left out, as in most supplier CAD downloads.

Usage (from the project folder):
    backend\\.venv\\Scripts\\python scripts\\engineering\\build.py            (Windows)
    backend/.venv/bin/python scripts/engineering/build.py                  (Mac/Linux)
Options: --out data/global/engineering  --only TEXT  --check (metadata only, no CadQuery)

Then import:  python -m partsfinder.ingest ../data/global/engineering   (from backend/)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT / "backend"))

from catalog import Item, catalog  # noqa: E402


def _cq():
    import cadquery as cq
    return cq


# ---- shapes ---------------------------------------------------------------------------------------
def ball_bearing(d, D, B, seal):
    cq = _cq()
    ring = cq.Workplane("XY").circle(D / 2).circle(d / 2).extrude(B)
    # recess between inner and outer ring (shield / seal / open race), depth differs per type
    t = (D - d) / 2
    r_in, r_out = d / 2 + t * 0.28, D / 2 - t * 0.22
    depth = {"open": B * 0.35, "2RS": 0.6, "2Z": 0.3}[seal]
    groove = cq.Workplane("XY").circle(r_out).circle(r_in).extrude(depth)
    ring = ring.cut(groove).cut(groove.translate((0, 0, B - depth)))
    if seal == "open":                                   # show the balls in the race
        n = max(7, int(math.pi * (r_in + r_out) / (t * 0.55)))
        rb = min((r_out - r_in) / 2 * 0.95, B * 0.32)
        balls = cq.Workplane("XY")
        for i in range(n):
            a = 2 * math.pi * i / n
            balls = balls.union(cq.Workplane("XY").sphere(rb).translate(
                ((r_in + r_out) / 2 * math.cos(a), (r_in + r_out) / 2 * math.sin(a), B / 2)))
        ring = ring.union(balls)
    return ring


def linear_bushing(d, D, L):
    cq = _cq()
    body = cq.Workplane("XY").circle(D / 2).circle(d / 2).extrude(L)
    for z in (L * 0.12, L * 0.88 - 1.1):                 # retaining ring grooves
        body = body.cut(cq.Workplane("XY").circle(D / 2 + 1).circle(D / 2 - 0.6).extrude(1.1).translate((0, 0, z)))
    return body


def shaft(d, L):
    cq = _cq()
    return cq.Workplane("XY").circle(d / 2).extrude(L).faces(">Z or <Z").edges().chamfer(min(0.5, d * 0.05))


def pillow_block(bore, H, Ht, L, J, A):
    cq = _cq()
    base_h = H * 0.42
    base = cq.Workplane("XY").box(L, A, base_h, centered=(True, True, False))
    hub_r = Ht - H
    hub = cq.Workplane("XZ").circle(hub_r).extrude(A / 2, both=True).translate((0, 0, H))
    web = cq.Workplane("XY").box(hub_r * 1.6, A * 0.8, H, centered=(True, True, False))
    body = base.union(web).union(hub)
    body = body.cut(cq.Workplane("XY").box(L * 2, A * 2, Ht, centered=(True, True, False)).translate((0, 0, Ht)))
    body = body.cut(cq.Workplane("XZ").circle(bore / 2).extrude(A, both=True).translate((0, 0, H)))
    slot_w = 13 if J < 120 else 17
    for x in (-J / 2, J / 2):
        body = body.cut(cq.Workplane("XY").slot2D(slot_w * 1.6, slot_w, 0).extrude(base_h * 3)
                        .translate((x, 0, -base_h)))
    return body


def stepper(flange, length, holes, pilot, ph, shaft, shaft_len):
    cq = _cq()
    body = cq.Workplane("XY").rect(flange, flange).extrude(length).edges("|Z").chamfer(flange * 0.09)
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.cut(cq.Workplane("XY").circle(1.6 if flange < 50 else 2.6).extrude(8)
                            .translate((sx * holes / 2, sy * holes / 2, length - 8)))
    pil = cq.Workplane("XY").circle(pilot / 2).extrude(ph).translate((0, 0, length))
    sh = cq.Workplane("XY").circle(shaft / 2).extrude(shaft_len).translate((0, 0, length + ph))
    # D-flat would differ per maker: round shaft
    return body.union(pil).union(sh)


def timing_pulley(z, od, bore, width, pitch):
    cq = _cq()
    r = od / 2
    tooth_depth = 0.75 if pitch <= 2 else 2.06
    pts = []
    for i in range(z):
        a0 = 2 * math.pi * i / z
        a1 = a0 + 2 * math.pi / z * 0.55
        for a, rr in ((a0, r), (a1, r), (a1 + 0.0001, r - tooth_depth), (a0 + 2 * math.pi / z - 0.0001, r - tooth_depth)):
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    teeth = cq.Workplane("XY").polyline(pts).close().extrude(width)
    fl = r + max(1.5, pitch * 0.6)
    flange_t = 1.0 if pitch <= 2 else 1.5
    hub_r = max(bore / 2 + 3.5, min(r - tooth_depth - 1, bore / 2 + 6))
    hub_l = 7 if pitch <= 2 else 10
    body = (teeth.union(cq.Workplane("XY").circle(fl).extrude(flange_t).translate((0, 0, -flange_t)))
            .union(cq.Workplane("XY").circle(fl).extrude(flange_t).translate((0, 0, width)))
            .union(cq.Workplane("XY").circle(hub_r).extrude(hub_l).translate((0, 0, -flange_t - hub_l))))
    body = body.cut(cq.Workplane("XY").circle(bore / 2).extrude(width + hub_l + 10).translate((0, 0, -hub_l - 5)))
    return body


def spur_gear(m, z, b, bore):
    cq = _cq()
    ra, rf = m * z / 2 + m, m * z / 2 - 1.25 * m
    pts = []
    for i in range(z):
        a = 2 * math.pi * i / z
        p = 2 * math.pi / z
        for frac, rr in ((0.0, rf), (0.12, rf), (0.22, ra), (0.38, ra), (0.48, rf)):
            pts.append((rr * math.cos(a + frac * p), rr * math.sin(a + frac * p)))
    g = cq.Workplane("XY").polyline(pts).close().extrude(b)
    g = g.cut(cq.Workplane("XY").circle(bore / 2).extrude(b))
    if bore >= 10:                                       # keyway DIN 6885 (approx.)
        kw = max(3, round(bore * 0.25))
        g = g.cut(cq.Workplane("XY").rect(kw, bore * 0.6).extrude(b).translate((0, bore / 2, 0)))
    return g


def tslot_profile(w, h, slot, core, L):
    cq = _cq()
    prof = cq.Workplane("XY").rect(w, h).extrude(L)
    depth = slot * 0.75 + 1.5
    centers = []
    nx, ny = int(round(w / 40)) or 1, int(round(h / 40)) or 1
    if w <= 30:
        nx = 1
    if h <= 30:
        ny = 1
    for i in range(nx):
        x = -w / 2 + w / nx * (i + 0.5)
        centers += [(x, h / 2 - depth / 2, 0, 0), (x, -h / 2 + depth / 2, 0, 0)]
    for j in range(ny):
        y = -h / 2 + h / ny * (j + 0.5)
        centers += [(w / 2 - depth / 2, y, 0, 1), (-w / 2 + depth / 2, y, 0, 1)]
    for x, y, _, vertical in centers:
        sw, sd = (depth, slot) if vertical else (slot, depth)
        prof = prof.cut(cq.Workplane("XY").rect(sw, sd).extrude(L).translate((x, y, 0)))
        # T-undercut
        uw, ud = (depth * 0.45, slot * 1.9) if vertical else (slot * 1.9, depth * 0.45)
        ox = (-depth * 0.2 if x > 0 else depth * 0.2) if vertical else 0
        oy = 0 if vertical else (-depth * 0.2 if y > 0 else depth * 0.2)
        prof = prof.cut(cq.Workplane("XY").rect(uw, ud).extrude(L).translate((x + ox, y + oy, 0)))
    for i in range(nx):
        for j in range(ny):
            prof = prof.cut(cq.Workplane("XY").circle(core / 2).extrude(L)
                            .translate((-w / 2 + w / nx * (i + 0.5), -h / 2 + h / ny * (j + 0.5), 0)))
    return prof


def cylinder_iso15552(bore, rod, stroke, sq):
    cq = _cq()
    head = sq * 0.55
    barrel = cq.Workplane("XY").rect(sq, sq).extrude(stroke + 20).edges("|Z").chamfer(sq * 0.12)
    barrel = barrel.translate((0, 0, head))
    caps = (cq.Workplane("XY").rect(sq, sq).extrude(head)
            .union(cq.Workplane("XY").rect(sq, sq).extrude(head).translate((0, 0, head + stroke + 20))))
    body = barrel.union(caps)
    pilot = cq.Workplane("XY").circle(rod * 1.3).extrude(4).translate((0, 0, 2 * head + stroke + 20))
    r = cq.Workplane("XY").circle(rod / 2).extrude(stroke * 0.3 + 25).translate((0, 0, 2 * head + stroke + 24))
    return body.union(pilot).union(r)


def cylinder_round(bore, rod, stroke):
    cq = _cq()
    D = bore + 4
    body = cq.Workplane("XY").circle(D / 2).extrude(stroke + 30)
    nose = cq.Workplane("XY").circle(D * 0.32).extrude(14).translate((0, 0, stroke + 30))
    back = cq.Workplane("XY").circle(D * 0.32).extrude(12).translate((0, 0, -12))
    r = cq.Workplane("XY").circle(rod / 2).extrude(stroke * 0.3 + 18).translate((0, 0, stroke + 44))
    return body.union(nose).union(back).union(r)


def flange(typ, pod, D, k, n, hd, t):
    cq = _cq()
    f = cq.Workplane("XY").circle(D / 2).extrude(t)
    rf = cq.Workplane("XY").circle(k / 2 - hd / 2 - 2).extrude(2).translate((0, 0, t))   # raised face
    f = f.union(rf)
    if typ == "11":
        neck_h = max(28, pod * 0.45)
        # hub tapers from the flange (thick) down to the pipe weld end (pipe OD)
        f = f.union(cq.Workplane("XY").circle(pod / 2).workplane(offset=neck_h)
                    .circle(pod / 2 + max(4, pod * 0.12)).loft().translate((0, 0, -neck_h)))
        f = f.cut(cq.Workplane("XY").circle(pod / 2 - 2.6).extrude(t + neck_h + 10).translate((0, 0, -neck_h - 5)))
    elif typ == "01":
        f = f.cut(cq.Workplane("XY").circle(pod / 2 + 0.6).extrude(t + 10).translate((0, 0, -5)))
    for i in range(n):
        a = 2 * math.pi * (i + 0.5) / n
        f = f.cut(cq.Workplane("XY").circle(hd / 2).extrude(t + 10)
                  .translate((k / 2 * math.cos(a), k / 2 * math.sin(a), -5)))
    return f


def rail(rw, rh, L, pitch):
    cq = _cq()
    r = cq.Workplane("YZ").rect(rw, rh).extrude(L).translate((0, 0, rh / 2))
    for side in (-1, 1):                                   # ball grooves
        r = r.cut(cq.Workplane("YZ").circle(rw * 0.09).extrude(L).translate((0, side * rw / 2, rh * 0.72)))
    n = int((L - 20) // pitch) + 1
    start = (L - (n - 1) * pitch) / 2
    for i in range(n):
        x = start + i * pitch
        r = r.cut(cq.Workplane("XY").circle(rw * 0.3).extrude(rh * 0.4).translate((x, 0, rh * 0.6)))
        r = r.cut(cq.Workplane("XY").circle(rw * 0.18).extrude(rh).translate((x, 0, 0)))
    return r


def carriage(cw, cl, ch, rw, rh):
    cq = _cq()
    block = cq.Workplane("XY").box(cl, cw, ch - 4, centered=(True, True, False)).translate((0, 0, 4))
    block = block.cut(cq.Workplane("XY").box(cl * 2, rw + 1, rh * 0.95 + 4, centered=(True, True, False)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            block = block.cut(cq.Workplane("XY").circle(2.5 if cw < 40 else 3.0).extrude(10)
                              .translate((sx * cl * 0.25, sy * cw * 0.35, ch - 10)))
    return block


def coupling(od, L, b1, b2):
    cq = _cq()
    c = cq.Workplane("XY").circle(od / 2).extrude(L)
    c = c.cut(cq.Workplane("XY").circle(b1 / 2).extrude(L / 2 + 0.01))
    c = c.cut(cq.Workplane("XY").circle(b2 / 2).extrude(L / 2).translate((0, 0, L / 2)))
    c = c.cut(cq.Workplane("XY").circle(od / 2 + 1).circle(od / 2 - 1.2).extrude(1.5).translate((0, 0, L / 2 - 0.75)))
    for z in (L * 0.2, L * 0.8):                           # set screw holes
        c = c.cut(cq.Workplane("YZ").circle(1.5 if od < 25 else 2.0).extrude(od).translate((0, 0, z)))
    return c


def socket_head_bolt(d, L, dk, k, s):
    cq = _cq()
    head = cq.Workplane("XY").circle(dk / 2).extrude(k).edges(">Z").chamfer(d * 0.08)
    head = head.cut(cq.Workplane("XY").polygon(6, s / math.cos(math.pi / 6)).extrude(k * 0.6).translate((0, 0, k * 0.4)))
    shank = cq.Workplane("XY").circle(d / 2).extrude(L).translate((0, 0, -L)).faces("<Z").edges().chamfer(d * 0.08)
    return head.union(shank)


def hex_bolt(d, L, s, k):
    cq = _cq()
    head = cq.Workplane("XY").polygon(6, s / math.cos(math.pi / 6)).extrude(k).edges(">Z").chamfer(k * 0.12)
    shank = cq.Workplane("XY").circle(d / 2).extrude(L).translate((0, 0, -L)).faces("<Z").edges().chamfer(d * 0.08)
    return head.union(shank)


def nyloc_nut(d, s, h):
    cq = _cq()
    hexn = cq.Workplane("XY").polygon(6, s / math.cos(math.pi / 6)).extrude(h * 0.72)
    dome = cq.Workplane("XY").circle(s * 0.46).extrude(h * 0.28).translate((0, 0, h * 0.72))
    return hexn.union(dome).cut(cq.Workplane("XY").circle(d * 0.43).extrude(h * 2).translate((0, 0, -h / 2)))


def dowel_pin(d, L):
    cq = _cq()
    return cq.Workplane("XY").circle(d / 2).extrude(L).faces(">Z").edges().fillet(d * 0.15) \
        .faces("<Z").edges().chamfer(d * 0.1)


def threaded_rod(d, L):
    cq = _cq()
    return cq.Workplane("XY").circle(d / 2).extrude(L).faces(">Z or <Z").edges().chamfer(d * 0.08)


def t_nut(slot, d):
    cq = _cq()
    w, h, length = slot * 1.95, slot * 0.6, slot * 1.4
    body = cq.Workplane("XY").box(length, w, h, centered=(True, True, False))
    neck = cq.Workplane("XY").box(length, slot - 0.3, h * 0.7, centered=(True, True, False)).translate((0, 0, h))
    return body.union(neck).cut(cq.Workplane("XY").circle(d * 0.43).extrude(h * 3).translate((0, 0, -h)))


def corner_bracket(leg, w, t):
    cq = _cq()
    a = cq.Workplane("XY").box(leg, w, t, centered=(False, True, False))
    b = cq.Workplane("XY").box(t, w, leg, centered=(False, True, False))
    rib = (cq.Workplane("XZ").polyline([(t, t), (leg, t), (t, leg)]).close().extrude(t / 2, both=True))
    br = a.union(b).union(rib)
    hole = w * 0.14
    br = br.cut(cq.Workplane("XY").circle(hole).extrude(t * 3).translate((leg * 0.62, 0, -t)))
    br = br.cut(cq.Workplane("YZ").circle(hole).extrude(t * 3).translate((-t, 0, leg * 0.62)))
    return br


def shaft_collar(d, od, b):
    cq = _cq()
    c = cq.Workplane("XY").circle(od / 2).circle(d / 2).extrude(b)
    return c.cut(cq.Workplane("YZ").circle(min(2.5, b * 0.2)).extrude(od).translate((0, 0, b / 2)))


SHAPES = {f.__name__: f for f in (ball_bearing, linear_bushing, shaft, pillow_block, stepper, timing_pulley,
                                   spur_gear, tslot_profile, cylinder_iso15552, cylinder_round, flange, rail,
                                   carriage, coupling, socket_head_bolt, hex_bolt, nyloc_nut, dowel_pin,
                                   threaded_rod, t_nut, corner_bracket, shaft_collar)}


def write(item: Item, out: Path, geometry: bool = True) -> Path:
    folder = out / item.category_path.split("/")[0]
    folder.mkdir(parents=True, exist_ok=True)
    step = folder / f"{item.id}.step"
    if geometry:
        cq = _cq()
        shape = SHAPES[item.shape](**item.args)
        cq.exporters.export(shape, str(step))
    (folder / f"{item.id}.json").write_text(json.dumps(item.metadata(), indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    return step


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PROJECT / "data" / "global" / "engineering"))
    ap.add_argument("--only")
    ap.add_argument("--check", action="store_true", help="only validate the metadata (no CadQuery)")
    ap.add_argument("--json-only", action="store_true", help="rewrite only the JSON files (metadata update)")
    args = ap.parse_args()
    from partsfinder.taxonomy import Taxonomy

    tax = Taxonomy.load()
    items = catalog()
    for i in items:
        tax.validate_category(i.category_path)
        for s in i.sectors:
            if s not in tax.sectors:
                raise ValueError(f"{i.id}: unknown sector {s}")
    if args.check:
        print(f"{len(items)} items, metadata OK")
        return 0
    if args.only:
        items = [i for i in items if args.only in i.id]
    out = Path(args.out)
    failed = []
    for n, item in enumerate(items, 1):
        try:
            write(item, out, geometry=not args.json_only)
        except Exception as exc:  # noqa: BLE001 - one broken part must not hold up the rest
            failed.append((item.id, f"{type(exc).__name__}: {exc}"[:200]))
        print(f"  {n}/{len(items)} {item.id:55}", end="\r", flush=True)
    print(f"\n{len(items) - len(failed)} engineering parts written to {out}"
          + (f", {len(failed)} failed:" if failed else ""))
    for i, e in failed:
        print(f"  - {i}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
