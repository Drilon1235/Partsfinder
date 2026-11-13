"""Find similar parts by shape: outer dimensions and volume, regardless of orientation.

This is deliberately simple and explainable: we compare the sorted outer dimensions (small, middle,
large) and the volume. It says nothing about details (holes, threads); it is a first
selection to compare, not proof that two parts are the same.
Company separation: only parts this company may see (_visible).
"""
from __future__ import annotations

import math
from typing import Any

from .repository import Repository, _owned, _visible, like_literal

MIN_SIMILARITY = 0.3
_SHARPNESS = 3.0            # a 10 % deviation in the dimensions gives about 0.74


def shape_distance(dims_a, vol_a, dims_b, vol_b) -> float:
    """0 = same dimensions and volume; larger = further away. Mean relative deviation (log)."""
    a, b = sorted(float(x) for x in dims_a), sorted(float(x) for x in dims_b)
    parts = [abs(math.log(max(x, 1e-6) / max(y, 1e-6))) for x, y in zip(a, b)]
    if vol_a and vol_b and vol_a > 0 and vol_b > 0:
        parts.append(abs(math.log(vol_a / vol_b)) / 3)    # volume counts, but less heavily
    return sum(parts) / len(parts)


def similarity(distance: float) -> float:
    return round(math.exp(-_SHARPNESS * distance), 3)


def find_similar(repo: Repository, dims_mm, volume_mm3: float | None, company_id: str | None, *,
                 kind: str | None = None, category: str | None = None, exclude_id: str | None = None,
                 limit: int = 5, factor: float = 3.0) -> list[dict[str, Any]]:
    """Best shape-similar parts. 'factor': only candidates of which every (sorted) dimension
    lies within a factor 3, so SQL does most of the work."""
    where, params = _visible(company_id)
    d = sorted(float(x) for x in dims_mm)
    small = "min(p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm)"
    large = "max(p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm)"
    mid = f"(p.bbox_x_mm + p.bbox_y_mm + p.bbox_z_mm - {small} - {large})"
    sql = f"""SELECT p.id, p.name, p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm, p.volume_mm3 FROM parts p
              WHERE {where} AND p.bbox_x_mm IS NOT NULL
              AND {small} BETWEEN ? AND ? AND {mid} BETWEEN ? AND ? AND {large} BETWEEN ? AND ?"""
    args: list[Any] = [*params]
    for x in d:
        args += [x / factor, x * factor]
    if kind:
        sql += " AND p.kind = ?"
        args.append(kind)
    if category:
        prefix = category.strip("/").lower()
        sql += " AND (p.category_path = ? OR p.category_path LIKE ? ESCAPE '\\')"
        args += [prefix, like_literal(prefix) + "/%"]
    if exclude_id:
        sql += " AND p.id != ?"
        args.append(exclude_id)
    # first score on the SQL columns; only the best 'limit' parts are loaded in full
    scored = []
    for row in repo.conn.execute(sql, args):
        dims = (row["bbox_x_mm"], row["bbox_y_mm"], row["bbox_z_mm"])
        sim = similarity(shape_distance(d, volume_mm3, dims, row["volume_mm3"]))
        if sim >= MIN_SIMILARITY:
            scored.append((sim, row["name"], row["id"]))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out = []
    for sim, _name, part_id in scored[:limit]:
        part = repo.get_part(part_id, company_id)
        if part is None or not part.bbox_mm:
            continue
        pd = sorted(part.bbox_mm)
        out.append({"part": part, "similarity": sim,
                    "dims_diff_mm": [round(b - a, 1) for a, b in zip(d, pd)]})
    return out


def find_duplicates(repo: Repository, company_id: str | None, *, tolerance: float = 0.01,
                    limit: int = 50) -> list[dict[str, Any]]:
    """Probable duplicates in the OWN library (without company_id: the general one): parts
    with (nearly) the same outer dimensions and the same volume. It is a hint to review: equal
    dimensions do not always mean the same part (e.g. an M8x40 bolt and a rod of the same size).
    Larger groups come first. Company separation: only parts this company owns itself."""
    where, params = _owned(company_id)
    rows = repo.conn.execute(
        f"""SELECT p.id, p.name, p.kind, p.volume_mm3, p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm FROM parts p
            WHERE {where} AND p.bbox_x_mm IS NOT NULL""", params).fetchall()
    items = []
    for r in rows:
        d = sorted((r["bbox_x_mm"], r["bbox_y_mm"], r["bbox_z_mm"]))
        items.append((d, r["volume_mm3"], r["kind"], r["id"], r["name"]))
    items.sort(key=lambda t: t[0][2])                      # on the largest dimension: neighbours are candidates

    def same(a, b) -> bool:
        if a[2] != b[2]:
            return False
        if any(abs(x - y) > tolerance * max(x, y, 1e-6) for x, y in zip(a[0], b[0])):
            return False
        va, vb = a[1], b[1]
        if va and vb:
            return abs(va - vb) <= 2 * tolerance * max(va, vb)
        return not va and not vb

    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        j = i + 1
        while j < len(items) and items[j][0][2] <= items[i][0][2] * (1 + tolerance) + 1e-9:
            if same(items[i], items[j]):
                parent[find(j)] = find(i)
            j += 1
    groups: dict[int, list] = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda t: t[4])
        out.append({"size": len(g), "bbox_mm": [round(x, 1) for x in g[0][0]],
                    "parts": [{"id": t[3], "name": t[4]} for t in g]})
    out.sort(key=lambda x: (-x["size"], x["parts"][0]["name"]))
    return out[:limit]
