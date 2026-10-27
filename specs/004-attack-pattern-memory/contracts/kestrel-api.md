# Contract: Kestrel API additions (feature 004)

Only the deltas from features 001–003 are listed. All existing endpoints and error shapes are unchanged.

## Target purpose description (FR-020)

- `POST /api/targets` and `PUT /api/targets/{id}` request body gain an optional `description: string | null`.
  - Trimmed; **max 200 characters** (422 `form_error` on `description` if longer); treated as **non-secret** (stored in plain, not encrypted).
  - Editing the description alone does **not** require a fresh connection test (it is not part of the connection fingerprint).
- `TargetSummary` / `TargetDetail` responses gain `description: string | null`.

## Run: use prior experience + write-back flag (FR-014, FR-010)

- `POST /api/runs` request body gains `use_prior_experience: boolean` (default **`true`**, FR-014). Recorded on the run on both run paths. For a single-turn run the value is stored but has **no behavioural effect** — a single-turn run has no attacker and no hints; the field is recorded only so runs group consistently in the feature-006 A/B harness. For an adaptive run it selects warm vs cold.
- `RunSummary` / `RunDetail` gain:
  - `use_prior_experience: boolean`
  - `memory_written: boolean | null` — `null` not yet attempted, `true` written, `false` failed (drives the screen's warning, FR-010).

> Storage note: schema v4 adds two run columns — `use_prior_experience` (set at claim time, default warm) and `memory_written` (set after write-back). Both are additive, like the feature-003 columns. The warm/cold decision does not change the verdict, only what the attacker was shown.

## Target profile (FR-022, FR-023, US4)

- New `GET /api/targets/{id}/profile` → `ProfileOut`:

```text
ProfileOut {
  target_id: int
  total_runs: int
  by_family:  [{ family: str, count: int }]
  by_verdict: [{ verdict: str, count: int }]   # succeeded | failed | unclear
  recent: [{ summary: str, family: str, verdict: str, created_at: str }]   # newest first, bounded
}
```

- Built only from that target's memory records (summaries + non-secret metadata). Contains **no** auth value, URL or name (SC-004, FR-023). Empty target → all counts 0 and `recent: []` (not an error).
- `404 not_found` if the target does not exist.

## Deletion also clears memory (FR-024)

- `DELETE /api/targets/{id}` deletes the SQLite target (cascades runs/headers/canaries, unchanged) **and** calls `experience.delete_target_memory(id)`. Shared patterns are not touched (FR-025). Still returns `204`.

## Config (for the screen and the A/B harness)

- `GET /api/config` `ConfigOut` gains:

```text
experience: {
  pattern_k: int,            # default 5
  memory_cap: int,           # default 10
  use_prior_experience_default: bool   # true
}
```

## Start-up

- On start-up the API builds the `ExperienceStore` and calls `seed_patterns(library)` once (idempotent, FR-004). If the library is unavailable, seeding is skipped with a warning (as the attack routes already degrade). Seeding failure is logged and does not stop the API, but is surfaced the same loud way write-back is if it recurs per run.
