# Roadmap

Partsfinder is an open-source (AGPL-3.0) desktop app by DZ IT Services. Tick off what is done: `- [x]`.

## Built so far
- [x] Data model with company separation in every query; categories and sectors (`taxonomy.yaml`)
- [x] Import of STEP, STL and native CAD files with dimensions, previews, mass, descriptions and folder rules
      (`.partsfinderignore`, `.partsfinderaccess`); background import; sync of a folder or NAS share
- [x] Search engine: hard filters, meaning (embeddings) and exact words (FTS5), merged; "No existing model found"
      when nothing fits; 170 ms at 100,000 parts
- [x] The library's own checks: thread, length, designation, standard, property class, material, DN, module, ...,
      with the deviation in numbers; most questions are settled in ~40 ms without AI
- [x] Engineering data: strength, mass, load, load ratings, tolerance, hardness, with where each value comes from;
      searchable as requirements ("at least 800 MPa", "holds 50 kg")
- [x] AI layer (optional): understands vague questions and judges what the checks cannot settle; never calls a
      part "close" for a value the engineer did not ask
- [x] Several parts in one question; filters panel; search with a photo or a STEP/STL file; compare; datasheet;
      where used; possible duplicates; quality report
- [x] Accounts (admin and company people), groups for restricted folders, "no AI" per company, audit log
- [x] Electron app; API with clickable documentation (`/docs`)

## Phase P0 — Brand and rules
- [x] DZ IT Services brand kit in `brand/` (marks, icons, colours, fonts, `brand/BRAND.md`)
- [x] Rules for contributors and AI assistants (`CLAUDE.md`)

## Phase P1 — Open-source ready
- [x] Name Partsfinder everywhere (package `partsfinder`, app, environment variables `PARTSFINDER_*`, database
      `partsfinder.db` with a one-time rename of the old file, folder rule files)
- [x] Bring your own key: Settings in the app, key encrypted by the OS, handed to the search engine on this pc only
      (`POST /settings/ai`); no Claude subscription path
- [x] No sign-in needed on your own pc; accounts are optional (Settings → Accounts), the user chooses the
      administrator's name and password; no default account or password
- [x] The app in the DZ brand: navy theme, Inter and Space Grotesk, Partsfinder icon, About in Settings
- [x] In-app confirmation instead of the browser's confirm box; the question stays in the search bar; an honest
      message for parts nobody could judge
- [x] `LICENSE` (AGPL-3.0), README, `CONTRIBUTING.md`, `SECURITY.md`, `NOTICE`
- [x] Secret scan of the tree; new repository with a clean history
- [ ] Make the repository public
- [x] Windows installer (electron-builder) with the Python engine and the language model included, built by
      GitHub Actions; a version tag makes a draft GitHub Release
- [x] Electron end-to-end test in the repository (from the source on every push, the installed app on every build)

## Phase P2 — A much larger library (open licences only)
- [x] Data packs: one builder for every source (`scripts/datapacks/build.py`), install and remove in the app
      (Settings → Data packs), on the command line (`python -m partsfinder.packs`) or the API (`/packs`);
      nothing of it in git
- [x] Source and licence per part, shown in Details with a link to the original file; files of open libraries stay
      at their repository (pinned commit) and are downloaded once when opened
- [x] Standard parts generated with bd_warehouse (Apache-2.0): ~6,000 ISO/DIN/ASME bolts, screws, nuts, washers,
      bearings, O-rings, retaining rings, keys, flanges and gears
- [x] The full FreeCAD parts library (CC-BY 3.0), ~2,500 parts
- [x] KiCad 3D models (CC-BY-SA 4.0 with exception), ~6,200 electronic components
- [x] Adafruit CAD parts (MIT), ~490 boards, breakouts and displays
- [ ] Licence filter in the filters panel
- [ ] The newest KiCad models from GitLab, BOLTS collections, NopSCADlib vitamins (GPL-3), built by GitHub Actions
- [ ] Data packs as release downloads once the repository is public; "Download" next to each pack in the app
- [ ] Live sources on the user's own key: Nexar/Octopart, DigiKey, Mouser (price, stock, datasheet)
- [ ] Benchmark from 26 to ~100 questions; measured before and after every source

## Later
- [ ] Company accounts that add their own people; single sign-on (Microsoft / Google)
- [ ] An on-premise package for a company's own server (installer, service, backups)
- [ ] A "BOM from STEP" button that uses the engine of Stepix, the sister app by DZ IT Services
