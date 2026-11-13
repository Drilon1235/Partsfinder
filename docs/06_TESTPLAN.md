# Test plan

## Automatic tests
`python -m pytest` in `backend/` (also part of `check.bat`): 313 tests covering the data model, company separation,
import, folder rules, accounts, the search engine and its checks, the AI layer (with a fake Claude), the API and the
test queries themselves. The tests use simple embeddings (`HashingEmbedder`) and never call an AI.

`python scripts/ui_screenshots.py` takes every screen of the app at 1440, 820 and 390 px with fixed test data
(`app/test/mock_partsfinder.js`) and fails on a JavaScript error, a window that scrolls sideways or a cut-off table.

## Test queries (`backend/tests/queries.yaml`)
50 questions, each with the expected result:
```yaml
- {group: clear, q: "hex bolt M8 x 40 DIN 933", ids: [bolt-din933-m8x40-88, bolt-din933-m8x40-a2]}
- {group: vague, q: "something to hang a shelf on the wall", category: connections/bracket/wall-bracket}
- {group: requirements, q: "chair", filters: {max_dims_mm: [400, 400, 600]}, category: furniture/seating/chair}
- {group: none, q: "titanium rocket engine nozzle", status: none}
- {group: separation, q: "growing tray for tomatoes", company: company_a, company_top: company_a}
```

| Group | Count | What is tested |
|---|---|---|
| clear | 20 | The exact part exists (dimensions, standards, thread sizes) |
| vague | 10 | Everyday words without technical terms |
| requirements | 8 | Hard filters as a caller sends them (dimensions, material, standard, sector, kind, colour) |
| none | 7 | Does not exist: the honest answer is "nothing found" |
| separation | 5 | Own parts yes, those of another company never |

For **every** question it is also checked that no part of another company is among the results.

## Goals and results (without AI)
After the English translation: offline embeddings on the 319 test models give 100% at rank 1, 100% in top 3, 100% rightly "nothing found", 0 leaks. On the real pc (1,370 parts, real model): 95% at rank 1, 100% in top 3, 0 leaks, 0 wrongly "nothing found", but only 71% rightly "nothing found": "solar panel" matches window *panels*, "smartphone case" matches a PC *case*. Without AI, an unknown word plus a known noun ("espresso machine") looks the same as a valid vague question ("ergonomic chair"), so this is a limit of word matching; with the AI judging these come back as `no_fit`.

| Measure | Goal | Simple embeddings | Real model (Windows) |
|---|---|---|---|
| Correct model at rank 1 | ≥ 60% | 90% | see `backend/eval_log.txt` |
| Correct model in top 3 | ≥ 80% | 93% | |
| Rightly "nothing found" | ≥ 90% | 100% | |
| Wrongly "nothing found" | as low as possible | 0 of 42 | |
| Leaks between companies | **0** | 0 | |
| Speed per query (300 parts) | < 5 s | 4 ms | |

## Result with AI (Claude Haiku 5.5)
`ai_test.bat` (needs `ANTHROPIC_API_KEY` in `backend/.env`): the 50 test queries + 2 extra (hex bolt M30x200,
garden chair in purple).
- **50/52 correct (96%), 0 leaks**, 2 requests to Claude per query.
- Miss 1: "hex nut M8": the M8 nut was among the candidates but the AI overlooked it. Fix: every candidate carries `query_words_matched` (which words of the question literally occur in it, also from properties like `thread: M8`), plus the instruction to check dimensions against the candidate itself.
- Miss 2: "greenhouse bracket for a growing gutter" as company B: no leak, but plain angle brackets came back as "close". Fix: "close" is only the same kind of part for the same purpose; a general part for something else is `no_fit`.

## Result on the demo library (1,370 parts, without AI)
After adding 527 standard parts (bd_warehouse) and 524 FreeCAD models, with simple embeddings:
**88% at rank 1, 93% in top 3, 100% rightly "nothing found", 0 leaks, 12 ms per query.**
- "solar panel 400 watt" first returned a resistor ("1/4 W", tag watt). Units (watt, volt, litre, mm, ...) now no longer count for "nothing found", like loose numbers (`UNIT_WORDS` in `search.py`).
- Test queries can also have `name_has`: another part whose name contains everything asked for also counts as correct.


## "Nothing found" without AI
Without Claude the search engine always returns its best results, even if nothing fits. So: if **no** result covers enough of the words of the question (weighted by rarity; loose numbers and units do not count), the answer is "nothing found". In English, compound nouns are separate words, so a generic word can match on its own ("machine" in "espresso machine" matches a machine guard). Calibrated on the English test queries: questions without a fitting part score at most ~0.32, questions with a fitting part at least ~0.38. The threshold is `MIN_WORD_COVERAGE = 0.35` in `search.py`. The word weights (idf) are computed only over the parts the asking company may see.

## Scale test (`scripts/scale_test.py`)
Temporary database with artificial parts, 46 libraries (general + 40 companies), 12 queries × 3:

| Parts | Average | 95% | Slowest | With filters |
|---|---|---|---|---|
| 10,000 | 19 ms | 22 ms | 26 ms | 5 ms |
| 50,000 | 86 ms | 106 ms | 109 ms | 24 ms |
| 100,000 | 170 ms | 210 ms | 216 ms | 44 ms |

The first measurement at 100,000 parts was 8.3 s on average (26 s slowest). Cause: the company filter was put on the word index as `rowid IN (subquery)`, recomputed per row. With a `JOIN` (same results) it is ~50× faster.

## Import robustness
Tested: subfolders, spaces and capitals in names (`.STEP`, `.stp`), broken and empty files (reported cleanly, the rest continues), loose native files (stored, not measured), text files (skipped).

## Running
- `check.bat`: everything (tests, test data, import, evaluation)
- `backend\.venv\Scripts\python eval_search.py --verbose`: evaluation with all questions shown
- `backend\.venv\Scripts\python ..\scripts\scale_test.py`: scale test
- `ai_test.bat`: the same questions with the AI as judge; one question: `ai_test.bat --only "hex nut"`

## Engineering evaluation (`backend/eval_engineering.py`)
48 questions in `backend/tests/queries_engineering.yaml`, phrased as a mechanical engineer asks
(designation, standard, thread x length, property class, NEMA frame + torque, DN/PN, ...). Without AI it
measures: exact part at position 1, correct status (found / partial / none), the deviating spec reported
for questions the library cannot fully meet, and **false fits** (a part marked `fits` that violates a spec
of the question; goal 0). Unit tests: `backend/tests/test_engineering.py`.
