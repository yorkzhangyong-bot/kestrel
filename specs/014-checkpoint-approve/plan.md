# Implementation Plan: LangGraph Checkpointer and Approve Node (014)

**Branch**: `014-checkpoint-approve` | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/014-checkpoint-approve/spec.md`

## Summary

Builds on #49 (typed `_State`/`_ReplayState`, reducers, and `LIVE_GRAPH`/`REPLAY_GRAPH` compiled once at import
with per-run values travelling as frozen runtime context) to close the rest of the "LangGraph idioms" roadmap item
in two parts, shipped as two pull requests after this spec merges.

**Part 1, the checkpointer**: each app builds its own checkpointed **copy** of `LIVE_GRAPH`
(`LIVE_GRAPH.copy(update={"checkpointer": saver})`, kept on `app.state`) — the module-level graph itself is never
mutated, which is also what keeps the experiment harness (which keeps calling bare `LIVE_GRAPH` directly, needing
no `thread_id` and no checkpointer) and the test suite's own isolation intact. The saver is a `BaseCheckpointSaver`
subclass over `TargetStore`'s own `sqlite3` connection, `asyncio.to_thread`-wrapped, constructed with its own
explicit serializer (`JsonPlusSerializer(allowed_msgpack_modules=[...three Kestrel types...])`) so the three
dataclasses a checkpoint may carry round-trip as themselves, with no warning, under the serializer's default mode
and its strict mode alike — no new dependency. Every invocation of a checkpointed graph requests **synchronous
durability**, the only mode under which a crash cannot leave the durable checkpoint more than one in-flight step
behind the side effects already caused; the `record` step's two writes (a turn row, its evidence) are made one
atomic write, guarded by an existence check, so re-executing it after an interruption can never duplicate either.
Which `in_progress` row is even eligible for any of this is decided at **claim time**, by a new `runs.is_checkpointed`
column the live run-start path alone sets. The start-up sweep moves into the API's `lifespan`, after the saver is
attached and a narrow, loudly-enforced version guard passes, and now **classifies** each row into one of several
distinct outcomes — including correctly telling apart a thread whose graph genuinely reached its own end from one
merely cut off mid-commit, two shapes that otherwise look identical. Because starting, resuming, deciding, and
stopping a run are all separate requests against one shared, in-process run id, a non-blocking **execution lease**
— taken immediately once a run exists, whichever request that is — makes "two requests driving the same run's graph
at once" and "a decision landing on the wrong turn" both structurally impossible. **Stop** — the documented way out
of *any* resumable run, paused or not — never resumes the graph at all, and reconciles an already-decided outcome
rather than overwriting one; it records the verdict of the run's own last durably judged turn, and its turn/token
counts from the run's own persisted progress. Every run writes back exactly once, wherever it actually finishes,
through one shared finishing function every path calls. A resumed live run's evidence checker is rebuilt from its
own stored token directly — distinctly from both a fresh claim (which would mint a new token) and a replay (which
never regenerates text) — so a resumed run's planted task text is still stripped from the shared pattern pool
exactly as an uninterrupted run's is, and the target echoing Kestrel's own in-flight message is never mistaken for
the target's own evidence. An interruption of a checkpointed run — a process death or an unhandled in-process
error alike — leaves it resumable immediately, with no new handler of its own: the absence of one, plus the
lease's own release, is what makes this true, and is exactly why a recurring failure's documented way out is Stop,
not an automatic retry.

**Part 2, the approve node**: one new, cheap node, added to the live graph's one topology when this part ships,
calls `interrupt()` when a run's own `ask_before_each_turn` state field is set and the turn is its second or later;
that field is seeded into the run's state exactly once, at claim, and never re-read from the stored column on a
resume. A decision names the exact pending turn (and the interrupt id LangGraph itself already tracks) it answers;
a request whose own named turn does not match the run's actual pending one is refused, sending nothing. The time
limit excludes both kinds of gap (an interruption's downtime, a pause's wait) by persisting the real wall-clock
time spent executing, recomputed fresh by every node's own returned delta from a fixed starting point, never
accumulated piecemeal within one invocation.

**Write-back's own scope**: `run_adaptive` keeps finishing its own row directly, through the same call it makes
today, for every caller (the live API path and the experiment harness alike), and returns the finished run. The
*extra* finishing function — write-back, checkpoint deletion, lease release, on top of a row already finished —
is called only from the API-driven live path (the original start reading that finished run back from
`run_adaptive`, a resume, a decision, a stop, and the sweep's own reconciliation), never from inside `run_adaptive`
itself, which the experiment harness also calls directly for a cold arm that must never write back (007) and
which a replay never touches at all (012); an exception exit leaves a run `in_progress` (FR-042) and never reaches
either function.

Approach and rationale: [research.md](research.md); shapes: [data-model.md](data-model.md) and
[contracts/](contracts/); validation: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, LangGraph (existing, `1.2.17` installed), httpx, SQLite (stdlib
`sqlite3`), ChromaDB, markdown-it-py — unchanged. **No new dependency** (Principle X, satisfied rather than
invoked): `langgraph-checkpoint` (`4.3.0` installed) is already present as a transitive dependency of `langgraph`
itself; this feature's own checkpoint saver is a plain subclass of its `BaseCheckpointSaver`, constructed with its
own explicit serializer rather than relying on any after-the-fact allowlist call (research D9). The owner's own
decision (Clarifications) rejected the alternative that *would* have been a new dependency —
`langgraph-checkpoint-sqlite` (`3.1.3`, verified to require `aiosqlite>=0.20`, `sqlite-vec>=0.1.6`, and a
`langgraph-checkpoint` bump to `>=4.3.1`) — in favour of this one, with three conditions carried as FR-035 to
FR-037: tests covering pending-writes replay (including the replace/ignore distinction a control write and a
regular write each need), a real interrupt/resume through the compiled graph, and one declared, loudly-enforced
version range — narrowed to exactly what is tested (`langgraph-checkpoint >=4.3.0,<4.4.0`, `langgraph
>=1.2.17,<1.3`, not the wide range `langgraph` itself merely requires, which every 4.x release would already
satisfy and so could never fail loudly) and verified to agree between `pyproject.toml` and the saver's own
constants by a `tomllib`-based test, parsing a version as two or three dotted components (the declared upper bound
`<1.3` itself has only two).

**Storage**: One store (`kestrel.db`) — no second file, no second migration story. Additive only: five columns on
`runs` (`ask_before_each_turn`; `is_checkpointed`, the claim-time flag that is the one and only classification
input the sweep needs; `attacker_prompt_id`/`attacker_prompt_version`, new columns that pin a resumed run's
attacker-prompt provenance — `judge_model`/`judge_prompt_id`/`judge_prompt_version` already exist as columns and
simply gain a claim-time write path alongside their existing finish-time one; `last_activity_at`, this run's own
idle clock, touched only on an accepted lease release, research D26), one unique index
(`uq_run_turns_position`, created inside the migration itself, after a check that refuses to start loudly if an
existing database already holds a duplicate `(run_id, position)` pair — never in the database's initial schema
script, which runs unconditionally before that check could ever see a duplicate), and two new tables for the custom
saver itself (`checkpoints`, `checkpoint_writes`, the latter carrying a `task_path` column) — **no rebuild**:
nothing here changes a `CHECK` constraint or a column's identity. All five new `runs` columns are added to
`RUNS_COLUMNS_SQL` itself, not only a later `ALTER`, so a fresh database and every future migration agree with what
an `ALTER` produces on an existing one. A run's own turn row and its evidence items are now written in one atomic
transaction, closing a gap where an interruption between two separate writes could leave a turn with no evidence,
silently lost on resume. The saver reads and writes its two tables only through `TargetStore`'s own `connect()`,
`asyncio.to_thread`-wrapped — never a second connection or a second file for anything this feature adds. Every
checkpoint's own metadata carries a small graph/state version stamp, written by the saver's own `aput` (not routed
through anything LangGraph itself needs to see); a mismatch is incompatible, closed with its own distinct reason,
never resumed against incompatible node topology — the version constant moves from `1` to `2` exactly when part 2
adds the `approve` node to the live graph's topology, so part 1's own checkpoints and part 2's are never confused
for each other.

**Testing**: pytest; unit + integration offline, over a `tmp_path` database that already carries the new tables and
columns. Simulating an interruption without actually killing the test process: start a checkpointed invocation
(always synchronous durability) against the real custom saver over that `tmp_path` store, have a monkeypatched node
raise an ordinary exception after N turns (or let a real interrupt simply not be resumed yet), assert the row is
still `in_progress` with a loadable checkpoint, then **construct an entirely fresh `_LiveDeps`** (never reusing the
first attempt's deps object, so the test cannot pass vacuously) and resume through the real, production live-graph
copy — never `InMemorySaver`, satisfying the owner's second condition directly rather than only through a
saver-isolated test. The saver's own contract tests include: a regular write recorded but never followed by a
completed checkpoint is ignored if a duplicate already exists and otherwise correctly replayed; a second control
write (an interrupt/resume-shaped one) replaces the first, never duplicating it; both serializer modes round-trip
the three registered types with no warning (the strict mode itself read once at import, so a test that needs it
either runs in a subprocess or constructs the equivalent explicit serializer directly); a `tomllib` read of
`pyproject.toml` matches the saver's own version-range constants exactly; and a monkeypatched installed-version
check outside either declared range fails the start-up guard loudly. The execution-lease and turn-specific-decision
tests drive two concurrent requests against one running event loop and assert exactly one succeeds in each shape:
resuming or deciding a currently leased run; two concurrent resumes for one run; two concurrent decisions for one
pending turn; a decision whose own named turn has already moved on. Tests first (Principle VII); every test carries
`014/FR-###`/`014/SC-###` or a module-level `FEATURE = "014"`.

