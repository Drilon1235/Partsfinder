"""Selection from the FreeCAD library for the demo library (CC-BY 3.0).

~520 real STEP models from all sectors of the FreeCAD library (doors and windows, pneumatic
cylinders, motors and servos, electronics, single-board computers, bearings, HVAC ducts,
household appliances, foundations, ...). The metadata (name, description, category,
sector, keywords) is in freecad_metadata.json: proposed once by Claude based on
path, file name and outer dimensions. This script copies the files and writes one JSON per file.

Usage:
    git clone --depth 1 https://github.com/FreeCAD/FreeCAD-library
    python scripts/demo/freecad_selection.py PATH/TO/FreeCAD-library [--out data/global/freecad]

Licence: CC-BY 3.0. Attribution: "FreeCAD-library contributors", with per part a link
to the original file (in source_ref); the authors are in the git history of that repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
REPO_URL = "https://github.com/FreeCAD/FreeCAD-library/blob/master/"
LICENSE = "CC-BY 3.0 (FreeCAD-library contributors)"

ATTRIBUTION = """# Attribution FreeCAD-library

The models in this folder come from the FreeCAD library (https://github.com/FreeCAD/FreeCAD-library),
made by the FreeCAD-library contributors and licensed under Creative Commons
Attribution 3.0 (CC-BY 3.0, https://creativecommons.org/licenses/by/3.0/).
Per part the link to the original file is in `source_ref`; the authors of each file
are in the git history of that repository. The files have not been modified; the name,
description and classification were added by us.
"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("library", help="folder with a clone of the FreeCAD library")
    ap.add_argument("--out", default=str(PROJECT / "data" / "global" / "freecad"))
    ap.add_argument("--metadata", default=str(HERE / "freecad_metadata.json"))
    args = ap.parse_args()
    lib, out = Path(args.library), Path(args.out)
    meta = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8")
    copied, missing = 0, []
    for rel, m in sorted(meta.items()):
        src = lib / rel
        if not src.is_file():
            missing.append(rel)
            continue
        pid = f"fc-{slug(Path(rel).stem)}-{hashlib.sha1(rel.encode()).hexdigest()[:6]}"
        folder = out / m["category_path"].split("/")[0]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{pid}{src.suffix.lower()}"
        shutil.copyfile(src, dest)
        sidecar = {
            "id": pid, "kind": m.get("kind", "part"), "name": m["name"], "description": m["description"],
            "category_path": m["category_path"], "sectors": m.get("sectors", []),
            "tags": sorted({t.lower() for t in m.get("tags", [])}), "material": m.get("material"),
            "properties": {"original_name": src.name, "folder_in_freecad_library": str(Path(rel).parent)},
            "source": "FreeCAD-library", "source_ref": REPO_URL + rel.replace(" ", "%20"), "license": LICENSE,
        }
        dest.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")
        copied += 1
    print(f"{copied} models copied to {out}" + (f", {len(missing)} not found" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
