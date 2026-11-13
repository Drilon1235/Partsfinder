"""What the app shows about one part: a short summary, a few key specs, a 3D mesh and a datasheet.

- summary / highlights: short text for the result card (first sentence of the description and
  at most three defining values, such as thread and length for a bolt).
- mesh: a binary STL for the 3D viewer, made from the STEP file on first request and cached in
  data/meshes/ (outside git). An STL file is served as it is.
- datasheet: a printable HTML page with everything that is known about the part.
"""
from __future__ import annotations

import hashlib
import html
import re
import struct
import uuid
from pathlib import Path
from typing import Any

from . import engineering
from .models import Part

MESHABLE = ("step", "stp", "stl")
MAX_SUMMARY = 150

# Defining values per kind of part, in order of importance. The first three that a part has
# go on its card; "Envelope" (outer dimensions) is the fallback.
HIGHLIGHT_KEYS = [
    "designation", "thread", "length_mm", "frame_size", "holding_torque_nm", "inner_diameter_mm",
    "outer_diameter_mm", "width_mm", "bore_mm", "shaft_diameter_mm", "module", "teeth", "belt_profile",
    "dn", "pn", "piston_diameter_mm", "stroke_mm", "rail_size", "profile_size", "slot_width_mm",
    "diameter_mm", "thickness_mm", "height_mm", "pitch_mm",
]
LABELS = {
    "dn": "DN", "pn": "PN", "frame_size": "NEMA frame", "holding_torque_nm": "Holding torque",
    "inner_diameter_mm": "Inner diameter", "outer_diameter_mm": "Outer diameter",
    "piston_diameter_mm": "Bore", "rail_size": "Rail size", "profile_size": "Profile",
}
UNITS = {"mm": " mm", "nm": " Nm", "deg": "°", "bar": " bar", "w": " W", "kg": " kg", "g": " g"}
HIDDEN = {"needs_review", "ai_metadata", "original_name", "folder_in_freecad_library"}


def _num(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 0.005 else f"{v:.2f}".rstrip("0").rstrip(".")


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    base = re.sub(r"_(mm|nm|deg|bar|w|kg|g)$", "", key).replace("_", " ")
    return base[:1].upper() + base[1:]


def value_text(key: str, value: Any) -> str:
    m = re.search(r"_(mm|nm|deg|bar|w|kg|g)$", key)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return _num(float(value)) + (UNITS[m.group(1)] if m else "")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)


def summary(part: Part) -> str:
    """First sentence of the description, without the 'Also known as' list; the name if empty."""
    text = re.split(r"\s*Also known as:", part.description or "")[0].strip()
    if not text:
        return part.name
    first = re.split(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z])", text, maxsplit=1)[0].rstrip(".")
    if len(first) > MAX_SUMMARY:
        first = first[:MAX_SUMMARY].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if first.strip().lower() == part.name.strip().lower() and part.category_path:
        # the description only repeats the name: say what kind of part it is instead
        kind = part.category_path.strip("/").split("/")[-1].replace("-", " ")
        first = f"{kind[:1].upper()}{kind[1:]}"
    return first


def highlights(part: Part, limit: int = 3) -> list[dict[str, str]]:
    props = part.properties or {}
    out: list[dict[str, str]] = []
    name_low = part.name.lower()
    for key in HIGHLIGHT_KEYS:
        v = props.get(key)
        if v in (None, "", []) or key in HIDDEN:
            continue
        text = value_text(key, v)
        if key == "designation" and all(t in name_low for t in re.findall(r"[a-z0-9.]+", text.lower())):
            continue                       # already in the name, the card shows the name
        out.append({"label": label(key), "value": text})
        if len(out) >= limit:
            return out
    if part.bbox_mm and len(out) < limit:
        out.append({"label": "Envelope", "value": " × ".join(_num(x) for x in part.bbox_mm) + " mm"})
    return out


# ---- 3D mesh ------------------------------------------------------------------------------
def mesh_source(part: Part, resolve) -> Path | None:
    """The file the mesh is made from: STL first (no conversion), then STEP."""
    for fmt in ("stl", "step", "stp"):
        f = next((x for x in part.files if x.format == fmt), None)
        if f is not None:
            p = resolve(f.path)
            if p.is_file():
                return p
    return None


def _write_binary_stl(path: Path, vertices, triangles) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # own temporary name per call: two requests for the same part at once must not write one file
    tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(b"Partsfinder mesh".ljust(80, b" "))
        fh.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            va, vb, vc = vertices[a], vertices[b], vertices[c]
            ux, uy, uz = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
            wx, wy, wz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]
            n = (uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx)
            ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
            fh.write(struct.pack("<12fH", n[0] / ln, n[1] / ln, n[2] / ln, *va, *vb, *vc, 0))
    try:
        tmp.replace(path)
    except OSError:
        # Windows: the other request just put the same mesh in place and it is open; theirs is identical
        tmp.unlink(missing_ok=True)
        if not path.is_file():
            raise


