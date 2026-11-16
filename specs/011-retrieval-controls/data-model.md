# Phase 1 Data Model: Retrieval Controls for the Experience Store (011)

No SQLite change (schema stays at v8). Every change is in the ChromaDB collection's metadata, in two in-process
value types, in the settings, and in the fields of three existing log events. No field anywhere holds a target URL,
display name, auth value, attack message, reply text or judge text (Principle IV, `010/FR-009`).

## ChromaDB collection metadata (`kestrel_experience`)

| Key | Type | Written | Rule |
|-----|------|---------|------|
| `kestrel_store_version` | str (`"1"`) | at creation (feature 004) | unchanged; a differing version still only warns |
| `kestrel_embedding_model` | str | at creation; stamped on first open of a store that lacks it | the name of the embedding model whose vectors the collection holds: `all-MiniLM-L6-v2` for the shipped default, `kestrel-lexical-stub` for the test stub; compared with the running model's name in `self_check` (FR-009 to FR-011) |
| `kestrel_distance_space` | str (`"l2"`) | at creation (the collection is created with `configuration={"hnsw": {"space": "l2"}}`); stamped on first open of a store that lacks it | the distance measure the index uses; `self_check` compares the index's **actual** space (`configuration_json["hnsw"]["space"]`) with `l2` and raises `SpaceMismatch` otherwise (FR-009 to FR-011, research D13) |

`collection.modify(metadata=…)` replaces the dict, so the stamp always rewrites all three keys — carrying the stored
model name when one is present (a stamp never overwrites a recorded name) and `l2` as the space. Only a store whose
actual index space is `l2` is stamped; a non-`l2` store is left unstamped and unlogged for `self_check` to fail.

## Pattern record (`type = "pattern"`) — extended

Feature-004 fields unchanged (`id`, `document`, `type`, `family`, `owasp_category`, `source`, `prompt_id` or
`origin_run_id`). New metadata:

| Field | Type | Set | Rule |
|-------|------|-----|------|
| `hit_count` | int ≥ 1 | `1` when a pattern is added (seeded or success-derived); `+1` on each merged success | absent on a pattern written before this feature → reads as 1 (FR-007); never reset by re-seeding (the seed upsert omits the key for existing ids, D4) |
| `last_hit_run_id` | int | on each merge | the run whose success was merged into this pattern most recently; absent until the first merge |

Lifecycle of a success write-back (FR-006, FR-008): `nearest same-family pattern within the threshold` → **merge**
(`hit_count + 1`, `last_hit_run_id = run`, no new record) · otherwise → **add** (`pattern:run:<run_id>`,
`hit_count = 1`). Non-success → nothing. De-duplication off → always add.

## Memory record (`type = "memory"`)

Unchanged (feature 004): selected by exact `target_id`, never by distance, never de-duplicated.

## In-process value types

Where each lives: `Candidate`, `PatternWrite`, `EmbeddingModelMismatch` and `SpaceMismatch` in
`src/kestrel/experience/store.py` (the store builds or raises them); `Selection` in
`src/kestrel/experience/retrieval.py`; `RetrievalSettings` in `src/kestrel/settings.py` (built by the
`Settings.retrieval` property).

```text
Candidate(id: str, document: str, distance: float, embedding: tuple[float, ...])          # store.py
    # one family-scoped hit for a query, nearest first; distance = the collection's l2 (squared Euclidean) measure

Selection(selected: list[Candidate], candidate_count: int, dropped_floor: int, dropped_duplicate: int)   # retrieval.py
    # invariant: candidate_count == dropped_floor + dropped_duplicate + len(selected)
    # invariant: len(selected) <= k; every selected.distance <= floor (when on);
    #            no two selected within dedupe_threshold of each other (when on); nearest first;
    #            short of k only when every candidate of the pool was examined
    # derived: pattern_ids, documents, distances (rounded to 4 decimals for the log line)

RetrievalSettings(k: int, distance_floor: float | None, dedupe_threshold: float | None)   # settings.py
    # Settings.retrieval: from experience_pattern_k / experience_distance_floor / experience_dedupe_threshold;
    # None = off

PatternWrite(outcome: "added" | "merged", pattern_id: str, hit_count: int, distance: float | None)   # store.py
    # the result of write_pattern on a success; distance = to the nearest existing same-family pattern
    # (None when the family had no pattern, or de-duplication is off)

EmbeddingModelMismatch(ExperienceStoreError)   # store.py; attributes: stored: str, expected: str (model names)
SpaceMismatch(ExperienceStoreError)            # store.py; attributes: stored: str, expected: str (space names)
```

