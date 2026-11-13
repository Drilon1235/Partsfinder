"""AI layer: Claude understands the question, the search engine searches, Claude judges.

Steps per question:
1. Question -> requirements: Claude turns "small green outdoor chair" into a search text
   and (only where the user really requires it) hard filters such as category or dimensions.
2. Search: the search engine (search.py) fetches candidates. If there are too few, the filters
   are relaxed step by step so Claude can also show near matches.
3. Judge: Claude looks at the candidates and says per part whether it fits, nearly fits
   or does not fit, with short reasons. Nothing usable? Then status "none".

Safety: Claude only sees candidates that the search engine has already filtered by company.
An id that Claude invents itself is ignored.
Cost: every request is counted; above the cap (PARTSFINDER_MAX_SPEND_USD) it stops.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .search import (MIN_WORD_COVERAGE, STOPWORDS, UNIT_WORDS, SearchEngine, SearchFilters, SearchHit,
                     _part_tokens, _query_words, _stem, filters_as_dict, looks_relevant, matched_query_words, merge_filters)
from .specs import (CONFIRM, KEY_SPECS, SPEC_LABELS, _prop, format_value, kind_of, kind_words, missing_defining,
                    parse_preferences, parse_specs, query_form, several_parts, split_preferences,
                    ATTRIBUTE_WORDS)
from .taxonomy import Taxonomy, TaxonomyError

# Price per million tokens (input, output) - see platform.claude.com/docs/en/about-claude/pricing
PRICES = {
    "haiku": (0.10, 0.50),
    "sonnet": (2.0, 10.0),
    "opus": (4.0, 20.0),
}
MAX_CANDIDATES = 15


class AIError(RuntimeError):
    """Claude could not be used (key, credit, network, cap)."""


class BudgetExceeded(AIError):
    pass


@dataclass
class Usage:
    model: str
    limit_usd: float | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = next((p for k, p in PRICES.items() if k in self.model), PRICES["sonnet"])
        return (self.input_tokens * price_in + self.cache_read_tokens * price_in * 0.1
                + self.output_tokens * price_out) / 1_000_000

    def add(self, resp: Any) -> None:
        u = getattr(resp, "usage", None)
        self.calls += 1
        if u is not None:
            self.input_tokens += int(getattr(u, "input_tokens", 0) or 0) + \
                int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            self.output_tokens += int(getattr(u, "output_tokens", 0) or 0)
            self.cache_read_tokens += int(getattr(u, "cache_read_input_tokens", 0) or 0)

    def check(self) -> None:
        if self.limit_usd is not None and self.cost_usd >= self.limit_usd:
            raise BudgetExceeded(
                f"Cost cap reached (${self.cost_usd:.3f} of ${self.limit_usd:.2f}). "
                "Raise PARTSFINDER_MAX_SPEND_USD in backend/.env to continue.")

    def summary(self) -> str:
        tokens = (f"{self.calls} Claude requests, {self.input_tokens + self.cache_read_tokens} tokens in, "
                  f"{self.output_tokens} out")
        return f"{tokens}, estimated cost ${self.cost_usd:.4f} ({self.model})"


@dataclass
class Judged:
    hit: SearchHit
    verdict: str                       # "fits" or "close"
    match_reasons: list[str] = field(default_factory=list)
    mismatch_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        p = self.hit.part
        return {
            "id": p.id,
            "library": p.library,
            "kind": p.kind,
            "name": p.name,
            "description": p.description,
            "category_path": p.category_path,
            "sectors": p.sectors,
            "material": p.material,
            "color": p.color,
            "dims_mm": list(p.bbox_mm) if p.bbox_mm else None,
            "volume_mm3": p.volume_mm3,
            "standards": p.standards,
            "properties": p.properties,
            "verdict": self.verdict,
            "score": round(self.hit.score, 5),
            "match_reasons": self.match_reasons,
            "mismatch_reasons": self.mismatch_reasons,
            "spec_checks": [c.as_dict() for c in self.hit.specs.checks] if self.hit.specs else [],
            "files": [f.model_dump() for f in p.files],
            "thumbnail_path": p.thumbnail_path,
        }


@dataclass
class FindResult:
    status: str                        # "found", "partial" or "none"
    message: str
    requirements: dict[str, Any]
    results: list[Judged]
    ai_used: bool = True
    usage: Usage | None = None
    # the library's own checks settle the question (see search_without_ai): no AI needed to answer it
    decided: bool = False
    # a question for several parts ("an M8 bolt and an Arduino"): per requested part ({request, quantity}, answer)
    groups: list[tuple[dict[str, Any], "FindResult"]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "interpreted_requirements": self.requirements,
            "results": [r.as_dict() for r in self.results],
            "ai_used": self.ai_used,
        }


# ---- instructions for Claude ----------------------------------------------------------
INTERPRET_SYSTEM = """You are the search assistant of Partsfinder, a library of existing CAD parts.
Before an engineer draws something new, we search this database of existing, approved CAD models.
You translate the user's question into a search request for that database.

Rules:
- search_text: short search text in English with the key words of the question (translate from
  the user's language), extended with 2-4 synonyms or technical terms (e.g. "workshop table" ->
  "workbench workshop table steel"). Copy dimensions, thread sizes (M8x40) and standards
  (DIN 933) literally.
- category: only if it is clear what kind of part is meant. Then pick the most specific path from
  the list that you are sure about; if you doubt between types, pick the level above
  (category/subcategory). Otherwise null.
- Hard filters (sectors, material, color, kind, max_dims_mm, min_dims_mm, standards): fill them in
  ONLY if the user explicitly requires it ("must be stainless steel", "at most 50 cm wide",
  "according to DIN 933"). A colour or sector that is simply mentioned in the question is usually
  a preference: put it in nice_to_have, not as a filter. Hard filters exclude parts completely.
- properties: technical values that the user explicitly mentions and that belong to a property from
  the "Available properties" list at the bottom (e.g. thread "M8", inner_diameter_mm 8,
  length_mm {{"min": 40, "max": 60}}). Use ONLY keys from that list, numbers in the unit of the key
  (mm), text as in the list. If in doubt, leave it out; a wrong filter excludes good parts. If
  nothing is found, we drop the filter automatically.
- Dimensions always in millimetres (50 cm = 500).
- must_have / nice_to_have: short phrases in plain language, used when judging. Only what the user
  says or clearly means; do not invent extra wishes (no material, standard or colour if the user
  does not mention it).

{taxonomy}"""

JUDGE_SYSTEM = """You judge candidate parts from Partsfinder, a database of existing CAD models.
An engineer wants to reuse an existing model instead of drawing from scratch, so be
honest and precise: a wrong suggestion costs more time than no suggestion.

