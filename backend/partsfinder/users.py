"""Accounts: people sign in with a name and a password (docs/10_COMPANY_LIBRARIES.md).

- Only a scrypt hash of each password is stored (salt per password); checks run in constant time.
- Signing in gives a random session token; the database only keeps its sha256. The token works like an
  API key (``Authorization: Bearer <token>``) and gives the same rights: an admin sees every company
  ('*'), a company account its own company and the restricted groups listed for it ('acme:nuclear').
- Wrong passwords are slowed down: after 5 failures for a name (or 20 from one address) within 15 minutes,
  signing in is refused for 15 minutes.
- The first admin account can only be made from this pc, and only while there is no account at all.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .access import valid_group

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")
COMPANY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
MIN_PASSWORD = 8
SESSION_HOURS = 12            # without "remember me"
REMEMBER_DAYS = 30
SCRYPT = (2 ** 14, 8, 1)      # n, r, p: ~50 ms per check, 16 MB memory


def scrub(conn: sqlite3.Connection) -> None:
    """Copies everything from the write-ahead log into the database and empties the log, so no old copy of a
    removed account or an old password hash stays behind in it (secure_delete already wipes freed pages).
    Best effort: a reader that is busy at that moment only delays it to the next time."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    except sqlite3.Error:
        pass


class AccountError(ValueError):
    """A request about accounts that cannot be done (the message says why)."""


def hash_password(password: str) -> str:
    n, r, p = SCRYPT
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")      # noqa: E731
    return f"scrypt${n}${r}${p}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(want))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY = hash_password(secrets.token_hex(8))       # an unknown name costs the same time as a wrong password


