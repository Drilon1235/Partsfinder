# Contributing to Partsfinder

Thanks for helping. Partsfinder is maintained by DZ IT Services; issues and pull requests are welcome.

## Before you start
- For anything bigger than a small fix, open an issue first, so we can agree on the approach.
- Read [CLAUDE.md](CLAUDE.md): its hard rules hold for every change, whoever writes it. The most important:
  company A never sees anything of company B; never force a bad match; no keys, CAD files, databases or `data/**`
  in git; only openly licensed data.
- Every change to the API or the data model also updates [docs/05_API.md](docs/05_API.md) and
  [docs/03_DATAMODEL.md](docs/03_DATAMODEL.md).
- English everywhere: code, comments, UI text, docs and data.

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
