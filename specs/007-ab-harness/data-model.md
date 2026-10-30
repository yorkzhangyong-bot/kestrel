# Data Model: A/B Harness (feature 007)

Schema **version 6** — additive over v5 (three new tables, no change to existing tables). New rows are created by the `CREATE IF NOT EXISTS` script; the migration adds `"5"` to the set of versions it upgrades from and bumps `SCHEMA_VERSION` to `"6"`. Every per-run fact (verdict, hard_evidence, tokens_used, attacker_model, judge_model, use_prior_experience, turns_used, succeeded_turn) continues to live on the existing `runs` table; `experiment_runs` only links a run to its experiment and arm (FR-004).

## Entities

### Campaign (value object, stored on the experiment row)
What is run, shared by both arms (FR-001).

| Field | Type | Rules |
| --- | --- | --- |
| target_id | int | one owned target; permission + terms gate applies (FR-015, Principle VIII) |
| families | list[str] | subset of the four families; **default: all four** |
| mode | str | `single_turn` or `adaptive`; shared by both arms (edge case: arms do not vary mode) |
| reps | int | N repetitions per family; **default 3**; ≥ 1 |
| seed_prompt_ids | map family→prompt_id | chosen once at start; both arms replay the same seeds (R5) |

### Arm (entity — `experiment_arms`)
A named configuration varied between A and B (FR-002). **Holds no secrets** (Principle IV).

| Field | Type | Rules |
| --- | --- | --- |
| label | str | `A` or `B` |
| attacker_model | str | model **name** only |
| judge_model | str | model **name** only |
| use_prior_experience | bool | the feature-004 retrieval switch (on/off) |
| turn_cap | int | per-run adaptive turn cap (≥ 1) |
| token_budget | int | per-run adaptive token budget (≥ 1) |
| write_back | bool | **cold arm = false** (FR-005); default true |
| run_order | int | 1 or 2 — which arm ran first (recorded by the engine) |

**Validation (FR-003)**: arm A and arm B MUST differ in at least one of {attacker_model, judge_model, use_prior_experience, turn_cap, token_budget}. The diff is derivable from the two rows and shown in the report/result.

### Experiment (entity — `experiments`)
One campaign run under arm A and arm B (FR-003, FR-016).

| Field | Type | Rules |
| --- | --- | --- |
| id | int | PK |
| target_id | int | FK → targets; ON DELETE CASCADE |
| mode, families, reps, seed_prompt_ids | campaign | as above (families/seeds stored as JSON text) |
| max_runs, token_budget_total, wall_clock_s | int | hard caps; **finite, required** (FR-008) |
| status | str | `running` / `finished` / `stopped` / `failed` |
| stopped_reason | str/null | `completed` / `max_runs` / `token_budget` / `wall_clock` / `failed:<why>` |
| created_at, started_at, finished_at | ISO-8601 UTC | |

### ExperimentRun (link — `experiment_runs`)
Tags an ordinary run with its experiment and arm (FR-004). One row per executed run.

| Field | Type | Rules |
| --- | --- | --- |
| experiment_id | int | FK → experiments; ON DELETE CASCADE |
| arm_id | int | FK → experiment_arms |
| rep_index | int | 0 … reps-1 |
| family | str | the family this run targeted |
| run_id | int/null | FK → runs; null only if the run could not be claimed (recorded, not dropped — FR-015) |
| send_ok | bool | false if the run could not be sent (model unavailable); the arm result notes the shortfall |

### ArmResult & Comparison (computed, not stored)
Derived on demand by `experiments/results.py` from the experiment's runs (so re-reading never re-runs anything, like the feature-005 report).

- **ArmResult**: confirmed rate + Wilson interval, suspected rate + Wilson interval, mean turns to success, mean tokens, estimated cost (or "unavailable"), per-family breakdown, per-OWASP breakdown, planned vs completed counts (FR-006).
- **Comparison**: for each headline metric the difference; on the **overall confirmed** rate a two-proportion z-test with a small-sample caveat (FR-007); per-family / per-OWASP differences are descriptive only.

## SQLite v6 (new tables)

```sql
-- Added in schema version 6 (feature 007). Additive; existing tables unchanged.
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('single_turn', 'adaptive')),
    families TEXT NOT NULL,                 -- JSON array of family keys
    reps INTEGER NOT NULL CHECK (reps >= 1),
    seed_prompt_ids TEXT NOT NULL,          -- JSON object family -> prompt_id (R5, FR-016)
    max_runs INTEGER NOT NULL CHECK (max_runs >= 1),
    token_budget_total INTEGER NOT NULL CHECK (token_budget_total >= 1),
    wall_clock_s INTEGER NOT NULL CHECK (wall_clock_s >= 1),
    status TEXT NOT NULL CHECK (status IN ('running', 'finished', 'stopped', 'failed')),
    stopped_reason TEXT,                     -- 'completed' | 'max_runs' | 'token_budget' | 'wall_clock' | 'failed:...'
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiments_target ON experiments (target_id, created_at DESC);
-- At most one running experiment per target, so arms never contend for the single active-run slot (FR-008).
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiments_active ON experiments (target_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS experiment_arms (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (label IN ('A', 'B')),
    attacker_model TEXT NOT NULL,           -- model name only; never a secret (Principle IV)
    judge_model TEXT NOT NULL,
    use_prior_experience INTEGER NOT NULL,  -- retrieval on (1) / off (0), feature-004 switch
    turn_cap INTEGER NOT NULL CHECK (turn_cap >= 1),
    token_budget INTEGER NOT NULL CHECK (token_budget >= 1),
    write_back INTEGER NOT NULL DEFAULT 1,  -- cold arm = 0 (FR-005)
    run_order INTEGER                       -- 1 or 2; set when the arm starts
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms ON experiment_arms (experiment_id, label);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    arm_id INTEGER NOT NULL REFERENCES experiment_arms(id) ON DELETE CASCADE,
    rep_index INTEGER NOT NULL,
    family TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,  -- null only if the run could not be claimed
    send_ok INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp ON experiment_runs (experiment_id, arm_id);
```

## Migration notes

- `SCHEMA_VERSION` → `"6"`. In `TargetStore._migrate`, extend the accepted-upgrade guard from `("1","2","3","4")` to include `"5"`; the three tables come from the `CREATE IF NOT EXISTS` script, so no `ALTER` is needed. Bump the stored `schema_version` to `"6"` at the end as the existing code already does.
- A unit test (schema v5 → v6) asserts an existing v5 database opens, gains the three tables, and reports version 6 (mirrors `test_store_migration_v5`). Tag it `FEATURE = "007"`.
- Deleting a target cascades to its experiments, arms, and experiment_run links; the underlying runs are deleted by the existing `runs` cascade, and the engine's cold/warm write-back decisions mean experience memory is cleaned by the existing `delete_target_memory` path (FR-015 integrity).
