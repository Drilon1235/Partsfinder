"""Simplified 3D shapes for test data (CadQuery). All dimensions in mm.

The shapes are deliberately simple (no thread, no real tooth form):
they must be recognisable and have the right outer dimensions, nothing more.
"""
from __future__ import annotations

import math

import cadquery as cq

W = cq.Workplane


# ---- basic blocks -------------------------------------------------------------
def _box(x, y, z, at=(0, 0, 0)):
    return W("XY").box(x, y, z, centered=(True, True, False)).translate(at)


def _cyl(d, h, at=(0, 0, 0)):
    return W("XY").circle(d / 2).extrude(h).translate(at)


def _ring(od, id_, h, at=(0, 0, 0)):
    return W("XY").circle(od / 2).circle(id_ / 2).extrude(h).translate(at)


def _hex(s, h, at=(0, 0, 0)):
    return W("XY").polygon(6, s / math.cos(math.pi / 6)).extrude(h).translate(at)


def _profile(points, length):
    return W("XY").polyline(points).close().extrude(length)


def _compound(*parts):
    wp = W("XY")
    for p in parts:
        wp = wp.add(p.vals())
    return wp


def _union(*parts):
    result = parts[0]
    for p in parts[1:]:
        result = result.union(p)
    return result


# ---- fasteners ----------------------------------------------------------------
def hex_bolt(d, L, s, k):
    return _union(_hex(s, k), _cyl(d, L, at=(0, 0, -L)))


def socket_screw(d, L, dk, k, socket):
    head = _cyl(dk, k).cut(_hex(socket, k * 0.6, at=(0, 0, k * 0.4)))
    return _union(head, _cyl(d, L, at=(0, 0, -L)))


def hex_nut(d, s, m):
    return _hex(s, m).cut(_cyl(d, m))


def washer(d1, d2, h):
    return _ring(d2, d1, h)


def wedge_anchor(d, L):
    return _union(_cyl(d, L), _ring(d * 2.2, d, d * 0.2, at=(0, 0, L - d * 1.2)),
                  _hex(d * 1.6, d * 0.8, at=(0, 0, L - d)))


# ---- connections ---------------------------------------------------------------
def angle_bracket(a, b, w, t, hole):
    body = _union(_box(a, w, t, at=(a / 2, 0, 0)), _box(t, w, b, at=(t / 2, 0, 0)))
    for x in (a * 0.4, a * 0.75):
        body = body.cut(_cyl(hole, t, at=(x, 0, 0)))
    for z in (b * 0.4, b * 0.75):
        body = body.cut(W("YZ").circle(hole / 2).extrude(t).translate((0, 0, z)))
    return body


def wall_bracket(a, b, t):
    """Shelf bracket: L-shape with brace."""
    w = max(20, a * 0.15)
    strut = _profile([(t, 0), (a * 0.7, 0), (t, b * 0.7)], t).rotate((0, 0, 0), (1, 0, 0), 90)
    return _union(angle_bracket(a, b, w, t, 5), strut.translate((0, t / 2, 0)))


def pipe_clamp(pipe_d, t, w):
    r = pipe_d / 2
    outer = W("XZ").circle(r + t).extrude(w / 2, both=True)
    inner = W("XZ").circle(r).extrude(w, both=True)
    half = outer.cut(inner).cut(_box(3 * (r + t), w * 2, r + t, at=(0, 0, -(r + t))))
    feet = _union(_box(r * 0.8, w, t, at=(r + t + r * 0.4, 0, 0)),
                  _box(r * 0.8, w, t, at=(-(r + t + r * 0.4), 0, 0)))
    return _union(half, feet)


def plate_with_holes(a, b, t, hole, inset):
    plate = _box(a, b, t)
    for x in (-1, 1):
        for y in (-1, 1):
            plate = plate.cut(_cyl(hole, t, at=(x * (a / 2 - inset), y * (b / 2 - inset), 0)))
    return plate


def hinge(length, width, t, knuckle_d):
    leaf1 = _box(width, length, t, at=(-width / 2 - knuckle_d / 2, 0, 0))
    leaf2 = _box(width, length, t, at=(width / 2 + knuckle_d / 2, 0, 0))
    knuckle = W("XZ").circle(knuckle_d / 2).extrude(length / 2, both=True).translate((0, 0, knuckle_d / 2))
    return _union(leaf1, leaf2, knuckle)


# ---- profiles ------------------------------------------------------------------
def rect_tube(a, b, t, L):
    return W("XY").rect(a, b).rect(a - 2 * t, b - 2 * t).extrude(L)


def round_tube(d, t, L):
    return _ring(d, d - 2 * t, L)


def angle_profile(a, t, L):
    return _profile([(0, 0), (a, 0), (a, t), (t, t), (t, a), (0, a)], L)


