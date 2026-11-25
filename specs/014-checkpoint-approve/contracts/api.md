# Contract: resuming, deciding, and stopping a run

An execution lease, turn-specific single-use decisions, a `/stop` endpoint usable on any resumable run, and
preconditions on resume/decision. Four endpoints change or are added, all synchronous (FR-025) — a request
completes once that one request's own action is done (a pause, a finish, or a refusal) — exactly like
`POST /api/runs` today. Every error uses the existing `{"error": {"code", "field", "message"}}` shape (`api_error`,
`contracts/kestrel-api.md`).

## Changed: `POST /api/runs`

One new optional field on the request body, accepted only for `mode == "adaptive"`:

```json
{"target_id": 3, "family": "direct_injection", "mode": "adaptive", "ask_before_each_turn": true}
```

A `422` form error (`field: "ask_before_each_turn"`) when `true` is given alongside `mode == "single_turn"` — the
store itself refuses a claim with `ask_before_each_turn=True` for a non-adaptive mode, so this is not left to the
implementer's judgement at the API layer alone.

The response is still **201** `RunDetail` — the run row is claimed either way — and MAY now describe a **paused**
run instead of only a finished or crashed one:

```json
{"id": 57, "status": "in_progress", "ask_before_each_turn": true, "resumable": true, "paused": true,
 "run_state": "paused", "idle_stop_at": "2026-11-26T10:15:00Z",
 "pending_turn": {"turn": 2, "interrupt_id": "...", "message": "<the attacker's drafted turn-2 message, masked>"},
 "..."}
```

With `ask_before_each_turn` false or omitted, `run.start` itself gains no new *visible* field — it omits
`ask_before_each_turn` entirely, exactly like every other optional field already on that line — but the response
body's `resumable`/`paused`/`pending_turn`/`run_state`/`idle_stop_at` are always present regardless
(`false`/`false`/`null`/one of this feature's own `run_state` values/`null` for a run this feature's pause
mechanism never touches): those five are new on `RunDetail` for **every run of every mode**, not only an adaptive
one, the same handful of differences FR-031 names explicitly for an adaptive run specifically (it is now
checkpointed and resumable rather than unconditionally closed on an interruption; its target lock now survives a
restart until someone resumes or stops it; its time limit is now measured as time spent executing; it is stopped
automatically if nobody acts on it within the configured idle window).

## New: `POST /api/runs/{run_id}/resume`

Continues a run that is **resumable but not paused** (cut off mid-step, nothing awaiting a decision). No request
body.

**200** `RunDetail`, the same shape `GET /api/runs/{id}` returns, once this request's own action is done — the run
reaching its next pause (if its own `ask_before_each_turn` is true), a finish, or a further interruption.

**404** `not_found` — no run with this id.

**409**, checked in this order:

| `code` | When | `message` |
|--------|------|-----------|
| `run_executing` | the run's execution lease is currently held (another request is driving it right now) | `"This run is currently executing."` |
| `not_resumable` | `status == "finished"` | `"This run has already finished."` |
| `not_resumable` | `mode != "adaptive"`, or `is_checkpointed` is false (never claimed through the live path) | `"This run cannot be resumed."` |
| `not_resumable` | `in_progress`, `is_checkpointed`, no loadable checkpoint, or its version stamp does not match this build | `"This run cannot be resumed."` |
| `paused` | `in_progress`, a loadable checkpoint **with** a pending decision | `"This run is paused awaiting a decision; decide it instead."` |
| `permission_missing` | the target's permission box is not confirmed | `"Tick the permission box and save the target before attacking it."` (same wording as `POST /api/runs`) |
| `terms_outdated` | the target's accepted terms are not current | `"The terms of service have changed; read them and tick the box again."` |
| `attacker_unavailable` | no attacker model is configured at all | `"No attacker model is configured, so an adaptive attack can't run."` (same wording as `POST /api/runs`) |
| `library_unavailable` | the attack library is not available | `"The attack library is not available."` (same wording as `POST /api/runs`) |
| `pinned_model_unavailable` | the run's own recorded attacker model, judge model, prompt version, or library seed can no longer be constructed | `"This run's own attacker or judge model (or its prompt version, or its own library seed) is no longer available; stop it instead."` |

