# Data model

## Table `parts`
| Field | Type | Notes |
|---|---|---|
| `pk` | INTEGER | Internal numeric ID (link to the search indexes) |
| `id` | TEXT (uuid) | Public unique ID |
| `company_id` | TEXT, NULL | **NULL = general library**, otherwise the company |
| `kind` | TEXT | `part` or `assembly` |
| `name` | TEXT | E.g. "Garden chair compact, steel" |
| `description` | TEXT | Free description (used for embedding) |
| `category_path` | TEXT | From taxonomy, e.g. `furniture/seating/chair` |
| `sectors` | JSON list | E.g. `["horticulture", "hospitality"]` |
| `tags` | JSON list | Free keywords |
| `material` | TEXT | E.g. "steel S235", "PP", "oak" |
| `color` | TEXT, NULL | |
| `bbox_x_mm`, `bbox_y_mm`, `bbox_z_mm` | REAL | Outer dimensions in mm along the model's own axes (X = width, Y = depth, Z = height) |
| `volume_mm3` | REAL, NULL | Measured from the CAD file (for STL only if the model is watertight) |
| `mass_g` | REAL, NULL | Real mass from the source; not filled anywhere yet and cannot be set via JSON. The API estimates mass when reading (see `mass_estimated`) without storing anything |
| `standards` | JSON list | E.g. `["DIN 933", "ISO 4017"]` |
| `properties` | JSON | Rest: thread, max. load, IP rating… Filterable via `filters.properties` and listable via `GET /properties` (keys `a-z0-9_`) |
| `source` | TEXT | `generated`, `upload`, `nas`, and the name of an open data pack |
| `source_ref` | TEXT, NULL | Original ID/path at the source |
| `license` | TEXT, NULL | Who may use it |
| `thumbnail_path` | TEXT, NULL | |
| `checksum` | TEXT | To detect duplicate imports |
| `created_at`, `updated_at` | TEXT (ISO) | |
| `access_group` | TEXT, NULL | Schema 2. **NULL = the whole company**; otherwise only keys with this group see the part (company parts only; `a-z0-9_-`, max 40). Set by the import from a `.partsfinderaccess` file, never by a JSON. See [10_COMPANY_LIBRARIES.md](10_COMPANY_LIBRARIES.md) |

Duplicate imports: the same `checksum` may occur only once per library. A file that was already imported is skipped on the next import, **unless the JSON next to it has changed**: then name, description, category, properties etc. are updated under the same id (including the search index). Improving metadata = edit the JSON and import again. An update replaces the part only if the new data is valid, and the old version is removed and the new one stored in one transaction (on any error the old version stays), and links to assemblies that contain the part are kept. If the JSON gives the same CAD file a **new id**, the part is moved to that id (assembly links and feedback move along); this is how the standard parts got their English ids (one-off rename script, last version in commit `7d84650`).

## Engineering properties (in `properties`)
Exact specs an engineer searches on. The search engine reads the same specs from the question
(`backend/partsfinder/specs.py`) and checks them per part (`spec_checks` in the API). Use these names so
they are checked; numbers in the unit of the key. A value may be a list when one CAD model is valid for
several variants (same geometry).

