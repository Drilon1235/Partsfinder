# Data packs

Thousands of openly licensed parts, ready to install in Partsfinder. Nothing of them is in git: these scripts build
them from the sources. Format and install rules: [docs/03_DATAMODEL.md](../../docs/03_DATAMODEL.md#data-packs-no-database-change);
why these sources: [docs/04_DECISIONS.md](../../docs/04_DECISIONS.md).

| Pack | Source | Licence | Parts | Files |
|---|---|---|---|---|
| `standard-parts` | generated with [bd_warehouse](https://github.com/gumyr/bd_warehouse) | Apache-2.0 | ~6,000 | in the pack |
| `kicad-3d` | [KiCad 3D models](https://github.com/KiCad/kicad-packages3D) | CC-BY-SA 4.0 + exception | ~6,200 | linked |
| `freecad-library` | [FreeCAD parts library](https://github.com/FreeCAD/FreeCAD-library) | CC-BY 3.0 | ~2,500 | linked |
| `adafruit-cad-parts` | [Adafruit CAD parts](https://github.com/adafruit/Adafruit_CAD_Parts) | MIT | ~490 | linked |

"Linked" packs carry metadata and previews only; each part points to its file at the original repository, pinned to
one commit, and the app downloads it the first time someone opens it.

## Build
From the repository folder, with the backend environment (`backend/.venv`). Only the STEP files are needed, so a
sparse clone saves gigabytes:
```
git clone --filter=blob:none --no-checkout https://github.com/KiCad/kicad-packages3D.git src/kicad
cd src/kicad && git sparse-checkout set --no-cone "*.step" "*.STEP" "LICENSE*" && git checkout && cd ../..
python scripts/datapacks/build.py kicad-3d --src src/kicad --zip
```
The same for `freecad-library` (FreeCAD-library) and `adafruit-cad-parts` (Adafruit_CAD_Parts). Standard parts are
generated first, in their own environment (bd_warehouse uses another OCP version than CadQuery):
```
python -m venv .venv-bd && .venv-bd/bin/pip install bd_warehouse==0.4.0
.venv-bd/bin/python scripts/datapacks/generate_standard_parts.py --out dist/standard-parts
python scripts/datapacks/build.py standard-parts --src dist/standard-parts --zip
```
`--limit 50` makes a quick test pack; a stopped build continues where it was when you run it again.
The result is `dist/packs/<name>/` and, with `--zip`, `dist/packs/partsfinder-pack-<name>-<date>.zip`.

## Add a source
A module in `sources/` with a `SOURCE = Source(...)` and an `items(src)` that returns one `Item` per part: an id
(prefixed, stable between builds), the CAD file, the metadata (name, description, a category of
`taxonomy.yaml`, tags, properties, `source`, `source_ref`, `license`) and either a pinned URL of the original file or
`None` to ship the file. Only sources whose licence allows sharing the models; check it before you add one.
