"""HTTP API of Partsfinder (FastAPI). See docs/05_API.md.

Start:     python -m partsfinder.api            (or double-click api.bat)
Docs:      http://127.0.0.1:8000/docs           (automatic, to try things out)

Endpoints:
  GET  /health                       does everything work? how many parts? AI available?
  POST /search                       search in plain language (with Claude if there is a key)
  GET  /parts/{id}                   all info of one part
  GET  /parts/{id}/file?format=step  download the CAD file
  GET  /parts/{id}/thumbnail         PNG preview
  GET  /parts/{id}/mesh              binary STL for the 3D viewer (made from STEP, cached)
  GET  /parts/{id}/datasheet         printable HTML datasheet
  GET  /parts/{id}/similar           parts with a similar shape
  POST /search/shape                 search with your own STEP/STL file (body = the file)
  POST /search/image                 search with a photo or drawing (Claude identifies the part)
  POST /ingest                       import a folder (optionally in the background)
  GET  /ingest/{job_id}              status of a background import
  POST /feedback, GET /feedback      thumbs up/down per part (local)
  GET  /properties                   filterable properties (only what the company may see)
  GET  /quality, GET /duplicates     completeness of the data; probable duplicates (own library)
  GET  /taxonomy                     categories and sectors
  GET  /companies                    known companies (for the test app; admin only with keys)

Company separation: pass company_id with every question. Without company_id you only see
the general library. Parts of another company always give 404.

The server by default only listens on this computer (127.0.0.1). Without PARTSFINDER_API_KEYS there is no
login: do not expose it on a network then. With keys: see docs/05_API.md.
"""
from __future__ import annotations

import base64
import dataclasses
import binascii
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import __version__
from .ai import NO_KEY, AIError, FindResult, Judged, PartFinder, ai_label, make_finder, search_several, search_without_ai
from . import auth
from .access import AI_HEADER, Scope, as_ai, full, join_groups, scope_key, split_groups, valid_group
from .config import PROJECT_DIR, Settings, get_settings
from .db import connect
from .ingest.geometry import ANALYZABLE, CAD_FORMATS, analyze
from .ingest.embeddings import Embedder, HashingEmbedder, SentenceTransformerEmbedder
from .ingest.metadata import ClaudeEnricher
from .ingest.pipeline import _rel, _under, ingest_folder, remove_folder, remove_parts
from .ingest.rules import ACCESS_FILE, RuleError, parse_access
from . import engineering
from .mass import estimate_mass_g
from . import preview
from .models import Part
from .repository import AccessError, Repository
from .similar import find_duplicates, find_similar
from .users import AccountError, Accounts, scrub
from .search import SearchEngine, SearchFilters, filters_as_dict, merge_filters, property_clauses

Dims = tuple[float, float, float]

MAX_SHAPE_BYTES = 50 * 1024 * 1024
ANSWER_CACHE_SIZE = 256        # remembered answers (search), cleared by every write to the library
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


# ---- request models ------------------------------------------------------------------
class FilterIn(BaseModel):
    category: str | None = None
    sectors: list[str] = Field(default_factory=list)
    material: str | None = None
    color: str | None = None
    standards: list[str] = Field(default_factory=list)
    kind: Literal["part", "assembly"] | None = None
    max_dims_mm: Dims | None = None
    min_dims_mm: Dims | None = None
    library: Literal["all", "global", "company"] = "all"
    properties: dict[str, Any] = Field(default_factory=dict, examples=[{"thread": "M8", "length_mm": {"min": 40, "max": 60}}])
    engineering: dict[str, Any] = Field(default_factory=dict, examples=[{"tensile_strength_mpa": {"min": 800}}])

    @field_validator("properties")
    @classmethod
    def _check_properties(cls, v: dict[str, Any]) -> dict[str, Any]:
        property_clauses(v)          # raises ValueError (→ 422) on an invalid key or condition
        return v

    @field_validator("engineering")
    @classmethod
    def _check_engineering(cls, v: dict[str, Any]) -> dict[str, Any]:
        return engineering.check_filter(v)

    def is_empty(self) -> bool:
        return not filters_as_dict(self.to_filters())

    def to_filters(self) -> SearchFilters:
        return SearchFilters(**self.model_dump())


class WithinIn(BaseModel):
    """What to search, from the app's folder picker. Leave it out to search everything you may see."""
    general: bool = True                     # the general library
    other: bool = True                       # the company's parts that were not uploaded (imported by the admin)
    folders: list[str] | None = Field(default=None, max_length=500)   # uploaded folders; None = all of them


class SearchIn(BaseModel):
    # empty only together with filters: then the parts that meet the filters, by name (the Filters panel)
    query: str = Field(default="", max_length=1000, examples=["small green outdoor chair"])
    company_id: str | None = Field(default=None, examples=["company_a"])
    limit: int = Field(default=5, ge=1, le=20)
    filters: FilterIn | None = None
    use_ai: bool = True
    within: WithinIn | None = None           # the app's folder picker; None = everything this caller may see


class BatchItem(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    filters: FilterIn | None = None


class BatchIn(BaseModel):
    searches: list[BatchItem] = Field(min_length=1, max_length=10)
    company_id: str | None = None


class FeedbackIn(BaseModel):
    part_id: str = Field(min_length=1, max_length=200)
    rating: Literal["up", "down"]
    company_id: str | None = None
    query: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=1000)


class ImageSearchIn(BaseModel):
    image_base64: str = Field(min_length=16, description="the image, base64 (no data: prefix)")
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"] = "image/jpeg"
    note: str = Field(default="", max_length=500, description="extra requirements, e.g. 'M8, 40 mm long'")
    company_id: str | None = None
    limit: int = Field(default=5, ge=1, le=20)
    filters: FilterIn | None = None          # hard requirements, as with /search
    within: WithinIn | None = None           # the app's folder picker, as with /search


class AISettingsIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=300)   # the user's own Anthropic key; empty = AI off


class CompanySettingsIn(BaseModel):
    confidential: bool


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    id: str | None = Field(default=None, max_length=40)     # made from the name when left out


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "company"] = "company"
    company_id: str | None = None
    groups: list[str] = Field(default_factory=list, max_length=20)


class UserUpdateIn(BaseModel):
    password: str | None = Field(default=None, max_length=200)
    disabled: bool | None = None
    groups: list[str] | None = Field(default=None, max_length=20)


class IngestIn(BaseModel):
    folder: str
    company_id: str | None = None
    use_ai: bool = True
    thumbnails: bool = True
    background: bool = False      # start the import in the background and query it later with GET /ingest/{job_id}
    sync: bool = False            # also remove parts of this folder whose file is gone or now excluded
    allow_mass_removal: bool = False


class FolderAccessIn(BaseModel):
    path: str = Field(default="", max_length=400)          # subfolder inside the uploaded folder, '' = all of it
    access: str = Field(min_length=1, max_length=400)      # 'inherit', 'company', or restricted groups "aero,nuclear"


