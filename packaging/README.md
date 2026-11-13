# Packaging: the Windows installer

GitHub Actions builds the installer ([../.github/workflows/build.yml](../.github/workflows/build.yml)):
- every push runs the backend tests and the end-to-end test of the app from the source;
- a version tag (`v0.2.0`, equal to `version` in `app/package.json`) or *Actions → Build → Run workflow* also builds
  `Partsfinder-Setup-<version>.exe`, runs the end-to-end test on the installed app, and for a tag:
  - when a **draft release for that tag already exists** (prepared by the maintainer with the release notes and the
    data pack zips as assets), it adds the tested installer, writes its SHA-256 where the notes say
    `<!-- installer -->`, and **publishes** the release; `download-link.yml` then adds the same installer as
    `Partsfinder-Setup.exe`, so the README button (`releases/latest/download/Partsfinder-Setup.exe`) always works;
  - otherwise it makes the release itself, with the notes of `.github/release-notes.md`, the installer and the data
    packs of the previous release, and publishes it. A new version is then only: raise `version` in
    `app/package.json`, commit, and push a tag `v<version>`.

## Build it yourself (Windows, from the repository folder)
```
python -m venv .build-venv
.build-venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
.build-venv\Scripts\pip install -r backend\requirements.txt -r packaging\requirements.txt
.build-venv\Scripts\pyinstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\partsfinder-backend.spec
.build-venv\Scripts\python packaging\fetch_model.py
cd app && npm ci && npx electron-builder --win --publish never
node test\e2e.js --packaged ..\dist\app\win-unpacked\Partsfinder.exe
```
Use the CPU-only torch: the CUDA build makes the installer several GB larger and the model does not need a GPU.

## What goes where
| Built | Ends up in the installed app |
|---|---|
| `dist/partsfinder-backend/` (PyInstaller, [partsfinder-backend.spec](partsfinder-backend.spec)) | `resources/backend/` |
| `dist/model/multilingual-e5-small/` ([fetch_model.py](fetch_model.py)) | `resources/model/` |
| `app/` (electron-builder, `build` in [app/package.json](../app/package.json)) | the app itself |

The installed app starts `resources/backend/partsfinder-backend.exe --port 8731` and keeps the library, uploads and
saved keys in `%APPDATA%\Partsfinder` (see `backendCommand` in [app/main.js](../app/main.js)).
