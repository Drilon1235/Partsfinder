"""Checks whether the development environment is ready.

Usage:  python check_env.py
Shows OK / ERROR per item and ends with exit code 1 if something is missing.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

RESULTS: list[tuple[str, bool, str, bool]] = []  # name, ok, detail, required


def check(name: str, required: bool = True):
    def wrap(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, detail, required))
        except Exception as exc:  # noqa: BLE001 - we want to show every error
            RESULTS.append((name, False, f"{type(exc).__name__}: {exc}", required))
        return fn
    return wrap


@check("Python version (3.11+)")
def _python():
    v = sys.version_info
    if not (v.major == 3 and v.minor >= 11):
        raise RuntimeError(f"Python {v.major}.{v.minor} found, 3.11+ needed")
    return f"{v.major}.{v.minor}.{v.micro}"


for pkg in ["pydantic", "dotenv", "yaml", "numpy", "anthropic", "fastapi", "uvicorn", "trimesh"]:
    @check(f"Package: {pkg}")
    def _pkg(pkg=pkg):
        mod = importlib.import_module(pkg)
        return getattr(mod, "__version__", "")


@check("SQLite + sqlite-vec")
def _sqlite_vec():
    import sqlite3

    import sqlite_vec

    conn = sqlite3.connect(":memory:")
    if not hasattr(conn, "enable_load_extension"):
        raise RuntimeError(
            "This Python does not allow SQLite extensions. Install Python from python.org."
        )
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    (version,) = conn.execute("select vec_version()").fetchone()
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    return f"sqlite {sqlite3.sqlite_version}, sqlite-vec {version}, FTS5 ok"


@check("CadQuery: write and read back STEP")
def _cadquery():
    import cadquery as cq

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_block.step"
        cq.exporters.export(cq.Workplane("XY").box(10, 20, 30), str(path))
        shape = cq.importers.importStep(str(path)).val()
        bb = shape.BoundingBox()
        dims = sorted(round(d) for d in (bb.xlen, bb.ylen, bb.zlen))
        if dims != [10, 20, 30]:
            raise RuntimeError(f"Wrong dimensions: {dims}")
    return f"version {getattr(cq, '__version__', '?')}"


@check("sentence-transformers (embedding model)")
def _st():
    import sentence_transformers

    return f"version {sentence_transformers.__version__} (model is only downloaded on first use)"


@check("AI key (optional: the user's own Anthropic key, set in the app's Settings)", required=False)
def _key():
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parent / ".env")
    except ImportError:
        pass
    if os.getenv("ANTHROPIC_API_KEY", ""):
        return "API key set in backend/.env"
    raise RuntimeError("no key in backend/.env; add your own key in the app (Settings), the AI is optional")


@check("Partsfinder package loads + taxonomy valid")
def _package():
    sys.path.insert(0, str(Path(__file__).parent))
    from partsfinder.taxonomy import Taxonomy

    tax = Taxonomy.load()
    return f"{len(tax.all_category_paths())} categories, {len(tax.sectors)} sectors"


def main() -> int:
    width = max(len(r[0]) for r in RESULTS)
    failed = 0
    for name, ok, detail, required in RESULTS:
        mark = "OK" if ok else ("ERROR" if required else "NOTE")
        failed += (not ok) and required
        print(f"[{mark:<6}] {name.ljust(width)}  {detail}")
    print()
    if failed:
        print(f"{failed} problem(s) found. See the ERROR lines above.")
        return 1
    print("All good. You can continue with the next phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
