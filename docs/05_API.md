# API

Other programs (a CAD tool, a script, another AI) search Partsfinder through this HTTP API; the app uses it too.

Start: double-click `api.bat` (or `python -m partsfinder.api` in `backend/`).
Base URL: `http://127.0.0.1:8000`. To try it out: **http://127.0.0.1:8000/docs** (automatic, clickable documentation).

By default the server listens only on the local computer. **Without keys** it has no login: anyone who can reach the API can pick any `company_id` and import any folder on that computer with `/ingest`. The server therefore **refuses to start on a network address (`--host`) without keys**.

## API keys (optional)
Set `PARTSFINDER_API_KEYS="key_a=company_a,key_b=company_b,key_n=company_a:nuclear,admin=*"` (in `backend/.env`, never in git). `company:group:group` also gives that company's restricted parts of those groups. Then:
- Every request except `GET /health` needs a key: `Authorization: Bearer <key>` or `X-API-Key: <key>`. Otherwise **401**.
- A company key is pinned to that company. A different `company_id` gives **403**; without `company_id` the own company is used. Parts of another company stay **404**.
- The admin key (`*`) picks `company_id` itself and is the only one allowed for `POST /ingest` and `GET /companies` (otherwise **403**).
- The test app asks for a key when `/health` says `keys_required` (checked with `GET /me`) and sends it with every request, previews and the datasheet window included.

## Restricted parts and outside AI
Details and the rules: [10_COMPANY_LIBRARIES.md](10_COMPANY_LIBRARIES.md).
- A part with `access_group` (shown in every part payload) is only visible to keys with that group, and to the admin key. For everyone else it does not exist (404, never in search, similar shapes, properties, quality or duplicates). Without keys, `PARTSFINDER_LOCAL_GROUPS="nuclear,aero"` shows those groups on this pc.
- **`X-Partsfinder-AI: 1`**: the request comes from an AI client (another AI that searches the library). It never gets restricted parts, nor any part of a confidential company. It can only reduce what is visible.
- `/search` with AI: Claude only judges when it may see everything this caller may see. Otherwise the library's own checks answer (`ai_used: false`, message "AI is off for this library ...").
- `/search/image` sends data to Claude: **403** for a confidential company and for a key that can see restricted parts of its company.
- `POST /companies/{id}/settings` `{"confidential": true}` (admin): no part of that company ever goes to an outside AI. `GET /companies` shows `confidential` and `restricted_parts`.

## Company separation
Pass `company_id` with every request (e.g. `"company_a"`). You then see the general library plus your own parts. Without `company_id` you see only the general library. A part of another company always gives **404**, as if it does not exist. Download links in a response already contain the `company_id`.

---

## `POST /search`
Find an existing model in plain language.

**Request**
```json
{
  "query": "small green outdoor chair, horticulture",
  "company_id": "company_a",
  "limit": 5,
  "filters": {"max_dims_mm": [600, 600, 900]},
  "use_ai": true
}
```
| Field | Required | Notes |
|---|---|---|
| `query` | yes* | The question (max 1000 characters). *Empty only together with `filters`: then the parts that meet the filters, by name (see "Filters without a question") |
| `company_id` | no | Who asks (see company separation) |
| `limit` | no | 1-20, default 5 |
| `filters` | no | **Hard requirements**, never relaxed: `category`, `sectors`, `material`, `color`, `standards`, `kind` (`part`/`assembly`), `max_dims_mm`, `min_dims_mm` (3 numbers, order/orientation does not matter), `library` (`all`/`global`/`company`), `properties` (see below), `engineering` (see below) |
| `use_ai` | no | `false` = search engine only, no Claude (faster, free) |

**Response**
```json
{
  "status": "found",
  "message": "2 matching garden chairs found.",
  "ai_used": true,
  "interpreted_requirements": {
    "search_text": "garden chair green outdoor horticulture small",
    "category": "furniture/seating/garden-chair",
    "sectors": [], "standards": [],
    "must_have": ["outdoor chair"], "nice_to_have": ["green", "small"],
    "fixed_filters": {"max_dims_mm": [600, 600, 900]},
    "search_steps": ["all requirements"]
  },
  "results": [
    {
      "id": "garden-chair-green",
      "library": "global",
      "company_id": null,
      "kind": "assembly",
      "name": "Garden chair green",
      "description": "Garden chair in green, powder-coated steel, seat height 450 mm, total height 820 mm.",
      "category_path": "furniture/seating/garden-chair",
      "sectors": ["horticulture", "hospitality", "consumer-products"],
      "tags": ["chair", "garden chair", "green"],
      "needs_review": false,
      "material": "steel powder-coated",
      "color": "green",
      "dims_mm": [460.0, 520.0, 820.0],
      "volume_mm3": 2671000.0,
      "mass_g": null,
      "standards": [],
      "properties": {"seat_height_mm": 450, "stackable": false, "outdoor": true},
      "source": "generated",
      "license": "Partsfinder test data (free to use)",
      "files": [
        {"format": "step", "is_primary": true, "path": "data/global/furniture/garden-chair-green.step",
         "url": "/parts/garden-chair-green/file?format=step&company_id=company_a"}
      ],
      "thumbnail_url": "/parts/garden-chair-green/thumbnail?company_id=company_a",
      "summary": "Stackable outdoor garden chair in green plastic",
      "highlights": [{"label": "Seat height", "value": "450 mm"}, {"label": "Envelope", "value": "460 × 520 × 820 mm"}],
      "mesh_url": "/parts/garden-chair-green/mesh?company_id=company_a",
      "datasheet_url": "/parts/garden-chair-green/datasheet?company_id=company_a",
      "verdict": "fits",
      "score": 0.05231,
      "match_reasons": ["outdoor garden chair", "green", "horticulture sector"],
      "mismatch_reasons": []
    }
  ]
}
```

