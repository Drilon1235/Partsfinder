"""Example: how another program (a CAD tool, a script, another AI) calls Partsfinder.

1. First start the API (double-click api.bat, or: python -m partsfinder.api).
2. Then run:  python examples/example_client.py "green garden chair" [company_id]

The script looks for an existing model. If there is a good match, it downloads
the CAD file to examples/downloads/ so it can be reused.
If there is nothing, the caller knows it has to be drawn new.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"


def find_existing_model(question: str, company_id: str | None = None,
                        max_dims_mm: tuple[float, float, float] | None = None) -> dict:
    body: dict = {"query": question, "company_id": company_id, "limit": 3}
    if max_dims_mm:                       # hard requirement from the caller: never relaxed
        body["filters"] = {"max_dims_mm": list(max_dims_mm)}
    r = requests.post(f"{API}/search", json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def download(url: str, target_dir: Path) -> Path:
    r = requests.get(API + url, timeout=60)
    r.raise_for_status()
    name = r.headers.get("content-disposition", "").split("filename=")[-1].strip('"') or "model.step"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_bytes(r.content)
    return path


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else "green garden chair"
    company = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        result = find_existing_model(question, company)
    except requests.ConnectionError:
        print("The API is not running. Start api.bat first.")
        return 1

    print(f"{result['status'].upper()}: {result['message']}")
    if result["status"] == "none":
        print("-> No existing model: draw this new.")
        return 0
    for res in result["results"]:
        print(f"- [{res['verdict']}] {res['name']} ({res['library']}), dimensions {res['dims_mm']} mm")
        for reason in res["match_reasons"]:
            print(f"    + {reason}")
        for reason in res["mismatch_reasons"]:
            print(f"    - {reason}")

    best = result["results"][0]
    primary = next((f for f in best["files"] if f["is_primary"]), best["files"][0] if best["files"] else None)
    if best["verdict"] == "fits" and primary:
        path = download(primary["url"], Path(__file__).parent / "downloads")
        print(f"-> Reuse: {path}")
    else:
        print("-> No exact match: the best result can be adapted as a starting point.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
