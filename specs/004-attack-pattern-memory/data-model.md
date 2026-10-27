# Data Model: Attack-Pattern Store and Per-Target Memory (feature 004)

Two stores. The existing **SQLite** file gains two additive columns (schema v4). A new local **ChromaDB** collection holds patterns and memory. No field anywhere holds a target URL, display name, auth header name/value, or any secret (Principle IV).

## SQLite (schema v4, additive)

`meta.schema_version` moves `3 → 4`. Migration allows `1`, `2`, `3` → `4` and `ALTER TABLE ADD COLUMN`s any missing columns (same additive pattern as v3); an unknown version still raises `UnknownSchemaVersion`.

### `targets` — one new column

| Column | Type | Notes |
|---|---|---|
| `description` | `TEXT` | Optional one-line purpose description (FR-020). Nullable; trimmed; **max 200 chars** (enforced by the API, like other target text). Non-secret: stored in plain, shown in the form and profile, fed to the attacker. Never an auth value. |

### `runs` — two new columns

| Column | Type | Notes |
|---|---|---|
| `use_prior_experience` | `INTEGER` | The per-run warm/cold choice, recorded on the run (FR-014). `1` = warm (default), `0` = cold. Set at `claim_run` time. Nullable only for legacy rows (treated as warm when read for display). |
| `memory_written` | `INTEGER` | Nullable tri-state (FR-010): `NULL` = write-back not attempted yet / legacy run; `1` = memory record stored; `0` = write-back failed (drives the UI warning). Set by `set_memory_written(run_id, bool)` after the run finishes. |

New migration column tuples (mirrors `ADAPTIVE_RUN_COLUMNS`):

```text
EXPERIENCE_RUN_COLUMNS = (
    ("use_prior_experience", "INTEGER NOT NULL DEFAULT 1"),
    ("memory_written", "INTEGER"),
)
# targets.description added by ALTER if missing (TEXT)
```

### In-memory types (dataclasses)

- `Target` gains `description: str | None = None`.
- `Run` gains `use_prior_experience: bool = True` and `memory_written: bool | None = None`.
- `create_target` / `update_target` accept `description: str | None`.
- `claim_run` accepts `use_prior_experience: bool = True` and stores it.
- New store method `set_memory_written(run_id: int, written: bool) -> None`.
- `delete_target` is unchanged in SQL (cascades runs/headers/canaries); the API additionally clears Chroma memory (see experience store).

## ChromaDB

**Client**: `PersistentClient(path=<KESTREL_CHROMA_PATH, default data/chroma>)`.
**Collection**: `kestrel_experience`, created with the default (or injected) embedding function and `metadata={"kestrel_store_version": "1"}` (FR-003). Every record has `type` ∈ {`pattern`, `memory`} (FR-002). ChromaDB metadata values must be scalar (`str`/`int`/`float`/`bool`) — no `None`, no lists.

### Pattern record (`type = "pattern"`)

Anonymised, shared, no target identity (FR-005). Retrieved by semantic similarity, family-scoped (FR-016/FR-017).

| Field | Source | Notes |
|---|---|---|
| `id` | — | `pattern:lib:<prompt_id>` (seeded) or `pattern:run:<run_id>` (success-derived) — deterministic, so re-seeding/re-writing is idempotent (SC-002, SC-003). |
| `document` (embedded) | library prompt text (seeded) **or** the attacker message(s) that succeeded (success-derived, FR-009) | Never a target reply. |
| `metadata.type` | `"pattern"` | |
| `metadata.family` | run/library | one of the four families; the `where` key for scoping. |
| `metadata.owasp_category` | run/library | Principle VI. |
| `metadata.source` | — | `"library:<version>"` or `"run:<run_id>"`. |
| `metadata.prompt_id` | library | seeded patterns only. |
| `metadata.origin_run_id` | run | success-derived patterns only (FR-009). |

### Memory record (`type = "memory"`)

One per run, per target (FR-006). Retrieved by exact `target_id` match, never semantically (FR-017/FR-018).

| Field | Source | Notes |
|---|---|---|
| `id` | — | `memory:run:<run_id>` — one per run, idempotent. |
| `document` (embedded) | the sanitised one-line summary | Also stored so the profile can read it back. Chroma still embeds it (unavoidable), but it is only ever fetched by metadata filter. |
| `metadata.type` | `"memory"` | |
| `metadata.target_id` | run | **internal id only** (FR-012); the `where` key for retrieval and deletion. |
| `metadata.family` | run | |
| `metadata.owasp_category` | run | Principle VI. |
| `metadata.verdict` | run | `succeeded` / `failed` / `unclear`. |
| `metadata.hard_evidence` | run | bool (FR-007). |
| `metadata.succeeded` | run | bool convenience = `verdict == "succeeded"`; used to keep same-family successes past the recency cap. |
| `metadata.turns_used` | run | int. |
| `metadata.stopping_condition` | run | str (or `""` for a single-turn run). |
| `metadata.attacker_model` | run | str (Principle III); `""` for single-turn. |
| `metadata.created_at` | — | ISO-8601 UTC string; also an int epoch `created_ms` for recency sort. |

### The one-line summary (FR-008, FR-013)

- **Built from**: the run's per-turn `judge_progress` notes, joined in order, with **no model call**.
- **Fallback** (no judge notes): fixed template from metadata, e.g. `"<family>: <verdict> after N turn(s); stopped at <condition>"` (+ `"; canary hard evidence"` when `hard_evidence`).
- **Sanitised** to a fixed shape: collapse whitespace to single spaces, strip control characters, truncate to **≈280 chars**, one line. Guarantees SC-009 and blocks self-injection.

## Retrieval selection (warm)

- **Patterns**: `query(query_texts=[family_goal + " " + recent_conversation], n_results=k (default 5), where={"$and":[{"type":"pattern"},{"family":fam}]})`.
- **Memory**: `get(where={"$and":[{"type":"memory"},{"target_id":tid}]})` → in Python, sort by `created_ms` desc, take first `cap` (default 10), then union with any `succeeded == true AND family == fam` records not already included (FR-016). Never return another target's memory (SC-006).

## Relationships

- A `Target` (SQLite) ↔ its memory records (Chroma, by `target_id`). Deleting the target deletes its SQLite rows (cascade) and its Chroma memory (explicit `delete(where=...)`); patterns persist (FR-024/FR-025).
- A `Run` (SQLite) → exactly one memory record (always) and at most one pattern record (only if `verdict == succeeded`). `runs.memory_written` records whether the memory write succeeded.
- Patterns have no relationship to any target.
