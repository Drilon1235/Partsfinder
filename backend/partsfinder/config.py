"""Settings, read from environment variables or backend/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
# The base of relative paths in the library and of data/ (thumbnails, packs). The installed app sets
# PARTSFINDER_HOME to the user's own data folder, so nothing is written next to the program.
PROJECT_DIR = Path(os.getenv("PARTSFINDER_HOME") or BACKEND_DIR.parent).resolve()

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
except ImportError:  # python-dotenv is optional
    pass


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    embedding_model: str
    embedding_dim: int
    anthropic_api_key: str | None
    claude_model: str
    max_spend_usd: float
    ai_backend: str = "auto"           # auto (AI when there is a key), api or off
    api_keys: str | None = None        # "key=company,key2=*"; empty = no keys needed
    local_groups: str | None = None    # without keys (one pc): restricted groups shown anyway, "nuclear,aero"


def default_db_path() -> Path:
    """backend/partsfinder.db; a library from before the rename (orlix_parts.db) is renamed once."""
    new, old = BACKEND_DIR / "partsfinder.db", BACKEND_DIR / "orlix_parts.db"
    if not new.exists() and old.exists():
        try:
            for suffix in ("", "-wal", "-shm"):
                src = old.with_name(old.name + suffix)
                if src.exists():
                    src.rename(new.with_name(new.name + suffix))
        except OSError:          # in use by a running old version: keep using the old file
            return old
    return new


def get_settings() -> Settings:
    return Settings(
        db_path=Path(os.getenv("PARTSFINDER_DB_PATH") or default_db_path()),
        data_dir=Path(os.getenv("PARTSFINDER_DATA_DIR") or PROJECT_DIR / "data"),
        embedding_model=os.getenv("PARTSFINDER_EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        embedding_dim=int(os.getenv("PARTSFINDER_EMBEDDING_DIM", "384")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        claude_model=os.getenv("PARTSFINDER_CLAUDE_MODEL", "claude-haiku-5-5"),
        max_spend_usd=float(os.getenv("PARTSFINDER_MAX_SPEND_USD", "0.50")),
        ai_backend=(os.getenv("PARTSFINDER_AI_BACKEND") or "auto").strip().lower(),
        api_keys=os.getenv("PARTSFINDER_API_KEYS") or None,
        local_groups=os.getenv("PARTSFINDER_LOCAL_GROUPS") or None,
    )
