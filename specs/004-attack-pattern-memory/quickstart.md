# Quickstart & validation: Attack-Pattern Store and Per-Target Memory (feature 004)

How to prove the feature works. Details live in [data-model.md](./data-model.md) and [contracts/](./contracts/); this is the run/validation guide. No attack text appears here or needs to be typed — Kestrel seeds and generates it.

## Prerequisites

- Python 3.12 + uv; `uv sync` (now pulls in `chromadb`).
- For the adaptive and e2e checks: `OPENROUTER_API_KEY` set, and an attacker model the key may use. Note: this account's guardrail may block the default DeepSeek attacker; set `KESTREL_ATTACKER_MODEL` to a permitted model such as `openai/gpt-4o-mini` for a live multi-turn run.
- Run locally:

```bash
# terminal 1 — API (seeds patterns on start-up)
KESTREL_MODE=local OPENROUTER_API_KEY=sk-or-... uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000
# terminal 2 — screen
uv run streamlit run ui/app.py
```

The store appears at `data/chroma/` next to `data/kestrel.db`.

## Automated tests

```bash
uv run pytest                                   # unit + integration, offline (stub embedder), no keys
uv run pytest -m e2e                            # the one end-to-end test; needs OPENROUTER_API_KEY
uv run --directory targets/hs_code pytest       # target smoke tests, unchanged
```

## Checks (map to FR/SC)

1. **Seeding is idempotent** (FR-004, SC-002): start the API twice against the same `data/chroma/`; the count of `pattern:lib:*` records is identical both times (0 duplicates).
2. **Memory after every run** (FR-006, SC-001): run one attack (single-turn or adaptive, any outcome); exactly one new `memory:run:<id>` record exists for that target.
3. **Pattern only on success** (FR-009, SC-003): a succeeded run adds exactly one `pattern:run:<id>`; a failed/unclear run adds none.
4. **No secrets in the store** (FR-005, FR-011, FR-012, SC-004, SC-008): with the sacrificial target's key as an auth header, that key, the target URL and its display name appear 0 times across all pattern and memory records; no memory document contains the raw target reply.
5. **Summary shape** (FR-008, FR-013, SC-009): every stored summary is one line within the max length, built from judge progress notes (or the metadata fallback) with no extra model call.
6. **Warm priming** (FR-016, SC-005): run twice warm against the same target; the second run's attacker is given ≥1 memory record from the first (inspect the hint block / retrieval). Patterns are family-scoped — 0 come from another family (SC-014).
7. **Cold is feature 003** (FR-015, SC-007): with the switch off and no purpose set, the attacker input has 0 added hints.
8. **Purpose fed regardless of switch** (FR-020, FR-021): set a one-line purpose; it reaches the attacker as background on both a warm and a cold run, and is never treated as a secret.
9. **Cross-target isolation** (FR-018, SC-006): two targets each with memory; attacking one offers 0 of the other's memory.
10. **Profile view** (FR-022, FR-023, SC-013): a target's profile shows run counts by family and verdict and recent summaries, with 0 secrets; an unused target shows an empty state, not an error.
11. **Delete forgets memory, keeps patterns** (FR-024, FR-025, SC-010): delete a target that had memory and a success-derived pattern; its memory records are gone, the shared pattern remains.
12. **Fail loudly** (FR-010, SC-011): with the store made unwritable, finish a run — its result is still saved, the run shows `memory_written=false` with a visible warning, and an error is logged; the attack result is not discarded.
13. **End-to-end** (FR-026, SC-012): `uv run pytest -m e2e` runs two warm runs against the sacrificial target and asserts the second run's attacker received ≥1 memory record produced by the first.

## Notes

- Offline tests inject a deterministic stub embedding function, so `uv run pytest` makes no network call and downloads no model (research R2).
- **The e2e uses ChromaDB's real default local embedding model, so the first e2e run downloads that model (~80 MB) and needs network once.** After that it is cached (under the ONNX/Hugging Face cache) and runs offline. `uv run pytest` (the offline suite) never downloads it.
- Schema moves SQLite `3 → 4` (additive: `targets.description`, `runs.use_prior_experience`, `runs.memory_written`); existing targets and runs keep working.
