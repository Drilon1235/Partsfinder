"""Classification (taxonomy) of parts: loading and validating."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).with_name("taxonomy.yaml")


class TaxonomyError(ValueError):
    """A category or sector does not exist in the taxonomy."""


def _norm(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


class Taxonomy:
    def __init__(self, data: dict[str, Any]):
        cats = data.get("categories") or {}
        if not isinstance(cats, dict) or not cats:
            raise TaxonomyError("taxonomy.yaml contains no 'categories'")
        self.categories: dict[str, dict[str, list[str]]] = {}
        for l1, subs in cats.items():
            if not isinstance(subs, dict):
                raise TaxonomyError(f"Category '{l1}' must contain subcategories")
            self.categories[_norm(l1)] = {
                _norm(l2): [_norm(t) for t in (types or [])] for l2, types in subs.items()
            }
        self.sectors: list[str] = [_norm(s) for s in data.get("sectors") or []]
        self.materials: list[str] = [_norm(m) for m in data.get("materials") or []]
        self.version = data.get("version", 1)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Taxonomy":
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {})

    # ---- querying ---------------------------------------------------------
    def all_category_paths(self, include_types: bool = True) -> list[str]:
        paths: list[str] = []
        for l1, subs in self.categories.items():
            for l2, types in subs.items():
                paths.append(f"{l1}/{l2}")
                if include_types:
                    paths.extend(f"{l1}/{l2}/{t}" for t in types)
        return paths

    def as_prompt_text(self) -> str:
        """Compact text version to give to Claude."""
        lines = ["Categories (category/subcategory: types):"]
        for l1, subs in self.categories.items():
            for l2, types in subs.items():
                lines.append(f"- {l1}/{l2}: {', '.join(types)}")
        lines.append("Sectors: " + ", ".join(self.sectors))
        return "\n".join(lines)

    # ---- validating ------------------------------------------------------
    def validate_category(self, category_path: str) -> str:
        """Returns the normalized category_path, or raises TaxonomyError."""
        parts = [_norm(p) for p in category_path.strip("/").split("/") if p.strip()]
        if len(parts) not in (2, 3):
            raise TaxonomyError(
                f"category_path '{category_path}' must be 'category/subcategory' "
                "or 'category/subcategory/type'"
            )
        l1, l2 = parts[0], parts[1]
        if l1 not in self.categories:
            raise TaxonomyError(self._unknown("category", l1, list(self.categories)))
        if l2 not in self.categories[l1]:
            raise TaxonomyError(self._unknown(f"subcategory in '{l1}'", l2, list(self.categories[l1])))
        if len(parts) == 3 and parts[2] not in self.categories[l1][l2]:
            raise TaxonomyError(
                self._unknown(f"type in '{l1}/{l2}'", parts[2], self.categories[l1][l2])
            )
        return "/".join(parts)

    def validate_sectors(self, sectors: list[str]) -> list[str]:
        result: list[str] = []
        for s in sectors:
            n = _norm(s)
            if n not in self.sectors:
                raise TaxonomyError(self._unknown("sector", n, self.sectors))
            if n not in result:
                result.append(n)
        return result

    @staticmethod
    def _unknown(kind: str, value: str, options: list[str]) -> str:
        close = difflib.get_close_matches(value, options, n=3, cutoff=0.5)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        return f"Unknown {kind}: '{value}'.{hint} Options: {', '.join(options)}"
