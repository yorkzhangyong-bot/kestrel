# Quickstart: Regression Replay (012)

Validates each user story against the shapes in `data-model.md` and `contracts/`. PowerShell commands shown; bash
equivalents are the same `uv run ...` invocations.

## Prerequisites

```powershell
uv sync
uv run pytest tests/unit tests/integration   # offline baseline, before touching anything
```

## US1 — Replay a past attack (P1)

Offline, once implemented:

```powershell
uv run pytest tests/integration/test_replay_run.py -v
```

Manual check against a local API + the HS-code target (same setup `CLAUDE.md`'s "HS-code target" section
describes):

```powershell
$env:HS_TARGET_API_KEY="test-key-123"; $env:HS_TARGET_CANARY="KESTREL-CANARY-local-001"
uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
# in another shell:
uv run uvicorn kestrel.api.main:create_app --factory --port 8000
```

1. Register the target, tick the permission box, save, run one single-turn attack against the `system_prompt_leak`
   family until it succeeds (or seed a canary and pick a prompt likely to trigger it).
2. `POST http://127.0.0.1:8000/api/runs/{that run's id}/replay` (or click **Replay** on the run page once the UI
   task lands). Expect a **201** `RunDetail` with `mode: "replay"`, `source_run_id` naming the original, and
   `replay_outcome` one of `fixed` / `still_vulnerable` / `inconclusive`.
3. `GET /api/runs/{the new replay's id}` — expect `comparison` present, naming both runs' verdicts.
4. Confirm in the server's log stream (`KESTREL_LOG_FORMAT=text` for a quick read) that no `model.request
   kind=attacker` line appears anywhere in the replay's scope, and no `memory.retrieval` line either.

## US2 — No trace in memory or the report (P1)

```powershell
uv run pytest tests/integration/test_replay_memory_isolation.py tests/integration/test_replay_report_exclusion.py -v
```

Both assert, over a `SpyExperienceStore`, that a single replay and a batch replay each produce zero `query_patterns`
and zero `write_pattern`/`write_memory` calls, and that `GET /api/targets/{id}/report` is byte-identical in its
finding count before and after replaying one of that target's existing findings.

## US3 — Batch replay (P2)

```powershell
uv run pytest tests/integration/test_replay_batch.py -v
```

Manual: seed a target with more than 20 (the default `KESTREL_REPLAY_BATCH_MAX_RUNS`) replayable runs and confirm
`POST /api/targets/{id}/replays` answers **409** `batch_too_large` naming the count and the cap before anything is
sent; lower the cap (`$env:KESTREL_REPLAY_BATCH_MAX_RUNS="2"`) and confirm a target with exactly 2 replayable runs
now succeeds, with `"complete": true` in the response. To see an incomplete batch, start one against a target
with several replayable runs and, from a second shell, call `POST /api/runs` against the same target while the
batch is mid-flight; confirm the batch's response has `"complete": false`, a `"stop_reason"` naming the collision,
and `"not_replayed_source_ids"` listing what it never reached — never a 409 for this case (`contracts/api.md`).

## US4 — CI gate (P2)

```powershell
uv run python scripts/check_replay.py --help
uv run pytest tests/unit/test_check_replay_script.py -v
```

Manual, against the local API above:

```powershell
uv run python scripts/check_replay.py --target-id 1
echo $LASTEXITCODE
```

Confirm the four exit codes by construction: an all-fixed target (`0`), a target with one still-vulnerable replay
mixed with an inconclusive one (`1`, not `2`), a target with only inconclusive replays (`2`), an incomplete batch
(the mid-flight-collision case above) with no still-vulnerable entry among those completed (also `2`), and a
wrong `--target-id` or `$env:KESTREL_API_URL` pointed at nothing (`3`); an incomplete batch caused by one entry's
own unexpected failure (`stop_reason: "replay_failed"`) exits the same way a collision does — `1` with a
completed still-vulnerable entry, else `2`. Confirm the script's own default timeout (printed with `-v`/debug
output, or just time it) is comfortably longer than `cap × per_replay_time_limit_s` (`GET /api/config`'s
`replay.per_replay_time_limit_s` — the longer of the adaptive and single-turn deadlines, not the adaptive one
alone), and that `--timeout 30` visibly overrides it on a target with nothing to replay (fast either way, but
the flag takes effect).

## Manual migration check (schema v10)

```powershell
# Against a copy of a v9 (or earlier) database file, never the real data/kestrel.db:
Copy-Item path\to\old\kestrel.db $env:TEMP\kestrel-v10-check.db
$env:KESTREL_DB_PATH="$env:TEMP\kestrel-v10-check.db"
$env:KESTREL_MODE="local"
uv run uvicorn --factory kestrel.api.main:create_app --port 8000
# Ctrl+C once it logs ready — create_app's own TargetStore(...) construction already ran the migration on start-up.
```

(Starting the API normally is both simpler and the realistic path, since `create_app`
already builds the store through the same `load_or_create_key` → `Vault` → `TargetStore(...)` sequence every
real start-up uses — a one-liner that constructs `TargetStore` directly would need to pass `Vault` key bytes,
not a module object.) `tests/unit/test_store_migration_v10.py` is the automated version of this and is the one
that gates CI — this manual step is only for eyeballing a real, previously-v9 database file before shipping.
Confirm the file's `schema_version` meta row reads `10`, every pre-existing run still has
`source_run_id`/`replay_outcome` as `NULL`, and (`sqlite3 $env:TEMP\kestrel-v10-check.db "select seq from
sqlite_sequence where name='runs';"`) the `runs` sequence did not drop below the highest id the file already had.

## End-to-end (`tests/e2e/test_us012_replay.py`, marker `e2e`)

```powershell
uv run pytest tests/e2e/test_us012_replay.py -v -m e2e
```

Against the real HS-code target and a real judge/attacker key (`OPENROUTER_API_KEY` set): run one real attack; a
live model's verdict on the day is not guaranteed `"succeeded"` (`tests/e2e/test_us1_attack.py` already documents
this for a comparable case), so the test promotes its own temporary database row directly — a documented,
test-only `UPDATE runs SET verdict = 'succeeded' WHERE id = ?`, **not** `TargetStore.finish_run` (which only
updates a row still `in_progress` and would raise on an already-finished one) —
so the run becomes replayable; replay it through the real, in-process API, and assert the replay's recorded
outcome (one of the three labels; the value itself is not asserted) and `GET /api/runs/{replay id}`'s
`comparison` are both present and consistent with the two runs' own verdicts.