Per candidate:
- "fits": meets the question and the must_have requirements; can be reused as is.
- "close": same kind of part for the same purpose, but it deviates (other size, colour, material,
  design); can serve as a starting point to modify. State precisely what deviates in
  mismatch_reasons.
- "no_fit": other kind of part, clearly unsuitable, or a generic part meant for something else
  (e.g. a plain angle bracket when someone asks for a greenhouse bracket for a growing gutter):
  adapting that is as much work as drawing new.

Always check dimensions, thread sizes (M8), bearing numbers and standards against the candidate's
own data (name, properties, dimensions). Every candidate has "query_words_matched": the words from
the question that literally occur in that part; a candidate with the requested size in there really
has that size. Every candidate also has "spec_checks": the technical requirements read from the
question (thread, designation, standard, property class, bore, module, DN, ...) checked against the
part: status "match", "mismatch" (value of the part differs) or "unknown" (the part does not state it).
A "mismatch" on thread, designation, frame size, bore, module, teeth, DN or profile size means a
different part: never "fits". Engineers need exact parts; "unknown" on a requirement the user gave
explicitly means "close" at best, and say what is not specified. In mismatch_reasons only mention
deviations from what the user asked, not wishes the user did not mention. A value the user did not give
(length, class, model, version, colour) is open: every value fits it, so it is never a reason for "close"
("an M8 bolt" is met by an M8 bolt of any length, "an Arduino" by every Arduino board).

Answer via the tool:
- results: only candidates with "fits" or "close", best first, at most {limit}. Use only ids from
  the list; invent nothing.
- match_reasons / mismatch_reasons: short English phrases with concrete properties (dimensions,
  material, standard, sector, colour). At most 4 per list. For a match, state the value you
  checked (e.g. "inner diameter 8 mm") and for a deviation the difference in numbers (requested
  versus present, e.g. "length 70 mm instead of 60 mm"); use only values from the data.
- status: "found" if there is at least one "fits", "partial" if there are only "close" ones,
  "none" if nothing is usable (then the engineer has to draw new).
- message: one or two sentences for the user, e.g. "Found 2 matching garden chairs." or
  "No existing model found.\""""

INTERPRET_TOOL = {
    "name": "search_request",
    "description": "Record what the user is looking for: search text, optional hard filters and requirements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "search_text": {"type": "string"},
            "category": {"type": ["string", "null"]},
            "sectors": {"type": "array", "items": {"type": "string"}},
            "material": {"type": ["string", "null"]},
            "color": {"type": ["string", "null"]},
            "standards": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": ["string", "null"], "enum": ["part", "assembly", None]},
            "max_dims_mm": {"type": ["array", "null"], "items": {"type": "number"}},
            "min_dims_mm": {"type": ["array", "null"], "items": {"type": "number"}},
            "properties": {"type": "object",
                           "description": "Technical properties: key -> value or {min, max}"},
            "must_have": {"type": "array", "items": {"type": "string"}},
            "nice_to_have": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["search_text"],
    },
}

JUDGE_TOOL = {
    "name": "judgement",
    "description": "Give the judgement on the candidates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["found", "partial", "none"]},
            "message": {"type": "string"},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "verdict": {"type": "string", "enum": ["fits", "close", "no_fit"]},
                        "match_reasons": {"type": "array", "items": {"type": "string"}},
                        "mismatch_reasons": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "verdict"],
                },
            },
        },
        "required": ["status", "message", "results"],
    },
}


IMAGE_SYSTEM = """You identify a mechanical part from a photo, render or drawing, so that it can be
looked up in a library of existing CAD models (machine parts, fasteners, bearings, drive parts,
profiles, pneumatics, motors, fittings). The user may add a note with extra requirements.

Rules:
- Describe only what you can see. Name the part the way a mechanical engineer would (e.g. "socket
  head cap screw", "deep groove ball bearing", "GT2 timing pulley", "T-slot aluminium profile").
- Never guess exact dimensions from a photo: a size is only known when the note gives it, when it is
  printed on the part (e.g. "6204-2RS" on a bearing seal, "M8" on a screw head) or when a clear scale
  reference is visible. Put such readable markings in markings.
- search_query: an English search text for the library in engineering terms: part type, design
  features and the sizes or designations that are certain (from markings or the note). No guessed
  sizes. Include the note's requirements.
- is_mechanical_part: false if the image does not show a technical part (a person, a landscape, a
  screenshot of text, ...). Then search_query is empty.
- confidence: high only if the part type is unambiguous."""

IMAGE_TOOL = {
    "name": "identify_part",
    "description": "Record which part the image shows and how to search for it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_mechanical_part": {"type": "boolean"},
            "part_type": {"type": "string"},
            "search_query": {"type": "string"},
            "visible_features": {"type": "array", "items": {"type": "string"}},
            "markings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["is_mechanical_part", "part_type", "search_query", "confidence"],
    },
}



