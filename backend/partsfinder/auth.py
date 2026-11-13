"""Optional API keys: every key belongs to one company (or is an admin with '*').

Set PARTSFINDER_API_KEYS="key1=company_a,key2=company_b:nuclear,admin=*". Without this setting there is
no check (only for an API that stays on your own pc; main() refuses a network address then). With keys:
- "company:group:group" also gives the restricted parts of those groups (docs/10_COMPANY_LIBRARIES.md);
- every request (except /health) needs a key: ``Authorization: Bearer <key>``
  or ``X-API-Key: <key>``;
- a company key only works for that company: another company_id gives 403 and without
  company_id the own company is used;
- /ingest and /companies are for the admin only.
"""
from __future__ import annotations

import hashlib
import hmac

from .access import valid_group

ADMIN = "*"


def parse_keys(raw: str | None) -> dict[str, str]:
    """'k1=company_a, k2=*' -> {'k1': 'company_a', 'k2': '*'}. Raises ValueError on a bad format."""
    keys: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, scope = part.partition("=")
        key, scope = key.strip(), scope.strip()
        if not sep or not key or not scope:
            raise ValueError("PARTSFINDER_API_KEYS must have the form 'key=company,key2=*'")
        if key in keys:
            raise ValueError("PARTSFINDER_API_KEYS contains the same key twice")
        company, *groups = [x.strip() for x in scope.split(":")]
        if not company or (company == ADMIN and groups):
            raise ValueError("PARTSFINDER_API_KEYS: use 'key=company', 'key=company:group' or 'key=*'")
        bad = [g for g in groups if not valid_group(g)]
        if bad:
            raise ValueError(f"PARTSFINDER_API_KEYS: invalid group name {bad[0]!r} (a-z, 0-9, - and _, max 40)")
        keys[key] = scope
    return keys


def split_scope(scope: str) -> tuple[str, frozenset[str]]:
    """'company_a:nuclear:aero' -> ('company_a', {'nuclear', 'aero'})."""
    company, *groups = [x.strip() for x in scope.split(":")]
    return company, frozenset(groups)


def fingerprint(key: str | None) -> str:
    """What the audit log stores instead of the key itself."""
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:12] if key else "local"


def lookup(keys: dict[str, str], presented: str | None) -> str | None:
    """Company or '*' for a valid key, otherwise None. Compares in constant time."""
    if not presented:
        return None
    found: str | None = None
    for key, scope in keys.items():
        if hmac.compare_digest(key.encode(), presented.encode()):
            found = scope
    return found


def presented_key(headers) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return (headers.get("x-api-key") or "").strip() or None
