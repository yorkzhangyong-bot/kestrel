# Contract: ExperienceStore changes (011)

`src/kestrel/experience/store.py`. Delta over feature 004's [experience-store contract](../../004-attack-pattern-memory/contracts/experience-store.md);
everything not listed here is unchanged. All methods stay synchronous and local. No method receives or stores a
target URL, display name or auth value (Principle IV).

## Construction

```text
ExperienceStore(path, *, embedding_function=None, store_version="1", embedding_model: str | None = None)
```

- `embedding_model` is the name the store compares against; `None` derives it from the embedding function in use
  with `embedding_model_name(embedding_function)`: `None` (the shipped default, which delegates every call to
  `ONNXMiniLM_L6_V2()`) → `all-MiniLM-L6-v2` (`ONNXMiniLM_L6_V2.MODEL_NAME`); otherwise the function's `MODEL_NAME`
  attribute when present, else its registered `name()`. Passing a different value is the test seam for "a different
  model" (ChromaDB's own check on the registered function *name* would otherwise fire first).
- The collection is created with `get_or_create_collection(COLLECTION, configuration={"hnsw": {"space": "l2"}},
  metadata={"kestrel_store_version": store_version, "kestrel_embedding_model": <expected>,
  "kestrel_distance_space": "l2"}, …)`. On a reopen ChromaDB ignores a conflicting configuration, so the
  constructor reads the index's **actual** space from `collection.configuration_json["hnsw"]["space"]` into
  `self.distance_space` and never assumes it (research D13).
- After `get_or_create_collection` the constructor reads the metadata:
  - `kestrel_embedding_model` present → `self.stored_embedding_model = <value>`; `kestrel_distance_space` present →
    `self.stored_distance_space = <value>`.
  - either key absent **and** `self.distance_space == "l2"` → `collection.modify(metadata={"kestrel_store_version":
    <stored version>, "kestrel_embedding_model": <the stored name when present, else the expected name>,
    "kestrel_distance_space": "l2"})` and one constant `message` line ("Recorded the embedding model name and
    distance space on the experience store.") (FR-011). A stored name is never overwritten by the expected one, so
    a store that carries a name but lacks the space key keeps its name and `self_check` still fails it on a model
    mismatch. A feature-004 store's index is `l2` already (created with no configuration under the default
    function, whose default space is `l2`), so only an `l2` store can be a feature-004 store.
  - either key absent and the actual space not `l2` → nothing is written and no stamp line is logged; `self_check`
    raises `SpaceMismatch` (below).
- `self.embedding_model` is the expected name; `DISTANCE_SPACE = "l2"` is the expected space. The store-version
  warning of feature 004 is unchanged.

## `self_check() -> None`

1. If `self.distance_space != "l2"` → raise `SpaceMismatch` (a subclass of `ExperienceStoreError`) with attributes
   `stored` (the actual space) and `expected` (`"l2"`) and a human-readable message naming both and the remedy
   ("Rebuild the store directory."). Nothing is written (FR-010).
2. Else if `self.stored_embedding_model != self.embedding_model` → raise `EmbeddingModelMismatch` (a subclass of
   `ExperienceStoreError`) with attributes `stored` and `expected` and a human-readable message naming both and the
   remedy ("Rebuild the store directory, or run Kestrel with the model that built it."). Nothing is written (FR-010).
3. Otherwise the feature-004 probe embed (upsert + delete of `kestrel:self-check`) runs as today.

The exception messages are for a human reading a traceback; the remedy reaches the log stream as the constant
`message` of the `experience.unavailable` line (`contracts/log-records-delta.md`), with the values as fields.
`store_error_kind(error)` returns `"embedding_model_mismatch"` for an `EmbeddingModelMismatch` and
`"space_mismatch"` for a `SpaceMismatch`; the other kinds are unchanged. `describe_store_error` names both values
in each case.

## `seed_patterns(library) -> int`

