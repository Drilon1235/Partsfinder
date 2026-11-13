"""Mass estimate from volume × density of the material.

This is an ESTIMATE: the volume comes from the CAD file, the density from a short table
based on the material name. Nothing is stored in the database; a real `mass_g` (from the
source) always takes precedence.
"""
from __future__ import annotations

# density in g/cm³; the first key that occurs in the material text wins, so specific before general
DENSITY_G_CM3: list[tuple[str, float]] = [
    ("stainless", 7.9), ("inox", 7.9),
    ("cast iron", 7.2), ("cast-iron", 7.2),
    ("steel", 7.85), ("iron", 7.87),
    ("aluminium", 2.70), ("aluminum", 2.70), ("alu", 2.70),
    ("brass", 8.5),
    ("bronze", 8.8),
    ("copper", 8.96),
    ("titanium", 4.5),
    ("wood", 0.7), ("oak", 0.75), ("beech", 0.72),
    ("polypropylene", 0.91), ("pp", 0.91),
    ("polyethylene", 0.95), ("pe", 0.95),
    ("pvc", 1.4),
    ("nylon", 1.14), ("polyamide", 1.14), ("pa6", 1.14), ("pa66", 1.14),
    ("abs", 1.05),
    ("pom", 1.41), ("delrin", 1.41),
    ("polycarbonate", 1.2),
    ("rubber", 1.2),
    ("glass", 2.5),
    ("concrete", 2.4),
    ("pc", 1.2), ("pa", 1.14),
]


def _tokens(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def density_for(material: str | None) -> float | None:
    """Density (g/cm³) for a material text, or None if it is not in the table."""
    if not material:
        return None
    text = material.lower()
    tokens = _tokens(text)
    for key, value in DENSITY_G_CM3:
        # short keys (pp, pe, abs, pom, alu…) only as a whole word, long ones also as part of a word
        if (key in tokens) or (len(key) > 4 and key in text):
            return value
    return None


def estimate_mass_g(volume_mm3: float | None, material: str | None,
                    bbox_mm: tuple[float, float, float] | None = None) -> float | None:
    """Estimated mass in grams (1 cm³ = 1000 mm³), rounded to 0.1 g. None if something is missing.
    If the volume does not fit in the bounding box (more than 5 % larger), the volume is wrong and
    we estimate nothing: better no number than an impossible number."""
    density = density_for(material)
    if not volume_mm3 or volume_mm3 <= 0 or density is None:
        return None
    if bbox_mm and None not in bbox_mm:
        box = float(bbox_mm[0]) * float(bbox_mm[1]) * float(bbox_mm[2])
        if box > 0 and volume_mm3 > box * 1.05:
            return None
    return round(volume_mm3 / 1000.0 * density, 1)
