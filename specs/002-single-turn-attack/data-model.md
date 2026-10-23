# Data Model: Run One Single-Turn Attack and Judge the Result

Extends feature 001's SQLite schema. `meta.schema_version` moves **1 → 2**. Feature 001's `targets`, `target_headers` and `meta` are unchanged; two tables are added. All SQL stays in `src/kestrel/store.py`.

## Migration 1 → 2

Additive only. On connect, when the stored version is below 2: create `target_canaries`, create `runs` with its indexes, set `schema_version = 2`. A database created fresh is built at version 2 directly. Nothing is rewritten, so saved targets and their encrypted headers survive untouched (R11).

## `target_canaries`

A string the user has placed in their agent, so that finding it in a reply is proof the agent revealed it. Not a credential, so stored as plain text (R7).

| Column | Type | Rules |
|---|---|---|
| `id` | INTEGER | primary key |
| `target_id` | INTEGER | not null, references `targets(id)` ON DELETE CASCADE |
| `position` | INTEGER | not null; the order shown in the form |
| `value` | TEXT | not null, `CHECK(length(value) >= 8)` (FR-025) |
| `created_at` | TEXT | not null, UTC ISO-8601 |

Unique index on `(target_id, value)` so the same canary cannot be declared twice on one target. A target may have zero canaries, in which case every run against it is judged by the judge alone (FR-024).

## `runs`

One attack sent to one target, and its outcome. Written before the send, updated at the end (R10). Rows live in the SQLite file, so runs survive a restart (FR-029).

| Column | Type | Rules |
|---|---|---|
| `id` | INTEGER | primary key |
| `target_id` | INTEGER | not null, references `targets(id)` ON DELETE CASCADE (FR-030) |
| `prompt_id` | TEXT | not null; the library's stable identifier |
| `prompt_title` | TEXT | not null; copied so a later library edit cannot rewrite history |
| `prompt_text` | TEXT | not null; the text as sent |
| `family` | TEXT | not null, `CHECK` in the four families |
| `owasp_category` | TEXT | not null (FR-002, Principle VI) |
| `attacker_source` | TEXT | not null; `library:<version>` (FR-019, R9) |
| `status` | TEXT | not null, `CHECK` in `in_progress`, `finished` |
| `reply_text` | TEXT | null when the send failed; masked and cut before storing |
| `reply_truncated` | INTEGER | not null, default 0; 1 when the reply was cut (FR-022) |
| `verdict` | TEXT | null while in progress or when the send failed; otherwise `CHECK` in `succeeded`, `failed`, `unclear` |
| `hard_evidence` | INTEGER | not null, default 0; 1 only when a canary matched (FR-018) |
| `reason` | TEXT | null while in progress; one line otherwise |
| `judge_used` | INTEGER | not null, default 0 |
| `judge_model` | TEXT | null when no judge was used; otherwise the model with its version (FR-019) |
| `failure_step` | TEXT | null unless the send failed; one of feature 001's step names (FR-014) |
| `started_at` | TEXT | not null, UTC ISO-8601 |
| `finished_at` | TEXT | null while in progress |

**Indexes**

- `idx_runs_target` on `(target_id, started_at DESC)` — the listing order in FR-028.
- `uq_runs_active` — `UNIQUE (target_id) WHERE status = 'in_progress'`. A partial unique index makes FR-010 a property of the database rather than of a process, so two API workers cannot both start a run against one target.

## How a run moves

```text
                    ┌──────────────┐
   POST /api/runs → │ in_progress  │ ── row written before anything is sent
                    └──────┬───────┘
                           │
       ┌───────────────────┼────────────────────┬─────────────────────┐
       │                   │                    │                     │
  send failed        canary matched       no canary match       process stopped
       │                   │                    │                     │
       ▼                   ▼                    ▼                     ▼
  finished            finished             judge asked           finished
  failure_step=…      verdict=succeeded         │                verdict=unclear
  verdict=null        hard_evidence=1           ▼                reason="interrupted"
  judge_used=0        judge_used=0         finished              (swept at start-up)
                                           verdict=judge's
                                           hard_evidence=0
                                           judge_used=1
```

A run only ever leaves `in_progress` once. The start-up sweep (FR-031) closes anything the process left behind, which is also what releases `uq_runs_active`.

## Validation rules

| Rule | Where | Requirement |
|---|---|---|
| Canary at least 8 characters | API, and a `CHECK` in the schema | FR-025 |
| Canary unique within a target | unique index | FR-024 |
| Exact, case-sensitive match against the masked reply | `runs.py` | FR-026, R6 |
| One in-progress run per target | partial unique index | FR-010 |
| Verdict is one of three values | `CHECK` | FR-017 |
| `hard_evidence = 1` only when a canary matched | `runs.py`; never set from a judge answer | FR-018, Principle II |
| `judge_model` present whenever `judge_used = 1` | `runs.py` | FR-019, Principle III |
| Reply masked for header values before storing, judging or display | `runs.py`, reusing `secrets.mask_values` | FR-015, FR-020, Principle IV |
| Target's terms version equals the current one | API, before a run starts | FR-023 |
| Target has a permission confirmation | API, before a run starts | FR-009 |

## Read-only data: the attack library

Not in the database. `src/kestrel/attacks/data/library.json` is loaded once at start-up, validated, and indexed by family. Its shape and its provenance rules are in [contracts/attack-library.md](./contracts/attack-library.md). It is read-only in this feature, so a prompt's identity lives in the file while a run keeps its own copy of the text — a later library edit cannot change what a past run says it sent.

## Entities not stored

- **Verdict** is not a table; it is the `verdict`, `hard_evidence`, `reason` trio on a run.
- **Attack family** is not a table; it is a checked string on a run and a field in the library file. A table would add a join for four fixed values.
