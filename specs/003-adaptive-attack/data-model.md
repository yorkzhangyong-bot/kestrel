# Data Model: Run a Multi-Turn Adaptive Attack and Judge the Result

Extends feature 002's schema. `meta.schema_version` moves **2 → 3**: columns are added to `runs` and a `run_turns` child table is created. Feature 001/002 tables are otherwise unchanged. All SQL stays in `src/kestrel/store.py`.

## Migration 2 → 3

Additive only. On connect, when the stored version is below 3: add the new `runs` columns, create `run_turns`, set `schema_version = 3`. A version below 2 first runs the 1 → 2 migration (feature 002), then 2 → 3. Existing runs become `mode = 'single_turn'` with null adaptive fields; their stored prompt and reply are untouched. A fresh database is built at version 3 directly. An unknown (newer) version is refused, as in feature 002.

## `runs` — added columns

Feature 002's columns stay. These are added (all nullable or defaulted, so existing rows migrate cleanly):

| Column | Type | Meaning |
|---|---|---|
| `mode` | TEXT NOT NULL DEFAULT 'single_turn' | `CHECK` in `single_turn`, `adaptive`. Existing rows are single-turn. |
| `attacker_model` | TEXT | The attacker model and version driving an adaptive run; null for single-turn (FR-015). |
| `turn_budget` | INTEGER | The turn cap the run was allowed (adaptive only). |
| `turns_used` | INTEGER | How many turns actually ran. |
| `token_budget` | INTEGER | The token budget the run was allowed. |
| `tokens_used` | INTEGER | Attacker + judge tokens actually used. |
| `time_limit_s` | INTEGER | The wall-clock limit the run was allowed. |
| `stopping_condition` | TEXT | How an adaptive run ended: `succeeded`, `turn_cap`, `token_budget`, `time_limit`, `send_failed`, `attacker_failed`, or `interrupted`. |
| `succeeded_turn` | INTEGER | The turn at which the run succeeded, or null (FR-019). |

`attacker_source` (feature 002) keeps recording the seed's origin, `library:<version>`; `attacker_model` records the model that then drove the conversation. An adaptive run names both.

For a single-turn run every added column stays at its default or null, so feature 002 behaviour is unchanged.

## `run_turns` — new table

One row per conversation turn of an adaptive run, ordered (FR-020). Single-turn runs write none (they keep their single prompt/reply on the run row).

| Column | Type | Rules |
|---|---|---|
| `id` | INTEGER | primary key |
| `run_id` | INTEGER | not null, references `runs(id)` ON DELETE CASCADE |
| `position` | INTEGER | not null; 1-based turn order |
| `attacker_message` | TEXT | not null; masked before storing (FR-021) |
| `reply_text` | TEXT | the target's reply, masked and cut; null if that turn's send failed |
| `reply_truncated` | INTEGER | not null, default 0 |
| `judge_verdict` | TEXT | null when a canary settled the turn or the send failed; otherwise `succeeded`/`failed`/`unclear` |
| `judge_reason` | TEXT | the judge's one-line reason for that turn, or null |
| `judge_progress` | TEXT | the judge's "how close" note for that turn, or null (R6) |
| `created_at` | TEXT | not null, UTC ISO-8601 |

Index `idx_run_turns_run` on `(run_id, position)` for ordered retrieval. Deleting a run (or its target, which cascades to runs) deletes its turns.

## How an adaptive run moves

```text
   POST /api/runs (mode=adaptive) → claim run row (mode=adaptive, in_progress)
                                       │
                                       ▼
   ┌──────────────── for each turn, while under all three caps ───────────────┐
   │ attacker node: next message from the conversation + last judge note      │
   │ send node: one request to the target (feature 002 tester)               │
   │   └─ send failed → finish: stopping_condition=send_failed, failure_step  │
   │ evidence node: canary check on the masked reply                          │
   │   └─ canary matched → finish: succeeded, hard_evidence, succeeded_turn   │
   │ judge node: verdict + progress note (no canary only)                    │
   │   └─ verdict=succeeded → finish: succeeded (judge), succeeded_turn       │
   │ record the turn in run_turns; add usage; next turn                       │
   └──────────────────────────────────────────────────────────────────────────┘
                                       │ a cap reached
                                       ▼
          finish: verdict = last turn's verdict (failed/unclear),
                  stopping_condition = turn_cap | token_budget | time_limit
```

A run leaves `in_progress` once. The start-up sweep (feature 002) closes any adaptive run left `in_progress` as `unclear` with `stopping_condition = interrupted`, keeping the `run_turns` already written.

## Validation rules

| Rule | Where | Requirement |
|---|---|---|
| `mode` is `single_turn` or `adaptive` | `CHECK` | FR-001 |
| One in-progress run per target (any mode) | the `uq_runs_active` partial index from feature 002 | FR-004 |
| Turn, token and time caps enforced, whichever first | `attack/graph.py` | FR-010, FR-011 |
| `stopping_condition` recorded whenever a run ends | `attack/graph.py` | FR-012 |
| `hard_evidence` only from a canary, never the judge | `attack/graph.py` | FR-018, Principle II |
| `attacker_model` and the budgets present on every adaptive run | `attack/graph.py` | FR-015, Principle III |
| Every message and reply masked before store/judge/display | reuse `secrets.mask_values` | FR-021, Principle IV |
| Target terms version equals the current one (now 3) | API, before a run starts | FR-003, R11 |

## Terms of service

No schema change: a target's accepted `terms_version` is already a `targets` column (feature 001). The terms text and version move to **3** (R11); a target on an older version is re-confirmed before an attack, by the feature 001 mechanism feature 002 already used for version 2.

## Entities not stored as tables

- **Attacker**, **Verdict** and **Conversation turn** are as in the spec's Key Entities; the attacker's identity is the `attacker_model` string on the run, the verdict is the `verdict`/`hard_evidence`/`reason` trio, and a conversation turn is a `run_turns` row.