def _dims(value: Any) -> tuple[float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(float(x) for x in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def property_hint(overview: list[dict[str, Any]], max_keys: int = 35) -> str:
    """Short list of filterable properties for the instruction to Claude."""
    rows = []
    for o in sorted(overview, key=lambda o: -o["count"])[:max_keys]:
        if o["count"] < 3:
            continue
        if o["type"] == "number":
            rows.append(f"- {o['key']}: number {o['min']:g} to {o['max']:g} ({o['count']} parts)")
        elif o["type"] == "boolean":
            rows.append(f"- {o['key']}: yes/no ({o['count']} parts)")
        else:
            vals = ", ".join(o.get("values", [])[:6])
            rows.append(f"- {o['key']}: text, e.g. {vals} ({o['count']} parts)")
    return "\n\nAvailable properties (for properties):\n" + "\n".join(rows) if rows else ""


def clean_properties(raw: Any, known: set[str]) -> dict[str, Any]:
    """Keeps only existing keys with a valid condition from what Claude returns."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, cond in raw.items():
        if key not in known:
            continue
        if isinstance(cond, bool):
            out[key] = cond
        elif isinstance(cond, (int, float)):
            out[key] = cond
        elif isinstance(cond, str) and 0 < len(cond.strip()) <= 60:
            out[key] = cond.strip()
        elif isinstance(cond, dict):
            rng = {k: float(v) for k, v in cond.items()
                   if k in ("min", "max") and isinstance(v, (int, float)) and not isinstance(v, bool)}
            if rng:
                out[key] = rng
    return out


def _candidate_line(hit: SearchHit, query: str = "") -> dict[str, Any]:
    p = hit.part
    return {
        "id": p.id,
        "query_words_matched": matched_query_words(query, p) if query else [],
        "name": p.name,
        "description": p.description[:300],
        "category": p.category_path,
        "kind": p.kind,
        "sectors": p.sectors,
        "material": p.material,
        "color": p.color,
        "dimensions_mm": [round(d, 1) for d in p.bbox_mm] if p.bbox_mm else None,
        "standards": p.standards,
        "properties": {k: v for k, v in p.properties.items() if k not in ("needs_review", "ai_metadata")},
        "library": "own company" if p.company_id else "general",
        "needs_review": "needs-review" in p.tags,
        # deterministic check of the specs in the question against this part's data
        "spec_checks": [c.as_dict() for c in hit.specs.checks] if hit.specs else [],
    }


class PartFinder:
    def __init__(self, engine: SearchEngine, taxonomy: Taxonomy, model: str,
                 api_key: str | None = None, client: Any = None, max_spend_usd: float | None = None):
        if client is None:
            if not api_key:
                raise AIError(NO_KEY)
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60)
        self.client = client
        self.engine = engine
        self.taxonomy = taxonomy
        self.model = model
        self.usage = Usage(model=model, limit_usd=max_spend_usd)
        self._interpret_system = INTERPRET_SYSTEM.format(taxonomy=taxonomy.as_prompt_text())

    def _property_overview(self) -> list[dict[str, Any]]:
        """Properties of the general library; without it (other engine) simply no list."""
        getter = getattr(self.engine, "general_properties", None)
        try:
            return list(getter()) if getter else []
        except Exception:                      # a broken list must never stop searching
            return []

    # ---- calling Claude -------------------------------------------------------------
    def _call(self, system: str, tool: dict[str, Any], content: str | list[dict[str, Any]],
              max_tokens: int) -> dict[str, Any]:
        self.usage.check()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # noqa: BLE001 - translate the error message
            raise AIError(_explain(exc)) from exc
        self.usage.add(resp)
        for block in getattr(resp, "content", []):
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool["name"]:
                data = block.input
                return data if isinstance(data, dict) else json.loads(data)
        raise AIError("Claude did not return a structured answer")

    # ---- step 1: question -> requirements ---------------------------------------------------
    def interpret(self, query: str) -> tuple[str, SearchFilters, dict[str, Any]]:
        overview = self._property_overview()
        raw = self._call(self._interpret_system + property_hint(overview), INTERPRET_TOOL,
                         f"User question: {query}", 600)
        req: dict[str, Any] = {"search_text": str(raw.get("search_text") or query).strip() or query}
        category = raw.get("category")
        if isinstance(category, str) and category.strip():
            try:
                req["category"] = self.taxonomy.validate_category(category)
            except TaxonomyError:
                try:  # the parent level often exists
                    req["category"] = self.taxonomy.validate_category("/".join(category.strip("/").split("/")[:2]))
                except TaxonomyError:
                    pass
        sectors = [s.strip().lower() for s in raw.get("sectors") or [] if isinstance(s, str)]
        req["sectors"] = [s for s in sectors if s in self.taxonomy.sectors]
        for key in ("material", "color"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                req[key] = raw[key].strip()
        req["standards"] = [str(s) for s in raw.get("standards") or []]
        if raw.get("kind") in ("part", "assembly"):
            req["kind"] = raw["kind"]
        for key in ("max_dims_mm", "min_dims_mm"):
            d = _dims(raw.get(key))
            if d:
                req[key] = list(d)
        props = clean_properties(raw.get("properties"), {o["key"] for o in overview})
        if props:
            req["properties"] = props
        specs = parse_specs(query)
        if specs:
            req["specs"] = specs
        if prefs := parse_preferences(query):
            req["preferences"] = prefs
        req["must_have"] = [str(x) for x in raw.get("must_have") or []][:6]
        req["nice_to_have"] = [str(x) for x in raw.get("nice_to_have") or []][:6]
        filters = SearchFilters(
            category=req.get("category"), sectors=req["sectors"], material=req.get("material"),
            color=req.get("color"), standards=req["standards"], kind=req.get("kind"),
            max_dims_mm=_dims(req.get("max_dims_mm")), min_dims_mm=_dims(req.get("min_dims_mm")),
            properties=props,
        )
        return req["search_text"], filters, req

    # ---- step 2: search (with relaxing) -----------------------------------------
    def gather(self, text: str, company_id: str | None, filters: SearchFilters,
               fixed: SearchFilters | None = None) -> tuple[list[SearchHit], list[str]]:
        """Search, and relax if needed. 'fixed' (hard requirements of the caller) always applies."""
        steps = [
            ("all requirements", filters),
            ("without sector/material/colour/kind", SearchFilters(
                category=filters.category, standards=filters.standards,
                max_dims_mm=filters.max_dims_mm, min_dims_mm=filters.min_dims_mm)),
            ("dimensions only", SearchFilters(max_dims_mm=filters.max_dims_mm, min_dims_mm=filters.min_dims_mm)),
            ("no filters", SearchFilters()),
        ]
        hits: dict[str, SearchHit] = {}
        used: list[str] = []
        seen_filters: list[SearchFilters] = []
        for label, f in steps:
            f = merge_filters(f, fixed)
            if f in seen_filters:
                continue
            seen_filters.append(f)
            new = self.engine.search(text, company_id, f, limit=MAX_CANDIDATES)
            if new:
                used.append(label)
            for h in new:
                hits.setdefault(h.part.id, h)
            if len(hits) >= 6:
                break
        ordered = sorted(hits.values(), key=lambda h: h.score, reverse=True)[:MAX_CANDIDATES]
        return ordered, used

    # ---- step 3: judge ---------------------------------------------------------
    def judge(self, query: str, req: dict[str, Any], hits: list[SearchHit], limit: int) -> tuple[str, str, list[Judged]]:
        if not hits:
            return "none", "No existing model found.", []
        payload = {
            "question": query,
            "requirements": {k: v for k, v in req.items() if v not in (None, [], "")},
            "candidates": [_candidate_line(h, query) for h in hits],
        }
        raw = self._call(JUDGE_SYSTEM.format(limit=limit), JUDGE_TOOL,
                         json.dumps(payload, ensure_ascii=False), 1500)
        by_id = {h.part.id: h for h in hits}
        judged: list[Judged] = []
        for item in raw.get("results") or []:
            if not isinstance(item, dict):
                continue
            hit = by_id.get(str(item.get("id")))
            verdict = item.get("verdict")
            if hit is None or verdict not in ("fits", "close") or any(j.hit is hit for j in judged):
                continue   # invented id, rejected or duplicate
            match = [str(x) for x in item.get("match_reasons") or []][:4]
            mismatch = [str(x) for x in item.get("mismatch_reasons") or []][:4]
            verdict, mismatch = drop_unasked(verdict, mismatch)
            verdict, match, mismatch = enforce_specs(hit, verdict, match, mismatch)
            verdict, mismatch = enforce_material(query, hit, verdict, mismatch)
            judged.append(Judged(hit, verdict, match, mismatch))
        judged.sort(key=lambda j: j.verdict != "fits")          # stable: Claude's order within a verdict
        judged = judged[:limit]
        # status follows from the real results, not blindly from what Claude says
        status = "found" if any(j.verdict == "fits" for j in judged) else ("partial" if judged else "none")
        message = str(raw.get("message") or "").strip()
        if status == "none" or not message or raw.get("status") != status:
            message = _default_message(status, judged)
        return status, message, judged

    # ---- search by image ------------------------------------------------------------------
    def identify_image(self, image_b64: str, media_type: str, note: str = "") -> dict[str, Any]:
        """Claude looks at the image and returns what part it is and a search text."""
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": f"Note from the user: {note.strip()}" if note.strip()
             else "The user added no note."},
        ]
        raw = self._call(IMAGE_SYSTEM, IMAGE_TOOL, content, 500)
        conf = raw.get("confidence") if raw.get("confidence") in ("low", "medium", "high") else "low"
        return {
            "is_mechanical_part": bool(raw.get("is_mechanical_part")),
            "part_type": str(raw.get("part_type") or "").strip(),
            "search_query": str(raw.get("search_query") or "").strip()[:300],
            "visible_features": [str(x) for x in raw.get("visible_features") or []][:6],
            "markings": [str(x) for x in raw.get("markings") or []][:6],
            "confidence": conf,
        }

    # ---- all together --------------------------------------------------------------
    def find(self, query: str, company_id: str | None = None, limit: int = 5,
             fixed_filters: SearchFilters | None = None) -> FindResult:
        """fixed_filters: hard requirements of the caller (e.g. a maximum size); never relaxed."""
        text, filters, req = self.interpret(query)
        if fixed_filters is not None:
            filters = merge_filters(filters, fixed_filters)
            req["fixed_filters"] = filters_as_dict(fixed_filters)
        hits, steps = self.gather(text, company_id, filters, fixed_filters)
        req["search_steps"] = steps
        hits = only_named(query, hits)
        need = need_for(query, req.get("specs") or {}, hits)
        if need:
            req["need"] = need
        status, message, judged = self.judge(query, req, hits, limit)
        return FindResult(status, message, req, judged, True, self.usage)


# ---- which AI to use? -----------------------------------------------------------------
# Bring your own key: every user runs the AI on their own Anthropic API key (Settings in the app, or
# ANTHROPIC_API_KEY in backend/.env). Without a key the library answers with its own rules only.
NO_KEY = "No API key: add your own Anthropic API key in Settings (or ANTHROPIC_API_KEY in backend/.env)"
BACKENDS = {"auto": "auto", "api": "api", "off": "off", "none": "off"}


def make_client(settings: Any, client: Any = None) -> Any:
    """The Anthropic client for PARTSFINDER_AI_BACKEND (auto or api: with the key; off: no AI)."""
    choice = BACKENDS.get(settings.ai_backend)
    if choice is None:
        raise AIError(f"Unknown PARTSFINDER_AI_BACKEND '{settings.ai_backend}' (choose auto, api or off)")
    if choice == "off":
        raise AIError("AI switched off (PARTSFINDER_AI_BACKEND=off)")
    if client is not None:
        return client
    if not settings.anthropic_api_key:
        raise AIError(NO_KEY)
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=60)


def make_finder(engine: SearchEngine, taxonomy: Taxonomy, settings: Any, model: str | None = None,
                client: Any = None) -> PartFinder:
    return PartFinder(engine, taxonomy, model or settings.claude_model, client=make_client(settings, client),
                      max_spend_usd=settings.max_spend_usd)


def ai_label(finder: PartFinder | None) -> str:
    return "off" if finder is None else f"{finder.model} on your API key"


def _default_message(status: str, judged: list[Judged]) -> str:
    if status == "found":
        n = sum(j.verdict == "fits" for j in judged)
        return f"Found {n} matching model{'s' if n > 1 else ''}."
    if status == "partial":
        return "No exact match, but there are models that can serve as a starting point."
    return "No existing model found."


# "the Arduino model was not specified", "length and class were not specified", "you did not specify the
# length": about the request, not the part. A value the engineer left open is no deviation.
# Only phrases about the request: "the part does not state a colour" is about the part and stays a deviation.
UNASKED = re.compile(r"\b(?:was|were) not (?:specified|requested|asked for)\b|"
                     r"\b(?:you|user|engineer|request|question|query) (?:did not|didn't|does not|doesn't) "
                     r"(?:specify|give|ask|mention|request|state)\b|"
                     r"\bnot (?:specified|given|mentioned|stated) in the (?:request|question|query)\b", re.IGNORECASE)


def drop_unasked(verdict: str, mismatch: list[str]) -> tuple[str, list[str]]:
    """A "close" whose only deviations are things the engineer did not ask is a fit: every value meets an open
    requirement. The library's own checks (enforce_specs, enforce_material) run after this and still win."""
    unasked = [m for m in mismatch if UNASKED.search(m) and "instead of" not in m.lower()]
    if not unasked:
        return verdict, mismatch
    kept = [m for m in mismatch if m not in unasked]
    return ("fits" if verdict == "close" and not kept else verdict), kept


def enforce_specs(hit: SearchHit, verdict: str, match: list[str],
                  mismatch: list[str]) -> tuple[str, list[str], list[str]]:
    """Deterministic guard on top of any verdict: a part that violates a key spec of the question
    (other thread, other bearing, other DN) is never "fits", and every deviation is stated in numbers."""
    s = hit.specs
    if s is None or not s.checks:
        return verdict, match, mismatch
    low = " ".join(mismatch).lower()
    for c in s.mismatched + [c for c in s.unknown if c.key in CONFIRM]:
        sentence = c.sentence()
        if c.label.lower() not in low and sentence not in mismatch:
            mismatch = [*mismatch, sentence]
    # an unconfirmed material or exclusion is not a fit either: "stainless" on a part that does not say so
    if verdict == "fits" and (s.mismatched or any(c.key in CONFIRM for c in s.unknown)):
        verdict = "close"
    if not match:
        match = [c.sentence() for c in s.matched][:4]
    return verdict, match[:5], mismatch[:5]


def enforce_material(query: str, hit: SearchHit, verdict: str, mismatch: list[str]) -> tuple[str, list[str]]:
    """A material the question asks for ("brass nut", "aluminium bracket") is a hard requirement, also when the
    AI judges: a part whose stated material is something else, or that states none, is never "fits"."""
    lacking = [w for w in missing_words(query, hit.part) if w in MATERIAL_WORDS]
    if not lacking:
        return verdict, mismatch
    notes = [f"{w}: not stated" for w in lacking if not any(w in m.lower() for m in mismatch)]
    return ("close" if verdict == "fits" else verdict), (mismatch + notes)[:5]


def _distance(summary: Any) -> float:
    """How far the deviating numeric specs are off (relative), for "nearest size" ordering."""
    total = 0.0
    for c in summary.mismatched:
        try:
            a = float(re.match(r"\d+(?:\.\d+)?", str(c.requested)).group(0))
            b = float(re.match(r"\d+(?:\.\d+)?", str(c.found if not isinstance(c.found, list) else c.found[0])).group(0))
            total += abs(a - b) / max(abs(a), 1.0)
        except (AttributeError, TypeError, ValueError):
            total += 1.0
    return total


# words that only phrase a spec ("at least 8 Nm", "bore 50", "8 mm shaft"): the spec checks cover them
SPEC_WORDS = {"least", "most", "max", "maximum", "min", "minimum", "bore", "stroke", "shaft", "teeth", "tooth",
              "module", "mod", "length", "long", "diameter", "width", "wide", "size", "slot", "pitch", "thread",
              "threaded", "class", "property", "grade", "exactly", "only", "strictly", "precisely", "type", "series",
              "rated", "holding", "torque", "nm", "dn", "pn", "nema", "seal", "sealed"}


# what a part is made of: when the part states its material, only that (and its name) counts, never a
# description such as "for aluminium profiles" or "with brass insert"
MATERIAL_WORDS = {"titanium", "brass", "bronze", "copper", "aluminium", "aluminum", "steel", "stainless", "plastic",
                  "nylon", "polyamide", "rubber", "wooden", "wood", "carbon"}
# the same word spelled another way
WORD_FORMS = {"aluminum": ("aluminium", "aluminum"), "aluminium": ("aluminium", "aluminum"),
              "galvanised": ("galvanised", "galvanized"), "galvanized": ("galvanised", "galvanized"),
              "anodised": ("anodised", "anodized"), "anodized": ("anodised", "anodized"),
              "grey": ("grey", "gray"), "gray": ("grey", "gray"), "colored": ("colored", "coloured"),
              "coloured": ("colored", "coloured"), "wooden": ("wooden", "wood"), "wood": ("wooden", "wood"),
              "chrome": ("chrome", "chromed"), "chromed": ("chrome", "chromed"),
              "plastic": ("plastic", "nylon", "polyamide", "pom", "abs", "pvc", "acetal", "ptfe", "pa6", "pa66"),
              "stainless": ("stainless", "inox", "a2", "a4")}


def _has_word(word: str, text: str) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z])", text) for form in WORD_FORMS.get(word, (word,)))