**Pre-existing tests this feature may edit, and why** (`_LiveDeps`/`_initial_state` are kept backward compatible by
giving every new field a default, research D23, so no *other* pre-existing test needs touching for that reason; the
`run.end` suppression (research D21) reads fields bound to the scope itself, never the store, so
`tests/unit/test_events.py` and `tests/unit/test_run_log_handler.py` — whose own `FakeStore` implements only
`add_log_line` — are both unaffected and need no edit either):

| Test | Why it must change |
|------|---------------------|
| `tests/integration/test_provenance_migration.py` | pins "the current schema version" as a literal string (the same class of edit every prior schema bump in this project has already made to its own predecessors) |
| `tests/unit/test_store_migration_v9.py` | same - found during implementation (not in the original plan): this file already pinned the literal from feature 013's own bump (`"11"`, with a stale comment trailing two bumps behind), so 014's own bump breaks it exactly the same mechanical way it breaks v10/v11's |
| `tests/unit/test_store_migration_v10.py` | same |
| `tests/unit/test_store_migration_v11.py` | same, plus one assertion on the ALTER'd `runs` table's own trailing column text (`"side_channel_status TEXT"` -> `"last_activity_at TEXT"`, the new last column v12's own ALTER loop appends) - the identical class of edit, not a new one: the literal it pins is "the last column the current schema version's own ALTER chain adds," which shifts for the same reason the version number itself does |
| `tests/unit/test_store_migration_v5.py` | same literal pin (found during implementation, the same class as v9/v10/v11) |
| `tests/unit/test_store_migration_v6.py` | same |
| `tests/unit/test_store_migration_v8.py` | same |
| `tests/integration/test_startup_events.py` | the "closed interrupted run(s)" count moved into `lifespan` (research D14), so the app must actually be entered (the test client's own context) for the sweep to run at all - a bare `create_app(...)` never swept anything |
| `tests/unit/test_optional_extra.py` | the fixed stack gains `langgraph-checkpoint`, which was already installed transitively and is now named explicitly to pin the range (FR-037) - never a new dependency (Principle X) |
| `tests/unit/test_adaptive_graph_state.py` | its `StubStore` implements only the two store calls a live-graph `record` node made before this feature (`add_turn`, `add_evidence`); the lifted `record` step's new `has_turn`/`add_turn_with_evidence` calls need both added to it, or its own `store.turns == [1, 2, 3]`-style assertions break — a stub gaining the store methods its own code under test now calls, never a behaviour change to what the test itself asserts |

The User Story 4 / FR-032 regression gate is: the full offline suite's pass/fail set is identical before and after
this feature, **except** for exactly these ten, each edited only for its own stated, mechanical reason (SC-003).
There is no production-code fallback for a store that lacks `has_turn`/`add_turn_with_evidence` — every real store
gains both in the same schema bump (T006), so the `record` step is written against them unconditionally.

Part 2's own topology change adds one more class, also mechanical: the `approve` node inserts one extra checkpoint
write per turn, so the fault-injection `fail_at` numbers in part 1's own test files
(`tests/unit/test_start_up_sweep_classification.py`'s put-number table, `test_checkpoint_gc.py`,
`test_idle_auto_stop.py`, `test_kept_log_continuity.py`, `test_live_checker_rebuild.py`,
`test_owasp_excludes_in_progress.py`, `test_resume_adaptive_run.py`, `test_resume_api.py`,
`test_resume_pinned_caps.py`, `test_stop_endpoint.py`, `test_write_back_once.py`) each shift by +1, and
`_STATIC_NEXT_STEP` gains the one plain edge the node adds (`"approve": "send"`, research D4) — the same
empirically-verified put-numbering technique T017 established, never a behaviour change to what any of those
tests asserts (FR-032's own part-2 half, SC-003).

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell), unchanged.

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API, unchanged. No new top-level
package.

**Performance Goals**: a checkpoint write happens once per completed graph step (roughly one per node, so ~7 per
turn once the `approve` node is added, up from #49's ~6), each awaited (synchronous durability) before the next
step starts — a local SQLite write, the same order of cost `store.py`'s own per-turn writes already are; no new
network call. Starting, resuming, deciding, and stopping a run all stay synchronous (FR-025) — no new background
task, no polling endpoint.

**Constraints**: no secret may ever reach a checkpoint, the run log, or an event line this feature adds (FR-033,
Principle IV) — the checkpointed state carries only the conversation/counters #49 already established, never the
runtime context that holds the secrets; no attack-prompt text in this feature's own code, tests, fixtures, or
commits (FR-034); resumability and the approve node must not alter a single-turn run's, a replay's, or an
experiment repetition's behaviour in any observable way (FR-032); a run's own turn/token/time caps and its recorded
attacker/judge model and prompt provenance stay pinned to what they were at claim time across any resume or
decision, never silently re-read from whatever Kestrel is currently configured with (FR-047).

**Scale/Scope**: single user, as the whole project is; one checkpoint thread per live, checkpointed adaptive run,
deleted once that run finishes by any path, or reconciled away if ever found orphaned (FR-006, FR-045) — no
accumulation across runs.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — no violation; Principle X's new dependency
question is satisfied outright (no new dependency), not invoked for a justified exception; no Complexity Tracking
entry needed.*

| Principle | Assessment |
|-----------|------------|
| I — security not quality | A checkpointer, an execution lease, and a pause control are reliability/workflow additions to the existing security loop; none introduces a quality metric. ✓ |
| II — hard evidence over opinion | Untouched, and actively protected: a resumed run's checker is rebuilt from its own stored token, distinctly from a fresh claim and from a replay, so its own in-flight message is never mistaken for the target's own evidence (research D17). The deterministic checker and the judge are still called in exactly the same fixed order on a resumed or decided turn as on a live one. ✓ |
| III — report states attacker model | Strengthened: a resumed or decided run now keeps using its own recorded attacker and judge models and prompt references (pinned, research D16), so the report can never state a model that is not actually the one that produced a given turn. ✓ |
| IV — secrets never leave the vault | Preserved by construction: the checkpointed state is exactly #49's existing conversation/counters, which already excludes every secret; the runtime context (which holds them) is never part of what a checkpointer persists, confirmed directly against the installed checkpoint shape. The configuration passed to look up a checkpoint carries nothing but the thread id (FR-004). ✓ |
| V — learn from every run | Strengthened: write-back is now a property of the one shared function every finishing path calls (research D19), including the sweep's own reconciliation of a thread that reached its own end and a decision reaching a stopping point — not left to each call site to remember on its own; a pause explicitly writes back 0 times. ✓ |
| VI — OWASP-mapped, fix-ready | Strengthened: the report now excludes every `in_progress` run (paused, resumable, or merely executing), the same way it already excludes a replay (research D25). ✓ |
| VII — tests first, thin slices, one e2e | TDD per story; vertical slice store (five columns, one index, two tables) → saver → graph (the per-app copy, the `approve` node, the lease, Stop) → API (resume/decision/stop endpoints, the async sweep) → UI. One e2e attempted against the HS-code target; currently blocked by an OpenRouter guardrail change unrelated to this feature (CLAUDE.md gotcha, first recorded 2026-11-21, recurred 2026-11-24) — not a failure of this feature; part 1's own automated scenario is an offline, in-process one (two `create_app` instances, one database), since a browser test cannot restart Kestrel (FR-030, SC-010). ✓ |
| VIII — only attack owned, hard caps | A resumable or paused run keeps its target locked for the entire gap, by the same mechanism that already enforces one active run per target (FR-015) — Stop (FR-040) is what releases it when nobody intends to continue. The turn/token/time caps are pinned at resume (FR-047), never loosened; the time limit's own accounting is corrected, not relaxed, to exclude only genuine downtime (FR-016, research D24). An execution lease additionally guarantees a run is never driven by two requests at once (FR-038). ✓ |
| IX — simple for a vibe coder | Two new button pairs ("Resume"/"Stop"; "Approve"/"Run to end"/"Stop"), both driven entirely by fields the API already computes — no new settings screen beyond the one existing-style environment variable (`KESTREL_RESUME_IDLE_HOURS`), no checkpoint-backend chooser in the UI (Out of Scope). An unanswered pause has no *invented, pause-specific* timeout; it shares the one deployment-wide idle window every stuck run already does (FR-058), which exists so a single user is never left permanently locked out of a target by a run nobody can act on; Stop is the one, always-available *manual* way out of *any* resumable run, paused or not (FR-040). ✓ |
| X — stack fixed; new dep needs justification | **No new dependency**, justified above and in `spec.md`'s Clarifications: a custom saver constructed with its own explicit serializer, reusing `langgraph-checkpoint`'s own serializer class, already installed transitively. Its own tables live inside `store.py`'s own schema; its own tested version range is pinned in one constant, checked against `pyproject.toml` by a test (FR-037). ✓ |

## Complexity Tracking

*No entries.* This feature adds no new dependency and bends no other principle.

## Project Structure

### Documentation (this feature)

```text
specs/014-checkpoint-approve/
├── plan.md              # this file
├── research.md          # Phase 0 — verified facts and decisions
├── data-model.md        # Phase 1 — the one store, the saver, the lease, the approve node, Stop, write-back-once,
│                         #   the live checker rebuild, the version stamp, classification
├── contracts/            # Phase 1 — api.md (resume/decision/stop endpoints, the lease, preconditions, the async
│                         #   sweep), log-records-delta.md (kept-log continuity, run.end, the new events)
├── quickstart.md        # Phase 1 — per-part manual validation, the automated SC-010 scenarios explained
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 — /speckit-tasks, split into part 1 and part 2
```

### Source code (files this feature touches)

```text
src/kestrel/
├── attack/graph.py                # PART 1: a module-level CURRENT_GRAPH_VERSION constant (1); the lifted, shared
│                                  #   `record` step calls the new atomic store method and its existence check
│                                  #   (research D6); every node sets `time_spent_s` fresh in its own returned
│                                  #   delta, `attacker` also sets `turn_time_spent_at_start`/`turn_attacker_usage`
│                                  #   (research D24); every
│                                  #   durability-aware call site passes synchronous durability (never on the bare,
│                                  #   checkpointer-free graph the experiment harness calls); `run_adaptive` takes
│                                  #   the lease immediately after `claim_run`, before its first invocation
│                                  #   (research D12); keeps calling `finish_run` directly and returns the
│                                  #   finished run to its own caller, exactly as today — it never calls the
│                                  #   shared *finishing function* itself, since the experiment harness calls this
│                                  #   same `run_adaptive` too, for a cold arm that must never write back; only
│                                  #   `api/main.py::start_run` (the live API path) calls the finishing function,
│                                  #   adding write-back/checkpoint-delete/lease-release on top of the already-
│                                  #   finished run `run_adaptive` returns to it, never a second `finish_run`
│                                  #   call (FR-055); `_State`
│                                  #   gains `time_spent_s` (plain field, read/set directly — it has no meaning
│                                  #   before this feature, so no default-read concern applies to it the way it
│                                  #   does to `ask_before_each_turn`)
│                                  #   PART 2: bumps CURRENT_GRAPH_VERSION to 2; wires the new `_approve_node` (no
│                                  #   "stop" branch — research D7) into the one topology, `attacker → approve →
│                                  #   send`; `_State` gains `ask_before_each_turn` (plain field, read everywhere
│                                  #   via `.get(key, default)`, research D18/D23); `_LiveDeps` gains
│                                  #   `ask_before_each_turn: bool = False` (defaulted, research D23)
├── checkpointing.py                # NEW — `KestrelCheckpointSaver(BaseCheckpointSaver)`: the five async methods,
│                                  #   asyncio.to_thread-wrapped over TargetStore.connect(); constructed with its
│                                  #   own explicit serializer (research D9); the version stamp written by `aput`
│                                  #   (research D18); `aput_writes`'s replace/ignore rule + task_path (research
│                                  #   D10); `SUPPORTED_LANGGRAPH_CHECKPOINT`/`SUPPORTED_LANGGRAPH` constants and
│                                  #   `check_supported_versions()`; `thread_config`, `classify` (research D13), the
│                                  #   per-app execution-lease helper (research D12), whose own release now also
│                                  #   calls `store.touch_last_activity(run_id)`, but only when `mark_active()` was
│                                  #   called inside the `with` block — never on a refused exit (research D26)
├── store.py                        # additive schema bump (RUNS_COLUMNS_SQL itself, not only ALTER); the
│                                  #   duplicate-(run_id,position) check inside _migrate, before the new index;
│                                  #   runs.ask_before_each_turn/is_checkpointed/attacker_prompt_id/
│                                  #   attacker_prompt_version/last_activity_at (research D26); claim_run(...)
│                                  #   gains these plus optional judge_model/judge_prompt_id/judge_prompt_version
│                                  #   keywords, and rejects ask_before_each_turn=True for a non-adaptive mode; also
│                                  #   gains an explicit now= keyword (default the real wall clock), passed
│                                  #   app.state.clock() by the live run-start path so last_activity_at agrees with
│                                  #   whatever clock a test substitutes; has_turn/add_turn_with_evidence
│                                  #   (research D6); touch_last_activity (D26); delete_checkpoint; the start-up
│                                  #   sweep's own classification query (is_checkpointed rows only, no idle-stop
│                                  #   check of its own, research D27)
├── runs.py                        # execute_adaptive_run gains ask_before_each_turn/is_checkpointed/provenance-pin
│                                  #   passthrough; new execute_resume/execute_decision/stop_run (one name
│                                  #   throughout — never a second name for this one function), each funnelling
│                                  #   through one shared finishing function (write-back once, checkpoint delete, lease
│                                  #   release, research D19); stop_run gains
│                                  #   triggered_by: Literal["user", "idle_timeout"] = "user" but takes no lease and
│                                  #   opens no scope of its own — both owned by whichever of its three callers
│                                  #   reaches it (the /stop handler, the decision handler's "stop" branch, or
│                                  #   check_idle_runs, research D29); new check_idle_runs (research D27), called
│                                  #   **only** by lifespan's own periodic task, never the start-up sweep — it takes
│                                  #   the lease and opens its own scope per row it actually stops, and never calls
│                                  #   mark_active (research D26)
├── settings.py                    # Settings.resume_idle_hours: float (default 24), a new, strictly-positive
│                                  #   parser distinct from the existing non_negative_float_or_off (research D28),
│                                  #   reported on GET /api/config
├── evidence/checker.py             # rebuild_live_checker (research D17): constructs the planted-override state
│                                  #   directly from the stored token and its recorded prompt version, looked up
│                                  #   against the run's own seed by its recorded prompt_id; note_sent gains
│                                  #   emit_disarm_event (default True)
├── events.py                        # CATALOGUE: run.start's ask_before_each_turn omitted when false; new
│                                  #   run.interrupted (kept, only for a checkpointed row, research D20),
│                                  #   run.resumed (+from_step), run.paused, run.decided, run.stopped (+trigger,
│                                  #   +idle_hours when automatic, research D29), idle_stop.check_failed (ERROR,
│                                  #   per-run with run_id and per-iteration with run_id omitted, research D27);
│                                  #   run.end withheld only for a
│                                  #   checkpointed, still-in_progress scope (research D21); whole-run accumulators
│                                  #   (cost, tokens, time, dropped-line count) persisted in checkpointed state for
│                                  #   a multi-segment run; RunLogHandler's seq continuation across a resume
├── api/schemas.py                 # RunRequest + ask_before_each_turn; RunSummary/RunDetail +
│                                  #   ask_before_each_turn/resumable/paused/run_state/idle_stop_at/pending_turn
│                                  #   (with interrupt_id, research D30); DecisionRequest {turn, decision};
│                                  #   TargetSummary + needs_attention (research D31, FR-062)
├── api/main.py                    # the lifespan: construct the saver, run the version guard, build each app's own
│                                  #   LIVE_GRAPH.copy(...), run the (now async, classifying) sweep (unchanged by
│                                  #   this addition — no idle-stop check of its own), capture app.state.started_at,
│                                  #   start a periodic background task calling check_idle_runs on an interval
│                                  #   (cancelled **and awaited** at teardown, guarded against both CancelledError
│                                  #   and any other exception, research D27), all before serving;
│                                  #   POST /api/runs/{id}/resume, /decision, /stop; GET /api/runs/{id} and the
│                                  #   run-list endpoint become async def; GET /api/config reports
│                                  #   resume_idle_hours as idle_hours in its own new resume group (never folded
│                                  #   into adaptive, which a pre-existing test asserts as an exact, closed shape);
│                                  #   target_report filters to
│                                  #   status == "finished" (research D25); GET /api/targets becomes async def too,
│                                  #   reporting needs_attention per target (research D31, FR-062)
└── experiments/engine.py          # UNCHANGED — keeps calling bare, checkpointer-free LIVE_GRAPH directly
                                   #   (research D2); never sets is_checkpointed or ask_before_each_turn
ui/
├── api_client.py                  # resume_run(run_id)/decide_run(run_id, turn, decision), run_attack's own 360s
│                                  #   timeout (both can drive a run all the way to completion); stop_run(run_id),
│                                  #   its own short timeout (it never drives a run further, only ends it)
└── app.py                        # the pending-turn display and its three (or two) controls, rendered on the run
                                   #   page ahead of any early-return branch, from run_state alone (FR-054), with
                                   #   idle_stop_at shown next to them whenever present; a leased ("running") run
                                   #   shows neither control pair; a target's own run list shows its one
                                   #   paused/resumable/stoppable run (if any) at the top of that list with its own
                                   #   idle_stop_at (research D30 — never a cross-target grouping, since at most one
                                   #   in_progress run exists per target); the target selector carries a small cue,
                                   #   read directly from GET /api/targets's own needs_attention field (research
                                   #   D31, FR-062), for a target whose run needs attention, so one on another
                                   #   target stays visible; the STOPPED label table gains "stopped_by_user"
docs/roadmap.md, CLAUDE.md, README.md   # part 1's docs task: rename "014 — Community prompt feed" to "015" in
                                   #   living documentation only — never a merged feature's own historical spec
                                   #   (FR-028); part 2's docs task: move "LangGraph idioms" to Done; a CLAUDE.md
                                   #   learned note per part
pyproject.toml                     # explicit dependency lines for langgraph-checkpoint and langgraph at the
                                   #   narrow, tested ranges the saver's own constants name (FR-037)
tests/                              # see tasks.md for the exact file list and task numbers each is written under
```

**Structure Decision**: the existing single package `src/kestrel/` + `ui/`, unchanged in shape. One new small module
(`checkpointing.py`), the same kind of thin seam `replay.py` already is beside `runs.py`/`attack/graph.py`. No new
top-level package, no new third-party package.

## Phase status

- Phase 0 (research): done — `research.md`, every decision verified directly against the installed LangGraph
  (`1.2.17`) and Kestrel's own source, never assumed.
- Phase 1 (design): done — `data-model.md`, `contracts/`, `quickstart.md`; Constitution Check re-evaluated after
  design: PASS. The schema change is additive only (no rebuild) — a direct consequence of reading
  resumability/pause status live from the checkpoint itself rather than mirroring it into a second, potentially
  stale column on `runs`, with the exceptions (`is_checkpointed`, the provenance pins) that genuinely must be
  claim-time facts, never derived.
- Phase 2 (tasks): `/speckit-tasks` → `tasks.md`, split into part 1 (checkpointer) and part 2 (approve node) per
  FR-027, each independently tested and mergeable.