def u_profile(h, b, tw, tf, L):
    return _profile([(0, 0), (b, 0), (b, tf), (tw, tf), (tw, h - tf), (b, h - tf), (b, h), (0, h)], L)


def i_profile(h, b, tw, tf, L):
    x, y = b / 2, h / 2
    pts = [(-x, -y), (x, -y), (x, -y + tf), (tw / 2, -y + tf), (tw / 2, y - tf), (x, y - tf),
           (x, y), (-x, y), (-x, y - tf), (-tw / 2, y - tf), (-tw / 2, -y + tf), (-x, -y + tf)]
    return _profile(pts, L)


def alu_slot_profile(a, b, L):
    body = W("XY").rect(a, b).extrude(L)
    slot = min(a, b) * 0.3
    for cx in ([0] if a == b else [-a / 4, a / 4]):
        body = body.cut(_cyl(min(a, b) * 0.22, L, at=(cx, 0, 0)))
        body = body.cut(_box(slot, min(a, b) * 0.25, L, at=(cx, b / 2 - min(a, b) * 0.125, 0)))
        body = body.cut(_box(slot, min(a, b) * 0.25, L, at=(cx, -b / 2 + min(a, b) * 0.125, 0)))
    for sx in (-1, 1):
        body = body.cut(_box(min(a, b) * 0.25, slot, L, at=(sx * (a / 2 - min(a, b) * 0.125), 0, 0)))
    return body


# ---- drive ----------------------------------------------------------------
def ball_bearing(d, D, B):
    m = (D - d) / 2
    return _compound(_ring(D, D - m * 0.7, B), _ring(d + m * 0.7, d, B))


def pillow_block(d, H, L):
    base = _box(L, H * 0.5, H * 0.25, at=(0, 0, 0))
    housing = W("XZ").circle(H * 0.45).circle(d / 2).extrude(H * 0.25, both=True).translate((0, 0, H * 0.55))
    body = _union(base, housing)
    for x in (-L * 0.38, L * 0.38):
        body = body.cut(_cyl(H * 0.12, H * 0.25, at=(x, 0, 0)))
    return body


def shaft(d, L):
    return _cyl(d, L)


def compression_spring(wire_d, D, L, coils):
    r = (D - wire_d) / 2
    helix = cq.Wire.makeHelix(pitch=L / coils, height=L, radius=r)
    return W("XZ").center(r, 0).circle(wire_d / 2).sweep(W("XY").add(helix), isFrenet=True)


def spur_gear(module, z, b, bore):
    ra, rf = module * (z + 2) / 2, module * (z - 2.5) / 2
    pts = []
    for i in range(z):
        a0 = 2 * math.pi * i / z
        step = 2 * math.pi / z
        for frac, r in ((0.0, rf), (0.15, ra), (0.45, ra), (0.6, rf)):
            a = a0 + frac * step
            pts.append((r * math.cos(a), r * math.sin(a)))
    return _profile(pts, b).cut(_cyl(bore, b))


def pulley(d, b, bore):
    groove = W("XZ").polyline([(d / 2, b * 0.2), (d / 2 - b * 0.35, b / 2), (d / 2, b * 0.8)]).close() \
        .revolve(360, (0, 0, 0), (0, 1, 0))
    return _ring(d, bore, b).cut(groove)


# ---- furniture ------------------------------------------------------------------
def chair_parts(w, d, h, seat_h, leg, back=True, round_legs=True):
    """Returns (leg, seat, backrest|None, full chair)."""
    seat_t = 25 if leg > 25 else 15
    leg_h = seat_h - seat_t

    def one_leg(at=(0, 0, 0)):
        return _cyl(leg, leg_h, at) if round_legs else _box(leg, leg, leg_h, at)

    seat = _box(w, d, seat_t)
    backrest = _box(w, seat_t, h - seat_h) if back else None
    legs = [one_leg((sx * (w / 2 - leg), sy * (d / 2 - leg), 0)) for sx in (-1, 1) for sy in (-1, 1)]
    assembled = [*legs, seat.translate((0, 0, leg_h))]
    if back:
        assembled.append(backrest.translate((0, -d / 2 + seat_t / 2, seat_h)))
    return one_leg(), seat, backrest, _compound(*assembled)


def bench_parts(length, d, h, seat_h):
    seat = _box(length, d, 40)
    leg = _box(60, d, seat_h - 40)
    back = _box(length, 30, h - seat_h)
    full = _compound(leg.translate((-length / 2 + 80, 0, 0)), leg.translate((length / 2 - 80, 0, 0)),
                     seat.translate((0, 0, seat_h - 40)),
                     back.translate((0, -d / 2 + 15, seat_h)))
    return leg, seat, back, full