def missing_words(query: str, part: Any) -> list[str]:
    """Plain words of the question that this part does not contain ("green", "galvanized", "nut" for a bolt).
    Numbers, units and specs are left out: those are checked as specs. Name, description, tags, material
    and properties count; a material word only counts in the stated material (or the name)."""
    words = [w for w in _query_words(kind_words(query))
             if not re.search(r"\d", w) and w not in UNIT_WORDS and w not in SPEC_WORDS]
    found = set(matched_query_words(" ".join(w for w in words if w not in ATTRIBUTE_WORDS), part))
    # colour, finish and material words only as a whole word: "green" is not in "greenhouse"
    text = " ".join([part.name, part.description, part.material or "", part.color or "", " ".join(part.tags),
                     " ".join(str(v) for v in part.properties.values())]).lower()
    material_props = " ".join(str(v) for k, v in part.properties.items() if "material" in k.lower())
    made_of = (" ".join([part.material, part.name, material_props]) if part.material else text).lower()
    found |= {w for w in words if w in ATTRIBUTE_WORDS and _has_word(w, made_of if w in MATERIAL_WORDS else text)}
    return [w for w in words if w not in found]


def names_part(word: str, part: Any) -> bool:
    """Is the part this thing: the word (whole word, singular or plural) in its name or its category, not
    somewhere in its description ("case" is not in "casement"; a bearing "with two metal shields" is no shield)."""
    text = " ".join([part.name, part.category_path, *(part.standards or []), *(part.tags or [])]).lower()
    return _stem(word) in {_stem(t) for t in re.findall(r"[a-z0-9]+", text)}


