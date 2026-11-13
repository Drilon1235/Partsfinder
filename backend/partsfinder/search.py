"""Search engine: hard filters + search by meaning + search by exact words.

Procedure per query:
1. Hard filters decide which parts may take part at all (company separation,
   category, sector, material, dimensions, ...). This happens in SQL.
2. Within that group: meaning score (cosine distance between embeddings) and
   keyword score (FTS5, bm25).
3. Both rankings are merged with Reciprocal Rank Fusion (RRF): whoever ranks high in
   both comes first. An exact standard (e.g. "DIN 933") gives extra points.

Scale: the meaning score is computed exactly for all parts that pass the filters.
That is fast enough up to roughly 100,000 parts; above that we switch to an
approximate index (see docs/02_ARCHITECTURE.md).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields
from typing import Any

import sqlite_vec

from . import engineering
from .ingest.embeddings import Embedder
from .models import Part
from .repository import Repository, _visible, like_literal
from .specs import (ALIASES as SPEC_ALIASES, KEY_SPECS, SpecSummary, kind_words, parse_preferences, parse_specs,
                    summarize)

RRF_K = 60
STANDARD_BOOST = 0.02          # roughly equal to "one extra first place" in RRF
COMPONENT_PENALTY = 0.85
FEEDBACK_BOOST = 0.015         # thumbs up/down of this company for exactly the same query: steer, never hide
COVERAGE_WEIGHT = 0.02        # how much it counts that (rare) search words really occur
# Engineering specs in the question (M8x30, 6204-2RS, NEMA 23, DN50, ...): checked per part (specs.py).
# Score -1..1 times this weight: an exact spec match beats a better text match, a wrong thread drops far.
SPEC_WEIGHT = 0.06
PREFERENCE_WEIGHT = 0.02      # "preferably A4": only the order, never the verdict
ENGINEERING_CANDIDATES = 400   # with an engineering filter: candidates looked at per ranking (checked per part)
ENGINEERING_BROWSE = 5000      # with an engineering filter and no search text: parts looked at (by name)
SPEC_CANDIDATES = 40          # extra candidates fetched directly on the key specs (properties)
KNN_FACTOR, KNN_MIN, KNN_MAX = 4, 200, 4096   # vector index: fetch extra so the filters still leave enough (max k of sqlite-vec)
SCAN_BELOW = 3000             # up to this many visible parts, comparing them all is fast enough (~25 ms)
KNN_MIN_SHARE = 0.3           # the index pays off when the question may see at least this share of all parts
# Without AI: "nothing found" if no result covers enough of the (idf-weighted) words of the question.
# Calibrated on tests/queries.yaml: questions without a matching part score at most ~0.32 (only a
# generic word matches, e.g. "machine" in "espresso machine"), questions with a matching part at least ~0.38.
MIN_WORD_COVERAGE = 0.35
# Units say something about the requirements, not about what the part is: they do not count for "nothing found"
UNIT_WORDS = {"mm", "cm", "m", "meter", "km", "inch", "kg", "gram", "g", "ton", "liter", "l", "ml", "watt", "w", "kw",
              "volt", "v", "kv", "ampere", "amp", "a", "ma", "bar", "psi", "pa", "kpa", "rpm", "nm", "hz", "khz",
              "degrees", "degree", "deg", "kwh", "mah", "ohm", "lumen", "lux", "db"}
STOPWORDS = {
    "the", "a", "an", "for", "with", "of", "to", "on", "in", "and", "or", "some", "something", "i",
    "need", "want", "looking", "that", "this", "it", "is", "can", "my", "we", "find", "search",
    "please", "which", "what", "must", "should", "one", "at", "by", "from", "me", "you", "our",
    # request phrasing ("make me ...", "can you give me ...", "I'd like ..."): says nothing about the part
    "make", "give", "get", "show", "draw", "create", "design", "provide", "send", "build", "model",
    "could", "would", "like", "us", "id", "im", "lets", "let", "have", "has", "do", "does", "got", "any",
    "d", "ll", "s", "ve", "re",                     # left over from I'd, I'll, let's, I've, we're
}


@dataclass
class SearchFilters:
    category: str | None = None                       # prefix, e.g. "furniture" or "furniture/seating"
    sectors: list[str] = field(default_factory=list)  # at least one of them
    material: str | None = None                       # part of the text, e.g. "stainless"
    color: str | None = None
    standards: list[str] = field(default_factory=list)
    kind: str | None = None                           # "part" or "assembly"
    min_dims_mm: tuple[float, float, float] | None = None   # compared regardless of orientation
    max_dims_mm: tuple[float, float, float] | None = None
    library: str = "all"                              # "all", "global" or "company"
    # Properties filter: key -> value (exact), True/False, or {"min": x, "max": y}
    properties: dict[str, Any] = field(default_factory=dict)
    # Engineering filter (engineering.meets): strength, load, mass, ... also where it follows from a standard
    # (property class 8.8 = at least 800 MPa), so it is checked per part after SQL, never in SQL
    engineering: dict[str, Any] = field(default_factory=dict)
    # which parts of the library, from the app's folder picker: (the general library, the company's parts that
    # were not uploaded, path prefixes of the chosen uploaded folders, the prefix of all its uploads); None = all
    within: tuple[bool, bool, tuple[str, ...], str] | None = None


_EMPTY = (None, [], {}, "all")
_PROP_KEY = re.compile(r"^[a-z0-9_]{1,60}$")


def merge_filters(base: SearchFilters, extra: SearchFilters | None) -> SearchFilters:
    """Fields filled in 'extra' take precedence; the rest comes from 'base'.
    Properties are merged (extra wins per key)."""
    if extra is None:
        return base
    values = {}
    for f in fields(SearchFilters):
        value = getattr(extra, f.name)
        values[f.name] = getattr(base, f.name) if value in _EMPTY else value
    values["properties"] = {**base.properties, **extra.properties}
    values["engineering"] = {**base.engineering, **extra.engineering}
    return SearchFilters(**values)


def filters_as_dict(f: SearchFilters | None) -> dict[str, Any]:
    if f is None:
        return {}
    return {k.name: getattr(f, k.name) for k in fields(SearchFilters)
            if getattr(f, k.name) not in _EMPTY}


def _number(key: str, value: Any) -> float:
    """A finite number, otherwise ValueError with a clear message (never TypeError/OverflowError)."""
    try:
        out = float(value) if not isinstance(value, bool) else float("nan")
    except (TypeError, ValueError, OverflowError):
        out = float("nan")
    if out != out or out in (float("inf"), float("-inf")):
        raise ValueError(f"Property '{key}': give a valid number")
    return out


def property_clauses(props: dict[str, Any]) -> tuple[list[str], list[Any]]:
    """SQL for the properties filter. The key is validated and passed as a parameter
    (never put in the SQL text)."""
    clauses: list[str] = []
    args: list[Any] = []
    for key, cond in props.items():
        if not _PROP_KEY.match(str(key)):
            raise ValueError(f"Invalid property '{key}' (only a-z, 0-9 and _)")
        path = f"$.{key}"
        if isinstance(cond, dict):
            unknown = set(cond) - {"min", "max"}
            if unknown or not cond:
                raise ValueError(f"Property '{key}': use only min and/or max")
            for op, name in ((">=", "min"), ("<=", "max")):
                if name in cond:
                    value = _number(key, cond[name])
                    clauses.append(f"CAST(json_extract(p.properties, ?) AS REAL) {op} ? "
                                   f"AND json_type(p.properties, ?) IN ('integer','real')")
                    args += [path, value, path]
        elif isinstance(cond, bool):
            clauses.append("json_extract(p.properties, ?) = ?")
            args += [path, int(cond)]
        elif isinstance(cond, (int, float)):
            clauses.append("json_type(p.properties, ?) IN ('integer','real') "
                           "AND CAST(json_extract(p.properties, ?) AS REAL) = ?")
            args += [path, path, _number(key, cond)]
        elif str(cond).strip().lower() in ("true", "false", "yes", "no", "ja", "nee"):
            # an AI or user writes "yes"/"true" as text; usually a real yes/no value is stored
            word = str(cond).strip().lower()
            flag = int(word in ("true", "yes", "ja"))
            clauses.append("(json_extract(p.properties, ?) = ? OR lower(CAST(json_extract(p.properties, ?) AS TEXT)) = ?)")
            args += [path, flag, path, word]
        else:
            clauses.append("lower(CAST(json_extract(p.properties, ?) AS TEXT)) = ?")
            args += [path, str(cond).strip().lower()]
    return clauses, args


def looks_relevant(hits: list["SearchHit"], threshold: float = MIN_WORD_COVERAGE) -> bool:
    """Does at least one word from the question really occur in one of the results?
    Questions without words (only filters or numbers) count as relevant."""
    if not hits:
        return False
    values = [h.word_coverage for h in hits if h.word_coverage is not None]
    return not values or max(values) >= threshold


@dataclass
class SearchHit:
    part: Part
    score: float
    vector_similarity: float | None
    keyword_rank: int | None
    vector_rank: int | None
    matched_standard: bool = False
    coverage: float | None = None      # share (0-1) of the search terms that really occur in this part
    word_coverage: float | None = None # same, words only (without loose numbers such as "400")
    specs: SpecSummary | None = None   # requested engineering specs versus this part

    def as_dict(self) -> dict[str, Any]:
        return {
            "part": self.part.model_dump(),
            "library": self.part.library,
            "score": round(self.score, 5),
            "vector_similarity": None if self.vector_similarity is None else round(self.vector_similarity, 4),
            "vector_rank": self.vector_rank,
            "keyword_rank": self.keyword_rank,
            "matched_standard": self.matched_standard,
            "coverage": None if self.coverage is None else round(self.coverage, 3),
            "word_coverage": None if self.word_coverage is None else round(self.word_coverage, 3),
            "spec_checks": [c.as_dict() for c in self.specs.checks] if self.specs else [],
        }


def _query_words(text: str) -> list[str]:
    words = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        # "25mm" -> "25", "m8x40" stays, but also yields "m8" and "40"
        w = re.sub(r"^(\d+(?:\.\d+)?)(mm|cm|m)$", r"\1", w)
        if w not in STOPWORDS:
            words.append(w)
            words += re.findall(r"m\d+(?=x)|(?<=x)\d+", w) if re.fullmatch(r"m\d+x\d+", w) else []
    return list(dict.fromkeys(words))


def _stem(w: str) -> str:
    """Very simple English stem: chairs -> chair, bolts -> bolt, batteries -> battery, tomatoes -> tomato."""
    if len(w) >= 5 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) >= 6 and w.endswith("oes"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _query_terms(text: str) -> list[tuple[str, bool]]:
    """Search terms as (term, prefix?)."""
    words = _query_words(text)
    terms: list[tuple[str, bool]] = []
    for w in words:
        stem = _stem(w)
        prefix = len(stem) >= 4 or bool(re.fullmatch(r"[a-z]\d+", stem))   # m6 -> also m6x25, m6x40, ...
        terms.append((stem, prefix))
    # thread size: "m6" + "25" -> also exactly "m6x25"
    threads = [w for w in words if re.fullmatch(r"m\d+", w)]
    numbers = [w for w in words if w.isdigit()]
    terms += [(f"{t}x{n}", False) for t in threads for n in numbers]
    return list(dict.fromkeys(terms))


def _fts_term(term: str, prefix: bool) -> str:
    return f'"{term}"*' if prefix else f'"{term}"'


def _fts_query(text: str) -> str | None:
    """Turn a user question into a safe FTS5 query (words with OR, prefix for longer ones)."""
    terms = _query_terms(text)
    return " OR ".join(_fts_term(t, p) for t, p in terms) if terms else None


def _term_in(term: str, prefix: bool, tokens: set[str]) -> bool:
    if prefix:
        return any(tok.startswith(term) for tok in tokens)
    if term.isdigit():                       # "25" also counts in "m6x25"
        return term in tokens or any(tok.endswith("x" + term) for tok in tokens)
    return term in tokens


def _part_tokens(part: Part) -> set[str]:
    text = " ".join([part.name, part.description, " ".join(part.tags), " ".join(part.standards),
                     part.material or "", part.color or "",
                     part.category_path.replace("/", " ").replace("-", " ")])
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def matched_query_words(query: str, part: Part) -> list[str]:
    """Which words from the question literally occur in this part (incl. properties such as thread: M8)?"""
    tokens = _part_tokens(part) | set(re.findall(
        r"[a-z0-9]+", " ".join(f"{k} {v}" for k, v in part.properties.items()).lower()))
    found = []
    for w in _query_words(query):
        stem = _stem(w)
        prefix = len(stem) >= 4 or bool(re.fullmatch(r"[a-z]\d+", stem))
        if _term_in(stem, prefix, tokens):
            found.append(w)
    return found


def _norm_standard(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class SearchEngine:
    def __init__(self, repo: Repository, embedder: Embedder):
        self.repo = repo
        self.embedder = embedder

    def general_properties(self) -> list[dict[str, Any]]:
        """Properties of the GENERAL library (never of a company), for the AI layer.
        Kept until the number of parts changes."""
        n = self.repo.count_parts(None)
        cache = getattr(self, "_prop_cache", None)
        if cache is None or cache[0] != n:
            cache = (n, self.repo.property_overview(None))
            self._prop_cache = cache
        return cache[1]

    # ---- filters -> SQL ---------------------------------------------------------
    def _filter_sql(self, company_id: str | None, f: SearchFilters) -> tuple[str, list[Any]]:
        where, params = _visible(company_id)
        clauses, args = [where], list(params)
        if f.library == "global":
            clauses.append("p.company_id IS NULL")
        elif f.library == "company":
            if company_id is None:
                clauses.append("0")
            else:
                clauses.append("p.company_id = ?")
                args.append(company_id)
        if f.within is not None:
            general, unlisted, prefixes, root = f.within
            path = ("replace(ifnull((SELECT pf.path FROM part_files pf WHERE pf.part_id = p.id AND pf.is_primary = 1 "
                    "LIMIT 1), ''), char(92), '/')")
            ors = ["p.company_id IS NULL"] if general else []
            for pre in prefixes:
                ors.append(f"(p.company_id IS NOT NULL AND substr({path}, 1, ?) = ?)")
                args += [len(pre), pre]
            if unlisted:
                ors.append(f"(p.company_id IS NOT NULL AND substr({path}, 1, ?) != ?)")
                args += [len(root), root]
            clauses.append("(" + " OR ".join(ors) + ")" if ors else "0")
        if f.category:
            prefix = f.category.strip("/").lower()
            clauses.append("(p.category_path = ? OR p.category_path LIKE ? ESCAPE '\\')")
            args += [prefix, like_literal(prefix) + "/%"]
        if f.sectors:
            marks = ",".join("?" * len(f.sectors))
            clauses.append(f"EXISTS (SELECT 1 FROM json_each(p.sectors) WHERE value IN ({marks}))")
            args += [s.lower() for s in f.sectors]
        if f.material:
            # "stainless-steel" and "stainless steel" are the same material
            clauses.append("replace(lower(ifnull(p.material, '')), '-', ' ') LIKE ? ESCAPE '\\'")
            args.append(f"%{like_literal(f.material.lower().replace('-', ' '))}%")
        if f.color:
            clauses.append("lower(ifnull(p.color, '')) LIKE ? ESCAPE '\\'")
            args.append(f"%{like_literal(f.color.lower())}%")
        if f.kind:
            clauses.append("p.kind = ?")
            args.append(f.kind)
        if f.standards:
            ors = []
            for s in f.standards:
                ors.append("EXISTS (SELECT 1 FROM json_each(p.standards) "
                           "WHERE replace(replace(lower(value), ' ', ''), '-', '') = ?)")
                args.append(_norm_standard(s))
            clauses.append("(" + " OR ".join(ors) + ")")
        if f.properties:
            pc, pa = property_clauses(f.properties)
            clauses += pc
            args += pa
        # dimensions regardless of orientation: compare sorted sizes (small, middle, large)
        small = "min(p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm)"
        large = "max(p.bbox_x_mm, p.bbox_y_mm, p.bbox_z_mm)"
        mid = f"(p.bbox_x_mm + p.bbox_y_mm + p.bbox_z_mm - {small} - {large})"
        for dims, op in ((f.max_dims_mm, "<="), (f.min_dims_mm, ">=")):
            if dims:
                d = sorted(float(x) for x in dims)
                clauses.append(f"p.bbox_x_mm IS NOT NULL AND {small} {op} ? AND {mid} {op} ? AND {large} {op} ?")
                args += d
        return " AND ".join(clauses), args

    def _spec_candidates(self, specs: dict[str, Any], where: str, args: list[Any]) -> list[int]:
        """Parts whose properties match at least one key spec exactly (e.g. designation 6204,
        inner diameter 20): found even when the text of the question does not mention them."""
        ors, oargs = [], []
        for key, want in specs.items():
            if key not in KEY_SPECS:
                continue
            for name in SPEC_ALIASES.get(key, [key]):
                path = f"$.{name}"
                if key == "designation" and str(want).isdigit() and len(str(want)) >= 4:
                    # same bearing series (62xx): candidates for "nearest size" if the exact one is missing
                    ors.append("CAST(json_extract(p.properties, ?) AS TEXT) LIKE ?")
                    oargs += [path, str(want)[:3] + "%"]
                if isinstance(want, (int, float)) and not isinstance(want, bool):
                    ors.append("(json_type(p.properties, ?) IN ('integer','real') "
                               "AND abs(CAST(json_extract(p.properties, ?) AS REAL) - ?) < 0.01)")
                    oargs += [path, path, float(want)]
                else:
                    ors.append("replace(replace(lower(CAST(json_extract(p.properties, ?) AS TEXT)), ' ', ''), '-', '') = ?")
                    oargs.append(path)
                    oargs.append(re.sub(r"[\s-]", "", str(want).lower()))
        if not ors:
            return []
        rows = self.repo.conn.execute(
            f"SELECT p.pk FROM parts p WHERE {where} AND ({' OR '.join(ors)}) LIMIT ?",
            [*args, *oargs, SPEC_CANDIDATES]).fetchall()
        return [r["pk"] for r in rows]

    # ---- search ------------------------------------------------------------------
    def _vector_rows(self, qvec: list[float], where: str, args: list[Any], candidates: int) -> list[Any]:
        """The `candidates` visible parts closest to the question vector, as (pk, cosine distance).
        Comparing every visible part costs ~8 us per visible part (400 ms at 49,000). The vec0 KNN index
        compares all parts, but ~4-8x faster (45-110 ms at 49,000). So when this company may see a large
        share of the library (KNN_MIN_SHARE) we use the index, sized for that share, and then apply the
        same WHERE as always (company + filters); when it sees a small share, scanning just those is faster. The embeddings
        are unit vectors, so the KNN order (L2) equals the cosine order and cosine distance = L2^2 / 2.
        If the filters still leave fewer than `candidates`, we compare every visible part after all:
        the result is always the same as the full scan."""
        blob = sqlite_vec.serialize_float32(qvec)
        conn = self.repo.conn
        visible_n = conn.execute(f"SELECT count(*) FROM parts p WHERE {where}", args).fetchone()[0]
        total = conn.execute("SELECT count(*) FROM parts").fetchone()[0] if visible_n > SCAN_BELOW else 0
        # a zero vector has no direction: full scan (dist NULL)
        if any(qvec) and visible_n > SCAN_BELOW and visible_n >= KNN_MIN_SHARE * total:
            k = min(KNN_MAX, max(KNN_MIN, math.ceil(candidates * KNN_FACTOR * total / visible_n)))
            knn = conn.execute(
                "SELECT rowid AS pk, distance FROM parts_vec WHERE embedding MATCH ? AND k = ?", [blob, k]).fetchall()
            dist = {r["pk"]: r["distance"] * r["distance"] / 2 for r in knn}
            visible = [r["pk"] for r in conn.execute(
                f"SELECT p.pk FROM parts p WHERE p.pk IN ({','.join('?' * len(dist))}) AND {where}",
                [*dist, *args])] if dist else []
            if len(visible) >= candidates or len(knn) < k:      # enough, or there is nothing beyond the KNN set
                return [{"pk": pk, "dist": dist[pk]} for pk in sorted(visible, key=dist.get)[:candidates]]
        return conn.execute(
            f"""SELECT v.rowid AS pk, vec_distance_cosine(v.embedding, ?) AS dist
                FROM parts_vec v JOIN parts p ON p.pk = v.rowid
                WHERE {where} ORDER BY dist LIMIT ?""",
            [blob, *args, candidates],
        ).fetchall()

    def search(
        self,
        query: str,
        company_id: str | None = None,
        filters: SearchFilters | None = None,
        limit: int = 10,
        candidates: int = 50,
    ) -> list[SearchHit]:
        f = filters or SearchFilters()
        where, args = self._filter_sql(company_id, f)
        query = (query or "").strip()
        if f.engineering:
            # checked per part after SQL (a value can follow from a standard): look at many more parts
            candidates = max(candidates, ENGINEERING_CANDIDATES)
        # Note: filters via JOIN, not via "rowid IN (subquery)". The latter is hundreds
        # of times slower with FTS on large databases (measured: 1.4 s -> 4 ms at 50,000 parts).

        vector: dict[int, tuple[int, float]] = {}      # pk -> (rang, similariteit)
        keyword: dict[int, int] = {}                    # pk -> rang
        if query:
            rows = self._vector_rows(self.embedder.embed_query(query), where, args, candidates)
            # dist is NULL for a zero vector (e.g. a text without usable characters): counts as "no similarity"
            vector = {r["pk"]: (i + 1, 1.0 - (r["dist"] if r["dist"] is not None else 1.0))
                      for i, r in enumerate(rows)}

            fts = _fts_query(query)
            if fts:
                rows = self.repo.conn.execute(
                    f"""SELECT f.rowid AS pk FROM parts_fts f JOIN parts p ON p.pk = f.rowid
                        WHERE parts_fts MATCH ? AND {where}
                        ORDER BY bm25(parts_fts, 10.0, 2.0, 4.0, 6.0, 3.0, 2.0) LIMIT ?""",
                    [fts, *args, candidates],
                ).fetchall()
                keyword = {r["pk"]: i + 1 for i, r in enumerate(rows)}
            specs = parse_specs(query)
            spec_pks = self._spec_candidates(specs, where, args) if specs else []
            pks = list(dict.fromkeys([*vector, *keyword, *spec_pks]))
        else:
            # without search text: just the filtered parts, by name
            rows = self.repo.conn.execute(
                f"SELECT p.pk FROM parts p WHERE {where} ORDER BY p.name LIMIT ?",
                [*args, ENGINEERING_BROWSE if f.engineering else limit]
            ).fetchall()
            pks = [r["pk"] for r in rows]
            specs = {}

        if not pks:
            return []
        marks = ",".join("?" * len(pks))
        part_rows = {r["pk"]: r for r in self.repo.conn.execute(
            f"SELECT * FROM parts p WHERE p.pk IN ({marks})", pks)}

        q_norm = _norm_standard(query)
        # "is this the right kind of part" only counts the kind words, not "preferably A4" or "not galvanized"
        required = kind_words(query)
        q_words = {_stem(w) for w in _query_words(required)}
        # rare words weigh more (idf): "planter" says more than "greenhouse"
        terms = _query_terms(required)
        # statistics only over the parts this company may see: another company's parts never influence the score
        # (and only the parts this caller may see: a restricted part never shapes the score for others)
        scope, scope_args = _visible(company_id)
        total = self.repo.conn.execute(f"SELECT count(*) FROM parts p WHERE {scope}", scope_args).fetchone()[0] or 1
        idf = {}
        for t, prefix in terms:
            df = self.repo.conn.execute(
                f"SELECT count(*) FROM parts_fts f JOIN parts p ON p.pk = f.rowid WHERE parts_fts MATCH ? AND {scope}",
                [_fts_term(t, prefix), *scope_args]).fetchone()[0]
            idf[(t, prefix)] = math.log((total + 1) / (df + 1)) + 0.1
        idf_sum = sum(idf.values()) or 1.0
        # real words only: no loose numbers ("400") and no units ("watt", "litre")
        word_idf = {k: w for k, w in idf.items() if re.search(r"[a-z]", k[0]) and k[0] not in UNIT_WORDS}
        if specs:
            # codes such as "6206-2rs1", "m8x30", "ucp208", "gt2" are checked as specs (spec_checks);
            # for "is this the right kind of part" only the plain words count
            word_idf = {k: w for k, w in word_idf.items() if not re.search(r"\d", k[0])}
        word_sum = sum(word_idf.values())
        component_pks = {r[0] for r in self.repo.conn.execute(
            f"""SELECT p.pk FROM assembly_components ac JOIN parts p ON p.id = ac.part_id
                WHERE p.pk IN ({marks})""", pks)}
        pk_feedback = self.repo.feedback_scores(query, company_id) if query else {}
        prefs = parse_preferences(query) if query else {}
        hits: list[SearchHit] = []
        for pk in pks:
            row = part_rows.get(pk)
            if row is None:
                continue
            part = self.repo._row_to_part(row)
            v_rank, v_sim = vector.get(pk, (None, None))
            k_rank = keyword.get(pk)
            score = (1 / (RRF_K + v_rank) if v_rank else 0) + (1 / (RRF_K + k_rank) if k_rank else 0)
            std_hit = bool(query) and any(_norm_standard(s) and _norm_standard(s) in q_norm
                                          for s in part.standards)
            if std_hit:
                score += STANDARD_BOOST
            coverage = word_coverage = None
            if terms:
                tokens = _part_tokens(part)
                hit_terms = {(t, prefix) for (t, prefix) in idf if _term_in(t, prefix, tokens)}
                coverage = sum(idf[k] for k in hit_terms) / idf_sum
                word_coverage = (sum(word_idf[k] for k in hit_terms if k in word_idf) / word_sum) if word_sum else None
                score += COVERAGE_WEIGHT * coverage
            spec_summary = summarize(specs, part) if specs else None
            if spec_summary is not None:
                score += SPEC_WEIGHT * spec_summary.score()
                if spec_summary.key_mismatch:
                    score -= SPEC_WEIGHT / 2          # other thread / bearing / frame: a different part
            if prefs:
                score += PREFERENCE_WEIGHT * summarize(prefs, part).score()
            # loose components of an assembly (leg, seat, ...) drop, unless asked for
            if pk in component_pks and _stem(part.name.lower().split()[-1]) not in q_words:
                score *= COMPONENT_PENALTY
            if not query:
                score = 0.0
            elif pk_feedback:
                score += FEEDBACK_BOOST * pk_feedback.get(part.id, 0)
            if f.engineering and not engineering.meets(part, f.engineering):
                continue
            hits.append(SearchHit(part, score, v_sim, k_rank, v_rank, std_hit, coverage, word_coverage,
                                  spec_summary))
        if query:
            hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