Constants (module level, not settings): `QUERY_MESSAGES = 2` (attacker messages in the query),
`CANDIDATE_MULTIPLIER = 4` (candidate pool = `min(k × 4, family pattern count)`).

## Retrieval query (FR-001)

```text
query_text  = family_label(family) + " " + " ".join(last QUERY_MESSAGES messages with role == "attacker")
query_count = number of attacker messages used (0 when the conversation holds none — the label alone)
```

Roles come from the graph's conversation list `(role, masked text)`: `attacker` (the seed on turn 1, the model's
messages after) and `agent` (the target's reply). Nothing else is ever in that list; the judge's reason and
progress live in the graph state and the turn rows and are not passed to the provider.

## Settings (`src/kestrel/settings.py`)

| Field | Env var | Default | Parsing |
|-------|---------|---------|---------|
| `experience_distance_floor: float \| None` | `KESTREL_EXPERIENCE_DISTANCE_FLOOR` | `1.8` | unset → default; `off` → `None`; else non-negative float, otherwise `SettingsError` |
| `experience_dedupe_threshold: float \| None` | `KESTREL_EXPERIENCE_DEDUPE_THRESHOLD` | `0.15` | same rule |

`Settings.retrieval` → `RetrievalSettings(k=experience_pattern_k, distance_floor=…, dedupe_threshold=…)`, the one
value `background_provider` reads. `GET /api/config` → `experience: {pattern_k, memory_cap, distance_floor: number |
null, dedupe_threshold: number | null, use_prior_experience_default}` (`schemas.ExperienceOut`).

## Log events (delta; the full rows go into `specs/010-structured-logging/contracts/log-records.md`)

| Event | New fields |
|-------|------------|
| `memory.retrieval` | `k` int · `distance_floor` number \| null · `dedupe_threshold` number \| null · `candidate_count` int · `dropped_floor` int · `dropped_duplicate` int · `distances` list[number] · `query_messages` int (`pattern_count` = selected, `warm` = `pattern_count > 0`, `pattern_ids`, `memory_count` as before) |
| `memory.writeback` | on a success: `pattern_outcome` `added`/`merged` · `pattern_id` str · `hit_count` int · `pattern_distance` number \| null (`written`, `pattern_written`, `error` as before) |
| `experience.unavailable` | on a model mismatch: `stored_model` str · `expected_model` str; on a space mismatch: `stored_space` str · `expected_space` str (`reason_kind` gains the values `embedding_model_mismatch` and `space_mismatch`); for those two kinds the constant `message` is the mismatch-specific text that states the remedy (verbatim in the contract) |

## Recall@k fixture (`tests/fixtures/retrieval_recall.json`)

Schema in [contracts/recall-fixture.md](contracts/recall-fixture.md): `k`, `distance_floor`, `dedupe_threshold`,
`min_recall`, `patterns[]` (`id`, `family`, `text` — neutral placeholders), `queries[]` (`text`, `family`,
`expected[]` — empty with `"no_relevant": true` for the negative cases), `duplicate_pairs[]` (`[id, id]`, both
patterns present; a query near both is listed under `queries` with one expected id). `recall@k` for a query =
|expected ∩ top-k selected| / |expected|; the fixture's score is the mean over queries with a non-empty `expected`.

## Relationships

- A run's success → exactly one `PatternWrite` (added or merged); a merged success leaves the pool's pattern count
  unchanged and raises one `hit_count`.
- A warm adaptive turn (turn ≥ 2) → one `Selection` → one `memory.retrieval` line; the hints block carries
  `Selection.documents` in selection order.
- The collection's `kestrel_embedding_model` ↔ the running embedding function's model name: equal → open; absent →
  stamp with the running name (only on an `l2` index); different → `EmbeddingModelMismatch` →
  `experience.unavailable` (`embedding_model_mismatch`) and a `None` store for the session — also when the store
  carries the name but lacks the space key, because a stamp never overwrites a recorded name.
- The index's actual space ↔ `l2`: equal → open (and `kestrel_distance_space` stamped if absent); different →
  `SpaceMismatch` → `experience.unavailable` (`space_mismatch`) and a `None` store for the session. A feature-004
  store is `l2` already and never trips it.
