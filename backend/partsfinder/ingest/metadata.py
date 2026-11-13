"""Determine the metadata of a part.

Order:
1. A JSON file next to the CAD file (same name) -> that is used.
2. Otherwise, if Claude is available -> Claude proposes name, description and classification.
3. Otherwise -> a guess based on the file name; the part gets the tag
   'needs-review' so a human can complete it later.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from ..taxonomy import Taxonomy, TaxonomyError
from .geometry import Geometry

REVIEW_TAG = "needs-review"
FALLBACK_CATEGORY = "other/unknown"

ALLOWED_KEYS = {
    "id", "kind", "name", "description", "category_path", "sectors", "tags", "material", "color",
    "standards", "properties", "source", "source_ref", "license", "components",
}


def load_sidecar(cad_path: Path) -> dict[str, Any] | None:
    meta_path = cad_path.with_suffix(".json")
    if not meta_path.exists():
        return None
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{meta_path.name}: expected a JSON object")
    # company_id and files never come from the JSON: the import decides those itself
    return {k: v for k, v in data.items() if k in ALLOWED_KEYS}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _matches(key: str, words: list[str], joined: str) -> float:
    """How well does a taxonomy word occur in the file name?
    1.0 = exact word, 0.6 = part of a compound (wallbracket -> bracket), 0 = not."""
    if " " in key:
        return 1.0 if f" {key} " in f" {joined} " else 0.0
    best = 0.0
    for w in words:
        if w == key:
            return 1.0
        if len(key) >= 4 and (w.startswith(key) or (len(w) >= 4 and key.startswith(w))):
            best = 0.6
        elif len(key) >= 5 and w.endswith(key):
            best = max(best, 0.6)
    return best


# material words in file names -> material name (so the mass estimate works)
_NAME_MATERIALS = {
    "stainless-steel": "stainless steel", "stainless": "stainless steel", "inox": "stainless steel",
    "rvs": "stainless steel", "a2": "stainless steel", "a4": "stainless steel",
    "steel": "steel", "staal": "steel", "alu": "aluminium", "aluminium": "aluminium", "aluminum": "aluminium",
    "brass": "brass", "messing": "brass", "copper": "copper", "koper": "copper", "bronze": "bronze",
    "brons": "bronze", "titanium": "titanium", "pvc": "PVC", "abs": "ABS", "nylon": "nylon", "wood": "wood",
    "hout": "wood", "oak": "oak", "eiken": "oak",
}
_STANDARD_RE = re.compile(r"\b(din|iso|en|nen|ansi)[ _\-]?(?:en[ _\-]?)?(\d{2,6})\b", re.IGNORECASE)
_THREAD_RE = re.compile(r"\bm(\d{1,3}(?:[.,]\d)?)(?:\s?[x×]\s?(\d{1,4}(?:[.,]\d)?))?\b", re.IGNORECASE)


def hints_from_name(stem: str) -> dict[str, Any]:
    """Technical hints from a file name, without AI: standard (DIN 933), thread (M8) and
    length (M8x40 -> 40 mm), material (stainless, alu...). Always a guess: the part stays 'needs-review'."""
    text = stem.replace("_", " ")
    out: dict[str, Any] = {"standards": [], "properties": {}}
    for m in _STANDARD_RE.finditer(text):
        label = f"{m.group(1).upper()} {m.group(2)}"
        if label not in out["standards"]:
            out["standards"].append(label)
    m = _THREAD_RE.search(text)
    if m:
        out["properties"]["thread"] = "M" + m.group(1).replace(",", ".")
        if m.group(2):
            out["properties"]["length_mm"] = float(m.group(2).replace(",", "."))
            if out["properties"]["length_mm"].is_integer():
                out["properties"]["length_mm"] = int(out["properties"]["length_mm"])
    for w in _words(text):
        if w in _NAME_MATERIALS:
            out["material"] = _NAME_MATERIALS[w]
            break
    return out


def guess_from_filename(cad_path: Path, geom: Geometry | None, taxonomy: Taxonomy) -> dict[str, Any]:
    """Without AI: name from the file name, category via keywords from the taxonomy."""
    stem = cad_path.stem
    words = _words(stem)
    joined = " ".join(words)
    best, best_score = FALLBACK_CATEGORY, 0
    for path in taxonomy.all_category_paths():
        parts = path.split("/")
        # a longer (more specific) keyword wins a tie: "garden chair" beats "chair"
        score = sum(depth * _matches(part.replace("-", " "), words, joined) * (1 + 0.1 * part.count("-"))
                    for depth, part in enumerate(parts[1:], start=1))
        if score > best_score:
            best, best_score = path, score
    name = re.sub(r"[_\-]+", " ", stem).strip() or stem
    description = f"Imported from {cad_path.name}"
    if geom:
        x, y, z = geom.bbox_mm
        description += f", outer dimensions {x:g} x {y:g} x {z:g} mm"
    hints = hints_from_name(stem)
    guess: dict[str, Any] = {
        "name": name[:1].upper() + name[1:],
        "description": description + ".",
        "category_path": best,
        "tags": [REVIEW_TAG, *words[:8]],
        "properties": {**hints["properties"], "needs_review": True},
    }
    if hints["standards"]:
        guess["standards"] = hints["standards"]
    if hints.get("material"):
        guess["material"] = hints["material"]
    return guess


class Enricher(Protocol):
    def enrich(self, cad_path: Path, geom: Geometry | None, guess: dict[str, Any]) -> dict[str, Any]: ...


class ClaudeEnricher:
    """Let Claude propose a description and classification for an unknown file."""

    def __init__(self, api_key: str | None, model: str, taxonomy: Taxonomy, client: Any = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.model = model
        self.taxonomy = taxonomy

    def _prompt(self, cad_path: Path, geom: Geometry | None) -> str:
        dims = "unknown"
        if geom:
            x, y, z = geom.bbox_mm
            dims = f"{x:g} x {y:g} x {z:g} mm"
            if geom.volume_mm3:
                dims += f", volume {geom.volume_mm3 / 1000:.1f} cm³"
        return (
            "You help organise a database of CAD parts. Based on the file name and the "
            "dimensions you propose metadata. Do not invent details you cannot derive; "
            "leave a field empty if you do not know it.\n\n"
            f"File name: {cad_path.name}\nFolder: {cad_path.parent.name}\nOuter dimensions: {dims}\n\n"
            f"{self.taxonomy.as_prompt_text()}\n\n"
            "Answer with only one JSON object with the fields: name (English, short), description "
            "(1-2 sentences), category_path (exactly from the list, 'category/subcategory' or "
            "'category/subcategory/type'), sectors (list from the sectors), material (or null), "
            "tags (English search words), standards (list, only if the name mentions a standard "
            "such as DIN 933). If unsure about the category, use other/unknown."
        )

    def enrich(self, cad_path: Path, geom: Geometry | None, guess: dict[str, Any]) -> dict[str, Any]:
        msg = self.client.messages.create(
            model=self.model, max_tokens=700,
            messages=[{"role": "user", "content": self._prompt(cad_path, geom)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("Claude returned no JSON")
        data = json.loads(match.group(0))
        result = dict(guess)
        result["properties"] = {**guess.get("properties", {}), "ai_metadata": True}
        for key in ("name", "description", "material"):
            if isinstance(data.get(key), str) and data[key].strip():
                result[key] = data[key].strip()
        for key in ("tags", "standards"):
            if isinstance(data.get(key), list):
                result[key] = [str(x) for x in data[key]][:15]
        try:
            result["category_path"] = self.taxonomy.validate_category(str(data.get("category_path", "")))
        except TaxonomyError:
            pass  # keep the guess from the file name
        sectors = [s for s in data.get("sectors", []) if isinstance(s, str)]
        result["sectors"] = [s for s in sectors if s.strip().lower() in self.taxonomy.sectors]
        # AI metadata stays needs-review, but is a much better start
        result["tags"] = [REVIEW_TAG, *[t for t in result.get("tags", []) if t != REVIEW_TAG]]
        return result


def make_enricher(settings: Any, taxonomy: Taxonomy) -> ClaudeEnricher | None:
    """Claude for metadata if an AI is available (the user's own API key), otherwise None."""
    from ..ai import AIError, make_client

    try:
        client, _ = make_client(settings)
    except AIError:
        return None
    return ClaudeEnricher(None, settings.claude_model, taxonomy, client=client)