# words a question can start with that only ask: "make me a", "could you show us an", "I need the", "please find"
REQUEST_WORDS = {"make", "me", "give", "get", "show", "draw", "create", "design", "provide", "send", "build",
                 "find", "search", "looking", "for", "could", "would", "can", "you", "please", "i", "we", "us",
                 "need", "want", "like", "id", "im", "d", "lets", "let", "s", "do", "have", "got", "a", "an",
                 "the", "some", "any", "one", "new", "model", "of"}


def head_noun(query: str) -> str | None:
    """The word that names the part in a short noun phrase ("cable gland" -> "gland", "servo motor 400 W" ->
    "motor"). None for a sentence ("something to hang a shelf on"): there the last word says nothing."""
    raw = re.findall(r"[a-z0-9]+", kind_words(query))
    # the request around it says nothing about the part: "make me a battery", "can you give me a hinge"
    while raw and raw[0] in REQUEST_WORDS:
        raw = raw[1:]
    if not raw or len(raw) > 6 or any(w in STOPWORDS for w in raw):
        return None
    # a name written with a capital after the first word is a product line, not the part ("dining table Nora")
    names = {w.lower() for w in re.findall(r"[A-Za-z]{2,}", query or "")[1:] if w[0].isupper()} - {raw[0]}
    words = [w for w in raw if not re.search(r"\d", w) and w not in UNIT_WORDS and w not in SPEC_WORDS
             and w not in ATTRIBUTE_WORDS and w not in names]
    return words[-1] if words and len(words[-1]) >= 3 else None