class UploadFinishIn(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    company_id: str | None = None
    use_ai: bool = True
    # who sees the whole folder: 'company' or restricted groups "aero,nuclear"; None keeps what it was
    access: str | None = Field(default=None, max_length=400)


class RemoveIn(BaseModel):
    folder: str = Field(min_length=1)
    company_id: str | None = None


# ---- helpers ----------------------------------------------------------------------
def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_DIR / p


def _url(path: str, company_id: str | None, **params: Any) -> str:
    q = {k: v for k, v in params.items() if v is not None}
    if company_id:
        q["company_id"] = company_id
    return path + (("?" + urlencode(q)) if q else "")


def _thumb_version(path: str | None) -> int | None:
    """Modification time of the preview, in the link: a redone preview gets a new link, so the app
    never shows an old copy from its cache."""
    try:
        return int(_resolve(path).stat().st_mtime) if path else None
    except OSError:
        return None


def _mass_fields(part: Part) -> dict[str, Any]:
    """Real mass if known; otherwise an estimate (volume × density) with the flag mass_estimated.
    For assemblies we do not estimate: parts can overlap in volume."""
    if part.mass_g is not None:
        return {"mass_g": part.mass_g, "mass_estimated": False}
    est = estimate_mass_g(part.volume_mm3, part.material, part.bbox_mm) if part.kind == "part" else None
    if est is None:
        return {"mass_g": None, "mass_estimated": False}
    return {"mass_g": est, "mass_estimated": True}


def part_payload(part: Part, company_id: str | None) -> dict[str, Any]:
    """Part as JSON, with download links. company_id = who is asking (is included in the links)."""
    return {
        "id": part.id,
        "library": part.library,
        "company_id": part.company_id,
        "access_group": part.access_group,               # restricted group, or null (whole company)
        "kind": part.kind,
        "name": part.name,
        "description": part.description,
        "category_path": part.category_path,
        "sectors": part.sectors,
        "tags": [t for t in part.tags if t != "needs-review"],
        "needs_review": "needs-review" in part.tags,
        "material": part.material,
        "color": part.color,
        "dims_mm": list(part.bbox_mm) if part.bbox_mm else None,
        "volume_mm3": part.volume_mm3,
        **_mass_fields(part),
        "standards": part.standards,
        "properties": part.properties,
        # strength, load, tolerance, hardness, mass: the part's own values, or what follows from a standard
        "engineering": engineering.values(part),
        "source": part.source,
        "source_ref": part.source_ref,
        "license": part.license,
        "files": [
            {"format": f.format, "is_primary": f.is_primary, "path": f.path,
             "url": _url(f"/parts/{part.id}/file", company_id, format=f.format)}
            for f in part.files
        ],
        "thumbnail_url": _url(f"/parts/{part.id}/thumbnail", company_id, v=_thumb_version(part.thumbnail_path))
        if part.thumbnail_path else None,
        "summary": preview.summary(part),
        "highlights": preview.highlights(part),
        "mesh_url": _url(f"/parts/{part.id}/mesh", company_id)
        if any(f.format in preview.MESHABLE for f in part.files) else None,
        "datasheet_url": _url(f"/parts/{part.id}/datasheet", company_id),
    }


def result_payload(result: FindResult, company_id: str | None) -> dict[str, Any]:
    out = _result_payload(result, company_id)
    if result.groups:
        # several parts asked for: the same answer per requested part (results above = all of them, in order)
        out["groups"] = [{"request": g["request"], "quantity": g.get("quantity"),
                          **{k: v for k, v in _result_payload(r, company_id).items() if k != "interpreted_requirements"}}
                         for g, r in result.groups]
    return out


def _result_payload(result: FindResult, company_id: str | None) -> dict[str, Any]:
    return {
        "status": result.status,
        "message": result.message,
        "ai_used": result.ai_used,
        "interpreted_requirements": result.requirements,
        "need": result.requirements.get("need", []),     # defining values the question leaves open
        "decided": result.decided,                        # settled by the library's own checks, no AI needed
        "results": [
            {**part_payload(j.hit.part, company_id),
             "verdict": j.verdict,
             "score": round(j.hit.score, 5),
             "match_reasons": j.match_reasons,
             "mismatch_reasons": j.mismatch_reasons,
             "spec_checks": [c.as_dict() for c in j.hit.specs.checks] if j.hit.specs else []}
            for j in result.results
        ],
    }


# ---- the app ----------------------------------------------------------------------------
class _LockedEngine:
    """Search engine whose search() always runs under the database lock."""

    def __init__(self, engine: SearchEngine, lock: threading.RLock):
        self._engine, self._lock = engine, lock

    def search(self, *args: Any, **kwargs: Any):
        with self._lock:
            return self._engine.search(*args, **kwargs)

    def general_properties(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._engine.general_properties()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)


def create_app(
    settings: Settings | None = None,
    *,
    conn=None,
    embedder: Embedder | None = None,
    finder: PartFinder | None = None,
    enable_ai: bool = True,
) -> FastAPI:
    """Creates the API. In tests you pass your own database, embedder and (fake) finder."""
    s = settings or get_settings()
    if conn is None:
        conn = connect(s.db_path, s.embedding_dim, check_same_thread=False)
    repo = Repository(conn)
    if embedder is None:
        row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
        embedder = HashingEmbedder(s.embedding_dim) if (row and row[0] == "hashing") else \
            SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim)
    # One database connection: database work happens one at a time (lock). Claude calls happen
    # outside the lock, so an AI question of 10 s does not hold up other questions (e.g. another app calling the API).
    lock = threading.RLock()
    engine = _LockedEngine(SearchEngine(repo, embedder), lock)
    answers: OrderedDict[tuple, dict[str, Any]] = OrderedDict()     # same question, same library = same answer
    answers_lock = threading.Lock()
    ai_error: str | None = None
    if finder is None and enable_ai:
        try:
            finder = make_finder(engine, repo.taxonomy, s)
        except AIError as exc:
            ai_error = str(exc)
    elif finder is None:
        ai_error = "AI switched off"
    if finder is not None and not isinstance(finder.engine, _LockedEngine):
        finder.engine = _LockedEngine(finder.engine, lock)

    app = FastAPI(
        title="Partsfinder",
        version=__version__,
        description="Search existing CAD models in plain language. See docs/05_API.md.",
    )
    app.state.repo, app.state.engine, app.state.finder = repo, engine, finder
    app.state.ai_note = ai_error
    app.state.public_url = "http://127.0.0.1:8000"     # main() sets the real port

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # without sending the entered value back: it cannot (e.g. 1e999) itself be sent as JSON
        detail = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": e.get("type", "")}
                  for e in exc.errors()]
        return JSONResponse({"detail": detail}, status_code=422)

    keys = auth.parse_keys(s.api_keys)
    accounts = Accounts(conn)
    app.state.accounts = accounts
    scrub(conn)                                         # no old copies of removed accounts left in the log
    OPEN = {"/health", "/login", "/setup"}              # reachable without signing in
    local_groups = frozenset(g.strip() for g in (s.local_groups or "").split(",") if g.strip())
    if any(not valid_group(g) for g in local_groups):
        raise ValueError("PARTSFINDER_LOCAL_GROUPS: invalid group name (a-z, 0-9, - and _, max 40)")

    def who_is(request: Request) -> tuple[str | None, dict[str, Any] | None]:
        """(rights, account) for this request: an API key, a signed-in session, PUBLIC or None (no sign-in
        on this server at all: one pc, as before). Raises 401 for a key or session that is not valid."""
        presented = auth.presented_key(request.headers)
        with lock:
            have_accounts = accounts.any()
        if not keys and not have_accounts:
            return None, None
        if presented:
            scope = auth.lookup(keys, presented)
            if scope is not None:
                return scope, None
            with lock:
                user = accounts.session(presented)
            if user is not None:
                return Accounts.scope_of(user), user
            raise HTTPException(401, "Your sign-in has expired or the key is not valid. Sign in again.")
        if keys:
            raise HTTPException(401, "API key missing or invalid")
        return PUBLIC, None                             # accounts but no keys: the general library for everyone

    @app.middleware("http")
    async def check_key(request: Request, call_next):
        request.state.scope, request.state.user = None, None
        try:
            request.state.scope, request.state.user = await run_in_threadpool(who_is, request)
        except HTTPException as exc:
            if request.url.path not in OPEN:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

    def company_for(request: Request, claimed: str | None) -> Scope | None:
        """Which company may this request use, and what of it? Without keys: what is asked for (and the
        restricted groups in PARTSFINDER_LOCAL_GROUPS). An AI client (header X-Partsfinder-AI: 1) never sees restricted
        parts or parts of a confidential company; that header can only reduce what is visible."""
        entry = request.state.scope
        for_ai = request.headers.get(AI_HEADER, "").strip() == "1"
        if entry == PUBLIC:
            if claimed is not None:
                raise HTTPException(403, "Sign in to search a company library")
            return None
        if entry is None:
            company, groups, everything = claimed, local_groups, False
        elif entry == auth.ADMIN:
            company, groups, everything = claimed, frozenset(), True
        else:
            company, groups = auth.split_scope(entry)
            everything = False
            if claimed not in (None, company):
                raise HTTPException(403, "This key does not apply to that company")
        return None if company is None else Scope(company, groups, all_groups=everything, for_ai=for_ai)

    def actor_of(request: Request) -> str:
        """For the audit log: who asked. Never the key itself."""
        if request.state.user is not None:
            return f"user:{request.state.user['username']}"
        if request.state.scope is None:
            return "local"
        if request.state.scope == PUBLIC:
            return "public"
        return auth.fingerprint(auth.presented_key(request.headers))

    def ai_sees_all(company_id: Scope | None) -> bool:
        """May an outside AI see everything this caller may see? If not, the request is answered by the
        library's own code only (rule 4 of docs/10_COMPANY_LIBRARIES.md)."""
        if company_id is None or company_id.for_ai:
            return True
        if company_id.all_groups or company_id.groups:
            with lock:                                  # only matters when this company has restricted parts
                if conn.execute("SELECT 1 FROM parts WHERE company_id = ? AND access_group IS NOT NULL LIMIT 1",
                                (str(company_id),)).fetchone():
                    return False
        with lock:
            return not repo.is_confidential(company_id)

    AI_OFF = "AI is off for this library (confidential or restricted parts); the library's own checks answered."

    audit_rows = [0]                                    # audit log rows written by this server (see below)

    def library_version() -> tuple[int, int]:
        """Changes with every write to the database: by this server (total_changes, e.g. feedback or an
        import) or by another program such as the import command (data_version). Writing the audit log
        does not count: otherwise every search would clear the remembered answers."""
        with lock:
            return conn.execute("PRAGMA data_version").fetchone()[0], conn.total_changes - audit_rows[0]

    def account_do(fn):
        """An account change under the lock; its rows do not count as a change of the library."""
        with lock:
            before = conn.total_changes
            try:
                return fn()
            except AccountError as exc:
                raise HTTPException(400, str(exc)) from None
            finally:
                audit_rows[0] += conn.total_changes - before

    def log(request: Request, company_id: str | None, action: str, target: str = "", detail: str = "") -> None:
        """Audit log: who (key fingerprint, never the key), which company, what (part id, never its name)."""
        with lock:
            repo.audit(actor_of(request), company_id, action, target, detail)
            audit_rows[0] += 1

    def remembered(key: tuple, compute) -> dict[str, Any]:
        """The answer for this question (route, body incl. company) in this version of the library, from
        memory when it was asked before. compute() returns (answer, may_keep): an answer that fell back
        because the AI failed is not kept."""
        key = (*key, library_version())
        with answers_lock:
            if key in answers:
                answers.move_to_end(key)
                return {**answers[key], "cached": True}
        out, keep = compute()
        if keep:
            with answers_lock:
                answers[key] = out
                while len(answers) > ANSWER_CACHE_SIZE:
                    answers.popitem(last=False)
        return {**out, "cached": False}

    def require_admin(request: Request) -> None:
        if request.state.scope not in (None, auth.ADMIN):
            raise HTTPException(403, "Only with an admin key")

    def get_visible(part_id: str, company_id: str | None) -> Part:
        part = repo.get_part(part_id, company_id)
        if part is None:   # does not exist or belongs to another company: same answer
            raise HTTPException(404, "Part not found")
        return part

    @app.get("/health")
    def health() -> dict[str, Any]:
        with lock:
            has_accounts = accounts.any()
            parts = conn.execute("SELECT count(*) FROM parts").fetchone()[0]
            row = conn.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()
        return {
            "status": "ok",
            "version": __version__,
            "parts": parts,
            "embedder": row[0] if row else None,
            "ai_available": app.state.finder is not None,
            "ai_model": app.state.finder.model if app.state.finder else None,
            "ai_note": app.state.ai_note,
            "ai_spent_usd": round(app.state.finder.usage.cost_usd, 5) if app.state.finder else 0.0,
            "image_search_available": app.state.finder is not None,
            "keys_required": bool(keys),        # every request needs a key or a sign-in
            "accounts": has_accounts,           # people can sign in; without it the general library is open
            "setup_needed": not has_accounts and not keys,   # the first admin account can be made (on this pc)
        }

    @app.post("/settings/ai")
    def set_ai(body: AISettingsIn, request: Request) -> dict[str, Any]:
        """The app hands over the user's own Anthropic API key (kept in the OS keychain by the app).
        Only from this pc and only for the admin (or the one-pc library). The key stays in memory:
        never written to the database, a file or a log. An empty key switches the AI off."""
        require_admin(request)
        if not request.client or request.client.host not in LOCAL_ADDRESSES:
            raise HTTPException(403, "The AI key can only be set from this pc")
        key = (body.api_key or "").strip() or None
        if key is None:
            app.state.finder, app.state.ai_note = None, NO_KEY
        else:
            try:
                app.state.finder = make_finder(engine, repo.taxonomy, dataclasses.replace(s, anthropic_api_key=key))
            except AIError as exc:
                raise HTTPException(400, str(exc)) from exc
            app.state.ai_note = None
        with answers_lock:
            answers.clear()                      # answers given without (or with another) AI
        return {"ai_available": app.state.finder is not None,
                "ai_model": app.state.finder.model if app.state.finder else None, "ai_note": app.state.ai_note}

    @app.get("/me")
    def me(request: Request) -> dict[str, Any]:
        """Who is asking: what the key in this request gives (for the app's sign-in). Never the key itself."""
        entry, user = request.state.scope, request.state.user
        base = {"keys_required": bool(keys), "username": user["username"] if user else None}
        if entry is None:
            return {**base, "role": "local", "company_id": None, "groups": sorted(local_groups), "key": None}
        if entry == PUBLIC:
            return {**base, "role": "public", "company_id": None, "groups": [], "key": None}
        fp = None if user else auth.fingerprint(auth.presented_key(request.headers))
        if entry == auth.ADMIN:
            return {**base, "role": "admin", "company_id": None, "groups": [], "key": fp}
        company, groups = auth.split_scope(entry)
        return {**base, "role": "company", "company_id": company, "groups": sorted(groups), "key": fp}

    # ---- accounts: signing in, and the admin's list of people -------------------------------------
    def address(request: Request) -> str:
        return request.client.host if request.client else "?"

    def signed_in(request: Request, token: str, user: dict[str, Any]) -> dict[str, Any]:
        request.state.user = user
        request.state.scope = Accounts.scope_of(user)
        return {"token": token, "me": me(request)}

    @app.post("/setup")
    def setup(body: LoginIn, request: Request) -> dict[str, Any]:
        """The first admin account: only while there is no account at all, and only from this pc."""
        if address(request) not in LOCAL_ADDRESSES:
            raise HTTPException(403, "The first admin account can only be made on the pc that runs the library")

        def make():
            if accounts.any():
                raise HTTPException(409, "There is an account already: sign in")
            accounts.create(body.username, body.password, "admin")
            return accounts.sign_in(body.username, body.password, address(request), body.remember)
        token, user = account_do(make)
        log(request, None, "account", user["username"], "first admin created")
        return signed_in(request, token, user)

    @app.post("/login")
    def login(body: LoginIn, request: Request) -> dict[str, Any]:
        try:
            token, user = account_do(lambda: accounts.sign_in(body.username, body.password, address(request),
                                                              body.remember))
        except HTTPException as exc:
            code = 429 if "Too many" in str(exc.detail) else 401
            raise HTTPException(code, exc.detail) from None
        return signed_in(request, token, user)

    @app.post("/logout")
    def logout(request: Request) -> dict[str, Any]:
        if request.state.user is not None:
            account_do(lambda: accounts.sign_out(auth.presented_key(request.headers)))
        return {"status": "signed out"}

    @app.get("/users")
    def list_users(request: Request, company_id: str | None = None) -> list[dict[str, Any]]:
        require_admin(request)
        with lock:
            return accounts.list(company_id)

    @app.post("/users")
    def create_user(body: UserIn, request: Request) -> dict[str, Any]:
        """Admin: a new account. A company account for a company that does not exist yet makes that company."""
        require_admin(request)
        user = account_do(lambda: accounts.create(body.username, body.password, body.role, body.company_id, body.groups))
        log(request, user["company_id"], "account", user["username"], f"created ({user['role']})")
        return user

    @app.patch("/users/{username}")
    def update_user(username: str, body: UserUpdateIn, request: Request) -> dict[str, Any]:
        require_admin(request)
        user = account_do(lambda: accounts.update(username, password=body.password, disabled=body.disabled,
                                                   groups=body.groups))
        what = ", ".join(k for k, v in (("password", body.password), ("disabled", body.disabled),
                                        ("groups", body.groups)) if v is not None)
        log(request, user["company_id"], "account", user["username"], f"changed: {what}")
        return user

    @app.delete("/users/{username}")
    def delete_user(username: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        user = account_do(lambda: accounts.get(username))
        if user is None:
            raise HTTPException(404, "Unknown user")
        account_do(lambda: accounts.delete(username))
        log(request, user["company_id"], "account", username, "removed")
        return {"removed": username}

    def within_filters(company: str | None, w: "WithinIn | None") -> SearchFilters | None:
        """The folder picker as a filter: the general library and/or the chosen uploaded folders."""
        if w is None:
            return None
        if company is None:
            return SearchFilters(within=(w.general, False, (), "\0"))
        root = uploads_dir(company)
        prefix = lambda d: _rel(d).rstrip("/") + "/"                    # noqa: E731 - as part_files stores paths
        folders = (prefix(root),) if w.folders is None else tuple(
            prefix(root / folder_name(n)) for n in dict.fromkeys(w.folders))
        return SearchFilters(within=(w.general, w.other, folders, prefix(root)))

    @app.post("/search")
    def search(body: SearchIn, request: Request) -> dict[str, Any]:
        body.company_id = company_for(request, body.company_id)
        fixed = body.filters.to_filters() if body.filters else None
        within = within_filters(body.company_id, body.within)
        if within is not None:
            fixed = merge_filters(fixed or SearchFilters(), within)
        if not body.query.strip():
            if body.filters is None or body.filters.is_empty():
                raise HTTPException(422, "Give a question, or at least one filter")
            return browse(body, fixed, request)

        def compute() -> tuple[dict[str, Any], bool]:
            start = time.perf_counter()
            keep = True
            ai_allowed = ai_sees_all(body.company_id)
            use_ai = app.state.finder is not None and body.use_ai and ai_allowed
            failed: list[str] = []

            def judge(text: str):
                """A requested part the library's own checks cannot settle: the AI judges that part alone."""
                try:
                    return app.state.finder.find(text, as_ai(body.company_id), body.limit, fixed_filters=fixed)
                except AIError as exc:
                    failed.append(str(exc))
                    return None

            several = search_several(engine, body.query, body.company_id, body.limit,
                                     reason="" if use_ai else (app.state.ai_note or "") if app.state.finder is None
                                     else "switched off in the request" if not body.use_ai else AI_OFF,
                                     filters=fixed, judge=judge if use_ai else None)
            if several is not None:                     # "an M8 bolt and an Arduino": answered per part
                out = result_payload(several, body.company_id)
                out["seconds"] = round(time.perf_counter() - start, 3)
                return out, not failed
            if use_ai:                                  # searching under the lock, Claude outside it
                try:
                    # Claude only ever gets what an outside AI may see
                    result = app.state.finder.find(body.query, as_ai(body.company_id), body.limit, fixed_filters=fixed)
                except AIError as exc:
                    keep = False                        # the AI may work again on the next try
                    result = search_without_ai(engine, body.query, body.company_id, body.limit,
                                               reason=str(exc), filters=fixed)
            else:
                if app.state.finder is None:
                    reason = app.state.ai_note or ""
                elif not body.use_ai:
                    reason = "switched off in the request"
                else:
                    reason = AI_OFF                     # restricted or confidential parts: code only
                result = search_without_ai(engine, body.query, body.company_id, body.limit,
                                           reason=reason, filters=fixed)
            out = result_payload(result, body.company_id)
            out["seconds"] = round(time.perf_counter() - start, 3)
            return out, keep

        log(request, body.company_id, "search", "", body.query)
        return remembered(("search", body.model_dump_json(), scope_key(body.company_id)), compute)

    def browse(body: SearchIn, fixed: SearchFilters, request: Request) -> dict[str, Any]:
        """No question, only filters: the parts that meet them, by name. Nothing to judge: no AI."""
        start = time.perf_counter()
        log(request, body.company_id, "search", "", "(filters only)")
        with lock:
            hits = engine.search("", body.company_id, fixed, limit=body.limit)
        n = len(hits)
        message = (f"{n} part{'s' if n != 1 else ''} meet{'s' if n == 1 else ''} the filters"
                   f"{' (the first ' + str(n) + ' by name)' if n == body.limit else ''}." if n else
                   "No part meets these filters. A part that does not state a filtered value drops out.")
        result = FindResult("found" if n else "none", message, {"search_text": "", "filters": filters_as_dict(fixed)},
                            [Judged(h, "close", [], []) for h in hits], ai_used=False, decided=True)
        return {**result_payload(result, body.company_id), "browse": True, "seconds": round(time.perf_counter() - start, 3),
                "cached": False}

    @app.post("/search/batch")
    def search_batch(body: BatchIn, request: Request) -> dict[str, Any]:
        """Search several parts in one request (e.g. bolt, nut and washer for one joint).
        Without AI judging: the fast route for another AI that judges the results itself."""
        company_id = company_for(request, body.company_id)
        log(request, company_id, "search", "", " | ".join(item.query for item in body.searches))
        out = []
        for item in body.searches:
            fixed = item.filters.to_filters() if item.filters else None
            result = search_without_ai(engine, item.query, company_id, item.limit, filters=fixed)
            out.append({"query": item.query, **result_payload(result, company_id)})
        return {"searches": out}

    @app.post("/search/image")
    def search_image(body: ImageSearchIn, request: Request) -> dict[str, Any]:
        """Search with a photo, render or drawing. Claude identifies the part and makes a search text;
        then the normal search (with judging) runs. Nothing is stored. Needs the AI."""
        company_id = company_for(request, body.company_id)
        if app.state.finder is None:
            raise HTTPException(503, f"Search by image needs the AI: {app.state.ai_note or 'not available'}")
        if not ai_sees_all(company_id):
            raise HTTPException(403, "Search by photo sends the photo to an outside AI. " + AI_OFF.split(";")[0] + ".")
        data = body.image_base64.split(",", 1)[1] if body.image_base64.startswith("data:") else body.image_base64
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(400, "The image is not valid base64") from exc
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "The image is larger than 10 MB")
        try:
            seen = app.state.finder.identify_image(base64.b64encode(raw).decode("ascii"), body.media_type, body.note)
        except AIError as exc:
            raise HTTPException(502, str(exc)) from exc
        if not seen["is_mechanical_part"] or not seen["search_query"]:
            return {"identified": seen, "status": "none", "ai_used": True,
                    "message": "The image does not show a technical part that can be searched for.",
                    "interpreted_requirements": {}, "results": []}
        query = seen["search_query"]
        log(request, company_id, "search_image", "", query)
        fixed = body.filters.to_filters() if body.filters else None
        within = within_filters(company_id, body.within)
        if within is not None:
            fixed = merge_filters(fixed or SearchFilters(), within)
        try:
            result = app.state.finder.find(query, as_ai(company_id), body.limit, fixed_filters=fixed)
        except AIError as exc:
            result = search_without_ai(engine, query, company_id, body.limit, reason=str(exc), filters=fixed)
        return {"identified": seen, "query": query, **result_payload(result, company_id)}

    @app.get("/parts/{part_id}")
    def get_part(request: Request, part_id: str, company_id: str | None = None) -> dict[str, Any]:
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
            payload = part_payload(part, company_id)
            components = repo.get_components(part_id, company_id) if part.kind == "assembly" else []
            used_in = repo.used_in(part_id, company_id)
        payload["components"] = [{"id": c.part.id, "name": c.part.name, "quantity": c.quantity}
                                 for c in components]
        # where used: the assemblies (this company may see) that contain this part
        payload["used_in"] = [{"id": a.part.id, "name": a.part.name, "quantity": a.quantity} for a in used_in]
        return payload

    def similar_payload(found: list[dict[str, Any]], company_id: str | None) -> list[dict[str, Any]]:
        return [{**part_payload(f["part"], company_id), "similarity": f["similarity"],
                 "dims_diff_mm": f["dims_diff_mm"]} for f in found]

    @app.get("/parts/{part_id}/similar")
    def similar_parts(request: Request, part_id: str, company_id: str | None = None,
                      limit: int = Query(default=5, ge=1, le=20),
                      same_category: bool = False) -> dict[str, Any]:
        """Parts with a similar shape (outer dimensions + volume), for the requesting company."""
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
            if not part.bbox_mm:
                raise HTTPException(400, "This part has no dimensions to compare with")
            found = find_similar(repo, part.bbox_mm, part.volume_mm3, company_id, kind=part.kind,
                                 category=part.category_path if same_category else None,
                                 exclude_id=part.id, limit=limit)
            results = similar_payload(found, company_id)
        return {"reference": part.id, "results": results}

    @app.post("/search/shape")
    async def search_shape(request: Request, company_id: str | None = None,
                           filename: str = Query(default="model.step", description="determines the format: step, stp or stl"),
                           limit: int = Query(default=5, ge=1, le=20),
                           kind: Literal["part", "assembly"] | None = None) -> dict[str, Any]:
        """Search by a CAD file: the body is the file itself (STEP or STL, max 50 MB). Nothing is
        stored; only outer dimensions and volume are measured and compared."""
        company_id = company_for(request, company_id)
        fmt = Path(filename).suffix.lower().lstrip(".")
        if fmt not in ANALYZABLE:
            raise HTTPException(400, "Only step, stp or stl can be measured")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length header") from None
        if declared > MAX_SHAPE_BYTES:
            raise HTTPException(413, "File is larger than 50 MB")
        data = await request.body()
        if not data or len(data) > MAX_SHAPE_BYTES:
            raise HTTPException(400 if not data else 413, "Empty file" if not data else "File is larger than 50 MB")

        def work() -> dict[str, Any]:
            with tempfile.TemporaryDirectory(prefix="partsfinder_shape_") as tmp:
                path = Path(tmp) / f"search.{fmt}"
                path.write_bytes(data)
                try:
                    geom = analyze(path)
                except Exception as exc:                      # broken or unreadable file
                    raise HTTPException(400, f"The file could not be read: {exc}") from exc
            if geom is None or not geom.bbox_mm:
                raise HTTPException(400, "No shape could be extracted from this file")
            with lock:
                found = find_similar(repo, geom.bbox_mm, geom.volume_mm3, company_id, kind=kind, limit=limit)
                results = similar_payload(found, company_id)
            return {"measured": {"dims_mm": [round(x, 2) for x in geom.bbox_mm],
                                 "volume_mm3": round(geom.volume_mm3, 1) if geom.volume_mm3 else None},
                    "results": results}

        return await run_in_threadpool(work)

    @app.get("/parts/{part_id}/file")
    def get_file(request: Request, part_id: str, company_id: str | None = None,
                 format: str | None = Query(default=None, description="e.g. step, stl, sldprt")) -> FileResponse:
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
        files = part.files
        chosen = next((f for f in files if f.format == format.lower().lstrip(".")), None) if format \
            else next((f for f in files if f.is_primary), files[0] if files else None)
        if chosen is None:
            raise HTTPException(404, f"No file in format '{format}' for this part")
        path = _resolve(chosen.path)
        if not path.is_file():
            raise HTTPException(410, "The file is no longer at the stored location")
        log(request, company_id, "download", part.id, chosen.format)
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/parts/{part_id}/thumbnail")
    def get_thumbnail(request: Request, part_id: str, company_id: str | None = None) -> FileResponse:
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
        if not part.thumbnail_path or not _resolve(part.thumbnail_path).is_file():
            raise HTTPException(404, "No preview for this part")
        return FileResponse(_resolve(part.thumbnail_path), media_type="image/png")

    @app.get("/parts/{part_id}/mesh")
    def get_mesh(request: Request, part_id: str, company_id: str | None = None) -> FileResponse:
        """Binary STL for the 3D viewer. From the STL file, or tessellated from STEP once and cached."""
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
        source = preview.mesh_source(part, _resolve)
        if source is None:
            raise HTTPException(404, "No STEP or STL file to show in 3D for this part")
        try:
            path = preview.mesh_file(source, s.data_dir / "meshes", part.id)
        except Exception as exc:                      # broken file: say so, do not crash the server
            raise HTTPException(422, f"The model could not be prepared for 3D: {exc}") from exc
        log(request, company_id, "mesh", part.id)
        return FileResponse(path, media_type="model/stl", filename=f"{part.id}.stl")

    @app.get("/parts/{part_id}/datasheet", response_class=HTMLResponse)
    def get_datasheet(request: Request, part_id: str, company_id: str | None = None) -> HTMLResponse:
        """Printable datasheet of one part (HTML; print -> Save as PDF)."""
        company_id = company_for(request, company_id)
        with lock:
            part = get_visible(part_id, company_id)
        thumb = _url(f"/parts/{part.id}/thumbnail", company_id) if part.thumbnail_path else None
        log(request, company_id, "datasheet", part.id)
        return HTMLResponse(preview.datasheet_html(part, thumb, date.today().isoformat()))

    def report_payload(report) -> dict[str, Any]:
        return {
            "added": report.added, "updated": report.updated, "skipped": report.skipped, "removed": report.removed,
            "needs_review": report.needs_review,
            "failed": [{"file": f, "error": e} for f, e in report.failed],
            "warnings": report.warnings, "components_linked": report.components_linked,
            "seconds": round(report.seconds, 1), "summary": report.summary(),
        }

    jobs: dict[str, dict[str, Any]] = {}          # background import; at most one at a time
    jobs_lock = threading.Lock()
    row_dim = conn.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()
    db_dim = int(row_dim[0]) if row_dim else s.embedding_dim      # the import connection must use the same dimension
    db_file = next((r["file"] for r in conn.execute("PRAGMA database_list") if r["name"] == "main"), "")

    def run_job(job_id: str, folder: Path, company_id: str | None, use_ai: bool, thumbnails: bool,
                sync: bool = False, allow_mass_removal: bool = False, actor: str = "local") -> None:
        """Own database connection, so searching keeps working during the import (WAL)."""
        job = jobs[job_id]
        job_conn = None
        try:
            job_conn = connect(db_file, db_dim, check_same_thread=False)
            job_repo = Repository(job_conn, repo.taxonomy)
            enricher = None
            if use_ai and app.state.finder is not None:
                enricher = ClaudeEnricher(None, app.state.finder.model, repo.taxonomy, client=app.state.finder.client)

            def log(line: str) -> None:
                job["log_tail"] = (job["log_tail"] + [line])[-8:]
                job["lines"] += 1

            report = ingest_folder(folder, job_repo, embedder, company_id=company_id, enricher=enricher,
                                   make_thumbnails=thumbnails, log=log, sync=sync,
                                   allow_mass_removal=allow_mass_removal, data_dir=s.data_dir)
            job_repo.audit(actor, company_id, "ingest", str(folder), _ingest_detail(report, sync))
            job["report"] = report_payload(report)
            job["status"] = "done"
        except Exception as exc:                    # the job must never disappear silently
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["status"] = "error"
        finally:
            if job_conn is not None:
                job_conn.close()

    def start_job(folder: Path, company_id: str | None, use_ai: bool, thumbnails: bool, sync: bool,
                  allow_mass_removal: bool, actor: str, before: Any = None) -> dict[str, Any]:
        """Import in the background (one at a time). before(): runs in the job first (e.g. moving an upload)."""
        with jobs_lock:
            if any(j["status"] == "running" for j in jobs.values()):
                raise HTTPException(409, "An import is already running; try again when it is done")
            job_id = uuid.uuid4().hex[:12]
            jobs[job_id] = {"job_id": job_id, "status": "running", "folder": str(folder),
                            "company_id": company_id, "lines": 0, "log_tail": []}
            for old in list(jobs)[:-20]:         # clean up old jobs
                jobs.pop(old, None)

        def go() -> None:
            if before is not None:
                try:
                    before()
                except Exception as exc:         # noqa: BLE001 - reported in the job
                    jobs[job_id].update(status="error", error=f"{type(exc).__name__}: {exc}")
                    return
            run_job(job_id, folder, company_id, use_ai, thumbnails, sync, allow_mass_removal, actor)
        threading.Thread(target=go, daemon=True, name=f"import-{job_id}").start()
        return {"job_id": job_id, "status": "running"}

    @app.post("/ingest")
    def ingest(body: IngestIn, request: Request) -> dict[str, Any]:
        require_admin(request)
        if body.company_id is not None and not COMPANY_ID.fullmatch(body.company_id):
            raise HTTPException(400, "A company id has 2-40 characters: a-z, 0-9, - or _")
        folder = Path(body.folder).expanduser()
        if not folder.is_dir():
            raise HTTPException(400, f"Folder does not exist: {folder}")
        if body.background and db_file:
            return start_job(folder, body.company_id, body.use_ai, body.thumbnails, body.sync,
                             body.allow_mass_removal, actor_of(request))
        enricher = None
        if body.use_ai and app.state.finder is not None:
            enricher = ClaudeEnricher(None, app.state.finder.model, repo.taxonomy, client=app.state.finder.client)
        with lock:
            report = ingest_folder(folder, repo, embedder, company_id=body.company_id, enricher=enricher,
                                   make_thumbnails=body.thumbnails, log=lambda _: None, sync=body.sync,
                                   allow_mass_removal=body.allow_mass_removal, data_dir=s.data_dir)
            repo.audit(actor_of(request), body.company_id, "ingest", str(folder), _ingest_detail(report, body.sync))
            answers.clear()
        return report_payload(report)

    @app.post("/remove")
    def remove(body: RemoveIn, request: Request) -> dict[str, Any]:
        """Admin: remove every part of this library whose file lies in this folder, completely (database
        rows, search entries, previews, 3D caches, feedback). The folder itself is not touched."""
        require_admin(request)
        with lock:
            removed = remove_folder(repo, body.folder, body.company_id, s.data_dir)
            repo.audit(actor_of(request), body.company_id, "remove", body.folder, f"{len(removed)} parts")
            answers.clear()
        return {"removed": removed, "total": len(removed)}

    @app.get("/ingest/{job_id}")
    def ingest_status(job_id: str, request: Request, company_id: str | None = None) -> dict[str, Any]:
        job = jobs.get(job_id)
        if request.state.scope not in (None, auth.ADMIN):
            # a company sees only the imports of its own library
            own = uploader(request, company_id)
            if job is not None and job.get("company_id") != own:
                job = None
        if job is None:
            raise HTTPException(404, "Unknown import")
        return dict(job)

    # ---- a company's own library: upload a folder from its own pc, update or remove it -------------
    def uploader(request: Request, claimed: str | None) -> str:
        """The company whose library this request may change. A company account or key: only its own; the
        admin (or this pc without accounts): the one it names. Never an AI client, never without sign-in."""
        entry = request.state.scope
        if entry == PUBLIC:
            raise HTTPException(401, "Sign in to change a company library")
        if request.headers.get(AI_HEADER, "").strip() == "1":
            raise HTTPException(403, "An AI client cannot change a library")
        if entry is None or entry == auth.ADMIN:
            company = (claimed or "").strip().lower()
            if not COMPANY_ID.fullmatch(company):
                raise HTTPException(400, "Name the company (company_id)")
            return company
        company, _groups = auth.split_scope(entry)
        if claimed not in (None, company):
            raise HTTPException(403, "This account does not apply to that company")
        return company

    def uploads_dir(company: str) -> Path:
        return s.data_dir / "companies" / company / "uploads"

    def folder_name(name: str) -> str:
        name = (name or "").strip().rstrip(". ")
        if not UPLOAD_NAME.fullmatch(name):
            raise HTTPException(400, "A folder name has 1-80 characters: letters, digits, spaces, '.', '_', '-', '(' or ')'")
        return name

    def company_groups(company: str) -> list[str]:
        """Every restricted group this company uses: on parts, on folders, given to people."""
        with lock:
            found = {g for (v,) in conn.execute("SELECT DISTINCT access_group FROM parts WHERE company_id = ? "
                                                "AND access_group IS NOT NULL", (company,)) for g in split_groups(v)}
            found |= {g for (v,) in conn.execute("SELECT access FROM folder_access WHERE company_id = ? AND access != 'company'",
                                                 (company,)) for g in split_groups(v)}
            for (g,) in conn.execute("SELECT groups FROM users WHERE company_id = ?", (company,)):
                found |= set(json.loads(g or "[]"))
        return sorted(found)

    def apply_folder_access(company: str, name: str, target: Path) -> None:
        """Write the folder settings made in the app as .partsfinderaccess files into the uploaded folder."""
        with lock:
            rows = conn.execute("SELECT path, access FROM folder_access WHERE company_id = ? AND upload = ?",
                                (company, name)).fetchall()
        for path, access in rows:
            d = target.joinpath(*PurePosixPath(path).parts) if path else target
            if d.is_dir():
                (d / ACCESS_FILE).write_text(f"{access}\n", encoding="utf-8")

    def caller_groups(request: Request) -> frozenset[str] | None:
        """The restricted groups of the caller; None for the admin (and this pc without accounts): every group."""
        entry = request.state.scope
        return None if entry in (None, auth.ADMIN) else auth.split_scope(entry)[1]

    def wanted_access(value: str, mine: frozenset[str] | None) -> str:
        """'inherit', 'company' or the groups, checked. A company account can only choose groups it has itself."""
        access = value.strip().lower()
        if access in ("inherit", "company"):
            return access
        try:
            access = join_groups(access) or ""
        except ValueError:
            access = ""
        if not access:
            raise HTTPException(400, "A restricted group is one word: a-z, 0-9, - or _ (for example nuclear); "
                                     "several are separated by commas")
        if mine is not None and not set(split_groups(access)) <= mine:
            raise HTTPException(403, "You can only choose restricted groups you have yourself")
        return access

    def may_change(target: Path, rel: PurePosixPath, mine: frozenset[str] | None) -> None:
        """A company account changes who sees a folder only when everyone at the company sees it now, or only
        groups it has itself: never a folder the administrator closed to it."""
        if mine is None:
            return
        now = current_access(target, rel)
        if now != "company" and (now == "invalid" or not set(split_groups(now)) <= mine):
            raise HTTPException(403, "This folder is restricted to a group you do not have; "
                                     "ask the administrator to change it")

    def save_access(company: str, name: str, path: str, access: str) -> None:
        with lock, conn:
            conn.execute("DELETE FROM folder_access WHERE company_id = ? AND upload = ? AND path = ?", (company, name, path))
            if access != "inherit":
                conn.execute("INSERT INTO folder_access(company_id, upload, path, access) VALUES (?,?,?,?)",
                             (company, name, path, access))

    @app.put("/uploads/{name}/access")
    def folder_access(name: str, body: FolderAccessIn, request: Request, company_id: str | None = None) -> dict[str, Any]:
        """Who may see an uploaded folder or one of its subfolders: everyone of the company, only people with
        a restricted group, or the same as the folder above ('inherit'). The admin chooses any group; a company
        account only groups it has, and only for folders it can see now. The folder is imported again (sync) so
        its parts follow at once; the setting is written into the folder again after every upload."""
        company, name = uploader(request, company_id), folder_name(name)
        mine = caller_groups(request)
        target = uploads_dir(company) / name
        rel = upload_dir_path(body.path)
        d = target.joinpath(*rel.parts) if rel.parts else target
        if not target.is_dir() or not d.is_dir():
            raise HTTPException(404, "Unknown folder")
        access = wanted_access(body.access, mine)
        may_change(target, rel, mine)
        path = rel.as_posix() if rel.parts else ""
        save_access(company, name, path, access)
        if access == "inherit":
            (d / ACCESS_FILE).unlink(missing_ok=True)
        else:
            (d / ACCESS_FILE).write_text(f"{access}\n", encoding="utf-8")
        log(request, company, "settings", f"upload:{name}/{path}", f"access={access}")
        return start_job(target, company, False, True, True, True, actor_of(request))

    @app.delete("/companies/{company_id}")
    def delete_company(company_id: str, request: Request) -> dict[str, Any]:
        """Admin: remove a company completely: every part of it (search entries, previews, 3D caches, feedback),
        its accounts and their sessions, its folder settings and the folders it uploaded. Files it was imported
        from elsewhere (a share) are not touched."""
        require_admin(request)
        if any(j["status"] == "running" and j.get("company_id") == company_id for j in jobs.values()):
            raise HTTPException(409, "An import for this company is running; try again when it is done")
        with lock:
            if not conn.execute("SELECT 1 FROM companies WHERE id = ?", (company_id,)).fetchone():
                raise HTTPException(404, "Unknown company")
            ids = [r[0] for r in conn.execute("SELECT id FROM parts WHERE company_id = ?", (company_id,))]
            removed = remove_parts(repo, ids, company_id, s.data_dir)
            with conn:
                conn.execute("DELETE FROM feedback WHERE company_id = ?", (company_id,))
                people = conn.execute("SELECT count(*) FROM users WHERE company_id = ?", (company_id,)).fetchone()[0]
                conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))   # accounts, sessions, folder settings
            answers.clear()
        if COMPANY_ID.fullmatch(company_id):            # never a path outside data/companies/<id>/uploads
            shutil.rmtree(uploads_dir(company_id), ignore_errors=True)
        log(request, company_id, "remove", f"company:{company_id}", f"{len(removed)} parts, {people} accounts")
        return {"removed_parts": len(removed), "removed_accounts": people}

    @app.get("/library")
    def library(request: Request, company_id: str | None = None) -> dict[str, Any]:
        """A company's own library: its parts, restricted parts, the folders it uploaded, and how complete
        the data is. The admin names the company."""
        company = uploader(request, company_id)
        root = uploads_dir(company)
        with lock:
            row = conn.execute(
                """SELECT c.id, c.name, c.confidential, count(p.pk) AS parts, count(p.access_group) AS restricted
                   FROM companies c LEFT JOIN parts p ON p.company_id = c.id WHERE c.id = ? GROUP BY c.id""",
                (company,)).fetchone()
            paths = repo.primary_paths(company)
            # what this caller may see of it: the admin everything, a company account its own groups too
            entry = request.state.scope
            seen = full(company) if entry in (None, auth.ADMIN) else Scope(company, auth.split_scope(entry)[1])
            quality = repo.quality_report(seen, worst=0) if row else None
        folders = []
        if root.is_dir():
            for d in sorted((x for x in root.iterdir() if x.is_dir() and not x.name.startswith(".")),
                            key=lambda x: x.name.lower()):
                n = sum(1 for _pid, path in paths if _under(path, d))
                tree = folder_tree(d, [p for _pid, p in paths])
                folders.append({"name": d.name, "parts": n, "access": tree[0]["access"] if tree else "company",
                                "updated_at": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="minutes"),
                                "tree": tree})
        uploaded = sum(f["parts"] for f in folders)
        return {"company_id": company, "name": row["name"] if row else company, "exists": row is not None,
                "confidential": bool(row["confidential"]) if row else False,
                "parts": row["parts"] if row else 0, "restricted_parts": row["restricted"] if row else 0,
                "other_parts": (row["parts"] if row else 0) - uploaded,
                # how complete the data is, over the parts this person can see (none: nothing to say)
                "folders": folders, "coverage": quality["coverage"] if quality and quality["total"] else {},
                "groups": company_groups(company),
                # what this caller can choose in "who sees it": the admin every group (and new ones), a company
                # account the groups it has itself
                "my_groups": None if caller_groups(request) is None else sorted(caller_groups(request)),
                "upload_extensions": UPLOAD_EXTENSIONS, "max_file_mb": MAX_UPLOAD_MB}

    @app.post("/uploads/{name}/start")
    def upload_start(name: str, request: Request, company_id: str | None = None) -> dict[str, Any]:
        """Start uploading a folder. The files go to a staging area first; only "finish" replaces the folder,
        so a broken upload never changes the library."""
        company, name = uploader(request, company_id), folder_name(name)
        staging = uploads_dir(company) / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        for old in staging.iterdir():                  # uploads left over from a day ago
            if old.is_dir() and time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
        upload_id = uuid.uuid4().hex[:16]
        (staging / upload_id).mkdir()
        (staging / upload_id / ".partsfinder-upload").write_text(name, encoding="utf-8")
        return {"upload_id": upload_id, "company_id": company, "name": name}

    @app.put("/uploads/{name}/files")
    async def upload_file(name: str, request: Request, upload_id: str = Query(pattern=r"^[0-9a-f]{16}$"),
                          path: str = Query(min_length=1, max_length=400), company_id: str | None = None) -> dict[str, Any]:
        """One file of the folder (raw bytes), at its path relative to the folder."""
        company, name = uploader(request, company_id), folder_name(name)
        base = uploads_dir(company) / ".staging" / upload_id
        if not base.is_dir() or (base / ".partsfinder-upload").read_text(encoding="utf-8") != name:
            raise HTTPException(404, "Unknown upload: start it again")
        rel = upload_path(path)
        target = base.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        size, limit = 0, MAX_UPLOAD_MB * 1024 * 1024
        try:
            with open(target, "wb") as fh:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"{rel.name} is larger than {MAX_UPLOAD_MB} MB")
                    fh.write(chunk)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return {"path": rel.as_posix(), "bytes": size}

    @app.post("/uploads/{name}/finish")
    def upload_finish(name: str, body: UploadFinishIn, request: Request) -> dict[str, Any]:
        """Replace the folder with the uploaded files and import it (in the background): new and changed files
        are imported, files that are no longer in the folder leave the library completely."""
        company, name = uploader(request, body.company_id), folder_name(name)
        root = uploads_dir(company)
        staged = root / ".staging" / body.upload_id
        if not staged.is_dir() or (staged / ".partsfinder-upload").read_text(encoding="utf-8") != name:
            raise HTTPException(404, "Unknown upload: start it again")
        cad = [p for p in staged.rglob("*") if p.is_file() and p.suffix.lower().lstrip(".") in CAD_FORMATS]
        if not cad:
            raise HTTPException(400, "The upload has no CAD file; nothing was changed")
        target = root / name
        access = None
        if body.access is not None:
            mine = caller_groups(request)
            access = wanted_access(body.access, mine)
            if access == "inherit":
                raise HTTPException(400, "Choose 'company' or the restricted groups")
            if target.is_dir():
                may_change(target, PurePosixPath(), mine)

        def swap() -> None:
            if access is not None:
                save_access(company, name, "", access)
            (staged / ".partsfinder-upload").unlink(missing_ok=True)
            old = root / ".staging" / f"old-{body.upload_id}"
            if target.exists():
                target.rename(old)
            staged.rename(target)
            shutil.rmtree(old, ignore_errors=True)
            apply_folder_access(company, name, target)       # who may see which folder, as set in the app
        with lock, conn:                                # committed: the import has its own connection
            repo.ensure_company(company)
        # the whole folder was sent again: removing what is no longer in it is the point, not a half-mounted share
        return start_job(target, company, body.use_ai, True, True, True, actor_of(request), before=swap)

    @app.delete("/uploads/{name}")
    def upload_remove(name: str, request: Request, company_id: str | None = None) -> dict[str, Any]:
        """Remove an uploaded folder: every part from it, completely, and the files themselves."""
        company, name = uploader(request, company_id), folder_name(name)
        target = uploads_dir(company) / name
        if not target.is_dir():
            raise HTTPException(404, "Unknown folder")
        with lock:
            removed = remove_folder(repo, target, company, s.data_dir)
            repo.audit(actor_of(request), company, "remove", f"upload:{name}", f"{len(removed)} parts")
            with conn:
                conn.execute("DELETE FROM folder_access WHERE company_id = ? AND upload = ?", (company, name))
            answers.clear()
        shutil.rmtree(target, ignore_errors=True)
        return {"removed": removed, "total": len(removed)}

    @app.post("/feedback")
    def post_feedback(body: FeedbackIn, request: Request) -> dict[str, Any]:
        """Thumbs up/down for a found part. Stays in the local database."""
        company_id = company_for(request, body.company_id)
        try:
            with lock:
                fid = repo.add_feedback(body.part_id, company_id, body.rating, body.query, body.note)
        except AccessError:
            raise HTTPException(404, "Part not found") from None
        return {"id": fid, "status": "saved"}

    @app.get("/feedback")
    def get_feedback(request: Request, company_id: str | None = None,
                     limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        company_id = company_for(request, company_id)
        with lock:
            return repo.list_feedback(company_id, limit)

    @app.get("/quality")
    def quality(request: Request, company_id: str | None = None) -> dict[str, Any]:
        """Completeness of the data in the own library of this company (or the general one)."""
        company_id = company_for(request, company_id)
        with lock:
            return repo.quality_report(company_id)

    @app.get("/duplicates")
    def duplicates(request: Request, company_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Probable duplicates (equal outer dimensions and volume) in the own library."""
        company_id = company_for(request, company_id)
        limit = max(1, min(int(limit), 500))
        with lock:
            groups = find_duplicates(repo, company_id, limit=limit)
        return {"groups": groups, "total": len(groups)}

    @app.get("/taxonomy")
    def taxonomy() -> dict[str, Any]:
        t = repo.taxonomy
        return {"categories": t.categories, "category_paths": t.all_category_paths(), "sectors": t.sectors}

    @app.get("/properties")
    def properties(request: Request, company_id: str | None = None,
                   category: str | None = None) -> list[dict[str, Any]]:
        """Which properties you can filter on (only parts this company may see)."""
        company_id = company_for(request, company_id)
        with lock:
            return repo.property_overview(company_id, category)

    @app.get("/filters")
    def filter_options(request: Request, company_id: str | None = None, category: str | None = None) -> dict[str, Any]:
        """What the Filters panel can offer, from the parts this company may see (within the category, if given):
        categories, materials, colours, standards, kinds, the largest sizes, the engineering values parts state
        and the properties (as GET /properties), each with how many parts have it."""
        company_id = company_for(request, company_id)

        def compute() -> tuple[dict[str, Any], bool]:
            with lock:
                return repo.facets(company_id, category), True
        # reading every part once per library version, not once per opened panel
        out = remembered(("filters", category or "", scope_key(company_id)), compute)
        return {k: v for k, v in out.items() if k != "cached"}

    @app.get("/audit")
    def audit(request: Request, company_id: str | None = None, action: str | None = None,
              limit: int = Query(default=200, ge=1, le=5000)) -> list[dict[str, Any]]:
        """Admin: who searched for and downloaded what, newest first, per company (without company_id:
        the general library)."""
        require_admin(request)
        with lock:
            return repo.audit_entries(company_id, limit, action)

    @app.get("/companies")
    def companies(request: Request) -> list[dict[str, Any]]:
        require_admin(request)
        with lock:
            rows = conn.execute(
                """SELECT c.id, c.name, c.confidential, count(p.pk) AS parts,
                          count(p.access_group) AS restricted FROM companies c
                   LEFT JOIN parts p ON p.company_id = c.id GROUP BY c.id ORDER BY c.id""").fetchall()
            people = dict(conn.execute("SELECT company_id, count(*) FROM users WHERE company_id IS NOT NULL "
                                       "GROUP BY company_id").fetchall())
        return [{"id": r["id"], "name": r["name"], "parts": r["parts"], "restricted_parts": r["restricted"],
                 "confidential": bool(r["confidential"]), "people": people.get(r["id"], 0),
                 "groups": company_groups(r["id"])} for r in rows]

    @app.post("/companies")
    def create_company(body: CompanyIn, request: Request) -> dict[str, Any]:
        """Admin: a new company with its own, empty library. The id (used in links and by its people) is made
        from the name unless given: "Janssen Engineering" -> "janssen-engineering"."""
        require_admin(request)
        name = " ".join(body.name.split())
        cid = (body.id or company_slug(name)).strip().lower()
        if not COMPANY_ID.fullmatch(cid):
            raise HTTPException(400, "A company id has 2-40 characters: a-z, 0-9, - or _")
        with lock:
            if conn.execute("SELECT 1 FROM companies WHERE id = ?", (cid,)).fetchone():
                raise HTTPException(409, f"There is already a company '{cid}'")
            with conn:
                repo.ensure_company(cid, name)
        log(request, cid, "settings", cid, "company created")
        return {"id": cid, "name": name, "parts": 0, "restricted_parts": 0, "confidential": False, "people": 0}

    @app.post("/companies/{company_id}/settings")
    def company_settings(company_id: str, body: CompanySettingsIn, request: Request) -> dict[str, Any]:
        """Admin: a confidential company never has any part sent to an outside AI."""
        require_admin(request)
        with lock:
            if not conn.execute("SELECT 1 FROM companies WHERE id = ?", (company_id,)).fetchone():
                raise HTTPException(404, "Unknown company")
            repo.set_confidential(company_id, body.confidential)
            answers.clear()                             # remembered answers may have used the AI
        log(request, company_id, "settings", company_id, f"confidential={body.confidential}")
        return {"id": company_id, "confidential": body.confidential}

    return app


def main() -> int:
    import argparse

    import uvicorn

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    ap = argparse.ArgumentParser(prog="python -m partsfinder.api")
    ap.add_argument("--host", default="127.0.0.1", help="by default only this computer")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()
    if not is_local_host(args.host) and not get_settings().api_keys and not _has_accounts():
        # without keys or accounts anyone who can reach this port could read every company's library
        print("Refusing to listen on a network address without API keys or accounts. Make the admin account "
              "in the app first, or set PARTSFINDER_API_KEYS (see docs/10_COMPANY_LIBRARIES.md), or keep --host 127.0.0.1.")
        return 2

    print("Starting the Partsfinder API (loading the AI model, please wait)...")
    app = create_app(enable_ai=not args.no_ai)
    app.state.public_url = f"http://127.0.0.1:{args.port}"
    app.state.engine.embedder.embed_query("warm up")      # load the model now, not at the first question
    print(health_line(app))
    print(f"Ready. Try it at http://{args.host}:{args.port}/docs  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _has_accounts() -> bool:
    s = get_settings()
    if not Path(s.db_path).exists():
        return False
    conn = connect(s.db_path, s.embedding_dim)
    try:
        return Accounts(conn).any()
    finally:
        conn.close()


def _ingest_detail(report: Any, sync: bool) -> str:
    return (f"added {len(report.added)}, updated {len(report.updated)}, removed {len(report.removed)}, "
            f"failed {len(report.failed)}{', sync' if sync else ''}")


COMPANY_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
UPLOAD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]{0,79}$")
RULE_FILES = {".partsfinderaccess", ".partsfinderignore"}
UPLOAD_EXTENSIONS = sorted(CAD_FORMATS | {"json"})
MAX_UPLOAD_MB = int(os.getenv("PARTSFINDER_UPLOAD_MAX_MB") or 500)


def upload_dir_path(path: str) -> PurePosixPath:
    """A subfolder inside an uploaded folder ('' = the folder itself): relative, no '..', no hidden folders."""
    rel = PurePosixPath((path or "").replace("\\", "/").strip("/"))
    if rel.parts and (rel.is_absolute() or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in rel.parts)):
        raise HTTPException(400, f"Not a folder in this upload: {path}")
    return rel


def current_access(root: Path, rel: PurePosixPath) -> str:
    """Who sees this folder now: 'company', the groups, or 'invalid' (the deepest .partsfinderaccess on the way)."""
    access, d = "company", root
    for part in ("", *rel.parts):
        d = d / part if part else d
        if (d / ACCESS_FILE).is_file():
            try:
                access = parse_access(d / ACCESS_FILE) or "company"
            except RuleError:
                access = "invalid"
    return access


def folder_tree(root: Path, part_paths: list[str]) -> list[dict[str, Any]]:
    """The folder and its subfolders that hold parts, each with who may see it: 'company', a group, or 'invalid'
    (an unusable .partsfinderaccess: that folder is skipped at import). 'own' = set in this folder itself."""
    out: list[dict[str, Any]] = []
    effective: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        here = Path(dirpath)
        rel = "" if here == root else here.relative_to(root).as_posix()
        parent = effective.get(rel.rpartition("/")[0] if "/" in rel else "", "company") if rel else "company"
        own = None
        if ACCESS_FILE in filenames:
            try:
                own = parse_access(here / ACCESS_FILE) or "company"
            except RuleError:
                own = "invalid"
        effective[rel] = own or parent
        n = sum(1 for p in part_paths if _under(p, here))
        if n or not rel:
            out.append({"path": rel, "depth": rel.count("/") + 1 if rel else 0, "parts": n,
                        "own": own, "access": effective[rel], "inherited": parent})
    return out


def company_slug(name: str) -> str:
    """"Janssen Engineering B.V." -> "janssen-engineering-b-v" (a-z, 0-9 and '-', at most 40)."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:40].strip("-")


def upload_path(path: str) -> PurePosixPath:
    """A file's path inside an uploaded folder: relative, no '..', no drive, a CAD file, a JSON next to it or a
    folder rule (.partsfinderaccess / .partsfinderignore). Anything else is refused before a byte is written."""
    rel = PurePosixPath(path.replace("\\", "/"))
    parts = rel.parts
    bad = (not parts or rel.is_absolute() or len(parts) > 25
           or any(p in ("", ".", "..") or p != p.strip() or any(ch in p for ch in ':<>"|?*') for p in parts)
           or any(p.startswith(".") for p in parts[:-1]))
    name = parts[-1] if parts else ""
    ok_name = name.lower() in RULE_FILES or (not name.startswith(".") and
                                              PurePosixPath(name).suffix.lower().lstrip(".") in UPLOAD_EXTENSIONS)
    if bad or not ok_name:
        raise HTTPException(400, f"Not accepted in an upload: {path}")
    return rel


PUBLIC = "public"            # rights of a request without sign-in on a server with accounts: the general library only
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_local_host(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1") or host.startswith("127.")


def health_line(app: FastAPI) -> str:
    parts = app.state.repo.count_parts(None)
    ai = f"AI: {ai_label(app.state.finder)}" if app.state.finder else f"AI: off ({app.state.ai_note or 'not configured'})"
    return f"{parts} parts in the general library, {ai}"


if __name__ == "__main__":
    sys.exit(main())