A run whose graph already reached its own end (its checkpoint holds a decided outcome, but nothing had yet
finished the row with it) is **not** refused here with a 409: `/resume` reconciles it on the spot, the same way
the start-up sweep would, and returns **200** with the now-finished `RunDetail`.

The preconditions (`permission_missing` through `pinned_model_unavailable`) are checked only after the lease is
acquired and the run is confirmed resumable (and not already reconciled away above), before anything is sent, and
**in the table's own row order** — so a run whose current settings have no attacker model configured at all
answers `attacker_unavailable`, never `pinned_model_unavailable`, even on a run whose own pinned client would
*also* fail for a different reason (a missing API key): the first check in the order that applies is the one that
answers, and `attacker_unavailable`'s own check always runs first.

## New: `POST /api/runs/{run_id}/decision`

Decides a run that is currently **paused**, for the exact pending turn it names. Request body:

```json
{"turn": 2, "decision": "approve"}
```

`decision` is one of `"approve"`, `"run_to_end"`, `"stop"` — a `422` form error for anything else. `turn` is
required — a request with no `turn` field is a `422` form error, never defaulted to "whichever is pending".

**200** `RunDetail`, once this request's own action is done.

**404** `not_found` — no run with this id.

**409**:

| `code` | When | `message` |
|--------|------|-----------|
| `run_executing` | the lease is held | `"This run is currently executing."` |
| `not_paused` | the run is not currently paused at all (finished, merely resumable, or never paused) | `"This run has no pending turn to decide."` |
| `not_paused` | the run **is** paused, but its pending turn does not match the request's own `turn` | `"This run's pending turn has already moved on."` |
| `permission_missing` / `terms_outdated` / `attacker_unavailable` / `library_unavailable` / `pinned_model_unavailable` | for `"approve"`/`"run_to_end"` only — the same checks and wording `/resume` uses; **not** checked for `"stop"`, which never sends |

The turn-mismatch check is what makes a decision single-use: once a turn is decided, the run's pending turn (if
any) is a different one, so a second, late request naming the original turn is refused here, sending nothing — a
bare, un-validated resume value would otherwise resolve silently against whatever is pending next instead.

## New: `POST /api/runs/{run_id}/stop`

Ends **any** `in_progress`, `is_checkpointed`, unleased run — paused, merely resumable, already at its own decided
outcome, or sitting with no usable checkpoint at all — without resuming its graph at all. No request body.

**200** `RunDetail`. Three distinct outcomes, depending on what the run's own persisted progress already holds:

- **The common case** — the run was genuinely cut off, with no outcome of its own yet: `status: "finished"`,
  `stopping_condition: "stopped_by_user"`, `verdict` taken from the last turn this run's own judge actually
  reached a verdict on (`unclear` if none did), with its turn and token counts exactly as the run's own persisted
  progress already shows them, and that judge's own pinned `judge_model`/`judge_prompt_id`/`judge_prompt_version`
  preserved (never left null) whenever a judge was actually used.
- **The reconciled case** — the run's own graph had already reached its own end, or its deterministic checks or
  judge had already decided an outcome for a turn not yet durably recorded (that turn is recorded now, through the
  same idempotent write a normal `record` step would have made, before the row is finished): the row is finished
  with **that already-decided outcome**, never `stopped_by_user`, its own judge provenance preserved the same way.
  This is the same reconciliation `/resume` and the start-up sweep perform for the identical shape; Stop never
  answers a 409 for it.
- **No usable checkpoint at all** (missing or unreadable) — Stop closes the row **exactly** the way the start-up
  sweep closes this shape, not merely similarly: `stopping_condition: "stopped_by_user"` is not used here, since
  nothing of this run's own progress survived to attribute a user action to; it closes `unclear`,
  `stopping_condition: "interrupted"`, with the identical reason text the sweep's own close uses for it, and —
  unlike the two outcomes above — attempts **no write-back** (`memory_written` stays `false`), since nothing of
  this run's own progress survived to write back either. Never a 409 — Stop needs no checkpoint to do this.

**404** `not_found`.

**409**:

| `code` | When | `message` |
|--------|------|-----------|
| `run_executing` | the lease is held | `"This run is currently executing."` |
| `not_resumable` | the run is not `in_progress`/`is_checkpointed` at all (already finished some other way, never claimed through the live path, or its version stamp does not match this build) | `"This run cannot be stopped."` |