Idempotent as before. New: reads the seed ids that already exist (`get(ids=…, include=[])`); new ids are upserted
with `hit_count: 1` in their metadata, existing ids are upserted **without** the `hit_count` key (ChromaDB keeps an
omitted key on upsert), so a library pattern's count survives every start-up (D4). Returns the number of library
prompts, as before.

## `query_patterns(*, family, query_text, n) -> list[Candidate]`

- `n` is clamped to `max(0, min(n, count("pattern", family=family)))`; `0` returns `[]` without querying (no
  ChromaDB warning, no error on an empty family).
- One `query(query_texts=[query_text], n_results=n, where={"$and": [{"type": "pattern"}, {"family": family}]},
  include=["documents", "distances", "embeddings"])`.
- Returns `Candidate(id, document, distance, embedding)` in the order ChromaDB returns them (nearest first;
  `distance` is the collection's `l2` value; `embedding` is a tuple of floats). `Candidate` is defined in this
  module (`store.py`) and imported by `retrieval.py`.
- Never touches memory records; never returns another family's pattern (`004/SC-014` still holds).

## `write_pattern(*, run_id, document, family, owasp_category, dedupe_threshold: float | None = None) -> PatternWrite`

Post-review fix: an added pattern's id is a fresh `pattern:run:<uuid4 hex>`, never `pattern:run:<run_id>` —
`run_id` is not guaranteed unique (a deleted target's run ids could be reissued on a pre-schema-v9 database), and
an add must never collide with, and silently overwrite, an unrelated surviving pattern. `run_id` is recorded only
as metadata (`source`, `origin_run_id`); the add itself uses `collection.add` (never `upsert`), so even the
astronomically unlikely case of a genuine id collision keeps the existing record rather than overwriting it.

- `dedupe_threshold is None` or the family has no pattern → add under a fresh `pattern:run:<uuid>` id with the
  feature-004 metadata plus `hit_count: 1`; return `PatternWrite("added", "pattern:run:<uuid>", 1, distance)` where
  `distance` is the nearest existing same-family pattern's distance when one was looked up, else `None`.
- Otherwise look up the nearest same-family pattern (`query(query_texts=[document], n_results=1, where=…,
  include=["metadatas", "distances"])`):
  - `distance <= dedupe_threshold` → `update(ids=[nearest_id], metadatas=[{"hit_count": previous + 1,
    "last_hit_run_id": run_id}])` (previous = the stored `hit_count`, 1 when absent) and return
    `PatternWrite("merged", nearest_id, previous + 1, distance)`; no new record, the document is untouched.
    `nearest_id` may be a legacy `pattern:run:<run_id>` id written before this fix, a `pattern:run:<uuid>` one, or
    `pattern:lib:*` — all three are valid merge targets.
  - else → add as above with `distance` filled in.
- Library-seeded (`pattern:lib:*`) and success-derived (`pattern:run:*`) patterns are both eligible merge targets;
  only the run's own family is searched (FR-006).
- Raises on any store failure (the caller's write-back fails loudly as a whole, `004/FR-010`).

## Legacy methods (kept)

`retrieve_patterns(*, family, query_text, k) -> list[str]` and `retrieve_patterns_with_ids(...)` keep returning the
k nearest documents with no floor and no de-duplication; production code no longer calls them (the feature-004
tests do). Their docstrings say so.

## Invariants (new)

- Every pattern added by this version carries `hit_count`; a merge only ever raises it by one and sets
  `last_hit_run_id`.
- An added pattern's id is always a fresh, unique value; `run_id` is never part of it, only of its metadata
  (post-review fix — see `write_pattern` above).
- The collection metadata always carries `kestrel_embedding_model` and `kestrel_distance_space` after one
  successful open by this version, and every collection this version creates has an `l2` index.
- `query_patterns` and `write_pattern` are the only readers of distances; both use the collection's own values.