| Key | Example | Used for |
|---|---|---|
| `designation` | `"6204-2RS"`, `"UCP205"`, `"LM12UU"`, `"ISO 4762 M8x30"` | catalogue designation |
| `thread` (or `for_thread` on washers) | `"M8"` | fasteners |
| `length_mm`, `pitch_mm` | `30`, `1.25` | fasteners, shafts, profiles, rails |
| `property_class` / `property_classes` | `"12.9"` / `["8.8","10.9","12.9","A2-70","A4-80"]` | bolts, nuts |
| `material_grade` / `material_grades` | `"100Cr6"`, `"6063-T5"` / `["P250GH","1.4404"]` | materials by grade |
| `inner_diameter_mm`, `outer_diameter_mm`, `width_mm` | `20`, `47`, `14` | bearings (d x D x B), bushings |
| `seal` | `"2RS"`, `"2Z"`, `"open"` | rolling bearings |
| `bore_mm`, `shaft_diameter_mm` | `8` | pulleys, gears, couplings, pillow blocks, motors |
| `frame_size`, `holding_torque_nm`, `rated_current_a` | `23`, `1.89`, `3.0` | stepper motors (NEMA) |
| `module`, `teeth` | `2`, `30` | gears, pulleys |
| `belt_profile` | `"GT2"`, `"HTD 5M"` | timing pulleys |
| `tensile_strength_mpa`, `yield_strength_mpa` (also `rm_mpa`, `rp02_mpa`) | `800`, `640` | strength; otherwise derived from `property_class` or a named grade in `material` |
| `max_load_kg` (also `load_capacity_kg`, `working_load_kg`, `max_load_n`, `max_load_kn`) | `80` | brackets, castors, hooks, shelves: the load it holds |
| `load_rating_kn`, `static_load_rating_kn` (also `c_kn`, `c0_kn`, `..._n`) | `14.8`, `7.8` | bearings: dynamic C and static C0 |
| `max_torque_nm`, `max_pressure_bar` (also `max_pressure_mpa`) | `12`, `16` | couplings, valves, cylinders |
| `tolerance` (also `general_tolerance`) | `"ISO 2768-mK"`, `"h7"` | machined parts, shafts |
| `hardness` (or `hardness_hrc` / `hardness_hv` / `hardness_hb`) | `"58 HRC"` / `58` | hardened parts |

Strength, load, tolerance, hardness and mass are shown per part under "Specifications" with where each value comes
from (`backend/partsfinder/engineering.py`). Nothing derived is stored: the part's own value always wins; strength
follows only from a property class (ISO 898-1, ISO 3506-1) or a named grade (EN 10025-2, EN 10088-2, EN 755-2), mass
from the measured volume × the density of the material (an estimate). Load ratings come only from the part's own data.
The same values can be filtered on (`filters.engineering`, the Filters panel): checked per part when searching, also
when the value follows from a standard; a part that states no value never passes. Nothing is stored for it.
| `profile_size`, `slot_width_mm` | `"40x40"`, `8` | T-slot profiles |
| `piston_diameter_mm`, `stroke_mm`, `port_thread` | `50`, `100`, `"G1/4"` | pneumatic cylinders |
| `dn`, `pn` | `50`, `16` | flanges, piping (EN 1092-1) |
| `nps`, `pressure_class` | `"1 1/2"`, `300` | ASME B16.5 flanges (NPS as written: `"2"`, `"3/4"`, `"1 1/2"`) |
| `chord_thickness_mm` (with `inner_diameter_mm`, `outer_diameter_mm`) | `2.62` | O-rings (cross section) |
| `width_mm`, `height_mm` (with `shaft_diameter_mm`, `length_mm`) | `8`, `7` | parallel keys (b x h x l, DIN 6885); without them the section follows from the shaft diameter |
| `rail_size` | `20` | linear guides |
| `tolerance` | `"h6"`, `"m6"` | shafts, dowel pins |
| `diameter_mm` | `6` | dowel pins |
| `power_w` (or `rated_power_w`, `nominal_power_w`, `output_power_w`) | `400` | motors, heaters, power supplies (in W) |

## Engineering demo library (`data/global/engineering`, not in git)
About 440 (439) generic engineering parts made by `scripts/engineering/build.py` from the data in
`scripts/engineering/catalog.py` (ISO 15 bearings with 2RS/2Z/open, UCP pillow blocks, LMxUU bushings,
h6 linear shafts, NEMA 17/23/34 steppers, GT2/HTD 5M pulleys, module 1-3 spur gears, T-slot profiles,
ISO 15552 / ISO 6432 cylinders, EN 1092-1 PN16 flanges type 01/05/11, size 15/20/25 profile rails and
carriages, jaw couplings, ISO 4762 / ISO 4017 bolts in common lengths, ISO 10511 nyloc nuts, ISO 8734 dowel
pins, DIN 976-1 threaded rod, T-slot nuts, corner brackets for T-slot profiles, DIN 705 shaft collars).
`source: "partsfinder-engineering"`, no manufacturer and no manufacturer part numbers.
`scripts/engineering/enrich_standard_parts.py` adds property classes, DIN equivalents and
bearing designations to the existing bd_warehouse standard parts (JSON only, geometry unchanged).

