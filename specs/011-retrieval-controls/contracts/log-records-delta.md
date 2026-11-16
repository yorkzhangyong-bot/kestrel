# Contract: log-record changes (delta to feature 010's `contracts/log-records.md`)

The implementation PR adds these fields to `events.CATALOGUE` and to the rows of
`specs/010-structured-logging/contracts/log-records.md` (carrying a `spec-change:` note, because that spec file
changes alongside `src/`). Everything else about the stream — one JSON object per line, the common fields, the
ordering inside a run's scope, the deny-list — is unchanged. Illustrative values only; no query text, pattern text
or message text ever appears on a line (`010/FR-009`).

## `memory.retrieval` (INFO, once per turn on which the run asks the store, from turn 2)

| Field | Type | Meaning |
|-------|------|---------|
| `turn`, `warm`, `pattern_count`, `memory_count`, `pattern_ids` | as today | `pattern_count` = patterns **selected**; `warm` = `pattern_count > 0` |
| `k` | int | the bound in effect (`KESTREL_EXPERIENCE_PATTERN_K`) |
| `distance_floor` | number \| null | the floor in effect; `null` when switched off |
| `dedupe_threshold` | number \| null | the near-identical threshold in effect; `null` when switched off |
| `candidate_count` | int | candidates examined (nearest first) — always `dropped_floor + dropped_duplicate + pattern_count` |
| `dropped_floor` | int | candidates beyond the floor |
| `dropped_duplicate` | int | candidates skipped as near-identical to an already selected hit |
| `distances` | list[number] | the selected hits' distances from the query, 4 decimals, in selection order (nearest first); empty when none |
| `query_messages` | int | attacker messages that entered the query (0–2) |

```json
{"ts":"2026-11-16T09:12:04.118Z","level":"INFO","logger":"kestrel","event":"memory.retrieval",
 "run_id":57,"target_id":3,"mode":"adaptive","family":"system_prompt_leak","turn":2,
 "warm":true,"pattern_count":2,"memory_count":1,"pattern_ids":["pattern:lib:spl-002","pattern:run:41"],
 "k":5,"distance_floor":1.8,"dedupe_threshold":0.15,"candidate_count":5,"dropped_floor":2,"dropped_duplicate":1,
 "distances":[0.2741,0.9876],"query_messages":1}
```

## `memory.writeback` (INFO, ERROR when failed; once per run inside its scope)

| Field | Type | Meaning |
|-------|------|---------|
| `written`, `pattern_written`, `error` | as today | `pattern_written` true when the success was recorded as a pattern — added **or** merged |
| `pattern_outcome` | `added` \| `merged` | only on a success: a new record was added, or an existing pattern's hit count was raised |
| `pattern_id` | str | only on a success: the pattern added, or merged into |
| `hit_count` | int | only on a success: the pattern's hit count after this write-back |
| `pattern_distance` | number \| null | only on a success: distance to the nearest existing same-family pattern; `null` when the family had none or de-duplication is off |

```json
{"ts":"2026-11-16T09:12:09.402Z","level":"INFO","logger":"kestrel","event":"memory.writeback",
 "run_id":57,"target_id":3,"mode":"adaptive","family":"system_prompt_leak",
 "written":true,"pattern_written":true,"pattern_outcome":"merged","pattern_id":"pattern:lib:spl-002",
 "hit_count":3,"pattern_distance":0.0412}
```

## `experience.unavailable` (ERROR, start-up)

| Field | Type | Meaning |
|-------|------|---------|
| `exc_type`, `reason_kind` | as today | `reason_kind` gains the values `embedding_model_mismatch` and `space_mismatch` |
| `stored_model` | str | only on a model mismatch: the model name recorded in the collection |
| `expected_model` | str | only on a model mismatch: the model name of the embedding function in use |
| `stored_space` | str | only on a space mismatch: the distance space the collection's index actually uses (`cosine`, `ip`, …) |
| `expected_space` | str | only on a space mismatch: the pinned space, `l2` |
| `message` | constant text | for these two reason kinds a **mismatch-specific constant** that states the remedy (below); every other cause keeps today's generic constant |

The two constants (verbatim — the implementation and the tests quote them):

- `embedding_model_mismatch`: "The experience store was built by a different embedding model, so it is disabled for
  this session and runs will record loudly as not written back (Principle V). Rebuild the store directory, or run
  Kestrel with the model that built it."
- `space_mismatch`: "The experience store's index uses a different distance space than Kestrel expects, so it is
  disabled for this session and runs will record loudly as not written back (Principle V). Rebuild the store
  directory."

```json
{"ts":"2026-11-16T09:00:01.007Z","level":"ERROR","logger":"kestrel","event":"experience.unavailable",
 "exc_type":"EmbeddingModelMismatch","reason_kind":"embedding_model_mismatch",
 "stored_model":"all-MiniLM-L6-v2","expected_model":"some-other-model",
 "message":"The experience store was built by a different embedding model, so it is disabled for this session and runs will record loudly as not written back (Principle V). Rebuild the store directory, or run Kestrel with the model that built it."}
```

Constant text is allowed as a line's `message` (as `key.mismatch` already does), so the remedy reaches the operator
on the line; the exception's own text still never does — as for every event, an attached exception renders as
`exc_type` and `stack` only.

## `message` (INFO, start-up)

One new constant message, no fields: "Recorded the embedding model name and distance space on the experience
store." — emitted once when a feature-004 store is stamped (FR-011).

## Deny-list check

New fields carry numbers, identifiers (`pattern:lib:<prompt_id>`, `pattern:run:<run_id>`), enum values, model
names and distance-space names, plus constant message text. Model and space names are not secrets. The redaction
runs of feature 010 (`tests/integration/test_log_redaction.py`)
keep passing unchanged; the 011 line tests additionally assert that the attacker's message text, the reply text and
the pattern documents appear zero times on the stream (SC-007).
