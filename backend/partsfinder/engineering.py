"""Engineering values of a part: strength, load, tolerance, hardness and mass.

What the part states itself always wins (a JSON file next to the CAD file, or the source). Otherwise only what
follows for certain from public standards, never a guess:
- bolts and screws: the minimum strength of their property class (ISO 898-1, ISO 3506-1 for stainless A2/A4);
- named material grades: the minimum strength of that grade (EN 10025-2 structural steel, EN 10088 stainless,
  EN 755-2 aluminium extrusions);
- mass: the volume measured from the CAD file times the density of the material (an estimate, marked as such).
Load ratings (bearings, castors, brackets) are only shown when the part states them: those are catalogue values
of a maker, and we do not copy catalogues.
"""
from __future__ import annotations

import re
from typing import Any

from .mass import density_for, estimate_mass_g

# ISO 898-1: minimum lower yield strength / 0.2 % proof strength and minimum tensile strength, MPa
PROPERTY_CLASS = {
    "4.6": (240, 400), "4.8": (340, 420), "5.6": (300, 500), "5.8": (420, 520), "6.8": (480, 600),
    "8.8": (640, 800), "9.8": (720, 900), "10.9": (940, 1040), "12.9": (1100, 1220),
}
# ISO 3506-1: stainless A2 / A4, class 50 / 70 / 80
STAINLESS_CLASS = {"50": (210, 500), "70": (450, 700), "80": (600, 800)}
# minimum yield / tensile strength of named grades, MPa: (pattern in the material text, yield, tensile, standard)
GRADES: list[tuple[str, int, int, str]] = [
    (r"\bs235", 235, 360, "EN 10025-2 (S235)"),
    (r"\bs275", 275, 410, "EN 10025-2 (S275)"),
    (r"\bs355", 355, 470, "EN 10025-2 (S355)"),
    (r"\b1\.4301\b|\baisi\s?304\b|\b304\b", 210, 520, "EN 10088-2 (1.4301 / 304)"),
    (r"\b1\.4404\b|\b1\.4401\b|\baisi\s?316l?\b|\b316l?\b", 220, 520, "EN 10088-2 (1.4404 / 316L)"),
    (r"\b6060\b.{0,6}t6|\b6060-t6", 150, 190, "EN 755-2 (6060-T6)"),
    (r"\b6063\b.{0,6}t6|\b6063-t6", 170, 215, "EN 755-2 (6063-T6)"),
    (r"\b6061\b.{0,6}t6|\b6061-t6", 240, 260, "EN 755-2 (6061-T6)"),
    (r"\b6082\b.{0,6}t6|\b6082-t6", 250, 290, "EN 755-2 (6082-T6)"),
    (r"\b7075\b.{0,6}t6|\b7075-t6", 480, 540, "EN 755-2 (7075-T6)"),
]

# what a company can put in "properties" of the JSON file next to a CAD file, and how it is shown
LABELS = {
    "mass_g": "Mass", "yield_strength_mpa": "Yield strength", "tensile_strength_mpa": "Tensile strength",
    "max_load_kg": "Maximum load", "load_rating_kn": "Dynamic load rating C", "static_load_rating_kn": "Static load rating C0",
    "tolerance": "Tolerance", "hardness": "Hardness", "max_torque_nm": "Maximum torque", "max_pressure_bar": "Maximum pressure",
}
UNIT = {"mass_g": "g", "yield_strength_mpa": "MPa", "tensile_strength_mpa": "MPa", "max_load_kg": "kg",
        "load_rating_kn": "kN", "static_load_rating_kn": "kN", "max_torque_nm": "Nm", "max_pressure_bar": "bar"}
