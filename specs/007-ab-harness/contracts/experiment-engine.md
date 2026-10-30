# Contract: Experiment engine (feature 007)

`src/kestrel/experiments/engine.py` — the A-then-B runner. Pure orchestration over the existing run path; unit-testable with fakes exactly like `runs.py`/`graph.py` tests (fake sender, fake judge, fake attacker, temp store, stub experience). **No attack text** appears here — the engine only selects seeds from the existing library and calls the existing run functions (behaviour only).

## Entry point

```python
async def run_experiment(
    store: TargetStore, *, experiment_id: int, settings: Settings,
    library: AttackLibrary, experience, transport=None, resolver=default_resolver,
    make_judge=..., make_attacker=..., clock: Callable[[], float] = time.monotonic,
) -> None:
```

`make_judge(model)` / `make_attacker(model)` build the per-arm clients (default: real `JudgeClient` / `AttackerClient` from `settings` keys; tests pass fakes). The function reads the experiment + arms from `store`, executes them, and writes all progress and outcomes to `store`. It returns nothing; callers read results from the DB. `POST /api/experiments` schedules it with `asyncio.create_task` and **stores the handle on `app.state`** (e.g. `app.state.experiment_tasks`) so it is not garbage-collected. Do **not** use FastAPI `BackgroundTasks` — that is for short post-response work, not a minutes-long job. Because all progress is in the DB, an integration test polls `GET …/status` to `finished` (fast with fakes), while unit tests `await run_experiment(...)` directly for determinism (T016).

## Execution order and per-run reuse (FR-004, FR-005, R4, R5)

1. Mark `status = running`, `started_at = now`; choose one seed prompt per family via `library.pick(family)` and persist `seed_prompt_ids` (R5).
2. For `arm` in `[A, B]` (record `run_order` 1 then 2):
   1. Build `judge = make_judge(arm.judge_model)` and, for adaptive mode, `attacker = make_attacker(arm.attacker_model)`.
   2. For `family` in campaign families, for `rep` in `range(reps)`:
      - **Cap check before the run** (FR-008, R9): if `completed_runs ≥ max_runs`, or `tokens_used ≥ token_budget_total`, or `clock() − start ≥ wall_clock_s`, **stop cleanly**: set `stopped_reason` to the hit cap, `status = stopped`, `finished_at = now`, and return. No run is left in progress.
      - Resolve the target's headers per run exactly as `POST /api/runs` does (never copied into an arm/result/log — Principle IV).
      - Execute the run with the **arm's** configuration:
        - adaptive → `execute_adaptive_run(..., attacker=attacker, judge=judge, max_turns=arm.turn_cap, token_budget=arm.token_budget, use_prior_experience=arm.use_prior_experience, hint_provider=<arm-scoped, same shape as api.main>)`.
        - single_turn → `execute_run(..., judge=judge, use_prior_experience=arm.use_prior_experience)`.
      - Record an `experiment_runs` row linking the new `run_id` to `(experiment_id, arm, rep, family)` (FR-004). If the run could not be claimed/sent, record the row with `run_id = null` / `send_ok = false` — **never dropped** (FR-015).
      - **Write-back toggle (FR-005)**: if `arm.write_back` is true, call `write_back(experience, store, run, turns)` (Principle V). If false (cold arm), **skip** write-back; the run keeps `memory_written = null`, and this is the recorded warming control (see plan Complexity Tracking).
3. If every planned run completed, set `status = finished`, `stopped_reason = completed`, `finished_at = now`.
4. Any unexpected error sets `status = failed`, `stopped_reason = "failed:<reason>"`, closes any open run (the existing `execute_*` already closes its row), and is logged without run content (one line, no prompt/reply/header — matches `runs.py` logging).

## Warming and order record (FR-005, FR-016)

- `run_order` on each arm captures A-then-B.
- The cold arm's skipped write-back + each run's `use_prior_experience` make the warming auditable; the result/report render it as the `warming` line ("A cold (no write-back); B warm").

## Caps and partial results (FR-008, SC-004)

- All three caps are checked at every run boundary; the first to trip stops the experiment and names itself in `stopped_reason`.
- Because checks happen **before** a run starts, a cap never truncates a run mid-flight and never leaves the target locked.
- The result endpoint returns the partial comparison over whatever runs completed, labelled with the cap that stopped it.

## Concurrency

- One running experiment per target (`uq_experiments_active`); the engine runs runs sequentially, so it never contends for the per-target single active-run slot (`uq_runs_active`).

## Testability (Principle VII)

- Unit: `run_experiment` with a fake sender/judge/attacker and a temp SQLite store asserts order (A then B), the cold-arm write-back skip, cap stop + partial results, and the no-secret-in-logs rule. Fakes make outcomes deterministic.
- Integration: drive it through `POST /api/experiments` + poll `GET …/status` to `finished`, then assert `GET …/result`.
- e2e: one real 2-arm N=1 retrieval-off-vs-on experiment vs the HS-code target producing a comparison.
