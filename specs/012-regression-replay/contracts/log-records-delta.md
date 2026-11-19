# Contract delta: the 010 log stream, for regression replay (012)

Rows to merge into `specs/010-structured-logging/contracts/log-records.md`'s event catalogue table, verbatim, when
this feature's implementation PR lands (carrying the `spec-change:` note the traceability gate requires, FR-043 to
FR-045). No existing row changes; three rows are added, and two existing rows gain one field each.

## Existing rows, one field added

| `event` | New field | Present |
|---------|-----------|---------|
| `run.start` | `source_run_id` | only when this run's `mode` is `replay` — names the run being replayed |
| `run.end` | `replay_outcome` | only when this run's `mode` is `replay` — `"fixed"` \| `"still_vulnerable"` \| `"inconclusive"` |

Both follow the log stream's general omit-when-not-applicable rule (`log-records.md`'s "Common fields" rules,
"fields are omitted when not applicable") — **not** the `| null` pattern `run.end`'s existing `verdict` and
`succeeded_turn` use (those are always present, `null` when unknown). A normal run's `run.end` line has no
`replay_outcome` key at all, never `"replay_outcome": null`.

No other field changes `run.start`/`run.end` already carry. A replay's `turn` lines need **no** new field: every
turn of a replay passes `attacker_generated=False` (not only turn 1), so `attacker_model`/`attacker_prompt` are
simply absent from every one of its `turn` lines — the existing gate on `attacker_generated` already produces the
right shape with no code change to `events.turn_ended` (research, "Events" code-fact). `source` on a replay's
`turn` line is computed exactly as a live adaptive run's already is (`library:<prompt_id>` for turn 1, the
attacker-prompt reference otherwise) — fed from the **source run's copied** provenance instead of a freshly-made
attacker call, which the field's existing meaning ("what produced this text") already covers correctly.

## New rows

| `event` | Level | Emitted | Fields (beyond the common ones) |
|---------|-------|---------|----------------------------------|
| `replay.batch.start` | INFO | once, before the first entry of a batch replay is claimed | `target_id`, `replayable_count` (how many runs this batch will process), `cap` (the configured `KESTREL_REPLAY_BATCH_MAX_RUNS` in effect) |
| `replay.batch.end` | INFO (ERROR when `error` is set) | once, after every entry has finished (or the batch stopped early) | `target_id`, `fixed_count`, `still_vulnerable_count`, `inconclusive_count`, `duration_ms`, `complete` (`false` on a mid-batch collision, mirroring `BatchResult.complete`; equally `false` on the other stop reason, one entry's own replay failing unexpectedly — `complete` is `false` for **either** `stop_reason`, `"run_in_progress"` or `"replay_failed"`, never just the collision), `stop_reason` (present only when `complete` is `false`), `error` (class name, only on an unexpected failure) |

Both are emitted **outside** any single replay's `run_scope()` — there is no one `run_id` for a whole batch — the
same way `events.connection_test(...)` already emits an unscoped line; `target_id` needs no catalogue entry (it is
already a `SCOPE_FIELD`, which `emit()` always allows regardless of catalogue, research "Events" code-fact).
`replayable_count`, `cap`, `fixed_count`, `still_vulnerable_count`, `inconclusive_count`, `duration_ms`,
`complete`, `stop_reason` and `error` are the new catalogue entries (`complete`
and `stop_reason` — and `error` — are already in the `replay.batch.end` row above, named again here for
completeness; `stop_reason` is `"run_in_progress"` or `"replay_failed"`, research D17).

A batch that is refused before it starts (`batch_too_large`, `permission_missing`, `terms_outdated`,
`run_in_progress`) emits **neither** line — the same convention a refused single run's claim already follows
(`run.start` is never emitted for a claim `RunInProgress` refuses today).

## Ordering inside a replay's own scope

Unchanged from a normal run's (`log-records.md`'s existing "Ordering guarantees" section): `run.start` first; per
turn, the same `(model.request kind=judge)? → turn` shape, with **no** `memory.retrieval` line ever (a replay never
calls the experience store, FR-025) and **no** `model.request kind=attacker` line ever (FR-002); then
`memory.writeback`? — **never emitted at all** for a replay (FR-026; a replay's `run.end` simply carries
`memory_written: null`, the existing "not attempted" value, exactly as a run that did not attempt a write-back
already renders); then `run.end` last.

## Deny-list (unchanged)

Every rule in `010/FR-009` applies unchanged to every line this feature adds: no attack text, reply text, judge
reason/progress text, target URL, target display name, or header value, on `replay.batch.start`/`.end` or on any
line of a replay's own scope (FR-045).
