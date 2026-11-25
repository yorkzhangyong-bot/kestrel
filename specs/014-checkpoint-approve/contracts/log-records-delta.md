# Contract delta: log records (014, over `specs/010-structured-logging/contracts/log-records.md`)

Every rule `log-records.md` already states still applies: one JSON object per line, values as fields never
%-interpolated, `events.CATALOGUE` is the allow-list, no secret/attack/reply text beyond what an ordinary turn line
already carries (FR-033). The implementation pull request edits `log-records.md` to merge these rows in verbatim
and carries a `spec-change:` note.

## Kept-log continuity across a resume (research D20)

A resumed or decided run's kept log is **one continuous sequence**, not a fresh one per request: the per-run
kept-line counter a new request's own lines start from is read from the highest one already stored for that run,
never reset to the start, and the run's kept-line cap is enforced over the whole run's accumulated count.
`GET /api/runs/{id}/log` returns every kept line from every segment, in that one continuous order. The run's own
dropped-line count is likewise a whole-run accumulator, carried in the run's own persisted state across segments
(alongside cost, tokens and time, below) — the final `log.truncated` marker for a multi-segment run reports the
true total dropped across every segment, not only what its own, last segment dropped.

## `run.start` — one new field, omitted when false

- `ask_before_each_turn` (bool) — present, `true`, on an adaptive run started with the checkbox ticked; **omitted
  entirely** when false, exactly like every other optional field already on this line (never a visible, literal
  `false`). Absent for a single-turn or replay `run.start`.

## New: `run.interrupted` — two distinct sources, both checkpointed rows only

| Field | Type | Meaning |
|-------|------|---------|
| `run_id` | int | the row (scoped automatically when written from inside a run's own open scope) |
| `resumable` | bool | `true` when left open (a loadable, version-compatible checkpoint, still mid-run); `false` when closed or reconciled-and-closed |
| `error` | str | **only** when written from the second source below — the escaped exception's own class name, never its text |

Written into **that run's own kept log**, not only emitted unscoped to the stream. Two distinct sources, never
confused for each other:

1. **The start-up sweep's own classification** of a row left `in_progress` by a *previous* process — emitted only
   for a row the sweep actually checkpoints-and-classifies (`is_checkpointed`, `mode == "adaptive"`); a single-turn
   run, a replay, or an experiment repetition the sweep closes through its pre-existing, unconditional path gets no
   such line, keeping that path's own behaviour exactly as it is today (FR-032). No `error` field (nothing escaped;
   this row was simply found this way at start-up).
2. **A checkpointed run's own scope exiting on an exception while its row is still `in_progress`**, within the
   *same* process, no restart or sweep involved (the reversed FR-042's own trace — this applies to the run's very
   first segment too, FR-053, not only a resumed one): `resumable` is always `true` here (the row and its
   checkpoint are, by construction, exactly as FR-042 leaves them), and `error` carries the exception's class name.
   Replaces `run.end` for that exit (below) — never emitted alongside it.

## New: `run.resumed` (a resumable or paused run's resume/decision actually proceeds)

| Field | Type | Meaning |
|-------|------|---------|
| (scoped: `run_id`) | | the usual scope fields, exactly as a fresh `run.start` carries them |
| `from_turn` | int | the turn the resumed run continues from (`state["turns_used"] + 1`) |
| `from_step` | str | which step it continues from — `"attacker"`, `"approve"`, `"send"`, `"evidence"`, `"judge"`, `"decide"`, or `"record"`; a cut right after the run's own input checkpoint (before `attacker` ever ran) reports `"attacker"` too, never the raw `"__start__"` |
| `was_paused` | bool | `true` when the loaded checkpoint held a pending decision; `false` for a plain crash-resume |

Emitted once, inside a freshly opened scope for that run, before the graph is invoked again.

## New: `run.paused` (the approve node actually interrupts)

| Field | Type | Meaning |
|-------|------|---------|
| (scoped: `run_id`, `turn`) | | |
| `turn` | int | the turn awaiting a decision |

