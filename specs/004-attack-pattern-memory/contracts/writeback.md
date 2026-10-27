# Contract: Write-back after every run

`src/kestrel/experience/writeback.py` (or an equivalent step called from `POST /api/runs`). Runs once after `execute_run` / `execute_adaptive_run` returns the finished `Run`. Guarantees Principle V: every run writes back, and a failure is loud (FR-006, FR-009, FR-010).

## Signature

```text
write_back(experience, store, run, turns) -> bool   # returns True if memory was written
```

- `experience`: the `ExperienceStore` (or `None` when the store is unavailable — then write-back fails loud, see below).
- `store`: the SQLite `TargetStore` (to set `memory_written`).
- `run`: the finished `Run`.
- `turns`: `store.list_turns(run.id)` (empty for a single-turn run).

## Behaviour

1. **Build the summary** (`experience/summary.py`): join the per-turn `judge_progress` notes in order; if there are none, use the fixed metadata template; sanitise to one bounded line (FR-008, FR-013).
2. **Write memory** (always, any verdict): `experience.write_memory(...)` with the run's metadata (FR-006, FR-007).
3. **Write a pattern** (only if `run.verdict == "succeeded"`): `experience.write_pattern(document=<winning attacker message(s)>, ...)` (FR-009). The winning messages are the attacker turns up to and including `run.succeeded_turn` (adaptive) or `run.prompt_text` (single-turn).
4. **Mark success**: `store.set_memory_written(run.id, True)`; return `True`.

## Fail loud (FR-010, SC-011)

If any step raises (store missing, Chroma error):

- The run's own SQLite row is **already saved** by `execute_*` — it is never touched or discarded.
- `store.set_memory_written(run.id, False)`.
- Log an error (`kestrel` logger) naming the run id and that write-back failed — **no** summary text, reply, or secret in the log line.
- Do **not** retry silently.
- Return `False`; the API includes `memory_written=false` in the `RunDetail` so the screen shows a visible warning.

## Notes

- Write-back is **not** part of `execute_run`/`run_adaptive`; those stay storage-agnostic (feature 002/003 unchanged). The single call site is `POST /api/runs`, which is the only place runs are created, so "after every run" holds.
- Single-turn runs: summary falls back to the metadata template (no judge progress notes exist as turns); a single-turn success writes the prompt text as the pattern document.
