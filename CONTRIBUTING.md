# Contributing to Partsfinder

Thanks for helping. Partsfinder is maintained by DZ IT Services; issues and pull requests are welcome.

## Before you start
- For anything bigger than a small fix, open an issue first, so we can agree on the approach.
- Read the [README](README.md) and [docs/](docs/): the roadmap is [docs/01_ROADMAP.md](docs/01_ROADMAP.md), the
  decisions are in [docs/04_DECISIONS.md](docs/04_DECISIONS.md), the brand in [brand/BRAND.md](brand/BRAND.md).
- English everywhere: code, comments, UI text, docs and data.

## Rules for every change
- **Company data stays apart.** Data of company A is never visible to company B: every query filters on
  `company_id IS NULL OR company_id = ?`. Restricted parts are only shown to the right groups, and restricted or
  confidential data never goes to an external AI.
- **Never force a bad match.** When nothing fits, the answer is `status: "none"` ("No existing model found").
  The library finds existing parts; it does not design.
- **Bring your own key.** The AI runs only on the user's own API key and the app works fully without it. No shared
  or built-in key. Keys live in the OS keychain (Electron `safeStorage`) or a local `.env`, never in the database,
  git or logs.
- **Only openly licensed data.** Import only data whose licence allows redistribution (CC0, CC-BY, CC-BY-SA, MIT,
  Apache-2.0, BSD, LGPL/GPL where compatible), and store source URL, author and licence for every part. No scraping,
  and never copy catalogues of manufacturers or distributors (McMaster-Carr, Misumi, TraceParts, GrabCAD, ...).
  Live vendor APIs (Nexar/Octopart, DigiKey, Mouser) only with the user's own key.
- **Nothing private in git.** No keys, `.env`, CAD files, databases or `data/**` (see `.gitignore`); data packs are
  built by `scripts/datapacks/`. Passwords only as scrypt hashes, never in code, git or logs.
- **Docs move with the code.** Every change to the API or the data model also updates
  [docs/05_API.md](docs/05_API.md) and [docs/03_DATAMODEL.md](docs/03_DATAMODEL.md).
- **Brand.** Use the colours, fonts and marks of `brand/` (`tokens.css`, `logos/`, `icons/`).

## Set up
Windows: `scripts\windows\setup_windows.bat`, then `scripts\windows\app.bat`. Mac: `bash scripts/setup_mac.sh`, then `cd app && npm install && npm start`.

## Check your change
```
cd backend
.venv\Scripts\python -m pytest            # all tests must pass; add tests for what you change
python ..\scripts\ui_screenshots.py         # for UI changes: every screen at 1440, 820 and 390 px
cd ..\app && npm run test:e2e              # for app changes: the real app window against a test library
```
The tests use simple embeddings and never call an AI, so they run offline and cost nothing.

## Pull requests
- One subject per pull request, with a short description of what changes for the user.
- Keep functions small and code readable; follow the style of the file you change.
- By opening a pull request you agree that your contribution is licensed under the
  [MIT licence](LICENSE), like the rest of the code.
- The names and logos of Partsfinder and DZ IT Services (`brand/`) are not part of the open-source licence;
  please do not change them in a pull request.
