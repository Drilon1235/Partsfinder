"""Engineering specs: read hard technical requirements from a question and check them per part.

An engineer does not ask for "a green chair" but for "DIN 912 M8x30 A2-70" or "deep groove ball
bearing 6204-2RS". Such a question contains exact requirements. This module:

1. parse_specs(query)  -> the requirements, deterministic (no AI needed), e.g.
   {"thread": "M8", "length_mm": 30, "standard": ["DIN 912"], "material_grade": "A2-70"}
2. check_specs(specs, part) -> per requirement: requested value, value of the part, status
   ("match", "mismatch" or "unknown"). This is the "requested versus found" table that
   the user sees, and the search engine uses it to rank and to decide fits/close/none.

Values on the part come from its properties (see docs/03_DATAMODEL.md, "Engineering properties"),
its standards and its material. A property can be a list (e.g. "property_classes": ["8.8", "10.9"]):
one CAD model that is valid for several grades.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import engineering
from .models import Part

# Specs that define WHAT the part is. A mismatch on one of these = a different part
# (other thread, other bearing, other motor frame), never "fits".
KEY_SPECS = {"standard", "standard_exact", "thread", "designation", "frame_size", "dn", "module", "teeth", "belt_profile",
             "profile_size", "bore_mm", "inner_diameter_mm", "outer_diameter_mm", "width_mm",
             "piston_diameter_mm", "rail_size", "shaft_diameter_mm", "diameter_mm", "power_w"}

# Equivalent standards (same part, other number): DIN 912 = ISO 4762, DIN 933 = ISO 4017, ...
EQUIVALENT_STANDARDS = [
    {"DIN 912", "ISO 4762"}, {"DIN 933", "ISO 4017"}, {"DIN 931", "ISO 4014"},
    {"DIN 934", "ISO 4032"}, {"DIN 985", "ISO 10511"}, {"DIN 125", "ISO 7089"},
    {"DIN 7991", "ISO 10642"}, {"DIN 913", "ISO 4026"}, {"DIN 7380", "ISO 7380"},
    {"DIN 625", "ISO 15"}, {"DIN 471", "ISO 464"}, {"DIN 6885", "ISO 773"},
    {"DIN 2501", "EN 1092-1"}, {"DIN 439", "ISO 4035"}, {"DIN 7984", "ISO 14580"},
]

STAINLESS = ("a2", "a4", "1.4301", "1.4307", "1.4404", "1.4401", "1.4571", "304", "316", "stainless", "inox")
# keys without spaces or hyphens (normalize_grade strips them): "AISI 316L", "EN AW-6082", "1.4404" all work
GRADE_ALIASES = {
    "aisi304": "1.4301", "304": "1.4301", "aisi304l": "1.4307", "304l": "1.4307",
    "aisi316": "1.4401", "316": "1.4401", "aisi316l": "1.4404", "316l": "1.4404", "316ti": "1.4571",
    "a2": "A2", "a4": "A4", "stainless": "stainless", "stainlesssteel": "stainless", "inox": "stainless",
    "s235": "S235JR", "s235jr": "S235JR", "1.0038": "S235JR", "s355": "S355J2", "s355j2": "S355J2",
    "1.0577": "S355J2", "1.0570": "S355J2", "c45": "C45", "1.0503": "C45", "42crmo4": "42CrMo4", "1.7225": "42CrMo4",
    "6061": "6061-T6", "6061t6": "6061-T6", "enaw6061": "6061-T6", "almg1sicu": "6061-T6",
    "6082": "6082-T6", "6082t6": "6082-T6", "enaw6082": "6082-T6", "alsi1mgmn": "6082-T6",
    "6063": "6063-T5", "6063t5": "6063-T5", "enaw6063": "6063-T5", "almgsi0.5": "6063-T5", "almgsi": "6063-T5",
    "pom": "POM", "pa6": "PA6", "pa66": "PA66", "ptfe": "PTFE",
}
# A family in the question accepts every member ("A4": 1.4401, 1.4404 or 1.4571); a precise number
# needs that number, and a part that only says its family ("A4") is then "unknown", not a mismatch.
GRADE_FAMILY = {"A2": "A2", "1.4301": "A2", "1.4307": "A2", "1.4541": "A2", "1.4567": "A2",
                "A4": "A4", "1.4401": "A4", "1.4404": "A4", "1.4571": "A4"}
GRADE_IN_TEXT = re.compile(
    r"\b(1\.4\d{3}|1\.0038|1\.0577|1\.0570|1\.0503|1\.7225|aisi\s?30[4]l?|aisi\s?316(?:l|ti)?|316(?:l|ti)|304l|"
    r"s235(?:jr)?|s355(?:j2)?|en\s?aw-?60(?:61|63|82)|alsi1mgmn|almg1sicu|almgsi(?:0\.5)?|"
    r"6061(?:-t6)?|6082(?:-t6)?|6063(?:-t5)?|c45|42crmo4|pom|pa66|pa6|ptfe)\b")
# Materials a question can rule out ("not galvanized", "no plastic"): name -> words that reveal it on a part
EXCLUDABLE = {
    "galvanized": ("galvanized", "galvanised", "zinc plated", "zinc-plated", "zinc", "hot-dip", "hdg"),
    "stainless": ("stainless", "inox", "a2", "a4", "1.4301", "1.4307", "1.4401", "1.4404", "1.4571"),
    "plastic": ("plastic", "nylon", "polyamide", "pa6", "pa66", "pom", "acetal", "delrin", "ptfe", "pvc", "abs",
                "polypropylene", "polyethylene", "peek"),
    "brass": ("brass", "cuzn"),
    "aluminium": ("aluminium", "aluminum", "6061", "6063", "6082", "almg", "alsi"),
    "copper": ("copper",),
    "rubber": ("rubber", "nbr", "epdm"),
}
_EXCLUDE_WORDS = {w: name for name, words in EXCLUDABLE.items() for w in words}
EXCLUSION = re.compile(r"\b(?:not|no|without|non|excluding|except|never)(?:\s+be)?(?:\s+(?:made\s+of|made\s+from|of|in|from))?[\s-]+("
                       + "|".join(sorted(map(re.escape, _EXCLUDE_WORDS), key=len, reverse=True)) + r")\b")
# Requirements the library can only confirm when the part's own text states them (finish, locking, certificates):
# shown as "not checked" until a part says so, never silently dropped
TEXT_FEATURES = ("black oxide", "blackened", "zinc flake", "geomet", "dacromet", "hard anodized", "anodized", "anodised",
                 "passivated", "nickel plated", "chrome plated", "powder coated", "nylok", "nyloc", "thread locking",
                 "pre-applied", "prevailing torque", "food grade", "rohs", "atex", "fda")
FEATURE_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(map(re.escape, TEXT_FEATURES)) + r")(?![a-z0-9])")
# upper limits: "max 50 mm", "at most 100 mm", "under 3 g", "lighter than 0.5 kg"
LIMIT_RE = re.compile(r"\b(?:max(?:imum)?\.?|at most|under|below|less than|smaller than|lighter than|no more than|"
                      r"not more than)\s*(?:length|size|weight|mass)?\s*(?:of\s)?(\d+(?:\.\d+)?)\s?(mm|cm|m|g|kg)\b")
# preferences only change the order: "preferably A4", "ideally ISO 4762", "if possible stainless"
# strength, load and tolerance requirements: checked as specs, never words the part's name must contain
_AT_LEAST = r"\s*(?:of\s+|at\s+least\s+|min(?:imum)?\.?\s+|>=?\s*|≥\s*)?"
ENGINEERING_RE = [re.compile(p) for p in (
    r"(?:\b(?:at\s+least|min(?:imum)?\.?)\s+)?(?:\b(?:tensile|yield|proof)\s+)?(?:\bstrength\s+)?(?:\bof\s+)?"
    r"(?:at\s+least\s+|min(?:imum)?\.?\s+|>=?\s*|≥\s*)?\d{2,4}(?:\.\d+)?\s?(?:mpa|n/mm2|n/mm²)(?![a-z0-9])",
    r"\b(?:static\s+load\s+rating(?:\s+c0)?|c0)" + _AT_LEAST + r"\d+(?:\.\d+)?\s?(?:kn|n)\b",
    r"\b(?:dynamic\s+)?load\s+rating(?:\s+c)?" + _AT_LEAST + r"\d+(?:\.\d+)?\s?(?:kn|n)\b",
    r"\b(?:holds?|holding|carr(?:y|ies|ying)|supports?|bears?|takes?|max(?:imum)?\s+load|working\s+load|load(?:\s+capacity)?"
    r"|capacity)" + _AT_LEAST + r"(?:up\s+to\s+)?\d+(?:\.\d+)?\s?(?:kg|kn|n|t)\b",
    r"\d+(?:\.\d+)?\s?(?:kg|kn|n|t)\s+(?:load|capacity)\b",
    r"\biso\s?2768\s?-?\s?[fmcv][hkl]?\b",
)]
PREFERENCE_RE = re.compile(r"\b(?:preferably|preferred|ideally|if possible|nice to have|optionally|prefer)\b\s*:?\s*([^,;.]*)")
STRICT_STANDARD = re.compile(r"\b(?:exactly|only|strictly|precisely|strict)\b\W+(?:\w+\W+){0,2}?(iso|din|en)\s?-?(\d{2,5})")
PROPERTY_CLASS = re.compile(r"(?<![\d.])(4\.6|5\.6|8\.8|10\.9|12\.9)(?![\d.])")
STAINLESS_CLASS = re.compile(r"\b(a[24])-(50|70|80)\b")

SPEC_LABELS = {
    "thread": "thread", "length_mm": "length", "standard": "standard", "material_grade": "material",
    "property_class": "property class", "designation": "designation", "seal": "seal",
    "inner_diameter_mm": "inner diameter d", "outer_diameter_mm": "outer diameter D",
    "width_mm": "width B", "frame_size": "NEMA frame", "holding_torque_nm": "holding torque",
    "shaft_diameter_mm": "shaft diameter", "module": "module", "teeth": "teeth",
    "belt_profile": "belt profile", "bore_mm": "bore", "dn": "DN", "pn": "PN",
    "profile_size": "profile size", "slot_width_mm": "slot width", "piston_diameter_mm": "piston diameter",
    "stroke_mm": "stroke", "rail_size": "rail size", "tolerance": "tolerance", "pitch_mm": "pitch",
    "rated_current_a": "rated current", "port_thread": "port thread", "diameter_mm": "diameter",
    "standard_exact": "standard (exactly)", "excluded": "excluded material", "feature": "requirement",
    "max_size_mm": "largest size", "max_mass_g": "mass", "power_w": "power",
    "yield_strength_mpa": "yield strength", "tensile_strength_mpa": "tensile strength", "max_load_kg": "maximum load",
    "load_rating_kn": "dynamic load rating C", "static_load_rating_kn": "static load rating C0",
}
UNITS = {"length_mm": "mm", "inner_diameter_mm": "mm", "outer_diameter_mm": "mm", "width_mm": "mm",
         "holding_torque_nm": "Nm", "shaft_diameter_mm": "mm", "bore_mm": "mm", "slot_width_mm": "mm",
         "piston_diameter_mm": "mm", "stroke_mm": "mm", "pitch_mm": "mm", "rated_current_a": "A",
         "diameter_mm": "mm", "max_size_mm": "mm", "max_mass_g": "g", "power_w": "W",
         "yield_strength_mpa": "MPa", "tensile_strength_mpa": "MPa", "max_load_kg": "kg", "load_rating_kn": "kN",
         "static_load_rating_kn": "kN"}
# how a requested value reads in the requirement table: "not galvanized", "≤ 50 mm"
REQUEST_PREFIX = {"excluded": "not ", "max_size_mm": "≤ ", "max_mass_g": "≤ ", "yield_strength_mpa": "≥ ",
                  "tensile_strength_mpa": "≥ ", "max_load_kg": "≥ ", "load_rating_kn": "≥ ", "static_load_rating_kn": "≥ "}
# strength and load: the part's own value, or what follows from its property class or material grade (engineering.py)
ENGINEERING = {"yield_strength_mpa", "tensile_strength_mpa", "max_load_kg", "load_rating_kn", "static_load_rating_kn"}
# requirements that must be confirmed by the part's own data before it can "fit" (also when the AI judges)
CONFIRM = KEY_SPECS | {"property_class", "material_grade", "excluded", "feature", "max_size_mm", "max_mass_g",
                       "yield_strength_mpa", "tensile_strength_mpa", "max_load_kg", "load_rating_kn",
                       "static_load_rating_kn", "tolerance"}
# "at least": a part that is stronger than asked still fits
AT_LEAST = {"holding_torque_nm", "pn", "yield_strength_mpa", "tensile_strength_mpa", "max_load_kg", "load_rating_kn",
            "static_load_rating_kn"}
# Where to look on the part, in order (properties with these names)
ALIASES = {
    "inner_diameter_mm": ["inner_diameter_mm", "bore_mm", "d_mm"],
    "outer_diameter_mm": ["outer_diameter_mm", "d_outer_mm", "D_mm"],
    "width_mm": ["width_mm", "b_mm", "face_width_mm"],
    "bore_mm": ["bore_mm", "inner_diameter_mm", "shaft_diameter_mm"],
    "shaft_diameter_mm": ["shaft_diameter_mm", "bore_mm", "inner_diameter_mm"],
    "property_class": ["property_class", "property_classes"],
    "material_grade": ["material_grade", "material_grades"],
    "thread": ["thread", "for_thread"],
    "power_w": ["power_w", "rated_power_w", "nominal_power_w", "output_power_w"],
}


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _fmt(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value)
    return str(value)


def format_value(key: str, value: Any) -> str:
    if value is None:
        return "-"
    unit = UNITS.get(key)
    if key == "frame_size":
        return f"NEMA {_fmt(value)}"
    if key == "dn":
        return f"DN{_fmt(value)}"
    if key == "pn":
        return f"PN{_fmt(value)}"
    if key == "module":
        return f"m{_fmt(value)}"
    return f"{_fmt(value)} {unit}" if unit and not isinstance(value, str) else _fmt(value)


def norm_standard(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _equivalents(std: str) -> set[str]:
    n = norm_standard(std)
    for group in EQUIVALENT_STANDARDS:
        if n in {norm_standard(g) for g in group}:
            return {norm_standard(g) for g in group}
    return {n}


def normalize_grade(text: str) -> str:
    t = text.strip().lower()
    return GRADE_ALIASES.get(re.sub(r"[\s\-]", "", t),
                             text.strip().upper() if re.fullmatch(r"[a-z]\d-\d+", t) else text.strip())


def grade_relation(wanted: str, have: str) -> str:
    """'match', 'unknown' or 'mismatch' between a requested grade and a grade the part states."""
    w, h = normalize_grade(wanted), normalize_grade(have)
    if _text_eq(w, h):
        return "match"
    if w == "stainless":
        return "match" if h in GRADE_FAMILY or any(x in h.lower() for x in STAINLESS) else "mismatch"
    if w in ("A2", "A4"):                              # a family: every member counts
        return "match" if GRADE_FAMILY.get(h) == w else "mismatch"
    if h in ("A2", "A4", "stainless") and (GRADE_FAMILY.get(w) == h or (h == "stainless" and w in GRADE_FAMILY)):
        return "unknown"                               # the part only says its family: could be the asked number
    return "mismatch"


# ---- 1. question -> specs ------------------------------------------------------------------------
def split_preferences(query: str) -> tuple[str, str]:
    """(hard part, preferred part) of a question: "M8x30 bolt, preferably A4" -> ("M8x30 bolt, ", "A4")."""
    text = query or ""
    prefs = [m.group(1) for m in PREFERENCE_RE.finditer(text.lower())]
    return PREFERENCE_RE.sub(" ", text.lower()) if prefs else text, " ".join(prefs)


def kind_words(query: str) -> str:
    """The words that say what kind of part is asked for: without what it prefers, rules out, limits or
    asks as a finish ("not galvanized", "max 50 mm", "food grade"); those are checked as specs instead."""
    text = split_preferences(query)[0].lower()
    for pattern in (EXCLUSION, LIMIT_RE, FEATURE_RE, *ENGINEERING_RE):
        text = pattern.sub(" ", text)
    # what is left of "a bracket that holds 50 kg" / "a castor with a load of ..." is "a bracket", "a castor"
    return re.sub(r"(?:\s+\b(?:that|which|with|to|and|of|an?|for|can)\b)+\s*$", "", text.rstrip())


def parse_preferences(query: str) -> dict[str, Any]:
    """What the question prefers but does not require: only used to order the results."""
    pref = split_preferences(query)[1]
    return parse_specs(pref) if pref else {}


def parse_specs(query: str) -> dict[str, Any]:
    """Hard requirements that are literally in the question. Only what is unambiguous; what it only
    prefers ("preferably A4") is left out (see parse_preferences)."""
    query = split_preferences(query)[0]
    q = " " + (query or "").lower().replace("×", "x").replace("ø", " ø") + " "
    q = re.sub(r"(\d),(\d)", r"\1.\2", q)
    specs: dict[str, Any] = {}

    # upper limits first, so "max 500 mm" is not also read as a length
    for m in LIMIT_RE.finditer(q):
        value, unit = _num(m.group(1)), m.group(2)
        if unit in ("g", "kg"):
            specs["max_mass_g"] = value * (1000 if unit == "kg" else 1)
        else:
            specs["max_size_mm"] = value * {"mm": 1, "cm": 10, "m": 1000}[unit]
    q = LIMIT_RE.sub(" ", q)
    # general tolerances ISO 2768-m / -mK: a tolerance class the part must state, not a standard it must name
    m = re.search(r"\biso\s?2768\s?-?\s?([fmcv])([hkl])?\b", q)
    if m:
        specs["tolerance"] = f"ISO 2768-{m.group(1)}{(m.group(2) or '').upper()}"
        q = q[:m.start()] + " " + q[m.end():]
    # strength: "at least 800 MPa", "tensile strength 800 N/mm2", "yield 640 MPa"
    for m in re.finditer(r"(\d{2,4}(?:\.\d+)?)\s?(?:mpa|n/mm2|n/mm²)(?![a-z0-9])", q):
        before = q[max(0, m.start() - 25):m.start()]
        key = "yield_strength_mpa" if re.search(r"yield|proof|rp0|\bre\b", before) else "tensile_strength_mpa"
        specs[key] = _num(m.group(1))
    # bearings: "static load rating 7 kN" / "C0 7 kN", "dynamic load rating 14 kN" / "load rating C 14 kN"
    at_least = r"\s*(?:of\s+|at\s+least\s+|min(?:imum)?\.?\s+|>=?\s*|≥\s*)?"
    m = re.search(r"\b(?:static\s+load\s+rating(?:\s+c0)?|c0)" + at_least + r"(\d+(?:\.\d+)?)\s?(kn|n)\b", q)
    if m:
        specs["static_load_rating_kn"] = _num(m.group(1)) * (0.001 if m.group(2) == "n" else 1)
        q = q[:m.start()] + " " + q[m.end():]
    m = re.search(r"\b(?:dynamic\s+)?load\s+rating(?:\s+c)?" + at_least + r"(\d+(?:\.\d+)?)\s?(kn|n)\b", q)
    if m:
        specs["load_rating_kn"] = _num(m.group(1)) * (0.001 if m.group(2) == "n" else 1)
        q = q[:m.start()] + " " + q[m.end():]
    # load: "holds 50 kg", "load 500 N", "capacity 2 kN", "max load 1 t", "50 kg load"
    m = (re.search(r"\b(?:holds?|holding|carr(?:y|ies|ying)|supports?|bears?|takes?|max(?:imum)?\s+load|working\s+load|"
                   r"load(?:\s+capacity)?|capacity)" + at_least + r"(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s?(kg|kn|n|t)\b", q)
         or re.search(r"(\d+(?:\.\d+)?)\s?(kg|kn|n|t)\s+(?:load|capacity)\b", q))
    if m:
        specs["max_load_kg"] = round(_num(m.group(1)) * {"kg": 1, "t": 1000, "n": 1 / 9.81, "kn": 1000 / 9.81}[m.group(2)], 1)
        q = q[:m.start()] + " " + q[m.end():]
    features = list(dict.fromkeys(FEATURE_RE.findall(q)))
    if features:
        specs["feature"] = features

    # standards: ISO 4762, DIN 912, EN 1092-1, ISO 15552
    stds = []
    for m in re.finditer(r"\b(iso|din|en)\s?-?(\d{2,5})(?:-(\d))?\b", q):
        stds.append(f"{m.group(1).upper()} {m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else ""))
    strict = {f"{m.group(1).upper()} {m.group(2)}" for m in STRICT_STANDARD.finditer(q)}
    exact = [x for x in dict.fromkeys(stds) if x.split("-")[0] in strict]
    loose = [x for x in dict.fromkeys(stds) if x not in exact]
    if loose:
        specs["standard"] = loose
    if exact:
        specs["standard_exact"] = exact               # "exactly ISO 4762": DIN 912 does not count

    # NEMA frame + holding torque (before thread/module so "nema 17" is not read as anything else)
    m = re.search(r"\bnema\s?-?(8|11|14|17|23|24|34|42)\b", q)
    if m:
        specs["frame_size"] = int(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s?(?:nm|n\.m|n·m)\b", q)
    if m and not re.search(r"\d\s?nm\s?(?:wavelength|laser)", q):
        specs["holding_torque_nm"] = _num(m.group(1))

    # power of motors, heaters, power supplies: "400 W", "0.75 kW", "400W" (never "W" alone)
    m = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(kw|w|watts?)\b", q)
    if m:
        specs["power_w"] = _num(m.group(1)) * (1000 if m.group(2) == "kw" else 1)

    # thread + length: M8x30, M8 x 30, M8 30mm, "M10 bolt 60 mm"
    m = re.search(r"\bm(\d{1,2}(?:\.\d)?)\s?x\s?(\d{1,3}(?:\.\d+)?)(?!\s?x)\b", q)
    pitch = None
    if m and float(m.group(2)) < 5 and "." in m.group(2):         # M8x1.25 = pitch, not length
        pitch = m.group(2)
        m = None
    if m and not re.search(r"\bmodule\b|\bmod\b", q[max(0, m.start() - 8):m.start()]):
        specs["thread"] = "M" + _fmt(_num(m.group(1)))
        specs["length_mm"] = _num(m.group(2))
    else:
        m = re.search(r"(?<![a-z0-9])m(\d{1,2}(?:\.\d)?)(?![\d.])", q)
        if m and not re.search(r"(module|mod)\s*$", q[:m.start()]):
            specs["thread"] = "M" + _fmt(_num(m.group(1)))
            rest = q[m.end():]
            lm = re.search(r"\b(?:length|l\s?=|long)?\s*(\d{1,3}(?:\.\d+)?)\s?mm\b(?!\s?(?:bore|shaft|wide|width|diameter))",
                           rest[:40])
            if lm:
                specs["length_mm"] = _num(lm.group(1))
    if pitch:
        specs["pitch_mm"] = _num(pitch)

    # property class (8.8, 10.9, 12.9) and stainless A2-70 / A4-80
    m = STAINLESS_CLASS.search(q)
    if m:
        specs["property_class"] = f"{m.group(1).upper()}-{m.group(2)}"
    else:
        m = re.search(r"\b(?:property\s)?class\s?(\d{1,2}\.\d)\b", q) or PROPERTY_CLASS.search(q)
        if m and "thread" in specs:
            specs["property_class"] = m.group(1)
    # materials the question rules out: "not galvanized", "no plastic", "without brass"
    excluded = list(dict.fromkeys(_EXCLUDE_WORDS[m.group(1)] for m in EXCLUSION.finditer(q)))
    if excluded:
        specs["excluded"] = excluded
    q_pos = EXCLUSION.sub(" ", q)                      # what is ruled out is not also a requirement
    # material grade (only explicit grades or "stainless", never a loose "steel")
    m = GRADE_IN_TEXT.search(q_pos)
    if m and re.fullmatch(r"60(?:61|63|82)", m.group(1)) and "bearing" in q:
        m = None                                       # "6082 bearing" is a bearing number, not aluminium
    if m:
        specs["material_grade"] = normalize_grade(m.group(1))
    elif "property_class" not in specs and re.search(r"\b(a2|a4)\b", q_pos):
        specs["material_grade"] = normalize_grade(re.search(r"\b(a2|a4)\b", q_pos).group(1))
    elif re.search(r"\b(stainless|inox)\b", q_pos) and not str(specs.get("property_class", "")).startswith("A"):
        specs["material_grade"] = "stainless"

    # bearing designation: 6204, 6204-2RS, 6204 ZZ, 608zz, 61804-2rs; not a year or a length
    m = re.search(r"(?<![\d.x])((?:6[0-3]|16|618|619|60|62|63)\d{1,3}|60[0-9]|62[0-9]|63[0-9]|"
                  r"608|623|624|625|626|627|629)(?:\s?-?\s?(2rs1?|2rsh|2z|zz|2rs|rs|z|llu|ddu))?(?![\d.]|\s?mm)", q)
    if m and ("bearing" in q or m.group(2) or re.search(r"\b(6[0-3]\d{2})\b", q) and "nema" not in q):
        base = m.group(1)
        grade_number = str(specs.get("material_grade", "")).startswith(base)     # "EN AW-6082" is aluminium
        if 3 <= len(base) <= 5 and not grade_number and not ("thread" in specs and specs.get("length_mm") == float(base)):
            specs["designation"] = base
            seal = (m.group(2) or "").upper()
            if seal:
                specs["seal"] = {"ZZ": "2Z", "2RS1": "2RS", "2RSH": "2RS", "LLU": "2RS", "DDU": "2RS",
                                 "RS": "RS", "Z": "Z"}.get(seal, seal)

    # alphanumeric catalogue designations: pillow blocks UCP205 / UCF206, linear bushings LM12UU
    m = re.search(r"\b(uc[pfl]?\d{3}|ucfl\d{3}|lm\d{1,2}uu(?:l)?)\b", q)
    if m and "designation" not in specs:
        specs["designation"] = m.group(1).upper()

    # dowel pins: "dowel pin 6x30", "parallel pin 8 x 40"
    if re.search(r"\b(dowel|parallel pin|locating pin|cylindrical pin)\b", q):
        m = re.search(r"(?<![\w.])(\d{1,2}(?:\.\d)?)\s?x\s?(\d{1,3})(?![\w.])", q)
        if m:
            specs.update(diameter_mm=_num(m.group(1)), length_mm=_num(m.group(2)))
        specs.pop("thread", None)                     # "m6" on a dowel pin is the tolerance, not a thread
        specs.pop("pitch_mm", None)

    # d x D x B triple (bearings, bushings, O-rings), e.g. 20x47x14
    m = re.search(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s?x\s?(\d{1,3}(?:\.\d+)?)\s?x\s?(\d{1,3}(?:\.\d+)?)(?![\w.])", q)
    if m and "thread" not in specs:
        a, b, c = (_num(x) for x in m.groups())
        if "bearing" in q or "bushing" in q or "bush" in q:
            specs.update(inner_diameter_mm=a, outer_diameter_mm=b, width_mm=c)

    # gears / pulleys: "module 2", "mod 1.5", "20 teeth", "z20", "20T", GT2, HTD 5M, T5
    m = re.search(r"\b(?:module|mod)\s?=?\s?(\d+(?:\.\d+)?)\b", q)
    if m:
        specs["module"] = _num(m.group(1))
    m = re.search(r"\b(\d{1,3})\s?(?:teeth|tooth|t)\b|\bz\s?=?\s?(\d{1,3})\b", q)
    if m and not re.search(r"\b(\d{1,3})\s?t\b", q[:5]):
        teeth = int(m.group(1) or m.group(2))
        if 6 <= teeth <= 200:
            specs["teeth"] = teeth
    m = re.search(r"\b(gt2|gt3|htd\s?[358]m|[358]m|t2\.5|t5|t10|xl|mxl)\b", q)
    if m and ("pulley" in q or "belt" in q or "gt" in m.group(1) or "htd" in m.group(1)):
        specs["belt_profile"] = m.group(1).upper().replace(" ", "").replace("HTD", "HTD ")

    # bore / shaft diameter: "bore 8", "8 mm bore", "for 20 mm shaft", "Ø8 shaft", "shaft 8 mm"
    m = (re.search(r"\bbore\s?(?:diameter)?\s?(?:of\s)?ø?\s?(\d{1,3}(?:\.\d+)?)", q)
         or re.search(r"(\d{1,3}(?:\.\d+)?)\s?mm\s?bore\b", q))
    if m:
        specs["bore_mm"] = _num(m.group(1))
    m = (re.search(r"\b(?:for|on)\s(?:an?\s)?(?:ø\s?)?(\d{1,3}(?:\.\d+)?)\s?mm\s(?:diameter\s)?shaft\b", q)
         or re.search(r"\bshaft\s?(?:diameter\s?)?ø?\s?(\d{1,3}(?:\.\d+)?)\s?mm\b", q)
         or re.search(r"ø\s?(\d{1,3}(?:\.\d+)?)\s?(?:mm\s)?shaft\b", q))
    if m:
        key = "shaft_diameter_mm" if "frame_size" in specs or "linear shaft" in q or "rod" in q else "bore_mm"
        if "bearing" in q or "bushing" in q or "pillow" in q or "coupling" in q or "pulley" in q:
            key = "bore_mm"
        specs.setdefault(key, _num(m.group(1)))
    if "frame_size" in specs:
        m = re.search(r"(\d{1,2}(?:\.\d+)?)\s?mm\s(?:shaft|axle)\b", q)
        if m:
            specs["shaft_diameter_mm"] = _num(m.group(1))
            specs.pop("bore_mm", None)

    # pipe flanges: DN50 PN16
    m = re.search(r"\bdn\s?(\d{1,4})\b", q)
    if m:
        specs["dn"] = int(m.group(1))
    m = re.search(r"\bpn\s?(\d{1,3})\b", q)
    if m:
        specs["pn"] = int(m.group(1))

    # aluminium profiles: 40x40 (two numbers, no third), slot 8 / "8 mm slot" / "b-type"
    if "profile" in q or "extrusion" in q or "t-slot" in q or "slot" in q:
        m = re.search(r"(?<![\w.x])(\d{2,3})\s?x\s?(\d{2,3})(?!\s?x\s?\d)(?![\w.])", q)
        if m and "thread" not in specs:
            specs["profile_size"] = f"{m.group(1)}x{m.group(2)}"
        m = re.search(r"\bslot\s?(?:width\s?)?(\d{1,2})\b|\b(\d{1,2})\s?mm\s?slot\b", q)
        if m:
            specs["slot_width_mm"] = _num(m.group(1) or m.group(2))
        m = re.search(r"\b(?:length|l\s?=)\s?(\d{2,4})\b|\b(\d{3,4})\s?mm\s?long\b", q)
        if m:
            specs["length_mm"] = _num(m.group(1) or m.group(2))

    # pneumatic cylinders: "bore 50 stroke 100", "ø50x100", ISO 15552 / ISO 6432
    if "cylinder" in q:
        m = re.search(r"ø\s?(\d{2,3})\s?x\s?(\d{2,4})\b", q)
        if m:
            specs["piston_diameter_mm"] = _num(m.group(1))
            specs["stroke_mm"] = _num(m.group(2))
        if "bore_mm" in specs:
            specs["piston_diameter_mm"] = specs.pop("bore_mm")
        m = re.search(r"\bstroke\s?(\d{1,4})\b|\b(\d{1,4})\s?mm\s?stroke\b", q)
        if m:
            specs["stroke_mm"] = _num(m.group(1) or m.group(2))

    # linear guides: "rail size 15", "size 20 linear guide", "hgr20"
    if "rail" in q or "linear guide" in q or "carriage" in q:
        m = re.search(r"\bsize\s?(\d{2})\b|\b(?:hg[rhw]?|mgn|rail)\s?(\d{2})\b", q)
        if m:
            specs["rail_size"] = int(m.group(1) or m.group(2))

    # length of bar stock (shafts, rails, profiles, tubes): "length 500", "L=500", "500 mm long"
    if "length_mm" not in specs:
        m = re.search(r"\b(?:length|l\s?=)\s?(\d{2,4}(?:\.\d+)?)\b|\b(\d{2,4})\s?mm\s?long\b", q)
        if not m and re.search(r"\b(shaft|rod|rail|profile|extrusion|tube)\b", q):
            nums = [x for x in re.findall(r"\b(\d{3,4})\s?mm\b", q)]
            m = re.match(r"(\d+)", nums[-1]) if nums else None
            if m:
                specs["length_mm"] = _num(m.group(1))
                m = None
        if m:
            specs["length_mm"] = _num(m.group(1) or m.group(2))

    m = re.search(r"\b([a-h]\d{1,2}|[A-H]\d{1,2})\s?(?:tolerance|fit)\b|\b(h6|h7|g6|k6|j6|f7|m6)\b", (query or ""))
    if (m and "thread" not in specs or (m and "shaft" in q)) and "tolerance" not in specs:
        specs["tolerance"] = (m.group(1) or m.group(2))
    return specs


# ---- what a question leaves open ---------------------------------------------------------------------
# What defines each kind of part. A question that names the kind but not these values is too vague to pick
# one model ("a bolt": which thread, which length?). Any key of a tuple is enough; the first kind found counts.
DEFINING = [
    (r"\bthreaded rods?\b|\bstuds?\b", [("thread",), ("length_mm",)]),
    (r"\b(?:bolts?|screws?)\b", [("thread",), ("length_mm",)]),
    (r"\bnuts?\b", [("thread",)]),
    (r"\bwashers?\b", [("thread", "inner_diameter_mm")]),
    (r"\b(?:pillow blocks?(?: bearings?)?|linear bearings?|linear bushings?)\b", [("designation", "bore_mm", "shaft_diameter_mm")]),
    (r"\bbearings?\b", [("designation", "inner_diameter_mm", "bore_mm")]),
    (r"\b(?:stepper|nema)\b", [("frame_size",)]),
    (r"\bpulleys?\b", [("belt_profile",), ("teeth",)]),
    (r"\bgears?\b", [("module",), ("teeth",)]),
    (r"\bflanges?\b", [("dn",)]),
    (r"\b(?:profiles?|extrusions?)\b", [("profile_size",)]),
    (r"\b(?:shaft |set |clamping )?collars?\b", [("bore_mm",)]),
    (r"\bcouplings?\b", [("bore_mm",)]),
    (r"\bcylinders?\b", [("piston_diameter_mm",), ("stroke_mm",)]),
]
# Words that describe how a part looks or what it is made of, not what it is. When no part of the asked kind
# has one ("a green bolt"), the answer is "no green bolt; the closest bolts", searched without that word.
# Any other missing word may say what the part is ("planetary gearbox", "gear pump"): never left out.
ATTRIBUTE_WORDS = {
    "red", "green", "blue", "yellow", "black", "white", "grey", "gray", "orange", "purple", "pink", "brown",
    "silver", "gold", "golden", "transparent", "clear", "colored", "coloured",
    "galvanized", "galvanised", "zinc", "plated", "chrome", "chromed", "nickel", "anodized", "anodised", "painted",
    "coated", "polished", "brushed", "oxide", "blackened", "passivated",
    "titanium", "brass", "bronze", "copper", "aluminium", "aluminum", "steel", "stainless", "plastic", "nylon",
    "polyamide", "rubber", "wooden", "wood", "carbon",
    "small", "large", "big", "tiny", "long", "short", "heavy", "light", "lightweight", "cheap", "strong",
}

# how a chosen value is added to the question so that parse_specs reads it back
QUERY_FORM = {"length_mm": "{} mm", "inner_diameter_mm": "{} mm bore", "frame_size": "NEMA {}", "teeth": "{} teeth", "module": "module {}",
              "dn": "DN{}", "bore_mm": "{} mm bore", "piston_diameter_mm": "bore {}", "stroke_mm": "stroke {}"}


def kind_of(query: str) -> tuple[str, list[tuple[str, ...]]] | None:
    """(pattern, defining specs) of the first kind of part the text names, or None."""
    q = (query or "").lower()
    return next(((pattern, groups) for pattern, groups in DEFINING if re.search(pattern, q)), None)


def missing_defining(query: str, specs: dict[str, Any]) -> list[str]:
    """Defining specs of the kind of part asked for that the question does not give, in asking order."""
    kind = kind_of(query)
    return [g[0] for g in kind[1] if not any(k in specs for k in g)] if kind else []


def several_parts(query: str) -> bool:
    """Does the question ask for more than one part ("bolt with nut and washer", "bearing and pillow block")?
    Then one search cannot settle it. On doubt (a joining word) we say yes: a slower answer, never a missing part."""
    q = split_preferences(query)[0].lower()
    kinds = 0
    for pattern, _ in DEFINING:                        # each piece of text names one kind at most
        if re.search(pattern, q):                      # ("pillow block bearing" is one part, not two)
            kinds += 1
            q = re.sub(pattern, " ", q)
    return kinds >= 2 or bool(re.search(r"\b(?:and|with|plus|including)\b|[+&]", q))


def query_form(key: str, value: Any) -> str:
    return QUERY_FORM.get(key, "{}").format(_fmt(value))


# ---- 2. specs x part -> checks ---------------------------------------------------------------------
@dataclass
class SpecCheck:
    key: str
    requested: Any
    found: Any
    status: str                        # "match", "mismatch", "unknown"

    @property
    def label(self) -> str:
        if self.key == "feature":                      # "dacromet not stated", not "requirement not stated"
            return str(self.requested)
        return SPEC_LABELS.get(self.key, self.key.replace("_", " "))

    def as_dict(self) -> dict[str, Any]:
        return {"spec": self.key, "label": self.label,
                "requested": REQUEST_PREFIX.get(self.key, "") + (str(self.requested) if self.key == "excluded"
                                                                 else format_value(self.key, self.requested)),
                "found": format_value(self.key, self.found) if self.found is not None else None,
                "status": self.status}

    def sentence(self) -> str:
        if self.key == "excluded":
            return {"match": f"not {self.requested}", "mismatch": f"{self.found} (not allowed: {self.requested})"}.get(
                self.status, f"not {self.requested}: material not stated")
        if self.key == "feature":
            return self.requested if self.status == "match" else f"{self.requested}: not checked (the part does not state it)"
        if self.key in ("max_size_mm", "max_mass_g") and self.status == "mismatch":
            return f"{self.label} {format_value(self.key, self.found)}, more than {format_value(self.key, self.requested)}"
        if self.key in ENGINEERING and self.status == "mismatch":
            return f"{self.label} {format_value(self.key, self.found)}, less than {format_value(self.key, self.requested)}"
        if self.status == "match":
            return f"{self.label} {format_value(self.key, self.found)}"
        if self.status == "mismatch":
            return f"{self.label} {format_value(self.key, self.found)} instead of {format_value(self.key, self.requested)}"
        return f"{self.label} {format_value(self.key, self.requested)} not specified"


def _prop(part: Part, key: str) -> Any:
    props = {k.lower(): v for k, v in part.properties.items()}
    for name in ALIASES.get(key, [key]):
        if name.lower() in props and props[name.lower()] not in (None, "", []):
            return props[name.lower()]
    return None


def _same_number(a: Any, b: Any, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return False


def _text_eq(a: Any, b: Any) -> bool:
    return re.sub(r"[\s\-_]", "", str(a).lower()) == re.sub(r"[\s\-_]", "", str(b).lower())


def check_specs(specs: dict[str, Any], part: Part) -> list[SpecCheck]:
    checks: list[SpecCheck] = []
    for key, want in specs.items():
        if key == "standard":
            have = list(part.standards) + ([part.properties["standard"]] if isinstance(
                part.properties.get("standard"), str) else [])
            have_norm = {norm_standard(s) for s in have}
            for std in want:
                if _equivalents(std) & have_norm:
                    found = next(s for s in have if norm_standard(s) in _equivalents(std))
                    checks.append(SpecCheck("standard", std, found, "match"))
                else:
                    checks.append(SpecCheck("standard", std, ", ".join(have) or None,
                                            "mismatch" if have else "unknown"))
            continue
        if key == "standard_exact":
            have = list(part.standards) + ([part.properties["standard"]] if isinstance(
                part.properties.get("standard"), str) else [])
            for std in want:
                same = [s for s in have if norm_standard(s) == norm_standard(std)]
                equal = [s for s in have if norm_standard(s) in _equivalents(std)]
                if same:
                    checks.append(SpecCheck(key, std, same[0], "match"))
                elif equal:
                    checks.append(SpecCheck(key, std, f"{equal[0]} (equivalent, not the same number)", "mismatch"))
                else:
                    checks.append(SpecCheck(key, std, ", ".join(have) or None, "mismatch" if have else "unknown"))
            continue
        if key == "excluded":
            text = " ".join([part.material or "", part.name, part.description, " ".join(part.tags),
                             " ".join(str(v) for k, v in part.properties.items()
                                      if any(w in k.lower() for w in ("material", "finish", "coating", "surface")))]).lower()
            for name in want:
                hit = next((w for w in EXCLUDABLE[name] if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text)), None)
                if hit:
                    checks.append(SpecCheck(key, name, hit, "mismatch"))
                else:
                    checks.append(SpecCheck(key, name, part.material, "match" if part.material else "unknown"))
            continue
        if key == "feature":
            text = " ".join([part.name, part.description, part.material or "", " ".join(part.tags),
                             " ".join(str(v) for v in part.properties.values())]).lower()
            for f in want:
                checks.append(SpecCheck(key, f, f, "match") if f in text else SpecCheck(key, f, None, "unknown"))
            continue
        if key in ENGINEERING:
            have = engineering.value(part, key)
            if have is None:
                checks.append(SpecCheck(key, want, None, "unknown"))
            else:
                checks.append(SpecCheck(key, want, round(float(have), 1), "match" if have >= want * 0.999 else "mismatch"))
            continue
        if key == "tolerance" and engineering.value(part, "tolerance") is not None:
            have = str(engineering.value(part, "tolerance"))
            norm = lambda x: re.sub(r"[\s\-_]", "", str(x).lower())          # noqa: E731
            checks.append(SpecCheck(key, want, have, "match" if norm(have).startswith(norm(want)) else "mismatch"))
            continue
        if key in ("max_size_mm", "max_mass_g"):
            have = max(part.bbox_mm) if key == "max_size_mm" and part.bbox_mm else (
                engineering.value(part, "mass_g") if key == "max_mass_g" else None)
            if have is None:
                checks.append(SpecCheck(key, want, None, "unknown"))
            else:
                checks.append(SpecCheck(key, want, round(float(have), 1), "match" if have <= want * 1.001 else "mismatch"))
            continue
        if key == "material_grade":
            have = _prop(part, key)
            mat = (part.material or "").lower()
            values = [str(v) for v in (have if isinstance(have, list) else ([have] if have else []))]
            values += [g for g in GRADE_IN_TEXT.findall(mat)] + (["stainless"] if re.search(r"stainless|inox", mat) else [])
            values += re.findall(r"\b(a[24])(?:-\d0)?\b", mat)
            wanted = normalize_grade(str(want))
            relations = [grade_relation(wanted, v) for v in values]
            if "match" in relations or _text_eq(wanted, mat):
                checks.append(SpecCheck(key, wanted, wanted, "match"))
            elif "unknown" in relations or not (values or mat):
                checks.append(SpecCheck(key, wanted, ", ".join(dict.fromkeys(values)) or None, "unknown"))
            else:
                checks.append(SpecCheck(key, wanted, ", ".join(dict.fromkeys(values)) or part.material, "mismatch"))
            continue
        have = _prop(part, key)
        if key == "property_class":
            values = have if isinstance(have, list) else ([have] if have else [])
            if not values:
                mat = (part.material or "").lower()
                stainless_req = str(want).upper().startswith("A")
                values_txt = re.findall(r"\b(?:a[24]-\d0|\d{1,2}\.\d)\b", mat)
                if values_txt:
                    values = values_txt
                elif mat and stainless_req != any(s in mat for s in STAINLESS):
                    checks.append(SpecCheck(key, want, part.material, "mismatch"))
                    continue
            if not values:
                checks.append(SpecCheck(key, want, None, "unknown"))
            elif any(_text_eq(v, want) for v in values):
                checks.append(SpecCheck(key, want, want, "match"))
            else:
                checks.append(SpecCheck(key, want, values, "mismatch"))
            continue
        if have is None:
            found = _text_fallback(key, want, part, specs)
            checks.append(SpecCheck(key, want, found, "match") if found is not None
                          else SpecCheck(key, want, None, "unknown"))
            continue
        if isinstance(have, list):
            ok = any(_text_eq(v, want) or _same_number(v, want) for v in have)
            checks.append(SpecCheck(key, want, have, "match" if ok else "mismatch"))
            continue
        if isinstance(want, (int, float)) and not isinstance(want, bool):
            try:
                hv = float(have)
            except (TypeError, ValueError):
                checks.append(SpecCheck(key, want, have, "unknown"))
                continue
            ok = hv >= float(want) * 0.999 if key in AT_LEAST else _same_number(hv, want)
            checks.append(SpecCheck(key, want, hv, "match" if ok else "mismatch"))
            continue
        if key == "designation":
            want_s = str(want).lower()
            have_s = str(have).lower().replace(" ", "")
            if want_s.isdigit():                       # bearing number: compare the number, not the suffix
                m = re.match(r"\d+", have_s)
                ok = bool(m) and m.group(0) == want_s
            else:
                ok = re.sub(r"[^0-9a-z]", "", have_s).startswith(re.sub(r"[^0-9a-z]", "", want_s))
            checks.append(SpecCheck(key, want, have, "match" if ok else "mismatch"))
            continue
        checks.append(SpecCheck(key, want, have, "match" if _text_eq(have, want) else "mismatch"))
    return checks


def _text_fallback(key: str, want: Any, part: Part, specs: dict[str, Any]) -> Any:
    """For parts without structured properties: the value literally in the name or tags counts
    ("Hex bolt M8x40" has thread M8 and length 40). Only for unambiguous tokens; never a mismatch."""
    text = " ".join([part.name, " ".join(part.tags)]).lower()
    tokens = set(re.findall(r"[a-z0-9.]+", text))
    w = str(want).lower()
    if key == "thread":
        if w in tokens or any(t.startswith(w + "x") for t in tokens):
            return want
    elif key == "length_mm" and specs.get("thread"):
        if f"{str(specs['thread']).lower()}x{_fmt(float(want))}" in tokens:
            return want
    elif key == "designation":
        if any(re.match(rf"{re.escape(w)}(?!\d)", t) for t in tokens):
            return want
    elif key == "frame_size":
        if f"nema{_fmt(want)}" in text.replace(" ", ""):
            return want
    elif key == "dn":
        if f"dn{_fmt(want)}" in tokens:
            return want
    elif key == "profile_size":
        if w in tokens:
            return want
    elif key == "power_w":
        watts = float(want)
        for number, unit in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(kw|w)\b", text):
            if _same_number(float(number) * (1000 if unit == "kw" else 1), watts):
                return want
    return None


@dataclass
class SpecSummary:
    checks: list[SpecCheck]

    @property
    def matched(self) -> list[SpecCheck]:
        return [c for c in self.checks if c.status == "match"]

    @property
    def mismatched(self) -> list[SpecCheck]:
        return [c for c in self.checks if c.status == "mismatch"]

    @property
    def unknown(self) -> list[SpecCheck]:
        return [c for c in self.checks if c.status == "unknown"]

    @property
    def key_mismatch(self) -> bool:
        return any(c.key in KEY_SPECS for c in self.mismatched)

    @property
    def key_match(self) -> bool:
        return any(c.key in KEY_SPECS for c in self.matched)

    @property
    def all_match(self) -> bool:
        return bool(self.checks) and all(c.status == "match" for c in self.checks)

    def score(self) -> float:
        """-1 .. 1: share of requirements met minus share violated (key specs count double)."""
        if not self.checks:
            return 0.0
        w = lambda c: 2.0 if c.key in KEY_SPECS else 1.0          # noqa: E731
        total = sum(w(c) for c in self.checks)
        return (sum(w(c) for c in self.matched) - sum(w(c) for c in self.mismatched)) / total


def summarize(specs: dict[str, Any], part: Part) -> SpecSummary:
    return SpecSummary(check_specs(specs, part) if specs else [])
