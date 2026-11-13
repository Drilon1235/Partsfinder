"""Who may see what: the company, its restricted groups, and whether the caller is an outside AI.

A `Scope` is the company id (a plain string everywhere it already travels: search, similar shapes,
repository, ...) that also carries what this caller may see beyond the company level. Every visibility
query builds its WHERE from it in one place (`access_sql`), so a forgotten detail fails closed: a plain
string or None sees no restricted part and nothing more than before. See docs/10_COMPANY_LIBRARIES.md.
"""
from __future__ import annotations

import re
from typing import Any

GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
AI_HEADER = "x-partsfinder-ai"         # sent by every AI client (client package / MCP server); can only reduce access


class Scope(str):
    """Company id + what this caller may see.

    groups      restricted groups of this company the caller may see
    all_groups  every group (admin, the import itself)
    for_ai      the caller is an outside AI: no restricted parts, no parts of confidential companies
    """

    groups: frozenset[str]
    all_groups: bool
    for_ai: bool

    def __new__(cls, company_id: str, groups: Any = (), all_groups: bool = False, for_ai: bool = False) -> "Scope":
        s = super().__new__(cls, str(company_id))
        s.groups = frozenset(groups)
        s.for_ai = bool(for_ai)
        s.all_groups = bool(all_groups) and not s.for_ai        # an AI never sees more, whatever else is said
        return s

    def key(self) -> tuple[Any, ...]:
        """For caches: two callers with different rights never share an answer."""
        return (str(self), tuple(sorted(self.groups)), self.all_groups, self.for_ai)

    def ai(self) -> "Scope":
        return Scope(self, for_ai=True)


def full(company_id: str | None) -> Scope | None:
    """Everything of this company (the import, an admin)."""
    return None if company_id is None else Scope(company_id, all_groups=True)


def as_ai(company_id: str | None) -> Scope | None:
    return None if company_id is None else Scope(company_id, for_ai=True)


def scope_key(company_id: str | None) -> tuple[Any, ...]:
    if company_id is None:
        return (None,)
    return company_id.key() if isinstance(company_id, Scope) else (str(company_id), (), False, False)


def access_sql(company_id: str, alias: str = "p") -> tuple[str, list[Any]]:
    """The extra condition on parts OF this company: which of its parts this caller may see."""
    if getattr(company_id, "for_ai", False):
        return (f"({alias}.access_group IS NULL AND {alias}.company_id NOT IN "
                f"(SELECT id FROM companies WHERE confidential = 1))"), []
    if getattr(company_id, "all_groups", False):
        return "1", []
    groups = sorted(getattr(company_id, "groups", ()))
    if groups:
        # a part may be restricted to several groups ("aero,nuclear"): having any one of them is enough
        anyone = " OR ".join(f"instr(',' || {alias}.access_group || ',', ?) > 0" for _ in groups)
        return f"({alias}.access_group IS NULL OR {anyone})", [f",{g}," for g in groups]
    return f"{alias}.access_group IS NULL", []


def valid_group(name: str) -> bool:
    return bool(GROUP_RE.fullmatch(name or ""))


def join_groups(groups: Any) -> str | None:
    """'nuclear, aero' or ['nuclear', 'aero'] -> 'aero,nuclear' (how a part or folder stores several groups);
    None for no group. Raises ValueError on a name that is not a valid group."""
    items = groups.replace(";", ",").split(",") if isinstance(groups, str) else list(groups or [])
    out = sorted({str(g).strip().lower() for g in items if str(g).strip()})
    bad = [g for g in out if not valid_group(g)]
    if bad:
        raise ValueError(f"'{bad[0]}' is not a valid group name (a-z, 0-9, - and _, max 40)")
    return ",".join(out) or None


def split_groups(value: str | None) -> list[str]:
    return [g for g in (value or "").split(",") if g]