**`spec_checks`** (per result, always present, empty if the question has no exact specs): the engineering
requirements read from the question (see "Engineering specs" below), each checked against the part's own data:
```json
"spec_checks": [
  {"spec": "designation", "label": "designation", "requested": "6204", "found": "6204-2RS", "status": "match"},
  {"spec": "seal", "label": "seal", "requested": "2Z", "found": "2RS", "status": "mismatch"}
]
```
`status`: `match`, `mismatch` (the part has another value) or `unknown` (the part does not state it).
The requirements themselves are in `interpreted_requirements.specs`.

**`verdict`**: `fits`, `close` or `no_fit` (the AI layer). `search_steps` lists the relaxing steps used: "all requirements", "without sector/material/colour/kind", "dimensions only", "no filters".

**`status`**
- `found`: at least one result with `verdict: "fits"`, reusable as is
- `partial`: only `verdict: "close"`, usable as a starting point to adapt (see `mismatch_reasons`)
- `none`: nothing usable: draw it new

**`need`**: the defining values the question leaves open, in asking order, each with the values that exist among the parts of that kind that were found (most common, at most 6, in size order), e.g. "a bolt" → `[{"spec": "thread", "label": "thread", "choices": ["M6", "M8", "M10", ...]}, {"spec": "length_mm", "label": "length", "choices": ["16 mm", "20 mm", ...]}]`. A choice is written so it can be added to the question as is ("a bolt M8"). Kinds: bolts and screws (thread, length), nuts and washers (thread), bearings (number or bore), pillow blocks and linear bearings, stepper motors (NEMA frame), pulleys (profile, teeth), gears (module, teeth), flanges (DN), profiles (size), collars and couplings (bore), cylinders (bore, stroke). The library never fills these in itself; the caller asks the engineer or takes them from the drawing. Empty when nothing is open. Also in `interpreted_requirements.need`.

**`decided`**: `true` when the library's own checks settle the question, so no AI is needed to answer it: one kind of part is asked for and either a part meets every requirement and every word (above), or the code knows that kind of part (bolts, nuts, washers, bearings, pillow blocks, steppers, pulleys, gears, flanges, profiles, collars, couplings, cylinders) and the library has it. Then the answer is the code's own: "fits", the deviation in numbers, which word no part has ("No bolt in the library is stated as green; the closest are shown.": when no part of that kind has a colour, finish or material word of the question, the search is done again without that word, so "a green bolt" and "a red bolt" give the same bolts and choices as "a bolt", each with "green: not stated"; a word that may say what the part is, such as "planetary" or "pump", is never left out, `interpreted_requirements.lacking`), and/or the open value to choose (`need`). `results` then only holds parts of that kind (a part counts when its name or category names it). Not decided: several parts in one question, plain language without a known kind, nothing of that kind in the library; the app has the AI judge those (when it is on).

**`groups`** (only when the question asks for several parts, e.g. "give me 1 M8 bolt and 1 arduino", "M8 bolt, nut and washer"): every requested part is searched and judged on its own, so a bolt is never judged against "arduino". Per requested part: `request` (its own search text: request words and the quantity taken off, a thread shared by the joint added to the parts that need one, "M8 nut"), `quantity` (the number asked for, or `null`) and the same `status`, `message`, `results`, `need`, `decided` and `ai_used` as a single search. The top level then has `results` = every group's results in order (for callers that do not read `groups`), `status` `found` when every part was found, `none` when none was, else `partial`, and `decided` = every group decided. With AI, Claude only judges the requested parts the library's own checks cannot settle (one call pair per such part). A piece that names no part is a requirement of the part before it ("M8x30 bolt, A4"), and "with" only separates where a known kind of part follows ("bolt with nut", not "bearing with two shields"). `interpreted_requirements.parts` lists the requested parts with their status.

**`seconds`** and **`cached`**: how long the search took on the server, and whether the answer came from memory. The server remembers the last 256 answers per route, question (all fields, including `company_id`) and library version; any write to the database (an import, feedback, also by another program such as the import command) starts a new version, so a remembered answer is never stale. An answer that fell back because Claude failed is not remembered. A remembered answer keeps its original `seconds`.

**`ai_used: false`**: Claude was unavailable (no key, credit used up, no internet, spending cap reached) or switched off. If the question contains exact engineering specs, the library judges itself on `spec_checks`: `fits` = every requirement is met by the part's own data (and the part is the kind of part asked for), `close` = the defining specs match but something else deviates or is not stated; `status` is then `found` / `partial` as above. Without specs you get the best search results, all marked `close`, and the reason is in `message`.

**Guard (with and without AI)**: a part that violates a defining spec of the question (standard, thread, designation, NEMA frame, bore, module, teeth, DN, profile size, rail size, piston diameter) is never `fits`; every deviation is added to `mismatch_reasons` in numbers ("thread M10 instead of M8").

### Engineering specs
Read deterministically from the question (no AI needed), e.g.:

| Question | `interpreted_requirements.specs` |
|---|---|
| `DIN 912 M8x30 A2-70` | `{"standard": ["DIN 912"], "thread": "M8", "length_mm": 30, "property_class": "A2-70"}` |
| `deep groove ball bearing 6204-2RS` | `{"designation": "6204", "seal": "2RS"}` |
| `bearing 20x47x14` | `{"inner_diameter_mm": 20, "outer_diameter_mm": 47, "width_mm": 14}` |
| `NEMA 23 stepper 1.89 Nm 8 mm shaft` | `{"frame_size": 23, "holding_torque_nm": 1.89, "shaft_diameter_mm": 8}` |
| `GT2 pulley 20 teeth 5 mm bore` | `{"belt_profile": "GT2", "teeth": 20, "bore_mm": 5}` |
| `spur gear module 1.5 z40` | `{"module": 1.5, "teeth": 40}` |
| `ISO 15552 cylinder bore 50 stroke 100` | `{"standard": ["ISO 15552"], "piston_diameter_mm": 50, "stroke_mm": 100}` |
| `weld neck flange DN50 PN16` | `{"dn": 50, "pn": 16}` |
| `T-slot profile 40x40 slot 8 length 1000` | `{"profile_size": "40x40", "slot_width_mm": 8, "length_mm": 1000}` |
| `M8x30 bolt A4 not galvanized` | `{"thread": "M8", "length_mm": 30, "material_grade": "A4", "excluded": ["galvanized"]}` |
| `exactly ISO 4762 M8x30` | `{"standard_exact": ["ISO 4762"], "thread": "M8", "length_mm": 30}` |
| `plate EN AW-6082` / `plate 1.0038` | `{"material_grade": "6082-T6"}` / `{"material_grade": "S235JR"}` |
| `servo motor 400 W` / `heater 0.75 kW` | `{"power_w": 400}` / `{"power_w": 750}` |
| `hex bolt M8x30 at least 1000 MPa` / `bolt M8 yield 640 MPa` | `{"thread": "M8", "length_mm": 30, "tensile_strength_mpa": 1000}` / `{"yield_strength_mpa": 640}` |
| `shelf bracket that holds 50 kg` / `bracket max load 500 N` | `{"max_load_kg": 50}` / `{"max_load_kg": 51.0}` |
| `bearing 6205 dynamic load rating 14 kN` / `static load rating 7 kN` | `{"designation": "6205", "load_rating_kn": 14}` / `{"static_load_rating_kn": 7}` |
| `plate ISO 2768-m` | `{"tolerance": "ISO 2768-m"}` (a tolerance class, not a standard the part must name) |

Equivalent standards count as the same (DIN 912 = ISO 4762, DIN 933 = ISO 4017, DIN 125 = ISO 7089, ...).
With "exactly", "only" or "strictly" before the standard (`standard_exact`) only that number counts: a DIN 912 part is then a mismatch, found "DIN 912 (equivalent, not the same number)".
**Materials (`material_grade`)**: explicit grades and EN numbers (1.4404, AISI 316L, S235 = 1.0038, EN AW-6082 = AlSi1MgMn, C45, POM, ...) and "stainless"/"inox". A family accepts every member (A4 = 1.4401, 1.4404, 1.4571; A2 = 1.4301, 1.4307, ...; "stainless" = any stainless grade); a precise number on a part that only states its family is `unknown`. A loose "steel" is never a requirement.
**Exclusions (`excluded`)**: "not / no / without / non / excluding" + galvanized (zinc, hot-dip), stainless, plastic (nylon, POM, PA, PTFE, ...), brass, aluminium, copper, rubber. The part's material, name, description, tags and material/finish/coating properties are checked: a hit is a mismatch ("found": the word, e.g. "zinc plated"), a stated other material is a match, nothing stated is `unknown`. In `spec_checks` the requested value reads "not galvanized".
**Text requirements (`feature`)**: finishes, locking and certificates the library can only see in the part's own text (black oxide, zinc flake, anodized, passivated, nyloc / nylok, thread locking, food grade, RoHS, ATEX, FDA, ...). A part that states it matches; otherwise the requirement is `unknown` ("black oxide: not checked"), never silently dropped.
**Upper limits (`max_size_mm`, `max_mass_g`)**: "max 50 mm", "at most 100 mm", "under 3 g", "lighter than 0.5 kg". The size is compared with the largest outer dimension, the mass with the stored mass (or the estimate from volume × density); read as "≤ 50 mm" in `spec_checks`.
**Strength and load (at least)**: `tensile_strength_mpa`, `yield_strength_mpa` ("at least 800 MPa", "N/mm²", "yield 640 MPa"), `max_load_kg` ("holds 50 kg", "load capacity 100 kg", "max load 500 N", "1 t"; N and kN are converted), `load_rating_kn` and `static_load_rating_kn` (bearings, "load rating C 14 kN", "C0 7 kN"). A part with a higher value fits ("≥ 800 MPa" in `spec_checks`; a lower one reads "tensile strength 800 MPa, less than 1000 MPa"). The value is the part's own (`properties`, see 03_DATAMODEL), otherwise what follows from a standard: the property class of a bolt (ISO 898-1: 8.8 = 640 / 800 MPa; ISO 3506-1: A2-70 = 450 / 700 MPa) or a named grade (EN 10025-2 S235/S275/S355, EN 10088-2 1.4301/1.4404, EN 755-2 6060/6061/6063/6082/7075-T6). A loose "steel" gives nothing. Load ratings only come from the part itself (catalogue values of a maker are not copied). Without a value the requirement is `unknown`, so the part is never `fits`.
**Tolerance (`tolerance`)**: "ISO 2768-m" (also "-mK"), "h7", "g6": the part's `tolerance` property must state it; "ISO 2768-mK" on the part meets "ISO 2768-m".
**Preferences (`interpreted_requirements.preferences`)**: what follows "preferably", "ideally", "if possible", "nice to have" or "optionally" (up to a comma) is not a requirement: it only moves parts that have it up the list, and it is not in `spec_checks`. "M8x30 bolt, preferably A4": every M8x30 bolt fits, the A4 ones first.
**Every word counts (without AI)**: a part is only `fits` when, besides meeting every spec, it contains every other word of the question in its name, description, tags, material or properties ("galvanized", "green", "nut"). Words that only phrase a spec ("at least", "bore", "shaft", "length", ...) and numbers and units are left out. A missing word makes the part `close` with "galvanized: not stated" in `mismatch_reasons`.
**Materials as words**: "aluminium" (or "aluminum"), "brass", "bronze", "copper", "titanium", "plastic", "nylon", "rubber", "wood", "steel", "stainless" count only in the part's stated `material` (and its name, and material properties); a part without a stated material is checked on its name, description and tags. "For aluminium profiles" in a description makes no part aluminium. Also when the AI judges, a part that lacks the asked material is never `fits` ("brass: not stated").
**Honest "none" without AI** (`decided: true`): for a short question that names a part ("cable gland"), when no candidate is that part (the last word, whole word, singular or plural; a capitalised product name such as "Nora" does not count), status is `none`: "no part in the library is a gland". When a defining spec of the question is stated by no candidate of that kind (e.g. `power_w` for "servo motor 400 W"), status is `none` too: "no motor in the library states its power, so none can be confirmed as 400 W". For other unknown kinds only candidates that are the thing asked for are shown.
**Message without AI**: with `use_ai: false` or the AI switched off the message is "The best search results, not judged yet: check whether they fit." (no error); "AI not available (...)" only when the AI failed.
**Confirmed before "fits"**: a defining spec, the property class, the material grade, every exclusion, text requirement and upper limit must be confirmed by the part's own data; when one is `unknown` the part is "close", also when the AI judged it "fits".
"At least" specs: `holding_torque_nm`, `pn` (a stronger part also fits). A part property may be a list
(e.g. `property_classes: ["8.8", "10.9", "12.9", "A2-70"]`): one CAD model valid for several grades.
Parts whose properties match a defining spec exactly are added to the candidates even when the question's
words do not mention them (e.g. "bearing 20x47x14" finds the 6204).

