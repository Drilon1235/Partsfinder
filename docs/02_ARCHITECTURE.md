# Architecture

```
            ┌──────────────┐        ┌──────────────┐
            │ Other program│        │ Electron app │
            │  or other AI │        │ (Partsfinder)│
            └──────┬───────┘        └──────┬───────┘
                   │ HTTP                  │ HTTP
                   ▼                       ▼
            ┌──────────────────────────────────────┐
            │         API (FastAPI, Python)        │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │  AI layer (Claude API, the user's    │
            │  own key; optional)                  │
            │ question → requirements → search →   │
            │ judge                                │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │             Search engine            │
            │ filters + semantic + keyword (FTS)   │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │  Database (SQLite + sqlite-vec)      │
            │  general  |  per company (private)   │
            └──────────────────▲───────────────────┘
                               │
            ┌──────────────────┴───────────────────┐
            │           Import pipeline            │
            │ read STEP/STL, dimensions,           │
            │ thumbnail, description, embedding    │
            └──────────────────▲───────────────────┘
                               │
              local folder / NAS │ later: open data packs
```

## How a search runs
1. **Question:** "small green outdoor chair, horticulture"
2. **Requirements (Claude):**
   ```json
   {"search_text": "garden chair green outdoor horticulture small",
    "category": "furniture/seating/garden-chair", "sectors": [], "color": null,
    "max_dims_mm": null, "standards": [],
    "must_have": ["outdoor chair"], "nice_to_have": ["green", "small"]}
   ```
3. **Search:** hard filters first (category, company separation), then semantic and keyword. This yields the best 15 candidates (if too few, filters are relaxed step by step; the caller's hard requirements never).
4. **Judge (Claude):** per candidate `fits`, `close` or `no_fit`, with `match_reasons` and `mismatch_reasons` (with numbers: asked vs present). The best (default 5) are returned.
5. **Answer:** status `found` / `partial` / `none` + results in JSON.

## Two ways to use an AI
- **The built-in AI layer** (`/search` with `use_ai: true`, the steps above), on the user's own Anthropic API key (Settings in the app, or `ANTHROPIC_API_KEY` in `backend/.env`). Without a key the library's own checks answer.
- **Another AI as judge**: another program's AI calls `/search` with `use_ai: false` and the header `X-Partsfinder-AI: 1` (it then never sees restricted or confidential parts), and judges the candidates itself.

## Tech choices
| Part | Choice | Why |
|---|---|---|
| Backend language | Python 3.11+ | CAD libraries (CadQuery, trimesh) and ML are Python |
| API | FastAPI | Simple, fast, automatic docs |
| Database | SQLite + sqlite-vec (later PostgreSQL + pgvector) | No server needed for a prototype, easy to scale |
| Keyword search | SQLite FTS5 | Built in, good for "DIN 933", "M8" |
| Embeddings | Local model via sentence-transformers (multilingual, e.g. multilingual-e5) | Free, offline; the library and all questions are in English |
| AI | Claude API (tool use) | Understand the question + explain |
| Reading CAD | CadQuery (OpenCascade) for STEP, trimesh for STL | Open source, Python |
| App | Electron | Windows + Mac |

## How the search engine ranks
1. Hard filters in SQL (company separation, category, sector, material, dimensions…) decide who takes part.
2. Two rankings within that group: meaning (cosine distance of embeddings) and exact words (FTS5/bm25).
3. Merged with Reciprocal Rank Fusion (`1/(60+rank)` per list), plus:
   - bonus when a standard from the question occurs exactly (DIN 933),
   - bonus for coverage of the query words, rare words weighing more (idf, counted only over the parts the asking company may see),
   - penalty for loose assembly components, unless the question is about them.

## Scalability
- Up to ~100,000 parts SQLite is fine: measured 170 ms per query at 100,000 parts (see `docs/06_TESTPLAN.md`).
- Towards millions of parts: switch to PostgreSQL + pgvector or a vector database. The search engine sits behind one interface, so the rest of the code does not change.