No permission/terms/attacker/model precondition applies — Stop never sends anything, so none of them can block it.
An incompatible-version checkpoint is the one shape Stop still 409s on: it cannot arise without a restart between
builds, which the sweep always resolves before any request could ever reach this endpoint for it.

## Changed: `GET /api/runs/{run_id}` and the run-list summary

Both endpoints are now `async def` (to await classification). `RunSummary`/`RunDetail` gain fields, computed live
by classification (never a stored flag):

```json
{"ask_before_each_turn": true, "resumable": true, "paused": true, "run_state": "resumable",
 "idle_stop_at": "2026-11-26T10:15:00Z",
 "pending_turn": {"turn": 2, "interrupt_id": "...", "message": "..."}}
```

`idle_stop_at` (FR-061) is present whenever `run_state` is `"paused"`, `"resumable"`, or `"stoppable"`, `null`
otherwise — the **earliest** time the automatic idle-stop check (below) may stop this run, never a promise of
exactly when: the actual stop happens at the first check that finds the run still idle at or after it, up to one
check interval later. It is itself grace-aware (FR-059): whichever is **later** of `last_activity_at` plus the
configured window, and the process's own start time plus the restart grace period — never a time already in the
past while that grace period is still running.

`resumable` and `paused` are both `false`, and `pending_turn` is `null`, for: every run this feature does not apply
to (single-turn, replay, an experiment repetition); any finished run; and a run whose execution lease is currently
held (it reads as plainly executing, not resumable and not paused, while a request is actively driving it) — all
four fields are always present, never omitted. A run whose graph reached its own end but was never finished, and a
run whose checkpoint is missing or unreadable, both read `resumable: false` too — identically to a leased run, and
to a run this feature does not apply to at all, three shapes `resumable`/`paused` alone cannot tell apart.

**`run_state` (FR-054) is the one field that can, and is what the UI MUST derive its controls from, never
`resumable`/`paused` reconstructed into a guess**: `"running"` (the lease is held — no control, matching FR-014);
`"paused"` (a pending decision — the three approve-node controls); `"stoppable"` (the graph already reached its
own end, or the checkpoint is missing or unreadable — **Stop** alone, never "Resume," so a user always has a way
to close these without waiting for a restart); `"resumable"` (merely cut off mid-step — **Resume** and **Stop**);
`"finished"` (the row is done; no control). `resumable`/`paused` are still computed and still present, for any
existing reader that already depends on them, but they are not what distinguishes `"running"` from `"stoppable"` —
both read `resumable: false, paused: false` identically, and only `run_state` tells them apart.

## The start-up sweep (changed)

Moved into `lifespan`, after the saver is attached and the version guard passes, before the app begins serving
requests. For each `in_progress` row:

- `mode != "adaptive"`, or `is_checkpointed` is false: closed exactly as today (`unclear`,
  `stopping_condition = "interrupted"`) — no checkpoint read attempted, and **no new kept log line** for it (the
  `run.interrupted` line below is written only for a row this sweep actually classifies through the checkpointer).
- `is_checkpointed`, no loadable checkpoint, an unreadable one, or a version-stamp mismatch: closed exactly as
  today, with `"incompatible checkpoint version"` as the distinct reason in the mismatch case — and, for each of
  these three, one `run.interrupted` line (`resumable: false`) written into that run's own kept log.
- `is_checkpointed`, a loadable checkpoint whose graph already reached its own end: reconciled — finished using the
  checkpoint's own recorded outcome — and its checkpoint deleted; one `run.interrupted` line (`resumable: false`)
  written into its kept log.
- `is_checkpointed`, a loadable checkpoint still mid-run (resumable or paused): left `in_progress`, untouched; one
  `run.interrupted` line (`resumable: true`) written into its kept log.

A checkpoint whose own `runs` row is not `in_progress` at all (an orphan left by a delete that did not complete) is
also deleted during this same pass, with no `run.interrupted` line (it belongs to a row already finished, not one
the sweep is classifying).

The existing start-up log line keeps its meaning (how many rows were closed outright); `run.interrupted` is the
new, per-row, kept line described above (see `contracts/log-records-delta.md`).