# other names a file may use for the same value, with the factor to our unit
OWN_NAMES: dict[str, list[tuple[str, float]]] = {
    "yield_strength_mpa": [("yield_strength_mpa", 1), ("yield_mpa", 1), ("rp02_mpa", 1), ("re_mpa", 1)],
    "tensile_strength_mpa": [("tensile_strength_mpa", 1), ("tensile_mpa", 1), ("rm_mpa", 1), ("uts_mpa", 1)],
    "max_load_kg": [("max_load_kg", 1), ("load_capacity_kg", 1), ("working_load_kg", 1), ("working_load_limit_kg", 1),
                    ("max_load_n", 1 / 9.81), ("load_capacity_n", 1 / 9.81), ("max_load_kn", 1000 / 9.81)],
    "load_rating_kn": [("load_rating_kn", 1), ("dynamic_load_rating_kn", 1), ("c_kn", 1), ("dynamic_load_rating_n", 0.001)],
    "static_load_rating_kn": [("static_load_rating_kn", 1), ("c0_kn", 1), ("static_load_rating_n", 0.001)],
    "max_torque_nm": [("max_torque_nm", 1), ("rated_torque_nm", 1)],
    "max_pressure_bar": [("max_pressure_bar", 1), ("max_pressure_mpa", 10)],
    "tolerance": [("tolerance", 1), ("general_tolerance", 1), ("tolerance_class", 1)],
    "hardness": [("hardness", 1), ("hardness_hrc", 1), ("hardness_hv", 1), ("hardness_hb", 1)],
}
HARDNESS_UNIT = {"hardness_hrc": "HRC", "hardness_hv": "HV", "hardness_hb": "HB"}


def _props(part: Any) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in (part.properties or {}).items() if v not in (None, "", [])}


def _own(part: Any, key: str) -> tuple[Any, str] | None:
    """(value, property name) when the part states it itself."""
    props = _props(part)
    for name, factor in OWN_NAMES.get(key, [(key, 1)]):
        if name in props:
            value = props[name]
            if key in ("tolerance", "hardness"):
                unit = HARDNESS_UNIT.get(name)
                return (f"{value} {unit}" if unit and not str(value).upper().endswith(unit) else str(value)), name
            try:
                return round(float(value) * factor, 3), name
            except (TypeError, ValueError):
                continue
    return None


def property_class(part: Any) -> str | None:
    """The bolt's property class, from its properties or its material text: "8.8", "A2-70"."""
    props = _props(part)
    values = props.get("property_class") or props.get("property_classes")
    values = values if isinstance(values, list) else ([values] if values else [])
    text = " ".join([str(v) for v in values] + [part.material or ""]).lower()
    m = re.search(r"\b(a[24])-(50|70|80)\b", text)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m = re.search(r"(?<![\d.])(4\.6|4\.8|5\.6|5\.8|6\.8|8\.8|9\.8|10\.9|12\.9)(?![\d.])", text)
    return m.group(1) if m else None


def strength(part: Any) -> tuple[int, int, str] | None:
    """(minimum yield, minimum tensile strength in MPa, where it comes from), from a standard."""
    cls = property_class(part)
    if cls in PROPERTY_CLASS:
        return (*PROPERTY_CLASS[cls], f"ISO 898-1, property class {cls}")
    if cls and cls[-2:] in STAINLESS_CLASS:
        return (*STAINLESS_CLASS[cls[-2:]], f"ISO 3506-1, {cls}")
    text = (part.material or "").lower()
    for pattern, yld, uts, std in GRADES:
        if re.search(pattern, text):
            return yld, uts, std
    return None


def mass(part: Any) -> tuple[float, bool] | None:
    """(grams, estimated?)."""
    if part.mass_g is not None:
        return float(part.mass_g), False
    est = estimate_mass_g(part.volume_mm3, part.material, part.bbox_mm) if part.kind == "part" else None
    return (est, True) if est is not None else None


def value(part: Any, key: str) -> Any:
    """One engineering value of the part (own data first, then what follows from a standard), or None.
    Used to check a requirement such as "at least 800 MPa" or "holds 50 kg"."""
    own = _own(part, key)
    if own is not None:
        return own[0]
    if key in ("yield_strength_mpa", "tensile_strength_mpa"):
        s = strength(part)
        return (s[0] if key == "yield_strength_mpa" else s[1]) if s else None
    if key == "mass_g":
        m = mass(part)
        return m[0] if m else None
    return None


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}" if abs(v) < 10 else f"{v:.1f}".rstrip("0").rstrip(".")
    return str(v)