def mesh_prefix(part_id: str) -> str:
    """Start of the cache file names of one part (removal deletes them)."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", part_id) + "-"


def mesh_file(source: Path, cache_dir: Path, part_id: str | None = None) -> Path:
    """Binary STL for the viewer. STL sources are served as they are; STEP is tessellated once
    and cached by content (path + size + modification time), named after the part."""
    if source.suffix.lower() == ".stl":
        return source
    st = source.stat()
    key = hashlib.sha256(f"{source.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:24]
    out = cache_dir / f"{mesh_prefix(part_id) if part_id else ''}{key}.stl"
    if out.is_file():
        return out
    import cadquery as cq

    shapes = cq.importers.importStep(str(source)).vals()
    if not shapes:
        raise ValueError("The STEP file contains no geometry")
    comp = cq.Compound.makeCompound(shapes)
    bb = comp.BoundingBox()
    size = max(bb.xlen, bb.ylen, bb.zlen) or 1.0
    verts, tris = comp.tessellate(size / 300, 0.3)
    if not tris:
        raise ValueError("The STEP file could not be turned into triangles")
    _write_binary_stl(out, [(v.x, v.y, v.z) for v in verts], [tuple(t) for t in tris])
    return out


# ---- datasheet ----------------------------------------------------------------------------
_CSS = """
:root{--ink:#16202a;--mute:#5b6874;--line:#d5dbe0;--paper:#fff;--accent:#1d5f8a}
*{box-sizing:border-box}body{margin:0;background:#e9edf0;color:var(--ink);
font:14px/1.5 "Segoe UI",system-ui,sans-serif}
.page{max-width:820px;margin:24px auto;background:var(--paper);padding:40px 48px;border:1px solid var(--line)}
header{display:flex;justify-content:space-between;gap:24px;border-bottom:2px solid var(--ink);padding-bottom:12px}
.kicker{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0}
h1{font-size:22px;margin:4px 0 2px}.id{font-family:Consolas,monospace;color:var(--mute);font-size:12px}
.lead{margin:16px 0 0;font-size:15px}.grid{display:grid;grid-template-columns:260px 1fr;gap:28px;margin-top:24px}
.fig{border:1px solid var(--line);aspect-ratio:1;display:flex;align-items:center;justify-content:center;
background:#f6f8f9}.fig img{max-width:100%;max-height:100%}
h2{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin:24px 0 6px;
border-bottom:1px solid var(--line);padding-bottom:4px}.grid h2:first-child{margin-top:0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:5px 8px 5px 0;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:500;width:45%}
td.n{font-variant-numeric:tabular-nums}.foot{margin-top:28px;font-size:11px;color:var(--mute)}
.print{position:fixed;right:20px;top:16px;padding:8px 14px;border:1px solid var(--ink);background:var(--paper);
font:inherit;cursor:pointer}
@media print{body{background:#fff}.page{margin:0;border:0;padding:0}.print{display:none}}
@media (max-width:640px){.page{padding:20px 16px}.grid{grid-template-columns:1fr}}
"""


def _rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(f"<tr><th>{html.escape(k)}</th><td class=n>{html.escape(v)}</td></tr>" for k, v in pairs if v)


def datasheet_html(part: Part, thumbnail_url: str | None, generated: str) -> str:
    """Printable datasheet (browser: print -> Save as PDF). Only data that is in the library."""
    e = html.escape
    general: list[tuple[str, str]] = [
        ("Category", " / ".join(part.category_path.strip("/").split("/"))),
        ("Kind", "assembly" if part.kind == "assembly" else "single part"),
        ("Material", part.material or ""),
        ("Standards", ", ".join(part.standards)),
        ("Colour", part.color or ""),
    ]
    geo: list[tuple[str, str]] = []
    if part.bbox_mm:
        geo.append(("Envelope (X × Y × Z)", " × ".join(_num(x) for x in part.bbox_mm) + " mm"))
    if part.volume_mm3:
        geo.append(("Volume", f"{_num(part.volume_mm3 / 1000)} cm³"))
    eng = [(v["label"], f'{v["text"]} ({v["source"]})') for v in engineering.values(part)]
    own = {name for names in engineering.OWN_NAMES.values() for name, _ in names}
    tech = [(label(k), value_text(k, v)) for k, v in (part.properties or {}).items()
            if k not in HIDDEN and k.lower() not in own and v not in (None, "", [])]
    files = [(f.format.upper(), "primary file" if f.is_primary else "") for f in part.files]
    fig = f'<img src="{e(thumbnail_url)}" alt="Preview of {e(part.name)}">' if thumbnail_url else \
        '<span style="color:#5b6874">no preview</span>'
    lib = "general library" if part.company_id is None else f"own library ({e(part.company_id)})"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Datasheet {e(part.name)}</title><style>{_CSS}</style></head><body>
<button class="print" onclick="window.print()">Print / Save as PDF</button>
<div class="page">
<header><div><p class="kicker">Datasheet · Partsfinder</p><h1>{e(part.name)}</h1>
<span class="id">{e(part.id)}</span></div>
<div style="text-align:right"><p class="kicker">Generated</p><div>{e(generated)}</div></div></header>
<p class="lead">{e(part.description or part.name)}</p>
<div class="grid"><div><div class="fig">{fig}</div>
<h2>Files</h2><table>{_rows(files) or '<tr><td>No CAD file stored</td></tr>'}</table></div>
<div><h2>General</h2><table>{_rows(general)}</table>
{f'<h2>Geometry</h2><table>{_rows(geo)}</table>' if geo else ''}
{f'<h2>Specifications</h2><table>{_rows(eng + tech)}</table>' if eng or tech else ''}</div></div>
<p class="foot">Source: {e(part.source)}{(' · ' + e(part.source_ref)) if part.source_ref else ''} · {lib}
{(' · License: ' + e(part.license)) if part.license else ''}. Values come from the library data and
the CAD geometry; check critical values against the manufacturer's documentation.</p>
</div></body></html>"""