---

Card fields (every part payload, also in `/parts/{id}`, `/similar`, `/search/batch`, `/search/image`):
- `summary`: one short sentence for a result card (first sentence of the description, max. ~150 characters, without the "Also known as" list; the kind of part when the description only repeats the name).
- `highlights`: at most 3 defining values (`label` + `value` with unit), e.g. thread and length for a bolt, d × D × B for a bearing; `Envelope` (outer dimensions) as the fallback. Provenance properties are never included.
- `thumbnail_url` carries `?v=<modification time>` of the preview, so a redone preview gets a new link and is never served from a stale cache.
- `mesh_url`: link to the 3D mesh, or `null` if the part has no STEP or STL file.
- `datasheet_url`: link to the printable datasheet.

## `GET /parts/{id}?company_id=...`
All info of one part (same fields as in `results`, without `verdict`/`score`/reasons), plus `components` for an assembly
and `used_in` ("where used": the assemblies that contain this part, with how many, at most 50; only assemblies this
company may see, so another company's assemblies never show):
```json
"components": [{"id": "garden-chair-leg", "name": "Garden chair leg", "quantity": 4}],
"used_in": [{"id": "machine-frame-1000", "name": "Machine frame 1000", "quantity": 24}]
```

## `GET /parts/{id}/file?format=step&company_id=...`
Download the CAD file. Without `format` you get the primary file.
- `404`: the part or that format does not exist (or belongs to another company)
- `410`: the file is no longer where it was imported from

## `GET /parts/{id}/thumbnail?company_id=...`
The PNG preview (256×256, transparent background).

## `GET /parts/{id}/mesh?company_id=...`
Binary STL (`model/stl`) for the 3D viewer in the app. An STL file of the part is served as it is; a STEP file is tessellated on the first request and cached in `data/meshes/` (outside git; key = file path + size + modification time, so a changed file gets a new mesh).
- `404`: the part does not exist, belongs to another company, or has no STEP/STL file
- `422`: the file could not be turned into triangles

## `GET /parts/{id}/datasheet?company_id=...`
Printable HTML datasheet: name, description, preview, general data, geometry (envelope, volume, mass), all technical properties and the stored file formats. Only data that is in the library; with a "Print / Save as PDF" button. The app opens it in its own window. `404` as above. With API keys the preview image on the page needs the key too (the page itself is meant for the local app).

## `POST /search/image`
Search with a photo, render or drawing of a part. Needs the AI (otherwise **503**).
```json
{"image_base64": "<base64, optionally with a data: prefix>", "media_type": "image/jpeg",
 "note": "M8, stainless", "company_id": "company_a", "limit": 5}
```
`media_type`: `image/png`, `image/jpeg`, `image/webp` or `image/gif`; max. 10 MB after decoding (**413**), invalid base64 gives **400**. Claude identifies the part and writes an engineering search text; sizes are only used when they are readable on the part (markings such as "6204-2RS") or given in `note`, never guessed from the photo. Then the normal `/search` runs (interpret, search, judge, spec checks). Nothing is stored. Optional `filters` and `within`, exactly as with `/search`: hard requirements that are never relaxed (the app sends its Filters panel and folder choice).
Response: the `/search` fields plus
```json
"identified": {"is_mechanical_part": true, "part_type": "socket head cap screw", "search_query": "socket head bolt M8",
               "visible_features": ["hexagon socket", "cylindrical head"], "markings": ["M8"], "confidence": "high"},
"query": "socket head bolt M8"
```
If the image shows no technical part: `status: "none"`, no results.

## `POST /ingest`
```json
{"folder": "C:/path/to/folder", "company_id": "company_a", "use_ai": true, "thumbnails": true, "background": false,
 "sync": false, "allow_mass_removal": false}
```
Imports all CAD files from a folder (a share such as `\\\\nas\\cad` works too). Without `company_id` they go to the general library; a `company_id` has 2-40 characters (a-z, 0-9, - or _), otherwise **400**. The response contains `added`, `updated`, `skipped`, `removed`, `needs_review`, `failed`, `warnings`, `components_linked`, `seconds` and `summary`.

**Folder rules** ([10_COMPANY_LIBRARIES.md](10_COMPANY_LIBRARIES.md)): files excluded by a `.partsfinderignore` are never read; a `.partsfinderaccess` gives the parts of that folder a restricted group (company libraries only); an unusable rule file skips its whole folder (in `failed`, as `folder/`). Rules in folders above the imported folder count too. A file with new content at the same path updates its part (same id). Restricted files and all files of a confidential company never get an AI description.

**`"sync": true`**: also removes the parts of this folder whose file is gone or is now excluded, completely (see `POST /remove`). If no CAD file is found at all, or more than half of the folder's parts (and more than 20) would go, nothing is removed and `warnings` says why, unless `"allow_mass_removal": true`.

## Data packs: `GET /packs`, `POST /packs/install` and `POST /packs/{name}/remove` (on this pc, like the AI key)
- `GET /packs` → `{"installed": [pack.json + installed_at, installed_parts]}`.
- `POST /packs/install` `{"path": "C:/.../partsfinder-pack-kicad-3d-2026-11-13.zip"}` (a pack folder or .zip on the
  pc of the search engine; only from that pc) → `{"job_id"}`; follow it with `GET /ingest/{job_id}`: `progress`
  `{"done", "total"}`, and when done `report` `{"name", "parts", "added", "updated", "unchanged", "duplicates",
  "failed", "errors"}`. Searching keeps working meanwhile; one import or install at a time (409 otherwise).
- `POST /packs/{name}/remove` → `{"name", "removed"}`; 404 when the pack is not installed.
- Parts from a pack have `source`, `source_ref` (the original file) and `license`. Their file can be an https URL at
  the original library: `GET /parts/{id}/file` and `/mesh` download it once (502 with a plain message when the
  internet is not reachable).

## `GET /audit?company_id=...&action=...&limit=200` (admin)
Who searched for and downloaded what, newest first, for one company (without `company_id`: the general library). Each entry: `id`, `at`, `actor` (`local`, or `key:` + the first 12 characters of the key's SHA-256; never the key), `company_id`, `action` (`search`, `search_image`, `download`, `mesh`, `datasheet`, `ingest`, `remove`, `settings`), `target` (part id or folder; never a part name) and `detail` (the question, the file format, or counts). Previews (thumbnails) are not logged. Writing the log does not clear the remembered answers.

## `POST /remove` (admin)
```json
{"folder": "//nas/cad/old", "company_id": "company_a"}
```
Removes every part of that library whose main file lies in that folder (the folder may already be gone), with everything stored about it: the rows, the search entries (text and vectors), previews, 3D caches and feedback. The database overwrites deleted pages (`secure_delete`), the text index is optimised and the write-ahead log truncated. The CAD files themselves are not touched. Response: `{"removed": [ids], "total": n}`. Logged in the audit log.

**Direct (default):** the request waits until the import is done and the server holds up other requests meanwhile (one database connection).

**In the background (`"background": true`):** the response is immediately `{"job_id": "…", "status": "running"}`. The import runs in its own database connection (WAL), so searching keeps working. Poll with `GET /ingest/{job_id}`: `{"status": "running" | "done" | "error", "lines": 12, "log_tail": ["…"], "report": {…same fields as above…}, "error": "…"}` (`report` when `done`, `error` when `error`). At most one import at a time (otherwise **409**); the last 20 jobs stay available while the server runs. Without a database file (`:memory:`, tests) this falls back to direct import. The test app uses the background variant and shows progress. Both are admin-only when API keys are set.

## `GET /health`
```json
{"status": "ok", "version": "0.1.0", "parts": 319, "embedder": "intfloat/multilingual-e5-small",
 "ai_available": true, "ai_model": "claude-haiku-5-5", "ai_note": null,
 "ai_spent_usd": 0.0123}
```
`ai_available`: whether the AI is on. It runs on the user's own Anthropic API key: set in the app (Settings → `POST /settings/ai`) or `ANTHROPIC_API_KEY` in `backend/.env`. Without a key `ai_note` says how to add one, and every question is answered by the library's own checks. `ai_spent_usd`: the estimated cost on that key since the server started.

`image_search_available`: whether `/search/image` can run (needs the AI).

`keys_required`: whether this API has keys (`PARTSFINDER_API_KEYS`); the test app then asks for one.

`accounts`: people can sign in with a name and password (there is at least one account). `setup_needed`: no account and no keys yet: the first admin account can be made with `POST /setup`.

## Accounts and signing in
People sign in with a name and a password (docs/10_COMPANY_LIBRARIES.md). The answer is a **session token**, used exactly like an API key: `Authorization: Bearer <token>`. It gives the same rights as a key: an admin account = `*`, a company account = `company:group:group`.
- **Without keys and without accounts** (one pc): no sign-in, everything as before.
- **With accounts, without keys**: a request without a token sees only the general library (`company_id` gives **403**, admin routes **401/403**). A token that is not valid (any more) gives **401**, also there.
- **With keys**: every request needs a key or a token (**401**), except `GET /health`, `POST /login`, `POST /setup`.

`POST /setup` `{"username", "password", "remember": false}`: the first admin account, only while there is no account at all (**409** otherwise) and only from the pc that runs the library (**403** from another address). Signs in at once.
`POST /login` `{"username", "password", "remember": false}` → `{"token": "...", "me": {...as GET /me}}`. Wrong name or password: **401** with the same message for both. After 5 failures for one name (or 20 from one address) within 15 minutes: **429** for 15 minutes, also with the right password. A session lasts 12 hours, with `remember` 30 days.
`POST /logout`: ends this session.
`POST /companies` `{"name": "Janssen Engineering", "id"?}` (admin) → the new company with an empty library; `id` is made from the name when left out (`janssen-engineering`; a-z, 0-9, `-`, `_`), **409** when it exists. `GET /companies` also gives `people` (number of accounts) and `groups` (every restricted group the company uses: on parts, on folders, given to people) per company.
**Searching chosen folders** (`/search` → `"within"`, the app's folder picker): `{"general": true, "other": true, "folders": ["Main CAD"] | null}`: the general library, the company's parts that were not uploaded (`other`), and the uploaded folders by name (`null` = all of them). Leave `within` out to search everything the caller may see. Nothing ticked = no results.

**Several groups on one part**: `access_group` may hold several groups, sorted and joined by commas (`"aero,nuclear"`); a caller with any one of them sees the part.

`DELETE /companies/{id}` (admin) → `{"removed_parts", "removed_accounts"}`: every part of the company completely (search entries, previews, 3D caches, feedback), its accounts and their sessions, its folder settings and the folders it uploaded. Files it was imported from elsewhere (a share) are not touched. **409** while an import for it runs.
Admin only: `GET /users?company_id=` (never a password hash), `POST /users` `{"username", "password", "role": "company" | "admin", "company_id", "groups": []}` (a new company id makes the company), `PATCH /users/{username}` `{"password"?, "disabled"?, "groups"?}` (a new password or disabling ends every session of that account), `DELETE /users/{username}`. The last admin account cannot be disabled or removed (**400**). After removing an account or changing a password the write-ahead log is emptied into the database (`wal_checkpoint(TRUNCATE)`, also at every start), so no old copy of the account or its password hash stays behind in a file (freed pages are wiped by `secure_delete`). Passwords: at least 8 characters; usernames 3-40 characters (letters, digits, `.`, `_`, `-`).

## Forgot the administrator password: `GET /setup/admins`, `POST /setup/reset` (on this pc)
On the pc that runs the library, whoever sits there (not signed in, or as an admin; never a company account, never
from another pc: **403**) can see the administrator accounts (`{"admins": [{"username", "disabled"}]}`) and give one
a new password: `POST /setup/reset` `{"username", "password", "remember"}`. The account is enabled again, every
other session of it ends, earlier failed tries no longer count, and the answer signs in like `/login`
(`{"token", "me"}`). **404** for a name that is not an administrator, **400** for a password under 8 characters.
Logged in the audit log as "admin password reset on this pc".

## `GET /me`
Who this request belongs to (key or signed-in account). Never returns a key or token:
`{"keys_required": false, "username": "anna", "role": "company", "company_id": "acme", "groups": ["nuclear"], "key": null}`. `role` is `company`, `admin` (`company_id` null), `public` (not signed in on a library with accounts), or `local` (no keys or accounts: `groups` = `PARTSFINDER_LOCAL_GROUPS`). `key` is the key's fingerprint when an API key was used, `username` when an account signed in.

## A company's own library: upload a folder from your own pc
For a company account or key (only its own company), and for the admin (`?company_id=` names the company). Never for an AI client (`X-Partsfinder-AI: 1`: **403**) or without signing in (**401**).
- `GET /library` → `{"company_id", "exists", "confidential", "parts", "restricted_parts", "other_parts", "folders": [{"name", "parts", "updated_at"}], "coverage": {...as /quality}, "upload_extensions": [...], "max_file_mb": 500}`. `other_parts`: parts of the company that were not uploaded (imported by the admin).
- `POST /uploads/{name}/start` → `{"upload_id"}`. `name`: 1-80 characters, letters, digits, spaces, `.`, `_`, `-`, `(`, `)`.
- `PUT /uploads/{name}/files?upload_id=&path=` with the raw bytes of one file. `path` is relative to the folder: no `..`, no drive or absolute path, no hidden folders, at most 25 levels; only CAD files, a JSON next to them, and the folder rules `.partsfinderaccess` / `.partsfinderignore` (**400** otherwise, before anything is written). At most `PARTSFINDER_UPLOAD_MAX_MB` (500) MB per file (**413**).
- `POST /uploads/{name}/finish` `{"upload_id", "use_ai": true, "access"?: "company" | "nuclear" | "aero,nuclear"}` → `{"job_id", "status": "running"}`: the uploaded files replace the folder (or make it) and it is imported in the background like `POST /ingest` with `sync`: new and changed files are imported, files no longer in the folder leave the library completely. An upload without a CAD file changes nothing (**400**). `access` sets who sees the whole folder, with the same rules as `PUT /uploads/{name}/access` (`inherit` is **400** here); left out, it stays what it was. Follow it with `GET /ingest/{job_id}` (a company only sees its own imports).
- `DELETE /uploads/{name}` → `{"removed": [...], "total": n}`: every part from that folder, completely, and the uploaded files.
- `GET /library` also gives `name`, `groups` (the company's restricted groups), `my_groups` (the groups this caller can choose for a folder: `null` for the admin = every group and new ones, a company account its own groups) and per folder `access` and `tree`: the folder and its subfolders that hold parts, `[{"path": "reactor", "depth": 1, "parts": 14, "own": "nuclear" | "company" | "invalid" | null, "access": "nuclear", "inherited": "company"}]` (`own` = set in that folder itself, `access` = what applies).
- `PUT /uploads/{name}/access?company_id=` `{"path": "reactor", "access": "nuclear" | "aero,nuclear" | "company" | "inherit"}` (several groups separated by commas: people with any one of them see the folder). The admin chooses any group. A company account only groups it has itself (**403** otherwise), and only for a folder that everyone at the company sees now or that is only for groups it has (**403** for a folder the administrator closed to it): who sees that folder and everything below it. It is written as a `.partsfinderaccess` file into the folder, kept in `folder_access` and written again after every upload (so it stays when the company sends the folder again), and the folder is imported again in the background (`{"job_id"}`; only the access of unchanged parts changes). `inherit` = the same as the folder above.
The test app applies `.partsfinderignore` on the pc before uploading, so an excluded file is never even read there; the library applies the rules again when it imports.

## AI judgement and properties
In AI mode (`use_ai: true`) Claude gets a list of the filterable properties of the **general** library (never of a company) and may fill in a `properties` filter for an explicit technical requirement (e.g. "M8", "shaft of 8 mm"). Only existing keys with a valid condition are used. If the first round finds nothing with this filter, it is dropped automatically (like sector, material and colour). The filter used is in `interpreted_requirements.properties`.

## `POST /settings/ai`
```json
{"api_key": "sk-ant-..."}
```
Hands the user's own Anthropic API key to the search engine (the app does this from Settings, and after every start).
Only on the pc that runs the search engine (**403** from another address), by whoever uses that pc: without
signing in, or as the admin; a company account or company key gets **403**. (Who sits at that pc can change its
settings anyway; accounts are for sharing the library with other pcs.) The key is kept in memory only: never in the database, a file or a log, and
never sent back. An empty key switches the AI off. Response: `{"ai_available": true, "ai_model": "claude-haiku-5-5",
"ai_note": null}`; **400** when the AI is switched off with `PARTSFINDER_AI_BACKEND=off`. Remembered answers are
cleared, so the next question is answered with (or without) the AI.

## Filter on properties (`filters.properties`)
A dictionary `key → condition`; all conditions must hold (hard requirement, never relaxed):
- text: `{"thread": "M8"}` (exact, case-insensitive)
- number: `{"length_mm": 60}` (exact) or `{"length_mm": {"min": 40, "max": 60}}` (range; text values never match)
- yes/no: `{"galvanized": true}`

Keys may contain only `a-z`, `0-9` and `_`, otherwise 422. A part without that property drops out. The key goes to SQL as a parameter, never in the SQL text.

## Filter on engineering values (`filters.engineering`)
A dictionary `key → condition` on the engineering values (see "Engineering data" below), also where a value follows from a standard (property class 8.8 = at least 800 MPa tensile strength, S235 = at least 360 MPa) or is an estimate (mass):
- numbers, `{"min": x, "max": y}` (either or both) in the unit of the key: `mass_g`, `yield_strength_mpa`, `tensile_strength_mpa`, `max_load_kg`, `load_rating_kn`, `static_load_rating_kn`, `max_torque_nm`, `max_pressure_bar`, and `hardness_hrc` (the HRC number of a stated hardness)
- `tolerance`: text the stated tolerance contains, `{"tolerance": "2768-m"}` (spaces and dashes ignored)

```json
"filters": {"engineering": {"tensile_strength_mpa": {"min": 800}, "max_load_kg": {"min": 50}}}
```
A part that does not state (or imply) the value drops out. Checked per part after the SQL filters, on up to 400 candidates per ranking; any other key or condition gives **422**.

## Filters without a question
`POST /search` with an empty `query` and at least one filter: the parts that meet the filters, by name, at most `limit`. Nothing to judge, so no AI: `ai_used: false`, `decided: true`, `browse: true`, every result `verdict: "close"` with no reasons, `status` `found` or `none` ("No part meets these filters. A part that does not state a filtered value drops out."). An empty `query` without filters gives **422**.

## `GET /filters`
Query: `company_id` (optional), `category` (optional prefix). What a filter panel can offer, from the parts this company may see (within the category):
```json
{"total": 1769,
 "categories": [{"value": "fasteners", "count": 541}, {"value": "fasteners/bolt", "count": 212}],
 "materials": [{"value": "steel 8.8", "count": 120}], "colors": [...], "standards": [{"value": "ISO 4017", "count": 60}],
 "kinds": [{"value": "part", "count": 1675}, {"value": "assembly", "count": 94}],
 "max_dims_mm": [400, 600, 2000],
 "engineering": [{"key": "tensile_strength_mpa", "label": "Tensile strength", "unit": "MPa", "type": "number", "count": 551}],
 "properties": [... as GET /properties ...]}
```
`categories` counts every level of the path; `materials`, `colors` and `standards` the 500 most common (a filter field you can type in narrows them); `max_dims_mm` the largest outer size per sorted axis; `engineering` only the values at least one part states (or implies). Another company's parts never count.

## `GET /properties`
Query: `company_id` (optional), `category` (optional prefix). Lists which properties exist on the parts this company may see:
`[{"key": "length_mm", "count": 12, "type": "number", "min": 8, "max": 100, "values": ["40", ...]}, {"key": "thread", "count": 30, "type": "text", "values": ["M8", "M6"]}]`.
Properties of other companies never appear. `type` is `number`, `text` or `boolean`; origin data (`needs_review`, `ai_metadata`, `original_name`, `folder_in_freecad_library`) is left out. For a boolean property the filter works with `true`/`false` and with the text `"yes"`/`"no"`. The part JSON also contains `source_ref`.

**Engineering data (`engineering`)**: every part in a result (and `GET /parts/{id}`) carries `[{"key", "label", "value", "unit", "text", "source"}]`: `mass_g`, `yield_strength_mpa`, `tensile_strength_mpa`, `max_load_kg`, `load_rating_kn`, `static_load_rating_kn`, `max_torque_nm`, `max_pressure_bar`, `tolerance`, `hardness`, only those that are known. `text` is ready to show ("≥ 800 MPa", "≈ 181 g", "14.8 kN"); `source` says where it comes from: `"part data"`, `"minimum per ISO 898-1, property class 8.8"` (or another standard), or `"estimate: volume from the CAD file × density of the material"`. Computed when reading, nothing is stored. Details, Compare and the datasheet show these under "Specifications", with the other specs.

**Mass:** `mass_g` is the real mass when known (`mass_estimated: false`). Otherwise the API estimates when reading: volume × material density (table in `partsfinder/mass.py`: steel, stainless, aluminium, copper, brass, wood, PP, PE, PVC, nylon, ABS, POM…), with `mass_estimated: true`. No estimate for assemblies, unknown material, missing volume, or if the volume exceeds the bounding box by more than 5 % (then the volume is wrong): `mass_g` is then `null`. Nothing is stored.

## `GET /parts/{id}/similar`
Parts with a similar shape. Query: `company_id`, `limit` (1-20, default 5), `same_category` (default `false`).
Compared are the **sorted outer dimensions** (so independent of orientation) and the volume; candidates lie within a factor 3 of every dimension.
Response: `{"reference": "id", "results": [{...part..., "similarity": 0.93, "dims_diff_mm": [0.5, -1.0, 2.0]}]}`.
`similarity` runs from 0 to 1 (10 % deviation in dimensions ≈ 0.74); below 0.3 nothing is returned. The part itself is excluded.
`dims_diff_mm` = candidate minus reference, per sorted dimension. Parts without dimensions give **400**. This says nothing about details (holes, threads): it is a first selection.

## `POST /search/shape`
Search by your own CAD file. The **body is the file itself** (`Content-Type: application/octet-stream`, max. 50 MB), not JSON.
Query: `filename` (decides the format: `step`, `stp` or `stl`), `company_id`, `limit`, `kind`. The file is measured and discarded; nothing is stored.
Response: `{"measured": {"dims_mm": [...], "volume_mm3": ...}, "results": [... as with /similar ...]}`.
Errors: **400** (other format, empty or unreadable file, invalid `Content-Length` header), **413** (too large). Only parts the company may see are returned.

## `POST /feedback` and `GET /feedback`
Thumbs up/down for a found part; stays local. Body of `POST`: `{"part_id": "...", "rating": "up" | "down", "company_id": "...", "query": "the question", "note": "..."}`.
The part must be visible to that company (otherwise **404**). `GET /feedback?company_id=...&limit=100` returns only that company's feedback (without `company_id`: the general library's), newest first.

**Learning from feedback:** for exactly the same query (case and whitespace ignored) a part with a thumbs up from this company moves up slightly and one with a thumbs down moves down slightly (the last rating counts). Parts never disappear from the results, and another company's feedback does not count.

## `POST /search/batch`
Several parts in one request (e.g. bolt, nut and washer of one connection).
```json
{"company_id": "company_a", "searches": [{"query": "hex bolt M8", "limit": 5, "filters": {"properties": {"thread": "M8"}}}, {"query": "hex nut M8"}]}
```
1 to 10 searches, each with `query`, `limit` (1-20) and the same `filters` as `/search`. No AI judgement (the caller judges). Response: `{"searches": [{"query": "...", "status": ..., "results": [...]}, ...]}` in the same order. The company applies to all searches.

## `GET /quality`
Query: `company_id`. How complete is the data of that company's **own** library (without `company_id`: the general one)? Response: `total`, `coverage` (percentage with `description`, `material`, `dimensions`, `volume`, `properties`, `preview_image` and `reviewed`), `needs_attention` (the 20 most incomplete parts with what is missing) and `incomplete_total`. The AI can only check requirements that are in the data; this shows what a company still has to complete. The test app shows it after an import.

## `GET /duplicates?company_id=...&limit=50`
Probable duplicates in the **own** library (without `company_id`: the general one): parts of the same kind with (nearly) the same sorted outer dimensions (1 %) and the same volume (2 %). Response:
`{"groups": [{"size": 3, "bbox_mm": [10, 20, 30], "parts": [{"id", "name"}, ...]}], "total": n}`, largest groups first.
A hint to check, not proof: equal dimensions do not always mean the same part. Company separation as `/quality`; `limit` 1-500; no change to the database. Client: `PartsLibrary.duplicates()`.

## `GET /taxonomy` and `GET /companies`
The categories and sectors (for dropdowns), and the known companies with their part count (for the test app).

---

## Use from another program (Python)
A full working example is in `backend/examples/example_client.py`. In short:
```python
import requests

r = requests.post("http://127.0.0.1:8000/search", json={
    "query": "M8 hex bolt 40 mm", "company_id": "company_a",
    "filters": {"max_dims_mm": [20, 20, 60]},
}, timeout=120).json()

if r["status"] == "found":
    best = r["results"][0]
    url = next(f["url"] for f in best["files"] if f["is_primary"])
    step = requests.get("http://127.0.0.1:8000" + url).content   # reuse
elif r["status"] == "partial":
    ...   # best result as starting point; r["results"][0]["mismatch_reasons"] says what to adapt
else:
    ...   # draw new
```

## Cost
Every `/search` with AI makes 2 Claude requests (understand the question + judge). With Haiku 5.5 that costs ~$0.001. The API stops using AI once `PARTSFINDER_MAX_SPEND_USD` is reached (per server run) and falls back to the plain search engine. `/health` shows what has been spent.