## Table `companies`
| Field | Type |
|---|---|
| `id` | TEXT (bv. `company_a`) |
| `name` | TEXT |
| `created_at` | TEXT |
| `confidential` | INTEGER (0/1) | Schema 2. 1 = no part of this company ever goes to an outside AI (`POST /companies/{id}/settings`, admin) |

A company is created automatically with its first part.

## Table `part_files`
One part can have several files (STEP + native + STL).
| Field | Type |
|---|---|
| `part_id` | TEXT |
| `format` | TEXT (`step`, `stl`, `sldprt`, `f3d`, `dxf`…) |
| `path` | TEXT |
| `is_primary` | BOOL (the file used for analysis) |

## Table `assembly_components`
| Field | Type |
|---|---|
| `assembly_id` | TEXT |
| `part_id` | TEXT |
| `quantity` | INTEGER |

Read both ways: an assembly's `components`, and a part's `used_in` ("where used", `GET /parts/{id}`), each only with
parts and assemblies the asking company may see. Nothing new is stored for it.

## Table `feedback`
Thumbs up/down from users per found part. Stays in the local database; nothing leaves it.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER | Sequence number |
| `company_id` | TEXT, NULL | Who gave it (NULL = general library only) |
| `part_id` | TEXT | The rated part (no foreign key: survives if the part disappears) |
| `query` | TEXT | The question for which the part was found |
| `rating` | TEXT | `up` of `down` |
| `note` | TEXT | Free note (max. 1000 characters) |
| `created_at` | TEXT | Timestamp (UTC) |

The table was added without bumping the schema version (`CREATE TABLE IF NOT EXISTS`): an existing database gets it on the next start.

## Table `audit_log` (schema 2)
Who searched for and downloaded what. See [10_COMPANY_LIBRARIES.md](10_COMPANY_LIBRARIES.md).
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER | Sequence number |
| `at` | TEXT | Timestamp (UTC) |
| `actor` | TEXT | `local` (no keys or accounts), `public` (not signed in), `user:<username>` (signed in), or `key:` + the first 12 characters of the key's SHA-256; never a key, token or password |
| `company_id` | TEXT, NULL | The company the request was for |
| `action` | TEXT | `search`, `search_image`, `download`, `mesh`, `datasheet`, `ingest`, `remove`, `settings`, `account` |
| `target` | TEXT | Part id or folder (never a part name) |
| `detail` | TEXT | The question for searches, the format for downloads, counts for imports |

## Table `users` (schema 3)
People who sign in (docs/10_COMPANY_LIBRARIES.md).
| Field | Type | Notes |
|---|---|---|
| `username` | TEXT PK (case-insensitive) | 3-40 characters: letters, digits, `.`, `_`, `-` |
| `password_hash` | TEXT | `scrypt$n$r$p$salt$hash` (n=16384, r=8, p=1, 16-byte salt); never the password |
| `role` | TEXT | `admin` (every company) or `company` |
| `company_id` | TEXT, NULL → companies | The company of a company account; NULL for an admin. Removing the company removes its accounts |
| `groups` | TEXT (JSON list) | Restricted groups this account sees (company accounts only) |
| `disabled` | INTEGER | 1 = cannot sign in; its sessions are ended |
| `created_at`, `last_login` | TEXT | UTC |