def table(w, d, h, top_t, leg):
    legs = [_box(leg, leg, h - top_t, at=(sx * (w / 2 - leg), sy * (d / 2 - leg), 0))
            for sx in (-1, 1) for sy in (-1, 1)]
    return _compound(*legs, _box(w, d, top_t, at=(0, 0, h - top_t)))


def cabinet(w, d, h, t):
    return _box(w, d, h).faces("<Y").shell(-t)


def shelving(w, d, h, shelves):
    posts = [_box(35, 35, h, at=(sx * (w / 2 - 17.5), sy * (d / 2 - 17.5), 0))
             for sx in (-1, 1) for sy in (-1, 1)]
    boards = [_box(w, d, 20, at=(0, 0, 100 + i * (h - 200) / max(1, shelves - 1)))
              for i in range(shelves)]
    return _compound(*posts, *boards)


# ---- enclosures ----------------------------------------------------------------
def enclosure(L, W_, H, t):
    return _box(L, W_, H).faces(">Z").shell(-t)


def guard(L, W_, H, t):
    return _box(L, W_, H).faces("<Z").shell(-t)


# ---- horticulture -------------------------------------------------------------------
def gutter(width, depth, t, L):
    pts = [(0, 0), (width, 0), (width, depth), (width - t, depth), (width - t, t),
           (t, t), (t, depth), (0, depth)]
    return _profile(pts, L)


def greenhouse_profile(h, b, t, L):
    pts = [(0, 0), (b, 0), (b, t), (b / 2 + t / 2, t), (b / 2 + t / 2, h), (b / 2 - t / 2, h),
           (b / 2 - t / 2, t), (0, t)]
    return _profile(pts, L)


def tray(L, W_, H, t):
    return _box(L, W_, H).faces(">Z").shell(-t)


def pot(top_d, H, t):
    rb, rt = top_d * 0.75 / 2, top_d / 2
    section = [(0, 0), (rb, 0), (rt, H), (rt - t, H), (rb - t, t), (0, t)]
    return W("XZ").polyline(section).close().revolve(360, (0, 0, 0), (0, 1, 0))


def hook(wire_d, L):
    path = W("XZ").moveTo(0, 0).lineTo(0, -L).threePointArc((L * 0.15, -L - L * 0.15), (L * 0.3, -L))
    return W("XY").circle(wire_d / 2).sweep(path)


# ---- piping --------------------------------------------------------------------
def pipe_bend(od, t, R):
    return W("XY").center(R, 0).circle(od / 2).circle(od / 2 - t).revolve(90, (-R, 0, 0), (-R, 1, 0))


def tee(od, t, L):
    run = W("YZ").circle(od / 2).extrude(L / 2, both=True)
    branch = W("XY").circle(od / 2).extrude(L / 2)
    hollow_run = W("YZ").circle(od / 2 - t).extrude(L / 2, both=True)
    hollow_branch = W("XY").circle(od / 2 - t).extrude(L / 2)
    return run.union(branch).cut(hollow_run).cut(hollow_branch)


def flange(D, bore, t, k, n, hole):
    body = _cyl(D, t) if bore == 0 else _ring(D, bore, t)
    for i in range(n):
        a = 2 * math.pi * i / n
        body = body.cut(_cyl(hole, t, at=(k / 2 * math.cos(a), k / 2 * math.sin(a), 0)))
    return body


def o_ring(id_, cs):
    return W("XY").add(cq.Solid.makeTorus(id_ / 2 + cs / 2, cs / 2))


# ---- machine elements --------------------------------------------------------
def bow_handle(centers, d, h):
    path = W("XZ").moveTo(-centers / 2, 0).lineTo(-centers / 2, h) \
        .lineTo(centers / 2, h).lineTo(centers / 2, 0)
    return W("XY").center(-centers / 2, 0).circle(d / 2).sweep(path, transition="round")


def knob(d, h, stud_d):
    return _union(_cyl(d, h * 0.6), W("XY").sphere(d * 0.4).translate((0, 0, h * 0.6)),
                  _cyl(stud_d, h * 0.8, at=(0, 0, -h * 0.8)))


def leveling_foot(base_d, thread_d, L):
    return _union(_cyl(base_d, base_d * 0.25), _cyl(thread_d, L, at=(0, 0, base_d * 0.25)))


def castor(wheel_d, width):
    wheel = W("YZ").circle(wheel_d / 2).extrude(width / 2, both=True).translate((0, 0, wheel_d / 2))
    fork = [_box(4, wheel_d * 0.4, wheel_d * 0.8, at=(sx * (width / 2 + 3), 0, wheel_d * 0.4))
            for sx in (-1, 1)]
    top = _box(width + 14, wheel_d * 0.6, 5, at=(0, 0, wheel_d * 1.15))
    return _compound(wheel, *fork, top)
