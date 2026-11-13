"""Test search engine for the end-to-end test (app/test/e2e.js): a small library in a temporary file, no model, no AI.

    backend/.venv/bin/python app/test/e2e_backend.py <folder> <port>

Makes <folder>/library.db with three parts (HashingEmbedder: finds identical words, no model download) and
serves the real API on 127.0.0.1:<port> until it is stopped.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

PARTS = [
    dict(id="hex-bolt-m8x30", name="Hex bolt M8x30 ISO 4017", category_path="fasteners/bolt/hex-bolt",
         description="Hex bolt fully threaded M8 x 30 mm, ISO 4017, steel 8.8.", standards=["ISO 4017"],
         bbox_mm=(13, 13, 35), material="steel 8.8", properties={"thread": "M8", "length_mm": 30, "pitch_mm": 1.25}),
    dict(id="profile-2020", name="T-slot aluminium profile 20x20 slot 6", category_path="profiles/aluminium/system-profile",
         description="T-slot aluminium profile 20x20, slot 6, length 500 mm.", bbox_mm=(20, 20, 500),
         properties={"profile_size": "20x20", "slot_width_mm": 6}),
    dict(id="flange-dn50", name="Weld neck flange DN50 PN16 EN 1092-1", category_path="piping/flange",
         description="Weld neck flange DN50 PN16 with 4 bolt holes M16.", properties={"dn": 50, "pn": 16}),
]


def main() -> int:
    folder, port = Path(sys.argv[1]), int(sys.argv[2])
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["PARTSFINDER_DB_PATH"] = str(folder / "library.db")
    os.environ["PARTSFINDER_DATA_DIR"] = str(folder / "data")
    os.environ.pop("ANTHROPIC_API_KEY", None)

    import uvicorn

    from partsfinder.api import create_app
    from partsfinder.config import get_settings
    from partsfinder.db import connect
    from partsfinder.ingest import HashingEmbedder, part_text
    from partsfinder.models import PartCreate
    from partsfinder.repository import Repository

    s = get_settings()
    conn = connect(s.db_path, s.embedding_dim, check_same_thread=False)
    repo, emb = Repository(conn), HashingEmbedder(s.embedding_dim)
    for d in PARTS:
        p = repo.add_part(PartCreate(**d))
        repo.set_embedding(p.id, emb.embed_passages([part_text(p)])[0])
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('embedder', 'hashing')")
    conn.close()

    app = create_app(s)          # reads the library from the file, like the real app
    app.state.public_url = f"http://127.0.0.1:{port}"
    print("e2e search engine ready", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
