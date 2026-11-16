# Quickstart / Validation: Retrieval Controls for the Experience Store (011)

Proves US1–US5 offline, then once end to end. Shapes and names: [data-model.md](data-model.md) and
[contracts/](contracts/). PowerShell first (Windows dev), bash where useful.

## Prerequisites

- Python 3.12 + uv; `uv sync`. The offline suite needs no keys and never touches `data/chroma` (every store is
  under `tmp_path`). Only the end-to-end run needs `OPENROUTER_API_KEY`, the HS-code target (project `CLAUDE.md`
  → "HS-code target") and the shipped embedding model (downloaded once, ~80 MB, then cached).

## US1 — the query is the attacker's own words (offline)

```
uv run pytest tests/unit/test_retrieval_query.py tests/integration/test_retrieval_query_isolation.py
```

Expected: `build_query` keeps only `attacker`-role messages, the last two, label first; two API-started warm runs
on one stub target whose purpose description, replies and judge notes carry the known markers (after the first run
the target's memory summary carries the judge-progress marker too), plus an experiment-executed warm run, produce
retrieval queries in which the markers appear 0 times and the family label and the attacker's messages appear
every time from turn 2 (SC-001).

## US2 — floor, de-duplication, ordering, the retrieval line (offline)

```
uv run pytest tests/unit/test_retrieval_selection.py tests/unit/test_experience_store_controls.py tests/integration/test_retrieval_lines.py
```

Expected: with a floor between known near and far patterns only the near ones come back (fewer than k, down to
none); with the floor off nothing is dropped for its distance, and with both controls off the k nearest come back
as in feature 004; of two near-identical hits only the nearer is selected and a third distinct one still fills the
selection; hits are nearest first; every `memory.retrieval` line carries `k`,
`distance_floor`, `dedupe_threshold`, `candidate_count`, `dropped_floor`, `dropped_duplicate`, `distances`,
`query_messages`, and `candidate_count == dropped_floor + dropped_duplicate + pattern_count` (SC-002, SC-003,
SC-007).

## US3 — a repeated success merges (offline)

```
uv run pytest tests/unit/test_experience_store_controls.py -k "write_pattern or hit_count" tests/integration/test_retrieval_lines.py -k writeback
```

Expected: a success near-identical to an existing same-family pattern raises that pattern's `hit_count` by one
and adds no record; a distinct success adds one with `hit_count` 1; a cross-family near-match adds; a replayed
library seed raises the seed's count; a non-success writes nothing; the `memory.writeback` line says `added` or
`merged` with the pattern id and the hit count; re-seeding the library leaves counts untouched (SC-004).

## US4 — the embedding model name (offline)

```
uv run pytest tests/unit/test_experience_store_model.py tests/integration/test_startup_model_mismatch.py
```

Expected: a fresh store's index space is `l2` and its metadata carries `kestrel_embedding_model` and
`kestrel_distance_space`; the same name reopens silently; a different name makes `self_check` raise
`EmbeddingModelMismatch` and the app emit one ERROR `experience.unavailable` with `reason_kind =
embedding_model_mismatch`, `stored_model`, `expected_model` and the mismatch constant message that states the
remedy, no exception text, and the store disabled (a run then records `memory_written` false and emits no
retrieval line); a collection created with a cosine index raises `SpaceMismatch` and the app emits the same line
with `reason_kind = space_mismatch`, `stored_space`, `expected_space` and the space constant; a feature-004 store
(version only) opens cleanly and is stamped with both keys (SC-006).

Manual check of the failure path on a local store (PowerShell):

```powershell
uv run python -c "import chromadb; c = chromadb.PersistentClient(path='data/chroma'); col = c.get_collection('kestrel_experience'); col.modify(metadata={**(col.metadata or {}), 'kestrel_embedding_model': 'some-other-model'})"
$env:KESTREL_MODE = "local"; $env:KESTREL_LOG_FORMAT = "text"
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000
```

Expected on stderr: one `ERROR experience.unavailable … reason_kind=embedding_model_mismatch
stored_model=some-other-model expected_model=all-MiniLM-L6-v2 message=The experience store was built by a
different embedding model, so it is disabled for this session and runs will record loudly as not written back
(Principle V). Rebuild the store directory, or run Kestrel with the model that built it.`; runs still execute and
show the "not written back" warning. Restore with the same one-liner and `'all-MiniLM-L6-v2'` (or delete
`data/chroma` to rebuild).

## US5 — recall@k (offline)

```
uv run pytest tests/unit/test_retrieval_recall.py
```

Expected: mean recall@k ≥ the fixture's `min_recall` (1.0), 0 hits for the `no_relevant` query, exactly one of each
duplicate pair, every published distance reproduced and at least 0.1 from both the fixture's floor (0.8) and its
threshold (0.5), no hash-bucket collision in the vocabulary, and the fixture's texts are placeholder vocabulary
only (SC-005).

## Settings (offline)

```
uv run pytest tests/unit/test_settings_experience.py tests/integration/test_api_base.py -k experience
```

Expected: defaults `1.8` / `0.15` (`settings.retrieval` carries them with `k`); `off` → `None`; a negative or
non-numeric value refuses to start with a
`SettingsError`; `GET /api/config` reports both values (`null` when off).

## Whole suite and gates (offline)

```
uv run pytest tests/unit tests/integration
uvx ruff check src ui tests
uv run python scripts/check_traceability.py
```

Expected: green; coverage ≥ 85 %; every `011/FR-###` and `011/SC-###` traced (or justified in
`traceability.md`); the fixed stack unchanged (SC-008, SC-009).

Watch a warm run live (local mode; text format for reading):

```powershell
$env:KESTREL_MODE = "local"; $env:KESTREL_LOG_FORMAT = "text"
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000 2>&1 |
    Select-String 'memory\.(retrieval|writeback)'
```

```bash
KESTREL_MODE=local KESTREL_LOG_FORMAT=text uv run uvicorn --factory kestrel.api.main:create_app --port 8000 2>&1 | grep -E 'memory\.(retrieval|writeback)'
```

## End to end (needs `OPENROUTER_API_KEY`)

```powershell
$env:OPENROUTER_API_KEY = "<key>"; $env:HS_TARGET_API_KEY = "test-key-123"; $env:HS_TARGET_CANARY = "KESTREL-CANARY-e2e"
uv run pytest -m e2e tests/e2e/test_us011_retrieval.py
```

Expected: two warm adaptive runs under a turn cap of four (time limit 120 s, so four real turns fit) against the
HS-code target — up to two more, four at most, while no run has reached turn 4, since a run ends early on success,
an attacker or send failure or the token or time limit, before the seed leaves the query window; at least one
`memory.retrieval` line exists across the runs (asserted first; the first run is warm on the library seeds too);
every one of them (read through `GET /api/runs/{id}/log`) carries `k = 5`, `distance_floor = 1.8`,
`dedupe_threshold = 0.15`, counts that add up and `pattern_count ≥ 1` with every distance ≤ 1.8, including at
least one line from turn 4 whose query no longer contains the seed (the test fails if no run produced one); on the
same store the three real-model write-backs give added (a neutral document), merged with hit count 2 (its one-word
variant) and added (its paraphrase) at the shipped 0.15; the temporary store's metadata records `all-MiniLM-L6-v2`
and `l2`; and the shipped default embedding and `ONNXMiniLM_L6_V2` embed a neutral probe identically (SC-010).
