"""What happens to a question before and after the search, the same with and without AI.

- prepare(): part names in Dutch, German and French are read as the English names the library uses
  ("inbusbout M8x30" -> "socket head bolt M8x30"), electrical values that no 3D model shows are set aside
  ("10k resistor 0603": the 0603 package decides the shape), and input that asks for nothing ("???", "x30")
  is answered as such instead of with random parts.
- gear_pairs(): "a spur gear pair for 3:1": two existing gears of the same module whose teeth give that ratio.
  The library still does not design: it only pairs models that exist.
- name_fits(): a designation that is literally in a part's name ("IPE 200", "SOIC-8", "SHS 50x50x4") settles it.
- drop_duplicates(): the same standard part from two sources is shown once.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from .specs import _fmt, parse_specs

# ---- 1. other languages ------------------------------------------------------------------------------
# whole words only, longest first; only names of parts and materials, never a size or a designation
TRANSLATIONS = {
    # Dutch
    "inbusbouten": "socket head bolts", "inbusbout": "socket head bolt", "inbusschroef": "socket head screw",
    "cilinderkopschroef": "socket head bolt", "zeskantbouten": "hex bolts", "zeskantbout": "hex bolt",
    "zeskantmoer": "hex nut", "zeskantschroef": "hex bolt", "verzonken schroef": "countersunk screw",
    "verzonken": "countersunk", "bolkopschroef": "button head screw", "stelschroef": "set screw",
    "draadstang": "threaded rod", "draadeind": "stud", "borgmoer": "nyloc nut", "moeren": "nuts", "moer": "nut",
    "bouten": "bolts", "bout": "bolt", "schroeven": "screws", "schroef": "screw", "sluitring": "washer",
    "vulring": "washer", "carrosseriering": "large washer", "veerring": "spring washer", "borgring": "retaining ring",
    "seegerring": "retaining ring", "kogellagers": "ball bearings", "kogellager": "ball bearing",
    "naaldlager": "needle bearing", "rollager": "roller bearing", "lagers": "bearings", "lager": "bearing",
    "staande lagerblok": "pillow block bearing", "lagerblok": "pillow block", "tandwielen": "gears",
    "tandwiel": "gear", "rondsel": "pinion gear", "tandriem": "timing belt", "riemschijf": "pulley",
    "poelie": "pulley", "lasflens": "weld neck flange", "blindflens": "blind flange", "flenzen": "flanges",
    "flens": "flange", "spie": "parallel key", "paspen": "dowel pin", "cilinderpen": "dowel pin",
    "stelring": "shaft collar", "koppeling": "coupling", "hoekprofiel": "angle bar", "hoekstaal": "angle bar",
    "platstaal": "flat bar", "rondstaal": "round bar", "vierkante koker": "square hollow section",
    "koker": "hollow section", "buis": "tube", "afdichtring": "o-ring", "veer": "spring", "scharnier": "hinge",
    "weerstand": "resistor", "condensator": "capacitor", "schakelaar": "switch", "drukknop": "push button",
    "stappenmotor": "stepper motor", "ventilator": "fan", "rvs": "stainless", "verzinkt": "galvanized",
    "staal": "steel", "messing": "brass", "lengte": "length",
    # German
    "innensechskantschrauben": "socket head bolts", "innensechskantschraube": "socket head bolt",
    "zylinderschraube": "socket head bolt", "sechskantschrauben": "hex bolts", "sechskantschraube": "hex bolt",
    "sechskantmutter": "hex nut", "senkschraube": "countersunk screw", "linsenkopfschraube": "button head screw",
    "gewindestift": "grub screw", "gewindestange": "threaded rod", "stiftschraube": "stud",
    "sicherungsmutter": "nyloc nut", "muttern": "nuts", "mutter": "nut", "schrauben": "screws",
    "schraube": "screw", "unterlegscheiben": "washers", "unterlegscheibe": "washer", "scheibe": "washer",
    "federring": "spring washer", "sicherungsring": "retaining ring", "kugellager": "ball bearing",
    "rillenkugellager": "deep groove ball bearing", "nadellager": "needle bearing", "lager": "bearing",
    "stehlager": "pillow block bearing", "zahnräder": "gears", "zahnrad": "gear", "stirnrad": "spur gear",
    "zahnriemen": "timing belt", "riemenscheibe": "pulley", "zahnriemenscheibe": "timing pulley",
    "vorschweißflansch": "weld neck flange", "blindflansch": "blind flange", "flansch": "flange",
    "passfeder": "parallel key", "zylinderstift": "dowel pin", "passstift": "dowel pin", "stellring": "shaft collar",
    "kupplung": "coupling", "welle": "shaft", "winkelprofil": "angle bar", "winkelstahl": "angle bar",
    "flachstahl": "flat bar", "rundstahl": "round bar", "vierkantrohr": "square hollow section",
    "rohr": "tube", "dichtring": "o-ring", "feder": "spring", "scharnier": "hinge", "widerstand": "resistor",
    "kondensator": "capacitor", "schalter": "switch", "taster": "push button", "schrittmotor": "stepper motor",
    "lüfter": "fan", "edelstahl": "stainless", "verzinkt": "galvanized", "stahl": "steel", "messing": "brass",
    # French
    "vis à tête cylindrique": "socket head bolt", "vis chc": "socket head cap screw", "vis tête hexagonale": "hex bolt",
    "vis th": "hex bolt", "vis sans tête": "grub screw", "tige filetée": "threaded rod", "écrou frein": "nyloc nut",
    "écrous": "nuts", "écrou": "nut", "ecrou": "nut", "rondelle": "washer", "rondelles": "washers",
    "roulement à billes": "ball bearing", "roulements": "bearings", "roulement": "bearing", "palier": "pillow block",
    "engrenage": "gear", "pignon": "pinion gear", "courroie": "belt", "poulie": "pulley", "bride": "flange",
    "goupille": "dowel pin", "clavette": "parallel key", "arbre": "shaft", "joint torique": "o-ring",
    "ressort": "spring", "charnière": "hinge", "résistance": "resistor", "condensateur": "capacitor",
    "interrupteur": "switch", "moteur pas à pas": "stepper motor", "acier": "steel", "laiton": "brass",
}
_TRANSLATE = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, TRANSLATIONS), key=len, reverse=True))
                        + r")(?![\w-])", re.IGNORECASE)
# Dutch "as" is a shaft, but only next to a size ("10 mm as"); "ring M8" is a washer
_DUTCH_AS = re.compile(r"(\d\s?mm\s)as\b|\bas\s(ø?\s?\d)", re.IGNORECASE)
_DUTCH_RING = re.compile(r"^\s*ring(en)?\s+(m\d{1,2})\b|\b(m\d{1,2})\s+ring(en)?\s*$", re.IGNORECASE)


def translate(query: str) -> str:
    text = _TRANSLATE.sub(lambda m: TRANSLATIONS[m.group(1).lower()], query)
    text = _DUTCH_AS.sub(lambda m: f"{m.group(1)}shaft" if m.group(1) else f"shaft {m.group(2)}", text)
    text = _DUTCH_RING.sub(lambda m: f"washer {m.group(2)}" if m.group(2) else f"{m.group(3)} washer", text)
    return text


# ---- 2. electrical values -------------------------------------------------------------------------------
_PASSIVE = re.compile(r"\b(resistors?|capacitors?|caps?|inductors?|chokes?|leds?|diodes?|crystals?|oscillators?|"
                      r"fuses?|potentiometers?|trimmers?)\b", re.IGNORECASE)
_VALUES = [
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?(?:[kmgr]|meg)?\s?(?:ohms?|Ω)(?![\w])", re.IGNORECASE),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?[pnuµ]f(?![\w])", re.IGNORECASE),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?[pnuµm]h(?![\w])", re.IGNORECASE),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?[km]?hz(?![\w])", re.IGNORECASE),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?%(?![\w])"),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?v(?:dc|ac)?(?![\w])", re.IGNORECASE),
    re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s?m?a(?![\w])", re.IGNORECASE),
]
_RESISTANCE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?[kmr]\d*(?![\w.])", re.IGNORECASE)    # 10k, 4k7, 2r2, 1M


def electrical_values(query: str) -> tuple[str, list[str]]:
    """(the question without them, the values): only for passive parts, whose model does not show its value."""
    if not _PASSIVE.search(query):
        return query, []
    found: list[str] = []
    text = query
    patterns = _VALUES + ([_RESISTANCE] if re.search(r"\bresistors?\b|\bpotentiometers?\b|\btrimmers?\b", query, re.I) else [])
    for pattern in patterns:
        found += [m.group(0).strip() for m in pattern.finditer(text)]
        text = pattern.sub(" ", text)
    return " ".join(text.split()), found


# ---- 3. input that asks for nothing ----------------------------------------------------------------------
_EMPTY_WORDS = {"a", "an", "the", "i", "me", "need", "want", "give", "find", "show", "search", "please", "some",
                "any", "part", "parts", "thing", "something", "it", "this", "that", "x", "and", "or", "for", "of"}


def asks_for_nothing(query: str) -> bool:
    """'???', 'a', 'M', 'x30': nothing to search for. A size or a designation alone ('608', 'M8') is a question."""
    if parse_specs(query):
        return False
    tokens = [t for t in re.findall(r"[^\W_]+", query.lower()) if t not in _EMPTY_WORDS]
    for t in tokens:
        letters = sum(c.isalpha() for c in t)
        digits = sum(c.isdigit() for c in t)
        if letters >= 2 or digits >= 3:
            return False
    return True


@dataclass
class Prepared:
    original: str
    text: str                                         # what is searched
    notes: list[str] = field(default_factory=list)    # said once above the answer
    empty: bool = False


def prepare(query: str) -> Prepared:
    original = query or ""
    text = translate(original)
    notes = []
    if text.lower() != original.lower():
        notes.append(f"Read as “{' '.join(text.split())}”.")
    text, values = electrical_values(text)
    if values:
        what = ", ".join(dict.fromkeys(values))
        notes.append(f"{what} {'is an electrical value' if len(values) == 1 else 'are electrical values'}: "
                     "a 3D model does not show it, the package decides the shape.")
    return Prepared(original, " ".join(text.split()) or original, notes, empty=asks_for_nothing(text))


EMPTY_MESSAGE = ("Type the part you need, for example “M8x30 socket head bolt”, “6205-2RS”, "
                 "“DN50 PN16 flange” or “SOIC-8”.")


# ---- 4. a designation literally in the name ----------------------------------------------------------------
def _norm(text: str) -> str:
    """'SOIC-8' and 'soic8', 'TO-220' and 'to220', 'Ø20' and '20' compare the same."""
    t = text.lower().replace("×", "x").replace("ø", " ").replace(",", ".")
    return re.sub(r"(?<=[a-z])[-_](?=\d)", "", t)


def size_tokens(query: str) -> list[str]:
    """The tokens of a question that hold a number: '50x50x4', 'soic8', '200', '2.54' (units dropped)."""
    out = []
    for raw in _norm(query).split():
        t = re.sub(r"(?<=\d)(mm|cm)$", "", raw.strip(".,;:!?()\"'"))
        if re.search(r"\d", t) and not re.fullmatch(r"\d+(?:x|pcs)", t):     # not a quantity ("3x")
            out.append(t)
    return out


def _has_token(token: str, text: str) -> bool:
    if re.fullmatch(r"\d+(?:\.\d+)?", token):          # a plain number: '10' is in 'D10.0mm', not in '100'
        for m in re.finditer(r"(?<![\d.])\d+(?:\.\d+)?", text):
            i, j = m.start(), m.end()
            before = text[i - 1] if i else " "
            after = text[j] if j < len(text) else " "
            if before == "x" and i >= 2 and text[i - 2].isdigit():
                continue                               # '0603' is not in '4x0603'
            if before.isalpha() and i >= 2 and text[i - 2].isalnum():
                continue                               # 'L50' and 'D10' count, 'hmb12' does not
            if after.isalpha() and after != "x" and not text.startswith("mm", j):
                continue                               # '0603' is not in '0603metric'
            same = m.group(0) == token if token.startswith("0") else float(m.group(0)) == float(token)
            if same:
                return True
        return False
    start = 0
    while (i := text.find(token, start)) >= 0:
        start = i + 1
        before = text[i - 1] if i else " "
        after = text[i + len(token)] if i + len(token) < len(text) else " "
        if before.isdigit() or before == "." or (before == "x" and i >= 2 and text[i - 2].isdigit()):
            continue                                   # '0603' is not in '4x0603' or '10603'
        if token[0].isdigit() and before.isalpha() and i >= 2 and text[i - 2].isalnum():
            continue                                   # '12' is in 'L50x50x5'-style 't12', not in 'hmb12'
        if token[-1].isdigit() and (after.isdigit() or (after == "." and text[i + len(token) + 1: i + len(token) + 2].isdigit())):
            continue                                   # '20' is not in '200' or '20.5'
        if token[-1].isdigit() and after.isalpha() and not text.startswith("mm", i + len(token)) and after != "x":
            continue                                   # '0603' is not in '0603metric'
        return True
    return False


# words that name another part than the one asked for: "Flange nut T8 lead screw" is a nut, not a lead screw
OTHER_PART = {"nut", "nuts", "bracket", "brackets", "holder", "mount", "housing", "block", "plate", "clamp", "adapter",
              "cover", "cap", "case", "kit", "cable", "extension", "washer", "bolt", "screw", "bearing", "coupling",
              "pulley", "gear", "flange", "spacer", "collar", "carriage", "matrix", "board",
              "shield", "breakout", "socket", "plug", "tool", "jig", "set", "assembly", "frame", "array", "network"}


def name_fits(query: str, part: Any) -> bool:
    """Every size or designation of the question is in the part's name, tags or designation, and the name names
    no other part than the question does."""
    tokens = size_tokens(query)
    if not tokens:
        return False
    asked = {w.rstrip("s") for w in re.findall(r"[a-z]+", query.lower())}
    if any(w in OTHER_PART and w.rstrip("s") not in asked for w in re.findall(r"[a-z]+", part.name.lower())):
        return False
    props = part.properties or {}
    text = _norm(" ".join([part.name, " ".join(part.tags or []),
                           " ".join(str(props[k]) for k in ("designation", "package", "size", "kicad_model") if k in props)]))
    text = re.sub(r"\d+\s?metric\b", " ", text)       # '0603 metric' is the 0201 imperial size
    return all(_has_token(t, text) for t in tokens)


# ---- 5. the same part from two sources ------------------------------------------------------------------------
_SAME_KEYS = ("thread", "length_mm", "pitch_mm", "dn", "pn", "nps", "pressure_class", "module", "teeth",
              "inner_diameter_mm", "outer_diameter_mm", "width_mm", "bore_mm", "shaft_diameter_mm", "seal",
              "property_class", "property_classes", "size", "profile_size", "chord_thickness_mm", "height_mm")


def _identity(part: Any) -> tuple | None:
    props = part.properties or {}
    values = tuple((k, _fmt(props[k]) if not isinstance(props[k], list) else ",".join(map(str, props[k])))
                   for k in _SAME_KEYS if props.get(k) not in (None, "", []))
    if len(values) < 2:                                # too little stated to call two parts the same
        return None
    return (part.category_path, values)


def drop_duplicates(judged: list[Any]) -> list[Any]:
    """The same standard part (same kind, same stated sizes, about the same outer size) once: the company's own
    model before a general one, otherwise the one ranked first."""
    kept: list[Any] = []
    for j in judged:
        part = j.hit.part
        ident = _identity(part)
        twin = next((k for k in kept if ident and _identity(k.hit.part) == ident and _similar(k.hit.part, part)), None)
        if twin is None:
            kept.append(j)
        elif part.company_id and not twin.hit.part.company_id:
            kept[kept.index(twin)] = j
    return kept


def _similar(a: Any, b: Any) -> bool:
    if not a.bbox_mm or not b.bbox_mm:
        return True
    return all(abs(x - y) <= 0.05 * max(x, y, 1.0) for x, y in zip(sorted(a.bbox_mm), sorted(b.bbox_mm)))


# ---- 6. gear pairs ----------------------------------------------------------------------------------------
_RATIO = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s?(?::|to)\s?1(?![\d.])|\bratio\s?(?:of\s)?(?:i\s?=\s?)?(\d{1,2}(?:\.\d+)?)\b|"
                    r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s?x\s(?:reduction|ratio)\b")
_CENTRE = re.compile(r"\bcent(?:re|er)\s?distance\s?(?:of\s|a\s?=\s?)?(\d{1,4}(?:\.\d+)?)\s?(?:mm)?")
MIN_TEETH = 17                                         # fewer teeth undercut at 20° without profile shift


def gear_pair_request(query: str) -> dict[str, Any] | None:
    q = query.lower()
    if not re.search(r"\bgears?\b|\bpinion\b", q):
        return None
    m = _RATIO.search(q)
    if not m or not (re.search(r"\b(?:pair|set|couple|mesh|meshing|reduction|ratio|transmission)\b", q) or ":" in q):
        return None
    ratio = float(next(g for g in m.groups() if g))
    if ratio < 1:
        ratio = 1 / ratio
    if ratio <= 1 or ratio > 20:
        return None
    req: dict[str, Any] = {"ratio": ratio, "type": "helical" if "helical" in q else "spur"}
    c = _CENTRE.search(q)
    if c:
        req["centre_distance_mm"] = float(c.group(1))
    module = parse_specs(_RATIO.sub(" ", _CENTRE.sub(" ", q))).get("module")
    if module is not None:
        req["module"] = module
    return req


def _module_ok(want: Any, have: float) -> bool:
    if isinstance(want, dict):
        return want.get("min", 0) - 1e-6 <= have <= want.get("max", 1e9) + 1e-6
    return abs(float(want) - have) < 1e-6


def gear_pairs(gears: list[Any], req: dict[str, Any]) -> list[tuple[Any, Any, float]]:
    """(pinion hit, wheel hit, centre distance) of existing gears that mesh at the asked ratio, best first."""
    by_module: dict[tuple[float, Any], dict[int, Any]] = {}
    for h in gears:
        p = h.part.properties or {}
        try:
            m, z = float(p["module"]), int(p["teeth"])
        except (KeyError, TypeError, ValueError):
            continue
        if "module" in req and not _module_ok(req["module"], m):
            continue
        by_module.setdefault((m, p.get("pressure_angle_deg", 20)), {}).setdefault(z, h)
    pairs = []
    for (m, _angle), teeth in by_module.items():
        for z1, pinion in teeth.items():
            z2 = req["ratio"] * z1
            if abs(z2 - round(z2)) > 1e-6 or round(z2) not in teeth or round(z2) == z1:
                continue
            a = m * (z1 + round(z2)) / 2
            if "centre_distance_mm" in req and abs(a - req["centre_distance_mm"]) > 0.05:
                continue
            pairs.append((pinion, teeth[round(z2)], a))
    # a pinion that does not undercut first, then the usual 18-25 teeth, then a common module (around 1.5)
    pairs.sort(key=lambda p: (int(p[0].part.properties["teeth"]) < MIN_TEETH,
                              abs(int(p[0].part.properties["teeth"]) - 20),
                              abs(math.log(float(p[0].part.properties["module"]) / 1.5))))
    # one pair per module first: m1, m1.5 and m2 say more than three m1 pairs
    seen: set[float] = set()
    first = [p for p in pairs if not (float(p[0].part.properties["module"]) in seen
                                      or seen.add(float(p[0].part.properties["module"])))]
    return first + [p for p in pairs if p not in first]