def check_password_rules(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AccountError(f"A password needs at least {MIN_PASSWORD} characters")
    if len(password) > 200:
        raise AccountError("A password can have at most 200 characters")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _Throttle:
    """Failed sign-ins per name and per address within a window."""
    window: float = 15 * 60
    per_name: int = 5
    per_address: int = 20
    fails: dict[str, list[float]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self.fails.get(key, []) if now - t < self.window]

    def blocked(self, name: str, address: str) -> bool:
        now = time.monotonic()
        with self.lock:
            return (len(self._recent("n:" + name.lower(), now)) >= self.per_name
                    or len(self._recent("a:" + address, now)) >= self.per_address)

    def fail(self, name: str, address: str) -> None:
        now = time.monotonic()
        with self.lock:
            for key in ("n:" + name.lower(), "a:" + address):
                self.fails[key] = self._recent(key, now) + [now]
            if len(self.fails) > 5000:                 # tried names must not pile up for ever
                for key in [k for k in self.fails if not self._recent(k, now)]:
                    del self.fails[key]

    def clear(self, name: str) -> None:
        with self.lock:
            self.fails.pop("n:" + name.lower(), None)


class Accounts:
    """Users and sessions in the library's database. The caller holds the database lock."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.throttle = _Throttle()

    # ---- users ----------------------------------------------------------------------------------
    def any(self) -> bool:
        return self.conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def get(self, username: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return self._public(row) if row else None

    def list(self, company_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM users", []
        if company_id is not None:
            sql, args = sql + " WHERE company_id = ?", [company_id]
        return [self._public(r) for r in self.conn.execute(sql + " ORDER BY company_id IS NOT NULL, company_id, username", args)]

    def create(self, username: str, password: str, role: str, company_id: str | None = None,
               groups: list[str] | None = None) -> dict[str, Any]:
        username = (username or "").strip()
        if not USERNAME_RE.fullmatch(username):
            raise AccountError("A username has 3-40 characters: letters, digits, '.', '_' or '-'")
        check_password_rules(password)
        if role not in ("admin", "company"):
            raise AccountError("The role is 'admin' or 'company'")
        if role == "company":
            company_id = (company_id or "").strip().lower()
            if not COMPANY_RE.fullmatch(company_id):
                raise AccountError("A company id has 2-40 characters: a-z, 0-9, '-' or '_'")
        else:
            company_id = None
        groups = self._groups(groups, role)
        if self.get(username):
            raise AccountError(f"The username '{username}' is already taken")
        now = _iso(_now())
        if company_id:
            self.conn.execute("INSERT OR IGNORE INTO companies(id, name, created_at) VALUES (?, ?, ?)",
                              (company_id, company_id, now))
        self.conn.execute(
            "INSERT INTO users(username, password_hash, role, company_id, groups, created_at) VALUES (?,?,?,?,?,?)",
            (username, hash_password(password), role, company_id, json.dumps(groups), now))
        self._commit(2)
        return self.get(username)

    def update(self, username: str, *, password: str | None = None, disabled: bool | None = None,
               groups: list[str] | None = None) -> dict[str, Any]:
        user = self.get(username)
        if user is None:
            raise AccountError("Unknown user")
        if password is not None:
            check_password_rules(password)
            self.conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(password), username))
            self.conn.execute("DELETE FROM sessions WHERE username = ?", (username,))     # signed out everywhere
        if disabled is not None:
            if disabled and user["role"] == "admin" and self._other_admins(username) == 0:
                raise AccountError("The last admin account cannot be disabled")
            self.conn.execute("UPDATE users SET disabled = ? WHERE username = ?", (int(disabled), username))
            if disabled:
                self.conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        if groups is not None:
            self.conn.execute("UPDATE users SET groups = ? WHERE username = ?",
                              (json.dumps(self._groups(groups, user["role"])), username))
        self._commit(3)
        if password is not None:
            scrub(self.conn)
        return self.get(username)

    def delete(self, username: str) -> None:
        user = self.get(username)
        if user is None:
            raise AccountError("Unknown user")
        if user["role"] == "admin" and self._other_admins(username) == 0:
            raise AccountError("The last admin account cannot be removed")
        self.conn.execute("DELETE FROM users WHERE username = ?", (username,))     # its sessions go with it
        self._commit(2)
        scrub(self.conn)

    # ---- signing in -------------------------------------------------------------------------------
    def sign_in(self, username: str, password: str, address: str, remember: bool = False) -> tuple[str, dict[str, Any]]:
        """(token, user). Raises AccountError with one message for every failure (no hint which part was wrong)."""
        username = (username or "").strip()
        if self.throttle.blocked(username, address):
            raise AccountError("Too many failed attempts. Try again in 15 minutes.")
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = verify_password(password or "", row["password_hash"] if row else _DUMMY)
        if not row or not ok or row["disabled"]:
            self.throttle.fail(username, address)
            raise AccountError("Wrong username or password")
        self.throttle.clear(username)
        return self.new_session(row["username"], remember), self._public(row)

    def new_session(self, username: str, remember: bool = False) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        until = now + (timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SESSION_HOURS))
        self.conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        self.conn.execute("INSERT INTO sessions(token_hash, username, created_at, expires_at) VALUES (?,?,?,?)",
                          (_token_hash(token), username, _iso(now), _iso(until)))
        self.conn.execute("UPDATE users SET last_login = ? WHERE username = ?", (_iso(now), username))
        self._commit(3)
        return token

    def session(self, token: str | None) -> dict[str, Any] | None:
        """The user of a valid session token, or None (unknown, expired, or the account is disabled)."""
        if not token or len(token) > 200:
            return None
        row = self.conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.username = s.username
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled = 0""",
            (_token_hash(token), _iso(_now()))).fetchone()
        return self._public(row) if row else None

    def sign_out(self, token: str | None) -> None:
        if token:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            self._commit(1)

    # ---- helpers ----------------------------------------------------------------------------------
    @staticmethod
    def scope_of(user: dict[str, Any]) -> str:
        """The same rights string an API key has: '*' or 'company:group:group'."""
        if user["role"] == "admin":
            return "*"
        return ":".join([user["company_id"], *user["groups"]])

    def _groups(self, groups: list[str] | None, role: str) -> list[str]:
        out = sorted({str(g).strip().lower() for g in groups or [] if str(g).strip()})
        bad = [g for g in out if not valid_group(g)]
        if bad:
            raise AccountError(f"'{bad[0]}' is not a valid group name (a-z, 0-9, - and _, max 40)")
        if out and role == "admin":
            raise AccountError("An admin sees every group already")
        return out

    def _other_admins(self, username: str) -> int:
        return self.conn.execute("SELECT count(*) FROM users WHERE role = 'admin' AND disabled = 0 AND username != ?",
                                 (username,)).fetchone()[0]

    def _commit(self, _rows: int) -> None:
        self.conn.commit()

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        """Never the password hash."""
        return {"username": row["username"], "role": row["role"], "company_id": row["company_id"],
                "groups": json.loads(row["groups"] or "[]"), "disabled": bool(row["disabled"]),
                "created_at": row["created_at"], "last_login": row["last_login"]}