def only_named(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """For a part the code knows no kind of ("make me a battery"): only the parts that name it, when there are
    any. A motor is no battery, also not for the AI to weigh."""
    head = None if kind_of(query) or several_parts(query) else head_noun(query)
    named = [h for h in hits if names_part(head, h.part)] if head else []
    return named or hits


def same_kind(query: str, part: Any) -> bool:
    """Is this part the kind of part the question names (a bolt for "bolt", not a button)? True when the
    question names no kind we know."""
    kind = kind_of(query)
    # the part's name or category names that kind ("Shaft collar ... with set screw" is a collar, not a screw)
    return kind is None or bool(re.search(kind[0], f"{part.name} {part.category_path.replace('-', ' ')}".lower()))


def judge_by_specs(hits: list[SearchHit], limit: int, query: str = "") -> list[Judged]:
    """Without AI: judge on the deterministic spec checks.
    fits  = every requirement of the question is met by the part's own data
    close = the defining specs match (or are not stated) but something else deviates
    Parts that violate a defining spec are only shown if nothing better exists."""
    fits, close, other = [], [], []
    for h in hits:
        s = h.specs
        match = [c.sentence() for c in s.matched][:4]
        mismatch = [c.sentence() for c in s.mismatched + s.unknown][:4]
        # the specs alone are not enough: the part must also be the kind of part asked for
        # ("planetary gearbox NEMA 23" is not a NEMA 23 stepper motor)
        relevant = h.word_coverage is None or h.word_coverage >= MIN_WORD_COVERAGE
        if not relevant:
            other.append(Judged(h, "close", match, mismatch))
        elif s.all_match:
            # every spec is met; "fits" also needs every other word of the question in the part:
            # "green bolt" or "galvanized bolt" is not settled by thread and length alone
            missing = missing_words(query, h.part) if query else []
            if missing:
                close.append(Judged(h, "close", match, [f"{w}: not stated" for w in missing]))
            else:
                fits.append(Judged(h, "fits", match, []))
        elif s.matched and not s.key_mismatch:
            close.append(Judged(h, "close", match, mismatch))
        else:
            other.append(Judged(h, "close", match, mismatch))
    # all requirements met: the one whose words fit the question best first ("carriage" vs "rail")
    fits.sort(key=lambda j: -round(j.hit.word_coverage or 0.0, 2))
    ordered = fits + close
    if not ordered:
        # no part has the defining spec: show at most two nearest of the right kind, marked as deviating
        # prefer parts that state their (deviating) value over parts that state nothing
        near = [j for j in other if j.hit.word_coverage is None or j.hit.word_coverage >= MIN_WORD_COVERAGE]
        near.sort(key=lambda j: (len([c for c in j.hit.specs.unknown if c.key in KEY_SPECS]),
                                 _distance(j.hit.specs)))
        ordered = near[:2]
    return ordered[:limit]


NEED_CHOICES = 6     # at most this many values offered per open spec


def need_for(query: str, specs: dict[str, Any], hits: list[SearchHit]) -> list[dict[str, Any]]:
    """The defining values the question leaves open ("a bolt": thread, length), each with the values that
    really exist among the found parts, most common first, then in size order. The caller asks the user
    (or fills them in from the drawing); the library itself never guesses them."""
    kind = kind_of(query)
    if not kind:
        return []
    # only parts of the kind asked for offer values (a bolt's "designation" is no bearing number)
    same_kind_hits = [h for h in hits if same_kind(query, h.part)]
    size = lambda c: float(m.group(0)) if (m := re.search(r"\d+(?:\.\d+)?", c)) else 0.0   # noqa: E731
    out = []
    for group in kind[1]:
        if any(k in specs for k in group):
            continue
        for key in group:                              # bearing: its number, else its bore
            counts: dict[str, int] = {}
            for h in same_kind_hits:
                value = _prop(h.part, key)
                for v in value if isinstance(value, list) else [value]:
                    if v not in (None, "", []):
                        form = query_form(key, v)
                        counts[form] = counts.get(form, 0) + 1
            if counts:
                break
        key = key if counts else group[0]
        common = sorted(counts, key=lambda c: -counts[c])[:NEED_CHOICES]
        out.append({"spec": key, "label": SPEC_LABELS.get(key, key), "choices": sorted(common, key=size)})
    return out


def search_without_ai(engine: SearchEngine, query: str, company_id: str | None, limit: int = 5,
                      reason: str = "", filters: SearchFilters | None = None) -> FindResult:
    """Fallback when Claude is not available: plain search results, marked as 'close'.
    If the question contains engineering specs (thread, bearing number, DN, ...), they are checked
    per part and parts that meet all of them are marked 'fits'.
    A word that no part of the asked kind has ("green" when no bolt is green) is said once and then left
    out: the search is done again without it, so "a green bolt" and "a red bolt" give the same bolts
    and the same choices as "a bolt", each marked with the word it lacks."""
    first = _search_without_ai(engine, query, company_id, limit, reason, filters)
    lacking = first.requirements.get("lacking")
    if not lacking:
        return first
    plain = re.sub(r"\b(?:" + "|".join(map(re.escape, lacking)) + r")\b", " ", query, flags=re.IGNORECASE)
    r = _search_without_ai(engine, " ".join(plain.split()), company_id, limit, reason, filters)
    if not r.results:
        return first
    kind = kind_of(query)
    plain_words = [w for w in _query_words(kind_words(" ".join(plain.split()))) if not re.search(r"\d", w)]
    noun = (re.search(kind[0], split_preferences(query)[0].lower()).group(0) if kind
            else (plain_words[-1] if plain_words else "part"))
    note = [f"{w}: not stated" for w in lacking]
    for j in r.results:
        j.verdict = "close"                            # it fits the rest, not the word it lacks
        j.mismatch_reasons = note + [m for m in j.mismatch_reasons if m != "not judged by AI"]
    status = "partial" if r.status == "found" else r.status
    msg = f"No {noun} in the library is stated as {' '.join(lacking)}; the closest are shown."
    rest = r.message if r.status != "found" else ""
    rest = rest.replace(NOT_JUDGED, "").strip()       # "the closest are shown" already says it
    return FindResult(status, f"{msg} {rest}".strip(), {**r.requirements, "search_text": query, "lacking": lacking},
                      r.results, ai_used=False, decided=r.decided or first.decided)


def _search_without_ai(engine: SearchEngine, query: str, company_id: str | None, limit: int,
                       reason: str, filters: SearchFilters | None) -> FindResult:
    specs = parse_specs(query)
    open_specs = missing_defining(query, specs)
    hits = engine.search(query, company_id, filters, limit=max(limit * 3, 80) if specs or open_specs else limit)
    reason_txt = f" ({reason})" if reason else ""
    req: dict[str, Any] = {"search_text": query}
    if specs:
        req["specs"] = specs
    if prefs := parse_preferences(query):
        req["preferences"] = prefs
    need = need_for(query, specs, hits) if open_specs else []
    if need:
        req["need"] = need
    kind = kind_of(query)
    kind_hits = [h for h in hits if kind and same_kind(query, h.part)]
    # a kind the code does not know ("hinge", "garden chair"): the parts with every word but colour,
    # finish or material play that role, so "a red hinge" is answered like "a hinge" too
    word_hits = kind_hits or [h for h in hits if all(w in ATTRIBUTE_WORDS for w in missing_words(query, h.part))]
    if word_hits and not several_parts(query):
        # never the word that names the kind itself ("screw" for a question answered with bolts)
        lacking = [w for w in lacking_words(query, word_hits) if not (kind and re.search(kind[0], w))]
        if lacking and all(w in ATTRIBUTE_WORDS for w in lacking):   # "green", not "planetary" or "pump"
            req["lacking"] = lacking
    head = None if kind else head_noun(query)
    if head and not several_parts(query) and not any(names_part(head, h.part) for h in hits):
        # "cable gland": cables and chain links are no gland; the word that names the part must be there
        article = "an" if head[0] in "aeiou" else "a"
        msg = f"No existing model found: no part in the library is {article} {head}."
        return FindResult("none", msg, {**req, "ai": f"not used{reason_txt}"}, [], ai_used=False,
                          decided=True)
    if specs and hits and any(h.specs for h in hits):
        judged = judge_by_specs(hits, limit, query)
        unconfirmable = _unconfirmable(specs, hits, query, judged)
        if unconfirmable:
            return FindResult("none", unconfirmable, {**req, "ai": f"not used{reason_txt}"}, [], ai_used=False,
                              decided=not several_parts(query))
        if judged and looks_relevant(hits):
            status = "found" if any(j.verdict == "fits" for j in judged) else "partial"
            n = sum(j.verdict == "fits" for j in judged)
            msg = (f"{n} model{'s' if n != 1 else ''} meet{'s' if n == 1 else ''} every requirement."
                   if status == "found" else
                   "No model meets every requirement; the closest ones are listed with their deviations.")
            # settled in code when one kind of part is asked for and a part meets every requirement
            # (or a defining value is still open: no AI can choose that for the engineer either)
            # settled in code: "fits" proven, or a kind the code knows with parts of that kind (then the
            # deviations are stated in numbers, exactly what the AI would say, in ~40 ms instead of 5-30 s)
            kind_parts = [j for j in judged if kind_of(query) and same_kind(query, j.hit.part)]
            decided = not several_parts(query) and (status == "found" or bool(kind_parts))
            if kind_parts:
                judged = kind_parts                    # a nut question shows nuts, not a bolt
            return FindResult(status, msg, {**req, "ai": f"not used{reason_txt}"}, judged, ai_used=False,
                              decided=decided)
    if not looks_relevant(hits):
        # nothing contains the words of the question: say so honestly, do not show random parts
        msg = "No existing model found: no part matches the main words of your question."
        return FindResult("none", msg, {**req, "ai": f"not used{reason_txt}"}, [], ai_used=False)
    shown = list(kind_hits)
    if need:          # asking a value: first the parts that state it (real bolts with a thread)
        shown.sort(key=lambda h: _prop(h.part, need[0]["spec"]) in (None, "", []))
    if shown:
        # parts that have every word first; the rest say which word they lack ("green: not stated")
        shown.sort(key=lambda h: bool(missing_words(query, h.part)))
        judged = [Judged(h, "close", [], [f"{w}: not stated" for w in missing_words(query, h.part)] or ["not judged by AI"])
                  for h in shown[:limit]]
    else:
        # parts with every word of the question first; the others say which word they lack
        # only parts that are the thing asked for ("case": a PC case, never a casement window)
        named = [h for h in hits if names_part(head, h.part)] if head else hits
        ranked = sorted(named, key=lambda h: len(missing_words(query, h.part)))[:limit] if head else hits[:limit]
        judged = [Judged(h, "close", [], [f"{w}: not stated" for w in missing_words(query, h.part)]
                         or ["not judged by AI"]) for h in ranked]
    if shown and need and (not reason or reason in DELIBERATE):
        msg = ""                                       # nothing missing: just ask the open value
    elif not reason or reason in DELIBERATE:
        msg = NOT_JUDGED
    else:
        msg = f"AI not available{reason_txt}; these are the best search results."
    if need:                                           # say why first, then what would narrow it down
        msg = f"{msg} {need_message(need)}".strip()
    # settled in code when the code knows the kind of part and the library has it: the engineer chooses
    # the open value, or reads which word no part has; the AI only for what the code cannot place
    return FindResult("partial", msg, req, judged, ai_used=False, decided=not several_parts(query) and bool(shown))


NOT_JUDGED = "The best search results, not judged yet: check whether they fit."


# ---- several parts in one question ---------------------------------------------------------------
# "give me 1 M8 bolt and 1 arduino" is two questions: an M8 bolt, and an Arduino. Searched as one text, the
# bolt lacks "arduino" and the Arduino lacks "M8", and neither can be judged. Each part is searched (and
# judged) on its own and the answer is grouped per requested part.
MAX_PIECES = 6
SPLIT_RE = re.compile(r"\s*(?:[,;+&]|\band\b|\bplus\b|\bas well as\b)\s*", re.IGNORECASE)
WITH_RE = re.compile(r"\s+with\s+", re.IGNORECASE)
LEAD_RE = re.compile(r"^(?:(?:please|can|could|would|will|you|give|get|find|show|make|send|search|me|us|i|we|"
                     r"i'd|id|i'm|im|need|want|like|looking|for|a|an|the|some|one|also|then)\s+)+", re.IGNORECASE)
FASTENER_RE = re.compile(r"\b(?:bolts?|screws?|nuts?|washers?|studs?|rivets?|pins?|clips?)\b")
QUANTITY_RE = re.compile(r"^(\d{1,3})\s*(x\b|×|pcs\.?|pieces?\b|of\b)?\s+(\S+)", re.IGNORECASE)


def _clean_piece(text: str) -> tuple[str, int | None]:
    """'give me 1 M8 bolt' -> ('M8 bolt', 1). A leading number is a quantity only when it says so ('4x', '4 pcs')
    or is small and not a size or designation ('608 bearing', '10 mm shaft' and '20 teeth' keep their number)."""
    t = LEAD_RE.sub("", " ".join(text.strip(" .!?").split()) + " ").strip()
    qty = None
    m = QUANTITY_RE.match(t)
    if m:
        n, unit, nxt = int(m.group(1)), m.group(2), m.group(3).lower().strip(".,")
        rest = t[m.start(3):].lower()
        # "100 M8 bolts", "250 nuts": fasteners come by the hundred; "608 bearing" and "40 profile" are designations
        many = n > 20 and bool(re.match(r"m\d", nxt) or (FASTENER_RE.search(rest) and not re.search(r"\bbearings?\b", rest)))
        if unit or ((1 <= n <= 20 or many) and nxt not in UNIT_WORDS and nxt not in SPEC_WORDS):
            qty = n
            t = LEAD_RE.sub("", t[m.start(3):] + " ").strip()
    return t, qty


def _names_a_part(text: str) -> bool:
    return bool(kind_of(text) or head_noun(text))


def split_request(query: str) -> list[dict[str, Any]]:
    """The parts a question asks for, each as its own search text with its quantity; [] for one part.
    'with' only separates where a known kind of part follows ('bolt with nut', not 'bearing with two shields');
    a piece that names no part is a requirement of the part before it ('M8x30 bolt, A4')."""
    if not several_parts(query):
        return []
    pieces: list[str] = []
    for chunk in SPLIT_RE.split(query or ""):
        bits = WITH_RE.split(chunk)
        current = bits[0]
        for nxt in bits[1:]:
            if kind_of(nxt):
                pieces.append(current)
                current = nxt
            else:
                current = f"{current} with {nxt}"
        pieces.append(current)
    out: list[dict[str, Any]] = []
    for piece in pieces:
        text, qty = _clean_piece(piece)
        if not text:
            continue
        if out and not _names_a_part(text):
            out[-1]["request"] += f", {text}"
            continue
        out.append({"request": text, "quantity": qty})
    if len(out) < 2 or not all(_names_a_part(o["request"]) for o in out):
        return []
    # one thread for the whole joint ("M8 bolt, nut and washer"): a part that needs a thread and gives none gets it
    threads = {parse_specs(o["request"]).get("thread") for o in out} - {None}
    if len(threads) == 1:
        thread = threads.pop()
        for o in out:
            kind = kind_of(o["request"])
            if kind and any("thread" in g for g in kind[1]) and "thread" not in parse_specs(o["request"]):
                o["request"] = f"{thread} {o['request']}"
    return out[:MAX_PIECES]


def _real_part(engine: SearchEngine, request: str, company_id: str | None) -> bool:
    """Is this piece a part of its own, or a word of one name ("pick and place head": "pick" is no part)? A kind the
    code knows, a name of two words or more, or one word that names a part in the library."""
    if kind_of(request):
        return True
    words = [w for w in _query_words(kind_words(request)) if not re.search(r"\d", w) and w not in UNIT_WORDS]
    if len(words) >= 2:
        return True
    head = head_noun(request)
    return bool(head) and any(names_part(head, h.part) for h in engine.search(request, company_id, limit=10))


def search_several(engine: SearchEngine, query: str, company_id: str | None, limit: int = 5, reason: str = "",
                   filters: SearchFilters | None = None, judge: Any = None) -> FindResult | None:
    """A question for several parts, answered per part; None when it asks for one part. judge(text) answers a
    part the library's own checks cannot settle (the AI), or None to keep the code's answer."""
    pieces = split_request(query)
    if not pieces or not all(_real_part(engine, p["request"], company_id) for p in pieces):
        return None
    groups: list[tuple[dict[str, Any], FindResult]] = []
    for piece in pieces:
        r = search_without_ai(engine, piece["request"], company_id, limit, reason, filters)
        if not r.decided and judge is not None:
            r = judge(piece["request"]) or r
        groups.append((piece, r))
    statuses = {r.status for _, r in groups}
    status = "found" if statuses == {"found"} else ("none" if statuses == {"none"} else "partial")
    found = sum(r.status == "found" for _, r in groups)
    names = [g["request"] for g, _ in groups]
    message = (f"{len(groups)} parts asked for ({'; '.join(names)}): {found} with a model that meets every "
               f"requirement.")
    results = [j for _, r in groups for j in r.results]
    req = {"search_text": query, "parts": [{**g, "status": r.status} for g, r in groups]}
    return FindResult(status, message, req, results, ai_used=any(r.ai_used for _, r in groups),
                      decided=all(r.decided for _, r in groups), groups=groups)


# reasons for answering without AI that are a choice, not a failure (another AI judges the results itself, or no AI is used)
DELIBERATE = {"switched off in the request", "AI switched off (PARTSFINDER_AI_BACKEND=off)", "AI switched off"}


def _unconfirmable(specs: dict[str, Any], hits: list[SearchHit], query: str, judged: list[Judged]) -> str:
    """A defining value no part of the asked kind states at all ("servo motor 400 W" when no servo states its
    power): nothing can be shown as close to it, so the honest answer is none. Empty when not the case."""
    if any(j.verdict == "fits" for j in judged):
        return ""
    relevant = [h for h in hits if h.specs and (h.word_coverage is None or h.word_coverage >= MIN_WORD_COVERAGE)
                and same_kind(query, h.part)]
    if not relevant:
        return ""
    for key in (k for k in specs if k in KEY_SPECS):
        if all(c.status == "unknown" for h in relevant for c in h.specs.checks if c.key == key):
            head = head_noun(query) or (re.search(kind_of(query)[0], query.lower()).group(0) if kind_of(query) else "part")
            label = SPEC_LABELS.get(key, key.replace("_", " "))
            return (f"No existing model found: no {head} in the library states its {label}, so none can be "
                    f"confirmed as {format_value(key, specs[key])}.")
    return ""


def lacking_words(query: str, hits: list[SearchHit]) -> list[str]:
    """Words of the question that none of these parts has ("green" when no bolt is green)."""
    missing = [set(missing_words(query, h.part)) for h in hits]
    return sorted(set.intersection(*missing)) if missing else []


def need_message(need: list[dict[str, Any]]) -> str:
    first = need[0]
    if not first["choices"]:
        return f"Which {first['label']}? Give it, so only parts that fit are shown."
    return (f"Which {first['label']}? The library has {', '.join(first['choices'])}. "
            "Choose one so only parts that fit are shown.")


def _explain(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc)
    low = text.lower()
    if name == "AuthenticationError" or "invalid x-api-key" in low:
        return "The Anthropic API key is invalid. Check the key in Settings."
    if "credit balance" in low or "billing" in low:
        return "The credit on this API key is used up or not available yet. See Billing in the Claude Console."
    if name == "NotFoundError" or ("model" in low and "not found" in low):
        return "The chosen Claude model does not exist. Check PARTSFINDER_CLAUDE_MODEL in backend/.env."
    if name == "RateLimitError":
        return "Too many requests to Claude at once; try again shortly."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "No connection to Claude (internet?)."
    return f"Claude error: {name}: {text[:200]}"