Emitted by the caller, once, immediately after the graph invocation returns a result carrying an interrupt — never
from inside the `approve` node itself, whose own re-execution by a bare status re-check must not re-emit this line
each time. No message/attack text — the pending message itself is never logged (it lives on the run's own page via
`pending_turn`, and in `run_turns` once sent).

## New: `run.decided` (one of the three controls is exercised)

| Field | Type | Meaning |
|-------|------|---------|
| (scoped: `run_id`, `turn`) | | the turn the decision applied to |
| `decision` | str | `"approve"` \| `"run_to_end"` \| `"stop"` |

Emitted once per decision, before the run continues (or ends, for `stop`).

## New: `run.stopped` (Stop ends a run without touching the graph)

| Field | Type | Meaning |
|-------|------|---------|
| (scoped: `run_id`) | | |
| `was_paused` | bool | whether the run was paused (the approve node's own Stop control) or merely resumable (the general way out) when stopped |
| `reconciled` | bool | `true` when the run's graph had already reached its own end and Stop finished it with that outcome instead of `stopped_by_user`; `false` for the ordinary case |

Emitted once, from the Stop handler itself — distinct from `run.decided`'s `"stop"` value, which covers only a
paused run's Stop button reaching the same underlying mechanism; `run.stopped` is emitted either way, so a reader
can find every Stop regardless of which control surfaced it.

## `run.end` — withheld only for a checkpointed, still-unfinished scope

010's own rule — one `run.end` per scope, naming the class of any exception that escaped, never its text — keeps
applying exactly as it does today for a single-turn run, a replay, an experiment repetition, and a checkpointed
adaptive run whose scope *did* finish the row (a clean success, a cap, or Stop). The **one** narrow exception: a
**checkpointed** adaptive run's scope ending while its row is **still `in_progress`** withholds `run.end` for that
exit — from the run's own very first segment on (FR-053), not only a resumed one; whichever later request actually
finishes the run emits it then, instead. This has two distinct shapes, never confused: a **clean** exit at a pause
emits neither `run.end` nor anything in its place (`run.paused` already told that story); an exit on an
**exception** emits a kept `run.interrupted` line instead (source 2, above) — so an in-process failure under the
reversed FR-042 still leaves *something* on the run's own kept log, even though no `run.end` fires for it. This
check is evaluated from fields bound to the scope itself when it opened, never a store read at exit; a scope whose
own run is never checkpointed (every pre-existing event-level test, including one that binds both a store and a
run but has no other reason to care whether it is checkpointed) can never satisfy it and is completely unaffected.

The one `run.end` that **is** emitted for a multi-segment checkpointed run reports whole-run totals — duration,
cost, tokens, judge usage, evidence, dropped-line count — read from accumulators carried in the run's own persisted
state across every segment, never only what the finishing request's own segment saw. `stopping_condition` gains
exactly one new possible value, `"stopped_by_user"` (no catalogue change beyond that value being possible).

### A resumed or decided mid-turn reopens its own turn context

A resume or decision that continues an already-started turn (every approved turn in part 2; a live-run resume cut
mid-turn in part 1), opened via **`events.reopened_run_scope(run)`** (data-model.md), explicitly reopens that
turn's own context — its number, and a start time that discounts the interruption or pause gap — rather than
relying on the attacker step's own turn-started signal, which does not run again for a turn that does not re-enter
that step. Every line produced for that turn carries that turn's number and reports only that turn's own real
processing time, computed against `_State.turn_time_spent_at_start` (data-model.md's time-spent section); the
attacker call's own tokens/cost, when the turn's draft itself was not re-executed, are carried over from
`_State.turn_attacker_usage` — the same field the attacker node itself set when it last actually ran — never
reported as missing.

## Secrets and attack text (FR-033, restated for this feature's own lines)

None of `run.interrupted`, `run.resumed`, `run.paused`, `run.decided`, or `run.stopped` carries the pending or any
other message's text, a secret, or a judge reason/progress note — every field above is a count, a flag, a turn/step
name, or one of a small fixed set of decision/mode strings, the same bar every other event line in this project
already holds itself to.
