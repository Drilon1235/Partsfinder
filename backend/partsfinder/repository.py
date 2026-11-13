"""Storing and retrieving parts, with hard separation between companies.

Rule: a company only sees the general library (company_id IS NULL)
and its own parts. Without company_id you only see the general library.
Within its own parts, restricted ones (access_group) only for callers with that group, and an outside AI
sees neither those nor any part of a confidential company (access.py, docs/10_COMPANY_LIBRARIES.md).
Every query below therefore uses _visible() or _owned().
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

import sqlite_vec

from . import engineering
from .access import access_sql, full, join_groups, valid_group
from .models import AssemblyComponent, Part, PartCreate, PartFile
from .taxonomy import Taxonomy


# provenance data says nothing about the part itself: not in the overview of filterable properties
OVERVIEW_HIDDEN = {"needs_review", "ai_metadata", "original_name", "folder_in_freecad_library"}


class DuplicatePartError(ValueError):
    """The same file (checksum) already exists in this library."""


def like_literal(text: str) -> str:
    """Text for a LIKE pattern in which % and _ are ordinary characters (with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AccessError(PermissionError):
    """The part does not exist or belongs to another company."""


def _groups_ok(value: str) -> bool:
    """One group, or several as stored: sorted and joined by commas ("aero,nuclear")."""
    try:
        return join_groups(value) == value
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _visible(company_id: str | None, alias: str = "p") -> tuple[str, list[Any]]:
    """What this caller may see: general + own parts (restricted ones only with their group)."""
    if company_id is None:
        return f"{alias}.company_id IS NULL", []
    acc, args = access_sql(company_id, alias)
    return f"({alias}.company_id IS NULL OR ({alias}.company_id = ? AND {acc}))", [company_id, *args]


def _owned(company_id: str | None, alias: str = "p") -> tuple[str, list[Any]]:
    """Own parts only (reports, duplicates, changing, deleting), with the same group rule."""
    if company_id is None:
        return f"{alias}.company_id IS NULL", []
    acc, args = access_sql(company_id, alias)
    return f"({alias}.company_id = ? AND {acc})", [company_id, *args]


class Repository:
    def __init__(self, conn: sqlite3.Connection, taxonomy: Taxonomy | None = None):
        self.conn = conn
        self.taxonomy = taxonomy or Taxonomy.load()

    # ---- companies --------------------------------------------------------
    def ensure_company(self, company_id: str, name: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO companies(id, name, created_at) VALUES (?, ?, ?)",
            (str(company_id), name or str(company_id), _now()),
        )

    def is_confidential(self, company_id: str | None) -> bool:
        if company_id is None:
            return False
        row = self.conn.execute("SELECT confidential FROM companies WHERE id = ?", (str(company_id),)).fetchone()
        return bool(row and row[0])

    def set_confidential(self, company_id: str, confidential: bool) -> None:
        with self.conn:
            self.ensure_company(company_id)
            self.conn.execute("UPDATE companies SET confidential = ? WHERE id = ?", (int(confidential), str(company_id)))

    def set_access_group(self, part_id: str, company_id: str, group: str | None) -> None:
        """Change only who may see a part (a .partsfinderaccess file changed, the CAD file did not)."""
        if group is not None and not _groups_ok(group):
            raise ValueError(f"Invalid group name '{group}'")
        with self.conn:
            self.conn.execute("UPDATE parts SET access_group = ?, updated_at = ? WHERE id = ? AND company_id = ?",
                              (group, _now(), part_id, str(company_id)))

    # ---- parts -------------------------------------------------------
    def add_part(self, data: PartCreate, replace_id: str | None = None) -> Part:
        """replace_id: delete that part of the same library in the SAME transaction (re-import).
        If inserting the new version fails, the old one stays."""
        category = self.taxonomy.validate_category(data.category_path)
        sectors = self.taxonomy.validate_sectors(data.sectors)
        part_id = data.id or str(uuid.uuid4())
        now = _now()
        bbox = data.bbox_mm or (None, None, None)
        if data.access_group is not None:
            # restricted parts only exist in a company library, with a valid group name
            if data.company_id is None:
                raise ValueError("The general library cannot have restricted parts")
            if not _groups_ok(data.access_group):
                raise ValueError(f"Invalid group name '{data.access_group}'")
        owner = full(data.company_id)           # the import may replace and read back every part of its library

        with self.conn:  # all or nothing
            if replace_id is not None:
                where, params = _owned(owner)
                self.conn.execute(f"DELETE FROM parts AS p WHERE p.id = ? AND {where}", [replace_id, *params])
            if data.company_id is not None:
                self.ensure_company(data.company_id)
            try:
                self.conn.execute(
                    """INSERT INTO parts (id, company_id, kind, name, description, category_path,
                        sectors, tags, material, color, bbox_x_mm, bbox_y_mm, bbox_z_mm,
                        volume_mm3, mass_g, standards, properties, source, source_ref, license,
                        thumbnail_path, checksum, created_at, updated_at, access_group)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        part_id, data.company_id, data.kind, data.name, data.description,
                        category, json.dumps(sectors), json.dumps(data.tags, ensure_ascii=False),
                        data.material, data.color, *bbox, data.volume_mm3, data.mass_g,
                        json.dumps(data.standards, ensure_ascii=False),
                        json.dumps(data.properties, ensure_ascii=False),
                        data.source, data.source_ref, data.license, data.thumbnail_path,
                        data.checksum, now, now, data.access_group,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "idx_parts_checksum" in str(exc):
                    raise DuplicatePartError(
                        f"This file already exists in this library (checksum {data.checksum})"
                    ) from exc
                raise
            self._insert_files(part_id, data.files)

        part = self.get_part(part_id, owner)
        assert part is not None
        return part

    def _insert_files(self, part_id: str, files: Sequence[PartFile]) -> None:
        has_primary = any(f.is_primary for f in files)
        for i, f in enumerate(files):
            primary = f.is_primary or (not has_primary and i == 0)
            self.conn.execute(
                "INSERT INTO part_files(part_id, format, path, is_primary) VALUES (?,?,?,?)",
                (part_id, f.format, f.path, int(primary)),
            )

    def get_part(self, part_id: str, company_id: str | None) -> Part | None:
        where, params = _visible(company_id)
        row = self.conn.execute(
            f"SELECT * FROM parts p WHERE p.id = ? AND {where}", [part_id, *params]
        ).fetchone()
        return self._row_to_part(row) if row else None

    def list_parts(
        self,
        company_id: str | None,
        category_prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Part]:
        where, params = _visible(company_id)
        sql = f"SELECT * FROM parts p WHERE {where}"
        if category_prefix:
            sql += " AND (p.category_path = ? OR p.category_path LIKE ? ESCAPE '\\')"
            prefix = category_prefix.strip("/").lower()
            params += [prefix, like_literal(prefix) + "/%"]
        sql += " ORDER BY p.pk LIMIT ? OFFSET ?"
        rows = self.conn.execute(sql, [*params, limit, offset]).fetchall()
        return [self._row_to_part(r) for r in rows]

    def count_parts(self, company_id: str | None) -> int:
        where, params = _visible(company_id)
        return self.conn.execute(f"SELECT count(*) FROM parts p WHERE {where}", params).fetchone()[0]

    def find_by_checksum(self, checksum: str, company_id: str | None) -> Part | None:
        """Searches only in the own library (for duplicate imports)."""
        where, params = _owned(company_id)
        row = self.conn.execute(
            f"SELECT * FROM parts p WHERE p.checksum = ? AND {where}", [checksum, *params]
        ).fetchone()
        return self._row_to_part(row) if row else None

    def delete_part(self, part_id: str, company_id: str | None) -> bool:
        where, params = _owned(company_id)
        with self.conn:
            cur = self.conn.execute(
                f"DELETE FROM parts AS p WHERE p.id = ? AND {where}", [part_id, *params]
            )
        return cur.rowcount > 0

    # ---- audit log ----------------------------------------------------------
    def audit(self, actor: str, company_id: str | None, action: str, target: str = "", detail: str = "") -> None:
        """Who did what. Never a key (only its fingerprint) and never a part name (only ids)."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_log(at, actor, company_id, action, target, detail) VALUES (?,?,?,?,?,?)",
                (_now(), actor, None if company_id is None else str(company_id), action, target[:500], detail[:1000]))

    def audit_entries(self, company_id: str | None, limit: int = 200, action: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id, at, actor, company_id, action, target, detail FROM audit_log WHERE "
        args: list[Any] = []
        sql += "company_id IS NULL" if company_id is None else "company_id = ?"
        if company_id is not None:
            args.append(str(company_id))
        if action:
            sql += " AND action = ?"
            args.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self.conn.execute(sql, [*args, limit])]

    def find_by_primary_path(self, path: str, company_id: str | None) -> Part | None:
        """The part of the own library whose main file is this path (a changed file: same part, new content)."""
        where, params = _owned(full(company_id))
        row = self.conn.execute(
            f"""SELECT p.* FROM parts p JOIN part_files f ON f.part_id = p.id
                WHERE f.is_primary = 1 AND f.path = ? AND {where}""", [path, *params]).fetchone()
        return self._row_to_part(row) if row else None

    def primary_paths(self, company_id: str | None) -> list[tuple[str, str]]:
        """(part id, main file path) of every part of the own library (for sync and removal)."""
        where, params = _owned(full(company_id))
        return [(r[0], r[1]) for r in self.conn.execute(
            f"""SELECT p.id, f.path FROM parts p JOIN part_files f ON f.part_id = p.id
                WHERE f.is_primary = 1 AND {where}""", params)]

    def remove_parts(self, part_ids: Sequence[str], company_id: str | None) -> list[Part]:
        """Remove parts of the own library completely: the part, its files list, its search entries
        (text and vectors, via triggers), assembly links and the feedback on it. secure_delete overwrites
        the freed pages; the text index is optimised and the write-ahead log truncated so nothing is left
        behind in the database files. Returns the removed parts (the caller deletes previews and caches)."""
        owner = full(company_id)
        removed = [p for p in (self.get_part(i, owner) for i in dict.fromkeys(part_ids)) if p is not None]
        if not removed:
            return []
        ids = [p.id for p in removed]
        marks = ",".join("?" * len(ids))
        where, params = _owned(owner)
        with self.conn:
            self.conn.execute(f"DELETE FROM feedback WHERE part_id IN ({marks})", ids)
            self.conn.execute(f"DELETE FROM parts AS p WHERE p.id IN ({marks}) AND {where}", [*ids, *params])
        with self.conn:
            self.conn.execute("INSERT INTO parts_fts(parts_fts) VALUES ('optimize')")
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:          # another connection is busy: the next checkpoint does it
            pass
        return removed

    def property_overview(self, company_id: str | None, category_prefix: str | None = None,
                          max_values: int = 20) -> list[dict[str, Any]]:
        """Which properties occur in the visible parts, with count,
        range (numbers) or occurring values (text). Only parts this company may see."""
        where, params = _visible(company_id)
        sql = f"SELECT p.properties FROM parts p WHERE {where}"
        if category_prefix:
            prefix = category_prefix.strip("/").lower()
            sql += " AND (p.category_path = ? OR p.category_path LIKE ? ESCAPE '\\')"
            params += [prefix, like_literal(prefix) + "/%"]
        stats: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(sql, params):
            for key, value in json.loads(row["properties"]).items():
                if key in OVERVIEW_HIDDEN:
                    continue
                st = stats.setdefault(key, {"key": key, "count": 0, "numbers": [], "values": {}, "bools": 0})
                st["count"] += 1
                if isinstance(value, bool):
                    st["bools"] += 1
                    st["values"][str(value).lower()] = st["values"].get(str(value).lower(), 0) + 1
                elif isinstance(value, (int, float)):
                    st["numbers"].append(float(value))
                else:
                    st["values"][str(value)] = st["values"].get(str(value), 0) + 1
        out = []
        for key in sorted(stats):
            st = stats[key]
            item: dict[str, Any] = {"key": key, "count": st["count"]}
            if st["bools"] == st["count"]:
                item["type"] = "boolean"
            elif st["numbers"]:
                item["type"] = "number"
                item["min"], item["max"] = min(st["numbers"]), max(st["numbers"])
            else:
                item["type"] = "text"
            if st["values"]:
                top = sorted(st["values"].items(), key=lambda kv: (-kv[1], kv[0]))[:max_values]
                item["values"] = [v for v, _ in top]
            out.append(item)
        return out

    def facets(self, company_id: str | None, category_prefix: str | None = None,
               max_values: int = 500) -> dict[str, Any]:
        """What the Filters panel can offer: the categories, materials, colours, standards and kinds that occur
        in the parts this company may see (within the category, if given), with counts, plus how many parts
        state each engineering value. Only parts this company may see."""
        where, params = _visible(company_id)
        sql = f"SELECT * FROM parts p WHERE {where}"
        if category_prefix:
            prefix = category_prefix.strip("/").lower()
            sql += " AND (p.category_path = ? OR p.category_path LIKE ? ESCAPE '\\')"
            params = [*params, prefix, like_literal(prefix) + "/%"]
        counts: dict[str, dict[str, int]] = {"categories": {}, "materials": {}, "colors": {}, "standards": {}, "kinds": {}}
        eng: dict[str, int] = {}
        total = 0
        sized: list[tuple[float, ...]] = []
        for row in self.conn.execute(sql, params):
            part = self._row_to_part(row)
            total += 1
            path = part.category_path.strip("/")
            # every level of the path, so "fasteners" counts its bolts and nuts too
            bits = path.split("/") if path else []
            for i in range(1, len(bits) + 1):
                key = "/".join(bits[:i])
                counts["categories"][key] = counts["categories"].get(key, 0) + 1
            for name, value in (("materials", part.material), ("colors", part.color), ("kinds", part.kind)):
                if value:
                    counts[name][value] = counts[name].get(value, 0) + 1
            for std in part.standards:
                counts["standards"][std] = counts["standards"].get(std, 0) + 1
            for key in engineering.FILTER_KEYS:
                if engineering.filter_value(part, key) is not None:
                    eng[key] = eng.get(key, 0) + 1
            if part.bbox_mm:
                sized.append(tuple(sorted(part.bbox_mm)))

        def top(d: dict[str, int], n: int = max_values) -> list[dict[str, Any]]:
            return [{"value": k, "count": c} for k, c in sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:n]]

        return {
            "total": total,
            "categories": [{"value": k, "count": c} for k, c in sorted(counts["categories"].items())],
            "materials": top(counts["materials"]),
            "colors": top(counts["colors"]),
            "standards": top(counts["standards"]),
            "kinds": top(counts["kinds"]),
            # the largest outer size per sorted axis (small, middle, large), for the size fields
            "max_dims_mm": [round(max(s[i] for s in sized), 1) for i in range(3)] if sized else None,
            "engineering": [{"key": k, "label": engineering.FILTER_LABELS[k], "unit": engineering.FILTER_UNITS.get(k, ""),
                             "type": "text" if k == "tolerance" else "number", "count": eng[k]}
                            for k in engineering.FILTER_KEYS if eng.get(k)],
            "properties": self.property_overview(company_id, category_prefix),
        }

    def quality_report(self, company_id: str | None, worst: int = 20) -> dict[str, Any]:
        """How complete is the data of the OWN library (without company_id: the general one)?
        The AI can only check requirements that are in the data; this shows what is missing."""
        where, params = _owned(company_id)
        checks = {
            "description": lambda r: bool((r["description"] or "").strip()),
            "material": lambda r: bool((r["material"] or "").strip()),
            "dimensions": lambda r: r["bbox_x_mm"] is not None,
            "volume": lambda r: bool(r["volume_mm3"]),
            "properties": lambda r: any(k not in OVERVIEW_HIDDEN for k in json.loads(r["properties"])),
            "preview_image": lambda r: bool(r["thumbnail_path"]),
            "reviewed": lambda r: "needs-review" not in json.loads(r["tags"]),
        }
        total = 0
        have = dict.fromkeys(checks, 0)
        incomplete: list[tuple[int, str, str, list[str]]] = []
        for r in self.conn.execute(
            f"SELECT id, name, description, material, bbox_x_mm, volume_mm3, properties, thumbnail_path, tags "
            f"FROM parts p WHERE {where}", params):
            total += 1
            missing = [name for name, ok in checks.items() if not ok(r)]
            for name in checks:
                have[name] += name not in missing
            if missing:
                incomplete.append((len(missing), r["name"], r["id"], missing))
        incomplete.sort(key=lambda t: (-t[0], t[1]))
        return {
            "total": total,
            "coverage": {k: (round(100 * v / total) if total else 0) for k, v in have.items()},
            "needs_attention": [{"id": i, "name": n, "missing": m} for _, n, i, m in incomplete[:worst]],
            "incomplete_total": len(incomplete),
        }

    # ---- feedback ---------------------------------------------------------
    def add_feedback(self, part_id: str, company_id: str | None, rating: str, query: str = "",
                     note: str = "") -> int:
        """Stores thumbs up/down. The part must be visible to this company."""
        if rating not in ("up", "down"):
            raise ValueError("rating must be 'up' or 'down'")
        if self.get_part(part_id, company_id) is None:
            raise AccessError("Part not found (or belongs to another company)")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO feedback(company_id, part_id, query, rating, note, created_at) VALUES (?,?,?,?,?,?)",
                (company_id, part_id, query[:1000], rating, note[:1000], _now()))
        return int(cur.lastrowid)

    def feedback_scores(self, query: str, company_id: str | None) -> dict[str, int]:
        """part_id -> +1 (last feedback was thumbs up) or -1 (down) for exactly the same query.
        Only the feedback of THIS company (without company_id: the general one); never that of another."""
        norm = " ".join((query or "").lower().split())
        if not norm:
            return {}
        where = "company_id IS NULL" if company_id is None else "company_id = ?"
        args: list[Any] = [] if company_id is None else [company_id]
        out: dict[str, int] = {}
        for r in self.conn.execute(
                f"SELECT part_id, rating, query FROM feedback WHERE {where} ORDER BY id", args):
            if " ".join((r["query"] or "").lower().split()) == norm:
                out[r["part_id"]] = 1 if r["rating"] == "up" else -1       # the last one counts
        return out

    def list_feedback(self, company_id: str | None, limit: int = 100) -> list[dict[str, Any]]:
        """Only the feedback of this company (without company_id: that of the general library), and only on
        parts this caller may see: feedback on a restricted part never shows its id or question to others."""
        where = "f.company_id IS NULL" if company_id is None else "f.company_id = ?"
        args: list[Any] = [] if company_id is None else [str(company_id)]
        visible, vargs = _visible(company_id)
        rows = self.conn.execute(
            f"""SELECT f.id, f.part_id, f.query, f.rating, f.note, f.created_at FROM feedback f
                JOIN parts p ON p.id = f.part_id WHERE {where} AND {visible}
                ORDER BY f.id DESC LIMIT ?""", [*args, *vargs, limit]).fetchall()
        return [dict(r) for r in rows]

    # ---- embeddings -------------------------------------------------------
    def set_embedding(self, part_id: str, vector: Sequence[float]) -> None:
        dim = int(self.conn.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()[0])
        if len(vector) != dim:
            raise ValueError(f"Embedding has {len(vector)} numbers, expected {dim}")
        row = self.conn.execute("SELECT pk FROM parts WHERE id = ?", (part_id,)).fetchone()
        if row is None:
            raise AccessError(f"Part {part_id} does not exist")
        blob = sqlite_vec.serialize_float32(list(vector))
        with self.conn:
            self.conn.execute("DELETE FROM parts_vec WHERE rowid = ?", (row["pk"],))
            self.conn.execute(
                "INSERT INTO parts_vec(rowid, embedding) VALUES (?, ?)", (row["pk"], blob)
            )

    # ---- assemblies -------------------------------------------------------
    def add_component(
        self, assembly_id: str, part_id: str, quantity: int, company_id: str | None
    ) -> None:
        assembly = self.get_part(assembly_id, company_id)
        if assembly is None or assembly.company_id != company_id:
            raise AccessError("Assembly not found in your own library")
        if assembly.kind != "assembly":
            raise ValueError(f"'{assembly.name}' is not an assembly")
        if self.get_part(part_id, company_id) is None:
            raise AccessError("Part not found (or belongs to another company)")
        if part_id == assembly_id:
            raise ValueError("An assembly cannot contain itself")
        with self.conn:
            self.conn.execute(
                """INSERT INTO assembly_components(assembly_id, part_id, quantity) VALUES (?,?,?)
                   ON CONFLICT(assembly_id, part_id) DO UPDATE SET quantity = excluded.quantity""",
                (assembly_id, part_id, quantity),
            )

    def get_components(self, assembly_id: str, company_id: str | None) -> list[AssemblyComponent]:
        if self.get_part(assembly_id, company_id) is None:
            return []
        where, params = _visible(company_id)
        rows = self.conn.execute(
            f"""SELECT p.*, ac.quantity AS _qty FROM assembly_components ac
                JOIN parts p ON p.id = ac.part_id
                WHERE ac.assembly_id = ? AND {where} ORDER BY p.name""",
            [assembly_id, *params],
        ).fetchall()
        return [AssemblyComponent(part=self._row_to_part(r), quantity=r["_qty"]) for r in rows]

    def used_in(self, part_id: str, company_id: str | None, limit: int = 50) -> list[AssemblyComponent]:
        """The assemblies this part is used in ("where used"), with how many: only assemblies this company may
        see, so another company's assemblies never show (not even that they exist)."""
        if self.get_part(part_id, company_id) is None:
            return []
        where, params = _visible(company_id)
        rows = self.conn.execute(
            f"""SELECT p.*, ac.quantity AS _qty FROM assembly_components ac
                JOIN parts p ON p.id = ac.assembly_id
                WHERE ac.part_id = ? AND {where} ORDER BY p.name LIMIT ?""",
            [part_id, *params, limit],
        ).fetchall()
        return [AssemblyComponent(part=self._row_to_part(r), quantity=r["_qty"]) for r in rows]

    # ---- internal -----------------------------------------------------------
    def _row_to_part(self, row: sqlite3.Row) -> Part:
        files = [
            PartFile(format=f["format"], path=f["path"], is_primary=bool(f["is_primary"]))
            for f in self.conn.execute(
                "SELECT * FROM part_files WHERE part_id = ? ORDER BY is_primary DESC, format",
                (row["id"],),
            )
        ]
        dims = (row["bbox_x_mm"], row["bbox_y_mm"], row["bbox_z_mm"])
        return Part(
            id=row["id"],
            company_id=row["company_id"],
            kind=row["kind"],
            name=row["name"],
            description=row["description"],
            category_path=row["category_path"],
            sectors=json.loads(row["sectors"]),
            tags=json.loads(row["tags"]),
            material=row["material"],
            color=row["color"],
            bbox_mm=dims if None not in dims else None,
            volume_mm3=row["volume_mm3"],
            mass_g=row["mass_g"],
            standards=json.loads(row["standards"]),
            properties=json.loads(row["properties"]),
            access_group=row["access_group"],
            source=row["source"],
            source_ref=row["source_ref"],
            license=row["license"],
            thumbnail_path=row["thumbnail_path"],
            checksum=row["checksum"],
            files=files,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
