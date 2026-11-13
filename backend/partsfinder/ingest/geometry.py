"""Analyse CAD files: dimensions, volume, surface area and a mesh for the preview."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# Formats we can open and measure ourselves
ANALYZABLE = {"step", "stp", "stl"}
# Formats we store with a part, but that can only be opened with their own CAD software
STORED_ONLY = {"iges", "igs", "obj", "3mf", "dxf", "dwg", "sldprt", "sldasm", "f3d", "ipt", "iam",
               "catpart", "catproduct", "prt", "par", "asm", "fcstd"}
CAD_FORMATS = ANALYZABLE | STORED_ONLY
# Preferred order for the "main file" of a part
PRIMARY_ORDER = ["step", "stp", "stl", "iges", "igs", "obj", "3mf"]


@dataclass
class Geometry:
    bbox_mm: tuple[float, float, float]
    volume_mm3: float | None
    area_mm2: float | None
    vertices: list[tuple[float, float, float]] = field(default_factory=list, repr=False)
    triangles: list[tuple[int, int, int]] = field(default_factory=list, repr=False)


def file_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def file_checksum(path: Path) -> str:
    """SHA-256 of the content. For STEP the header (with date/time) is skipped,
    so the same model exported again gets the same checksum."""
    data = path.read_bytes()
    if file_format(path) in ("step", "stp"):
        start, end = data.find(b"HEADER;"), data.find(b"ENDSEC;")
        if 0 <= start < end:
            data = data[:start] + data[end + len(b"ENDSEC;"):]
    return hashlib.sha256(data).hexdigest()


def analyze(path: Path) -> Geometry | None:
    """Returns None for formats we cannot open ourselves."""
    fmt = file_format(path)
    if fmt in ("step", "stp"):
        return _analyze_step(path)
    if fmt == "stl":
        return _analyze_stl(path)
    return None


def _analyze_step(path: Path) -> Geometry:
    import cadquery as cq

    shapes = cq.importers.importStep(str(path)).vals()
    if not shapes:
        raise ValueError("STEP file contains no geometry")
    comp = cq.Compound.makeCompound(shapes)
    bb = comp.BoundingBox()
    size = max(bb.xlen, bb.ylen, bb.zlen) or 1.0
    verts, tris = comp.tessellate(size / 400, 0.4)
    return Geometry(
        bbox_mm=(round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)),
        volume_mm3=round(comp.Volume(), 3),
        area_mm2=round(comp.Area(), 3),
        vertices=[(v.x, v.y, v.z) for v in verts],
        triangles=[tuple(t) for t in tris],
    )


def _analyze_stl(path: Path) -> Geometry:
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    if mesh.is_empty:
        raise ValueError("STL file contains no triangles")
    ext = mesh.extents
    return Geometry(
        bbox_mm=(round(float(ext[0]), 3), round(float(ext[1]), 3), round(float(ext[2]), 3)),
        volume_mm3=round(float(mesh.volume), 3) if mesh.is_watertight else None,
        area_mm2=round(float(mesh.area), 3),
        vertices=[tuple(map(float, v)) for v in mesh.vertices],
        triangles=[tuple(map(int, f)) for f in mesh.faces],
    )
