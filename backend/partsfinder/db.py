"""Database: connect and create the schema (SQLite + FTS5 + sqlite-vec)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_VERSION = 4          # 2: access groups, confidential companies, audit log; 3: accounts and sign-in sessions;
                            # 4: who may see which uploaded folder, set in the app (folder_access)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confidential INTEGER NOT NULL DEFAULT 0     -- 1 = no part of this company ever goes to an outside AI
);

-- pk = internal numeric ID (needed for the search indexes), id = public uuid
CREATE TABLE IF NOT EXISTS parts (
    pk             INTEGER PRIMARY KEY AUTOINCREMENT,
    id             TEXT NOT NULL UNIQUE,
    company_id     TEXT REFERENCES companies(id) ON DELETE CASCADE,  -- NULL = general
    kind           TEXT NOT NULL CHECK (kind IN ('part', 'assembly')),
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    category_path  TEXT NOT NULL,
    sectors        TEXT NOT NULL DEFAULT '[]',
    tags           TEXT NOT NULL DEFAULT '[]',
    material       TEXT,
    color          TEXT,
    bbox_x_mm      REAL,
    bbox_y_mm      REAL,
    bbox_z_mm      REAL,
    volume_mm3     REAL,
    mass_g         REAL,
    standards      TEXT NOT NULL DEFAULT '[]',
    properties     TEXT NOT NULL DEFAULT '{}',
    source         TEXT NOT NULL,
    source_ref     TEXT,
    license        TEXT,
    thumbnail_path TEXT,
    checksum       TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    access_group   TEXT          -- NULL = whole company; else only keys with this group (company parts only)
);
CREATE INDEX IF NOT EXISTS idx_parts_company  ON parts(company_id);
CREATE INDEX IF NOT EXISTS idx_parts_category ON parts(category_path);
-- the same file not twice in the same library
CREATE UNIQUE INDEX IF NOT EXISTS idx_parts_checksum
    ON parts(ifnull(company_id, ''), checksum) WHERE checksum IS NOT NULL;

CREATE TABLE IF NOT EXISTS part_files (
    part_id    TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    format     TEXT NOT NULL,
    path       TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (part_id, path)
);

CREATE TABLE IF NOT EXISTS assembly_components (
    assembly_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    part_id     TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    PRIMARY KEY (assembly_id, part_id)
);

-- User feedback (thumbs up/down per part); stays local, no FK so it survives a
-- deleted part. company_id = who gave it (NULL = general library).
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT,
    part_id    TEXT NOT NULL,
    query      TEXT NOT NULL DEFAULT '',
    rating     TEXT NOT NULL CHECK (rating IN ('up','down')),
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_company ON feedback(company_id);

-- Who searched for and downloaded what (docs/10_COMPANY_LIBRARIES.md). No keys, only a fingerprint;
-- part ids, never part names.
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL,          -- 'local', 'admin' or 'key:<sha256 first 12>'
    company_id TEXT,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_log(company_id, id);

-- Accounts (schema 3): people sign in with a name and a password (docs/10_COMPANY_LIBRARIES.md).
-- Only a scrypt hash of the password is stored. role 'admin' sees every company; 'company' only its own.
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'company')),
    company_id    TEXT REFERENCES companies(id) ON DELETE CASCADE,   -- NULL for an admin
    groups        TEXT NOT NULL DEFAULT '[]',                         -- restricted groups (JSON list)
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    CHECK ((role = 'admin' AND company_id IS NULL) OR (role = 'company' AND company_id IS NOT NULL))
);
-- Signed-in sessions: only the sha256 of the token is stored, never the token itself
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username);

-- Schema 4: who may see a folder a company uploaded, set in the app (docs/10_COMPANY_LIBRARIES.md). Written as a
-- .partsfinderaccess file into that folder on every upload, so it survives "Update" from the company's pc.
CREATE TABLE IF NOT EXISTS folder_access (
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    upload     TEXT NOT NULL,                -- the uploaded folder's name
    path       TEXT NOT NULL DEFAULT '',     -- subfolder inside it ('' = the whole folder)
    access     TEXT NOT NULL,                -- 'company' (everyone of the company) or a restricted group
    PRIMARY KEY (company_id, upload, path)
);

-- Keyword search (FTS5), rowid = parts.pk, kept up to date automatically via triggers
CREATE VIRTUAL TABLE IF NOT EXISTS parts_fts USING fts5(
    name, description, tags, standards, material, category_path,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS parts_fts_ai AFTER INSERT ON parts BEGIN
    INSERT INTO parts_fts(rowid, name, description, tags, standards, material, category_path)
    VALUES (new.pk, new.name, new.description, new.tags, new.standards,
            ifnull(new.material, ''), new.category_path);
END;
CREATE TRIGGER IF NOT EXISTS parts_fts_au AFTER UPDATE ON parts BEGIN
    UPDATE parts_fts SET name = new.name, description = new.description, tags = new.tags,
        standards = new.standards, material = ifnull(new.material, ''),
        category_path = new.category_path
    WHERE rowid = new.pk;
END;
CREATE TRIGGER IF NOT EXISTS parts_fts_ad AFTER DELETE ON parts BEGIN
    DELETE FROM parts_fts WHERE rowid = old.pk;
END;
"""


class SchemaMismatchError(RuntimeError):
    """The existing database does not match the current settings."""


def connect(db_path: str | Path, embedding_dim: int = 384, check_same_thread: bool = True) -> sqlite3.Connection:
    """Opens (or creates) the database and makes sure the schema is ready.
    check_same_thread=False: the connection may be used from several threads (the API then uses a lock)."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")          # deleted parts are overwritten, not left in free pages
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")      # let a second connection (background import) wait briefly
    _load_vec(conn)
    init_schema(conn, embedding_dim)
    return conn


def _load_vec(conn: sqlite3.Connection) -> None:
    if not hasattr(conn, "enable_load_extension"):
        raise RuntimeError(
            "This Python installation does not support SQLite extensions. "
            "Install Python from python.org (not the built-in macOS Python)."
        )
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_schema(conn: sqlite3.Connection, embedding_dim: int) -> None:
    # databases from before schema 2 get the new columns first (the CREATE statements below skip existing tables)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='parts'").fetchone():
        _add_column(conn, "parts", "access_group", "access_group TEXT")
        _add_column(conn, "companies", "confidential", "confidential INTEGER NOT NULL DEFAULT 0")
    conn.executescript(SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_parts_group ON parts(company_id, access_group)")
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())

    stored_dim = meta.get("embedding_dim")
    if stored_dim is not None and int(stored_dim) != embedding_dim:
        raise SchemaMismatchError(
            f"Database uses embeddings of {stored_dim} numbers, settings say "
            f"{embedding_dim}. Use the same model or rebuild the embeddings."
        )
    stored_version = meta.get("schema_version")
    if stored_version is not None and int(stored_version) > SCHEMA_VERSION:
        raise SchemaMismatchError(
            f"Database has schema v{stored_version}, this code only knows up to v{SCHEMA_VERSION}."
        )

    # Vector index, rowid = parts.pk
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS parts_vec USING vec0(embedding float[{embedding_dim}])"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS parts_vec_ad AFTER DELETE ON parts BEGIN "
        "DELETE FROM parts_vec WHERE rowid = old.pk; END;"
    )
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        [("schema_version", str(SCHEMA_VERSION)), ("embedding_dim", str(embedding_dim))],
    )
    conn.commit()