def values(part: Any) -> list[dict[str, Any]]:
    """Every engineering value of the part, for the card, Details, Compare and the datasheet:
    [{"key", "label", "value", "unit", "text", "source"}]. source: "part data", a standard, or "estimate"."""
    out: list[dict[str, Any]] = []

    def add(key: str, v: Any, source: str, prefix: str = "") -> None:
        unit = UNIT.get(key, "")
        out.append({"key": key, "label": LABELS[key], "value": v, "unit": unit,
                    "text": f"{prefix}{_fmt(v)}{' ' + unit if unit else ''}", "source": source})

    m = mass(part)
    if m:
        add("mass_g", m[0], "estimate: volume from the CAD file × density of the material" if m[1] else "part data",
            "≈ " if m[1] else "")
    s = strength(part)
    for key, idx in (("yield_strength_mpa", 0), ("tensile_strength_mpa", 1)):
        own = _own(part, key)
        if own is not None:
            add(key, own[0], "part data")
        elif s:
            add(key, s[idx], f"minimum per {s[2]}", "≥ ")
    for key in ("max_load_kg", "load_rating_kn", "static_load_rating_kn", "max_torque_nm", "max_pressure_bar",
                "tolerance", "hardness"):
        own = _own(part, key)
        if own is not None:
            add(key, own[0], "part data")
    return out


def density(part: Any) -> float | None:
    return density_for(part.material)


# ---- filtering on engineering values (the Filters panel; filters.engineering in the API) ---------------
# numbers: {"min": x, "max": y} in the unit of the key; hardness_hrc: the HRC number of a stated hardness;
# tolerance: text the stated tolerance contains ("2768-m"). A part that states no value never passes.
FILTER_NUMBERS = tuple(UNIT)
FILTER_KEYS = (*FILTER_NUMBERS, "hardness_hrc", "tolerance")
FILTER_LABELS = {**LABELS, "hardness_hrc": "Hardness (HRC)"}
FILTER_UNITS = {**UNIT, "hardness_hrc": "HRC"}


def filter_value(part: Any, key: str) -> Any:
    """The value a filter compares: a number for FILTER_NUMBERS and hardness_hrc, text for tolerance."""
    if key == "hardness_hrc":
        text = value(part, "hardness")
        m = re.search(r"(\d+(?:\.\d+)?)\s*hrc", str(text or "").lower())
        return float(m.group(1)) if m else None
    v = value(part, key)
    if key == "tolerance":
        return str(v) if v not in (None, "") else None
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def check_filter(conds: dict[str, Any]) -> dict[str, Any]:
    """Validates filters.engineering; raises ValueError (the API answers 422)."""
    for key, cond in (conds or {}).items():
        if key not in FILTER_KEYS:
            raise ValueError(f"Engineering filter '{key}': use one of {', '.join(FILTER_KEYS)}")
        if key == "tolerance":
            if not isinstance(cond, str) or not 0 < len(cond.strip()) <= 40:
                raise ValueError("Engineering filter 'tolerance': give the text to look for, e.g. \"2768-m\"")
            continue
        if not isinstance(cond, dict) or not cond or set(cond) - {"min", "max"}:
            raise ValueError(f"Engineering filter '{key}': use min and/or max")
        for v in cond.values():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
                raise ValueError(f"Engineering filter '{key}': give a valid number")
    return conds


def meets(part: Any, conds: dict[str, Any]) -> bool:
    """Does the part meet every engineering filter? Never when it does not state (or imply) the value."""
    for key, cond in (conds or {}).items():
        v = filter_value(part, key)
        if v is None:
            return False
        if key == "tolerance":
            norm = lambda s: re.sub(r"[\s-]", "", str(s).lower())   # noqa: E731
            if norm(cond) not in norm(v):
                return False
            continue
        if "min" in cond and v < float(cond["min"]):
            return False
        if "max" in cond and v > float(cond["max"]):
            return False
    return True