The sweep itself runs **no** idle-stop check of its own (FR-058) — there is nothing left for one to find, since
every reached-end, no-checkpoint, and unreadable row it would itself reconcile or close is already handled by its
own classification above, before any idle check could run, and a genuinely resumable/paused row's own wall-clock
idle time (research D26) does not depend on whether the process just started. The periodic check below is the
only idle-stop mechanism; its own first tick after the restart grace period is what catches a run that became
overdue while the process was down.

## New: the periodic idle-stop check (no endpoint — an internal, unscoped background task)

Started in `lifespan` after the start-up sweep completes, running for as long as the app stays up, cancelled
**and awaited** at teardown before tracing shuts down: every few minutes (a small, non-configurable interval,
short against the configured idle window), it first checks a **restart grace period** — if less than
`min(1 hour, the configured window)` has elapsed since the process itself started, the whole tick is a no-op,
deliberately, so a run already idle past the window when Kestrel restarts is not stopped the instant the new
process comes up for time that elapsed while it was down. Past that, for every row whose classification reads
`"paused"`, `"resumable"`, or `"stoppable"`, idle at least the configured window (measured fresh, re-read and
re-classified under that row's own lease, never trusted from the tick's own initial listing): it is stopped
through the identical mechanism `POST /api/runs/{run_id}/stop` uses (below), never a 409 for it, since nothing is
asking. It calls no endpoint and answers no request. Before ever attempting a row's own lease, a cheap, unlocked
check against that row's own last-known `last_activity_at` skips anything not yet due — a live request against
that same row is therefore never refused by a check that was never going to stop it anyway; a row currently leased
by another request is skipped at that check and reconsidered at the next one, never waited for. A failure stopping
one particular row (a catalogued `ERROR` line, never its own exception text) never stops the check from
considering every other row at that same tick; a failure outside any single row's own handling — the listing call
itself, for instance — is isolated the same way, one level up, so that tick alone stops nothing but the background
task itself still runs again at the next interval.

## Changed: `POST /api/runs/{run_id}/stop` (automatic trigger, FR-058 to FR-060)

The automatic idle-stop check reaches the identical `stop_run` mechanism this endpoint's own handler calls, with
one internal difference only: `triggered_by="idle_timeout"` instead of the default `"user"`. Every response field
this contract already documents for `POST /api/runs/{run_id}/stop` is identical either way **for the identical
persisted shape** — the response names exactly what that shape's own manual branch would have recorded:
- the **ordinary** shape's own stored `reason` reads `"Kestrel stopped this run automatically after {hours} hours
  with nobody acting on it."` instead of naming a user action — `stopping_condition` stays `"stopped_by_user"`
  either way;
- the **reconciled** shape (the graph already reached its own end, or a turn's outcome was already decided) keeps
  its own decided `stopping_condition` and reason completely unchanged — never `stopped_by_user`, manually or
  automatically;
- the **no-checkpoint-or-unreadable** shape keeps `stopping_condition: "interrupted"` and the sweep's own exact
  reason text (FR-056), unchanged.

In every one of the three shapes, the `run.stopped` log line gains `trigger`/`idle_hours`
(`contracts/log-records-delta.md`) — the one place an automatic stop is actually named as such, regardless of
which shape's own fields it otherwise produced.

## Changed: `GET /api/config`

Gains a new `resume` group: `{"idle_hours": 24.0}` (the configured `KESTREL_RESUME_IDLE_HOURS`) — its own group,
never folded into the existing `adaptive` one, which `tests/integration/test_api_config_adaptive.py` already
asserts as an exact, closed object (`{"max_turns", "token_budget", "time_limit_s"}`) that a new key would break.

## Changed: `GET /api/targets` and `GET`/`POST`/`PUT` target-detail (FR-062)

`GET /api/targets` becomes `async def`. Each `TargetSummary` gains `needs_attention` (bool), computed the same
live way `idle_stop_at` is: `true` when that target's one possible `in_progress` run (`uq_runs_active` already
caps it at one) currently classifies `"paused"`, `"resumable"`, or `"stoppable"`; `false` when it has none, or
that run is currently leased. This is the one field the target selector's own cue (FR-061) is built from — the UI
reads it directly, never deriving it from a separate per-target call or by guessing from any other field this
endpoint already returns. `TargetDetail` (which extends `TargetSummary`) carries this identical, identically
computed field on every response that returns one (`GET /api/targets/{id}`, and the `POST`/`PUT` target-save
endpoints' own response body) — the list and a single target's own detail can never disagree about it.
