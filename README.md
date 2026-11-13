<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logos/partsfinder-logo-white.svg">
    <img src="brand/logos/partsfinder-logo.svg" alt="Partsfinder by DZ IT Services" height="72">
  </picture>
</p>

<p align="center"><b>Find an existing CAD part before you draw a new one.</b></p>

Partsfinder is a parts library you search in plain language. Ask for *"M8x30 bolt 8.8"*, *"bearing 6205-2RS"*,
*"bracket that holds 50 kg"* or *"1 M8 bolt and 1 Arduino"*, drop in a photo or your own STEP file, and it shows the
existing models that fit, with every requirement checked against the part's own data. When nothing fits, it says so
instead of forcing a bad match.

It is a desktop app (Windows and Mac) with a local search engine. Your CAD files and your library stay on your own pc.

## What it does
- **Plain-language search**: name, size, thread, standard, material, strength or load, in one question.
- **Every requirement checked**: thread, length, bearing number, property class, tolerance, *at least 800 MPa*,
  *holds 50 kg*. Each result shows what fits and what deviates, in numbers.
- **Engineering data**: strength, mass, load, load ratings, tolerance and hardness, with where each value comes from.
- **Several parts in one question**, **filters** (library, category, material, standard, fits within L × W × H),
  **search with a photo or a STEP/STL file**, **compare** parts side by side, **datasheets**, **where used** and
  **possible duplicates**.
- **Company libraries**: a general library for everyone, plus a private library per company. Company A never sees
  company B. Folders can be restricted to groups, and a company can be marked *no AI*: nothing of it ever leaves the pc.

## How it works
Partsfinder answers with its own checks first (about 40 ms). They settle most questions: exact sizes, standards and
designations. For vague questions and for parts its checks cannot settle, it can use an AI that judges the candidates.

**The AI runs on your own key.** Add your Anthropic API key in **Settings**; Anthropic bills your own account (a search
costs about a tenth of a cent). The key is stored encrypted by your operating system and only handed to the search
engine on your own pc. Without a key everything works, with the library's own checks.

## Getting started (Windows)
**With the installer:** download `Partsfinder-Setup-<version>.exe` from
[Releases](https://github.com/Drilon1235/Partsfinder/releases) and run it. Everything is included: the app, the search
engine and its language model, so it works offline from the first start. Your library and settings live in
`%APPDATA%\Partsfinder`; uninstalling keeps them. The installer is not code-signed yet, so Windows SmartScreen may
ask you to confirm (*More info → Run anyway*).

**From the source:**
1. Download this repository (green **Code** button → *Download ZIP*, or `git clone`).
2. Double-click `setup_windows.bat`. It installs Python 3.12 if needed, creates a virtual environment, installs the
   packages and runs the tests (about 10 minutes the first time). The result is in `backend/setup_log.txt`.
3. Double-click `app.bat`. The first time it installs Node.js and the app's packages, then opens Partsfinder.

Then, optional: open **Settings** (gear icon) and add your own Anthropic API key.

On a Mac: `bash scripts/setup_mac.sh`, then `cd app && npm install && npm start`.

### Filling the library
This repository holds no CAD data. To start:
- `engineering.bat` builds a generic engineering library (about 400 parts: ISO bolts and nuts, bearings, profiles,
  motors, pulleys, ...) and imports it.
- Import your own folders: in the app, **Companies and people → General library → Import a folder**, or
  `backend\.venv\Scripts\python -m partsfinder.ingest PATH\TO\FOLDER [--company acme]`.
  A JSON file next to a CAD file adds metadata; see [docs/03_DATAMODEL.md](docs/03_DATAMODEL.md).

Only import data you are allowed to use. Partsfinder never downloads catalogues from manufacturers or distributors.

## The API
`api.bat` starts the search engine at `http://127.0.0.1:8000`; `/docs` lets you try every call. Other programs
(and other AIs) can search the library through it. See [docs/05_API.md](docs/05_API.md).

## Documentation
| | |
|---|---|
| [Roadmap](docs/01_ROADMAP.md) | what is built and what comes next |
| [Architecture](docs/02_ARCHITECTURE.md) | how the parts work together |
| [Data model](docs/03_DATAMODEL.md) | what is stored per part |
| [Decisions](docs/04_DECISIONS.md) | choices and why |
| [API](docs/05_API.md) | every call |
| [Test plan](docs/06_TESTPLAN.md) | how quality is measured |
| [Company libraries](docs/10_COMPANY_LIBRARIES.md) and [guide](docs/11_GUIDE_COMPANY_LIBRARIES.md) | accounts, groups, folder rules |

## Development
```
cd backend
.venv\Scripts\python -m pytest          # Windows  (Mac: .venv/bin/python -m pytest)
python scripts/ui_screenshots.py         # every screen at 1440, 820 and 390 px (needs Playwright)
cd ../app && npm run test:e2e           # the real app window against a small test library
```
The Windows installer is built by GitHub Actions ([build.yml](.github/workflows/build.yml)) for every version tag;
see [packaging/README.md](packaging/README.md) to build it yourself.
See [CONTRIBUTING.md](CONTRIBUTING.md). Report security problems privately: [SECURITY.md](SECURITY.md).

## Licence
Partsfinder is free software under the [GNU Affero General Public License v3.0](LICENSE). If you run a changed version
for others over a network, you must offer them its source code.

The names and logos of Partsfinder and DZ IT Services (the `brand/` folder) are not covered by that licence; forks use
their own name and logo. Third-party material and its licences: [NOTICE](NOTICE).

---
<p align="center">Made by <a href="https://dzitservices.be">DZ IT Services</a></p>