## Table `sessions` (schema 3)
| Field | Type | Notes |
|---|---|---|
| `token_hash` | TEXT PK | SHA-256 of the session token; the token itself is never stored |
| `username` | TEXT → users | Removing or renaming the account removes / follows its sessions |
| `created_at`, `expires_at` | TEXT | UTC; 12 hours, or 30 days with "stay signed in". Expired sessions are cleaned up at the next sign-in |

Writes to `users`, `sessions` and `audit_log` do not count as a change of the library (remembered answers stay valid).
Removing an account or changing a password empties the write-ahead log into the database right away (and so does
every start of the API), and freed pages are overwritten (`secure_delete`): no old copy of a removed account or an
old password hash stays in `partsfinder.db` or `partsfinder.db-wal`. The audit log keeps the name (`user:anna`), never a password.

## Uploaded folders (no database change)
A company's folder uploaded from its own pc is stored under `data/companies/<company>/uploads/<folder name>/` (outside git)
and imported from there like any folder; its parts point to those files. Uploads go to
`uploads/.staging/<upload id>/` first and only replace the folder when the upload is finished.

## Table `folder_access` (schema 4)
Who may see a folder a company uploaded, as set in the app (admin). Written as `.partsfinderaccess` into that folder after every upload.
| Field | Type | Notes |
|---|---|---|
| `company_id` | TEXT → companies | Removing the company removes its rows |
| `upload` | TEXT | The uploaded folder's name |
| `path` | TEXT | Subfolder inside it, `''` = the whole folder |
| `access` | TEXT | `company` (everyone of the company) or restricted groups, sorted and joined by commas (`aero,nuclear`) |

## Schema 4 (10 Nov 2026)
An existing database gets the table `folder_access` on the next start.

## Schema 3 (10 Nov 2026)
An existing database gets the tables `users` and `sessions` on the next start (nothing is rebuilt). An older program refuses a schema 3 database.

## Schema 2 (10 Nov 2026)
An existing database gets `parts.access_group`, `companies.confidential` and `audit_log` on the next start (added columns; nothing is rebuilt). An older program refuses a schema 2 database. The connection runs with `PRAGMA secure_delete = ON`: deleted parts are overwritten in the database file.

## Data packs (no database change)
A data pack is an openly licensed parts library, built by `scripts/datapacks/build.py` (folder or `.zip`):
| File | Content |
|---|---|
| `pack.json` | `format` (1), `name` (a-z, 0-9, -), `title`, `version`, `license`, `homepage`, `files` (`remote` or `included`), `source_revision`, `parts` |
| `parts.jsonl` | one part per line: the fields of `PartCreate` (id, name, description, category_path, sectors, tags, standards, properties, material, bbox_mm, volume_mm3, checksum, source, source_ref, license); `thumbnail_path` relative to the pack; `files[].path` relative to the pack (`files/...`) or an https URL at the original repository, pinned to a commit |
| `thumbnails/<id>.png` | preview per part |
| `files/` | the CAD files, for packs that ship them |
| `LICENSE.txt`, `ATTRIBUTION.md` | the licence of the data and who made it |

Installing (`partsfinder/packs.py`) copies the pack to `data/packs/<name>/`, adds its parts to the general library
(same id: updated; same file already in the library under another id: skipped), computes the search vectors with this
installation's own model and records the pack in `meta` as `pack:<name>` (pack.json + `installed_at`,
`installed_parts`). Removing deletes exactly the ids of its `parts.jsonl`.
- `part_files.path` may be an https URL (`raw.githubusercontent.com` or `gitlab.com` only, `remote.py`): the file is
  downloaded once, when someone opens or views it, to `data/cache/files/` (a cache, safe to delete).
- `PARTSFINDER_HOME` (optional) is the base of relative paths and of `data/`; the installed app sets it to the user's
  own data folder.

