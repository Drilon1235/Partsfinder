# Decisions

## Partsfinder: open source (12 Nov 2026)
| # | Question | Decision |
|---|---|---|
| 1 | Name and owner | **Partsfinder**, a product of DZ IT Services (dzitservices.be) |
| 2 | Licence | Code **AGPL-3.0**; the names and logos of Partsfinder and DZ IT Services (`brand/`) are not covered by it |
| 3 | Form | Desktop app (Electron + local Python search engine), per user or per company pc |
| 4 | AI | Bring your own key: every user enters their own Anthropic API key; everything works without AI |
| 5 | Data | Only openly licensed sources: no scraping, no copied catalogues of manufacturers or distributors |
| 6 | Language | App, docs, code and data in English |
| 7 | Brand | The DZ IT Services brand (`brand/`), shared with the sister app Stepix and dzitservices.be |

## Why the user's own key, and no subscription
Anthropic does not allow a product for others to run on a claude.ai login or subscription limits. Each user therefore
runs the AI on their own API key and pays Anthropic directly; Partsfinder never holds a shared key. The key is stored
encrypted by the operating system and only handed to the search engine on the same pc. Without a key every question
is answered by the library's own checks, which settle most technical questions anyway.

## Choices made
- **Python backend with FastAPI.** Other programs call it over HTTP; the app uses the same API.
- **"All formats":** STEP/STL are analysed fully. Native formats (.sldprt, .f3d, .ipt, ...) can only be opened with
  their own software, so they are stored with the part and analysed via a STEP version.
- **Sorting** uses a fixed taxonomy (`taxonomy.yaml`), later alignable with eCl@ss.
- **Company separation** is in every database query (`company_id`), even without a login.
- **The code answers first, the AI only judges what the code cannot settle.** Faster (~40 ms), cheaper, and honest:
  a wrong defining spec is never "fits", whatever the AI says.
- **Another AI as judge:** another program's AI can call `/search` with `use_ai: false` and judge the candidates
  itself; with the header `X-Partsfinder-AI: 1` it never sees restricted or confidential parts.
- **API keys are optional** (`PARTSFINDER_API_KEYS`): without keys everything works as before (handy locally and in tests); with keys each key is pinned to one company. Separation stays in every query; the key only decides which `company_id` is allowed.
- **Mass is an estimate when reading**, not in the database: a real weighed mass must never be overwritten and wrong table values are easy to fix this way. Always marked with `mass_estimated`.
- **Shape search compares only outer dimensions and volume**, not details: honest and explainable, without an extra library. A real shape descriptor (e.g. a 3D embedding) is a later step.
- **Feedback stays local** (own table, per company). Nothing is shared automatically or used to train models.
- **Feedback adjusts the order (round 3b):** only for exactly the same question and only within the same company; small effect (`FEEDBACK_BOOST`, about one rank), never hiding. One company can push its favourite part up without anyone else noticing.
- **Engineering specs are checked deterministically, not only by the AI:** engineers ask for exact parts (6204-2RS, DIN 912 M8x30 12.9, NEMA 23 1.89 Nm, DN50 PN16). `specs.py` reads these from the question and checks them against the part's properties; the result (`spec_checks`, requested versus found) goes to the user, the ranking and the AI judge. A wrong defining spec is never "fits", whatever the AI says. Without AI, a part that meets every spec is "fits" by itself.
- **Engineering demo library instead of consumer test data for demos:** about 400 generic engineering parts (`scripts/engineering`), dimensions from public standards, no manufacturer names or part numbers (we invent nothing that looks like a real catalogue entry). Motor ratings are labelled "typical". The consumer test models stay for the automated tests (company separation etc.).
- **One CAD model for several grades:** a DIN 912 M8x30 has the same geometry in 8.8, 12.9 or A2-70; the part lists `property_classes` instead of five identical files (which the duplicate check would refuse anyway).

## Engineering data, no commercial data
- A part shows and can be searched on strength, load, tolerance, hardness and mass. Not price, supplier or stock.
- Only certain values: the part's own data, or what a public standard fixes (minimum strength of a property class or
  a named grade). A loose "steel" gives no strength. Mass from volume × density is shown as an estimate (≈).
- Load ratings of bearings, castors and the like come only from the part's own data: those are a maker's catalogue
  values, and we do not copy catalogues (same rule as no scraping).

## Data
- No free source has millions of usable models. The general library grows only from openly licensed sources, with
  source and licence stored per part: **bd_warehouse** (standard parts generated ourselves, Apache-2.0), the
  **FreeCAD parts library** (CC-BY 3.0, attribution kept), KiCad 3D models (CC-BY-SA 4.0 with exception) and BOLTS.
  See the roadmap, phase P2.
- **Not used:** the ABC dataset (copyright with the makers, no licence from the researchers) and the Fusion 360
  Gallery (non-commercial research only), not even for internal testing.
- Catalogues of manufacturers and distributors (TraceParts, McMaster-Carr, Misumi, GrabCAD, ...) are never copied.
  Live sources with an official API (Nexar/Octopart, DigiKey, Mouser) only on the user's own key, with the results
  kept on the user's pc.
