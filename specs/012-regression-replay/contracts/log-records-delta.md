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
| `replay.batch.end` | INFO (ERROR when `error` is set) | once, after every entry has finished (the batch stopped early, or a crash escaped the per-entry handling entirely) | `target_id`, `fixed_count`, `still_vulnerable_count`, `inconclusive_count`, `duration_ms`, `complete` (`false` on a mid-batch collision, mirroring `BatchResult.complete`; equally `false` on the other stop reason, one entry's own replay failing unexpectedly; equally `false` again for a crash outside the per-entry handling, which never produces a `BatchResult` at all — `complete` is `false` for **either** `stop_reason` or for neither), `stop_reason` (present only for the two cases that resolve into a `BatchResult`; **absent**, not `null`, for a crash outside the per-entry handling), `error` (class name, present for a `replay_failed` stop **and** for the no-`stop_reason` crash case — absent only for a `run_in_progress` collision) |

Both are emitted **outside** any single replay's `run_scope()` — there is no one `run_id` for a whole batch — the
same way `events.connection_test(...)` already emits an unscoped line; `target_id` needs no catalogue entry (it is
already a `SCOPE_FIELD`, which `emit()` always allows regardless of catalogue, research "Events" code-fact).
`replayable_count`, `cap`, `fixed_count`, `still_vulnerable_count`, `inconclusive_count`, `duration_ms`,
`complete`, `stop_reason` and `error` are the new catalogue entries (`complete`
and `stop_reason` — and `error` — are already in the `replay.batch.end` row above, named again here for
completeness; `stop_reason` is `"run_in_progress"` or `"replay_failed"`, research D17).

**Clarified after independent review (round 1, item 8):** `error` is present for a `"replay_failed"` stop — the
crashed entry's own root-cause class (the same one its own `run.end` already carries, never the internal
`ReplayFailed` wrapper's name) — and absent for a `run_in_progress` collision, which is an expected stop, not a
failure. The first implementation round left this field unset in both cases; independent review caught that
`run.end` for the crashed entry itself also named the wrapper (`"ReplayFailed"`) instead of the original fault.

**Clarified again after independent review (round 2, item D1):** `error` is **not** present only when
`stop_reason` is `"replay_failed"` — a crash outside the per-entry handling (`replay.py`'s own outer `try`
around `store.list_turns`, or rebuilding a crashed entry's row) also sets `error` to its root-cause class, with
**no** `stop_reason` at all, because that failure never resolves into a `BatchResult` in the first place: the
line is logged and the exception then propagates, so the HTTP request itself fails with an unhandled 500. This
third shape — `complete: false`, `stop_reason` absent, `error` set — is the one case where `replay.batch.end`
is not followed by a clean (if incomplete) 200 response; it is kept, deliberately, as the only record of what
the batch was doing when it failed outright.

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