## Derived files (no database change)
- `data/meshes/<part id>-<key>.stl`: 3D meshes for the app's viewer (`GET /parts/{id}/mesh`), tessellated from the STEP file on first use and named after the part, so removing a part removes its cache too. A cache: safe to delete, outside git, not referenced from the database. (Older caches without the part id in the name can simply be deleted.)
- Previews (`data/thumbnails/...png`) of elongated parts (longest / second dimension > 6) show a piece of 3 × the second dimension (ingest/thumbnail.py); existing ones are redone with `scripts/demo/rethumb_elongated.py` (only PNG files change).
- `summary`, `highlights`, `mesh_url` and `datasheet_url` in the API are computed from the existing fields; nothing new is stored.

## Search indexes
- `parts_vec`: sqlite-vec table with an embedding per part (`rowid` = `parts.pk`)
- `parts_fts`: FTS5 op `name`, `description`, `tags`, `standards`, `material`, `category_path` (`rowid` = `parts.pk`)
- Both are updated or cleaned up automatically via triggers when a part changes or disappears.
- Vector search: up to 3,000 visible parts, or when a company may see less than 30 % of all parts, every visible part is compared (`vec_distance_cosine`); otherwise the `parts_vec` KNN index is used and the same company and filter conditions are applied to its results (the embeddings are unit vectors, so the order is the same). The result is always identical to comparing every part (test: `tests/test_speed.py`). Measured at 49,000 parts: 400 ms → 55 ms per vector search.
- Remembered answers (`/search`) live only in the server's memory; nothing is stored in the database.

## Metadata next to a CAD file (`<name>.json`)
If `chair.json` sits next to `chair.step`, the import pipeline uses that data instead of letting Claude guess. Allowed fields: `id`, `kind`, `name`, `description`, `category_path`, `sectors`, `tags`, `material`, `color`, `standards`, `properties`, `source`, `source_ref`, `license`, plus `components` (for assemblies: list of `{"id": ..., "quantity": ...}`).

Anything the import determines itself is ignored if it appears in the JSON: `company_id` (the library you import into), `access_group` (only from `.partsfinderaccess`), `files`, dimensions, volume, checksum and preview image. A JSON can therefore never put a part in another company's library or make it visible to other people. A JSON excluded by `.partsfinderignore` is never read.

The test data uses this format (`source: "generated"`). Use it too for your own models whose properties you already know.

## Taxonomy (`backend/partsfinder/taxonomy.yaml`)
Own tree with 3 levels (category/subcategory/type), later alignable with the industry standard eCl@ss. An unknown category or sector is rejected with a suggestion ("Did you mean…?"). Excerpt:
```yaml
categories:
  furniture: [seating, tables, storage, bedroom]
  fasteners: [bolt, nut, screw, washer, pin, rivet]
  connections: [bracket, hinge, coupling, plate]
  profiles: [steel, aluminium, plastic]
  drivetrain: [bearing, shaft, gear, transmission, spring]
  enclosures: [electronics, machine]
  construction: [structure, finishing, element, sanitary]
  horticulture: [greenhouse, cultivation]
sectors: [construction, horticulture, agriculture, industry, machine-building, furniture,
          hospitality, office, automotive, electronics, logistics, medical, ...]
```
The taxonomy is a file, not code: adding categories needs no programming.

`other/unknown` is for imports that could not (yet) be classified. Such parts get the tag `needs-review` and `properties.needs_review = true`, so they are easy to find and complete later.

## Guess from the file name (import without JSON)
`hints_from_name` fills `standards`, `material` and the properties `thread` and `length_mm` from the file name (DIN/ISO/EN number, `M8x40`, stainless/alu/...). The part stays marked `needs-review`; a JSON file or AI always takes precedence.

## Settings outside the database
- **The user's own AI key** is never in the database: the app stores it encrypted by the operating system
  (`anthropic-key.bin` in the app's data folder) and the search engine keeps it in memory (`POST /settings/ai`).
- **Database file:** `backend/partsfinder.db` (`PARTSFINDER_DB_PATH`). A library from before the rename
  (`backend/orlix_parts.db`, with its `-wal` and `-shm` files) is renamed to it once, at the first start.
