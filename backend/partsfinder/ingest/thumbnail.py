"""Render a small PNG preview of a model (matplotlib, headless)."""
from __future__ import annotations

from pathlib import Path

from .geometry import Geometry

MAX_TRIANGLES = 15000
LIGHT = (0.4, -0.5, 0.75)
ELONGATED = 6.0        # long / second dimension above which the preview is shortened
SHOWN_LENGTH = 3.0     # shortened preview length, in times the second dimension


def is_elongated(dims) -> bool:
    """A profile of 30 x 30 x 1000 mm shows as a thin line in a whole-part preview."""
    d = sorted(float(x) for x in dims)
    return d[1] > 0 and d[2] / d[1] > ELONGATED


def shorten(v):
    """For elongated parts (profiles, shafts, tubes, threaded rod) the preview shows a short piece:
    the long axis is clamped at SHOWN_LENGTH x the second dimension. For an extrusion that is the same
    cross-section, just shorter; the real length stays in the data and on the card."""
    import numpy as np

    lo, hi = v.min(axis=0), v.max(axis=0)
    ext = hi - lo
    order = np.argsort(ext)
    long_axis, second = order[2], ext[order[1]]
    if second <= 0 or ext[long_axis] / second <= ELONGATED:
        return v
    v = v.copy()
    v[:, long_axis] = np.minimum(v[:, long_axis], lo[long_axis] + SHOWN_LENGTH * second)
    return v


def render(geom: Geometry, out_path: Path, size_px: int = 256) -> Path | None:
    if not geom.triangles:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    v = shorten(np.asarray(geom.vertices, dtype=float))
    faces = v[np.asarray(geom.triangles, dtype=int)]          # (n, 3, 3)
    if len(faces) > MAX_TRIANGLES:
        # the largest triangles determine the shape; random choice gave "shards" for large models
        area = np.linalg.norm(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]), axis=1)
        faces = faces[np.argpartition(area, -MAX_TRIANGLES)[-MAX_TRIANGLES:]]

    # simple lighting: the more a face points at the light, the lighter
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0)
    light = np.asarray(LIGHT) / np.linalg.norm(LIGHT)
    shade = 0.35 + 0.65 * np.abs(normals @ light)
    base = np.array([0.36, 0.55, 0.82])
    colors = np.clip(shade[:, None] * base[None, :] + 0.08, 0, 1)

    fig = plt.figure(figsize=(size_px / 100, size_px / 100), dpi=100)
    try:
        ax = fig.add_subplot(projection="3d")
        ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolor="none"))
        lo, hi = v.min(axis=0), v.max(axis=0)
        center, half = (lo + hi) / 2, max(hi - lo) / 2 or 1.0
        ax.set_xlim(center[0] - half, center[0] + half)
        ax.set_ylim(center[1] - half, center[1] + half)
        ax.set_zlim(center[2] - half, center[2] + half)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=25, azim=-60)
        ax.set_axis_off()
        fig.subplots_adjust(0, 0, 1, 1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, transparent=True)
    finally:
        plt.close(fig)               # release the figure even on an error (otherwise memory fills up)
    return out_path
