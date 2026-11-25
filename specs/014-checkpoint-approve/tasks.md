---

description: "Task list for feature 014 — LangGraph checkpointer and approve node"
---

# Tasks: LangGraph Checkpointer and Approve Node (014)

**Input**: Design documents from `specs/014-checkpoint-approve/` (plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md)

Every task below is written test-first (Principle VII): an implementation task always follows the test task that
must fail before it passes.

Every requirement is kept consistent with `spec.md`/`plan.md`/`research.md`/`data-model.md`/`contracts/`/
`quickstart.md`: every checkpointed call uses synchronous durability, never passed to the experiment harness's own
checkpointer-free call (T007/T008); the `record` step writes a turn and its evidence atomically, guarded by an
existence check (T005/T006); each app gets its own checkpointed copy of `LIVE_GRAPH`, never a mutated module-level
object (T009/T010); classification reads a claim-time `is_checkpointed` column, with distinct results for no
checkpoint, an unreadable one, an incompatible one, one whose graph already reached its own end, one merely
resumable, and one paused (T017/T018); the execution lease is taken by the original start immediately after claim,
and by resume, decision, and stop (T019/T020); Stop never resumes the graph, reconciling an already-decided outcome
when one exists instead of overwriting it with `stopped_by_user` (T021/T022); write-back happens exactly once, from
the one shared finishing function every path calls (T023/T024); a resumed live run's checker is rebuilt from its
own stored token directly, never through the live-claim path (which would mint a new one) or the replay path (which
never regenerates text) (T025/T026); time spent is recomputed fresh by every node's own returned delta from a fixed
anchor, never accumulated piecemeal (T011/T012); a resumed or decided run's attacker and judge models and prompt
references are pinned to what was recorded at claim (T033/T034).

**Tests**: REQUIRED — Principle VII. Every test carries `014/FR-###` / `014/SC-###` (or a module-level
`FEATURE = "014"`). Tests are written FIRST and must fail before the implementation task that satisfies them. Every
store in a test is a temporary one (`tmp_path`), never the repository's `data/kestrel.db`. **No attack-prompt text
anywhere** — neutral placeholder messages, replies and fixtures only (FR-034).

**Delivery**: two pull requests after this spec merges (FR-027). **Part 1** = Phases 1–6 (Setup, Foundational,
User Story 1, the part-1 half of User Story 4, Part-1 end-to-end, Part-1 Polish). **Part 2** = Phases 7–11 (its own
Foundational, User Story 2, User Story 3, the part-2 half of User Story 4, Part-2 Polish). The Delivery paragraph's
phase count matches the headings below exactly — six phases in part 1 (1 through 6), five in part 2 (7 through 11).
Part 1's own Polish phase renames the roadmap's planned "014" entry to "015" (FR-028, living documentation only,
never a merged feature's own spec files); part 2's own Polish phase moves "LangGraph idioms" to Done (FR-029) and
rewrites `traceability.md` for the whole feature, mirroring 013's own precedent for a part-1/part-2 feature.

## Phase 1: Setup (Part 1)

- [ ] T001 [P] Add explicit dependency lines to `pyproject.toml`: `langgraph-checkpoint>=4.3.0,<4.4.0` (already
      resolved transitively by `langgraph`, so `uv lock` changes no resolved version, only makes the dependency and
      its narrow, tested range explicit) and widen/pin the existing `langgraph` line to `>=1.2.17,<1.3` (the range
      this saver is actually tested against, narrower than today's bare `langgraph>=0.2`). Run `uv lock` and confirm
      the diff touches only these two packages' declared constraints, not their resolved versions (014/FR-037).

## Phase 2: Foundational (Blocking Prerequisites, Part 1)

**⚠️ Blocks every part-1 user story**: the schema, the saver (with its version guard and pending-writes contract),
the per-app graph copy, durability, the atomic record step, and time-spent accounting every later task needs.

- [ ] T002 [P] Unit test `tests/unit/test_store_migration_v12.py` (`FEATURE = "014"`, following the
      `test_store_migration_v<N>.py` convention): a hand-written prior-version database migrated via
      `TargetStore.__init__`/`_migrate` ends at the new schema version; all four new `runs` columns
      (`ask_before_each_turn`, `is_checkpointed`, `attacker_prompt_id`, `attacker_prompt_version`) exist in
      `RUNS_COLUMNS_SQL` itself (assert a **fresh** database's `CREATE TABLE` already has them, not only a migrated
      one), `NOT NULL DEFAULT 0` for the first two, nullable for the last two, every pre-existing row reading the
      defaults; `uq_run_turns_position` exists (created inside `_migrate`, after the duplicate-row check below —
      **not** in the database's initial schema script, which `TargetStore.__init__` runs unconditionally before
      `_migrate` ever gets a chance to check for a pre-existing duplicate) and a second `add_turn` at the same
      `(run_id, position)` (bypassing the store's own atomic-write guard, calling the raw SQL directly) raises
      `sqlite3.IntegrityError`; `checkpoints`/`checkpoint_writes` exist with their documented columns,
      `checkpoint_writes` including `task_path`; running `_migrate` a second time is a no-op. **The duplicate-row
      refusal**: seed a database whose `run_turns` already holds two rows at the same `(run_id, position)`
      (hand-written SQL, bypassing every application-level guard) and assert `_migrate` raises a clear, named error
      identifying the migration and the table, checked *before* the index is ever created, rather than a bare
      `sqlite3.IntegrityError` from the index itself or a silent partial migration (014/FR-003, FR-004).
- [ ] T003 [P] Unit test `tests/unit/test_state_ask_before_each_turn.py` (`FEATURE = "014"`): `claim_run(...,
      ask_before_each_turn=True, is_checkpointed=True, attacker_prompt_id="attacker:direct_injection",
      attacker_prompt_version="1", judge_model="j/m", judge_prompt_id="judge", judge_prompt_version="1")`
      round-trips through the matching `Run` fields; **the store itself rejects `ask_before_each_turn=True` for
      `mode != "adaptive"`**, raising a clear `ValueError` the API layer turns into its own `422`; a single-turn or
      replay claim that never passes any of these keywords defaults them all to their documented defaults
      (014/FR-002, FR-018, FR-047).
- [ ] T004 Implement schema v12 in `src/kestrel/store.py` per `data-model.md`: all four new `runs` columns in
      `RUNS_COLUMNS_SQL` itself; the duplicate-row check and `uq_run_turns_position`, both inside `_migrate`; the
      `checkpoints`/`checkpoint_writes` tables (with `task_path`); `claim_run(..., ask_before_each_turn=False,
      is_checkpointed=False, attacker_prompt_id=None, attacker_prompt_version=None, judge_model=None,
      judge_prompt_id=None, judge_prompt_version=None)` with the non-adaptive rejection (T003); the matching `Run`
      fields (014/FR-003, FR-004, FR-047).
- [ ] T005 [P] Unit test `tests/unit/test_record_step_atomic.py` (`FEATURE = "014"`): a new store method writing a
      turn row and its evidence items in one transaction; calling it twice for the same `(run_id, position)` with
      identical arguments is a no-op the second time (no duplicate row, no duplicate evidence, no exception);
      injecting a failure *between* the turn insert and the evidence insert (monkeypatch the connection) and
      confirming — on a real retry over the same `tmp_path` database — that the method's own atomicity means
      either both exist or neither does, never one without the other (014/FR-012).
- [ ] T006 Implement `add_turn_with_evidence`/`has_turn` in `src/kestrel/store.py` per `data-model.md`; the lifted,
      shared `record` step (`attack/graph.py`) calls `has_turn` first and, when a row already exists, returns the
      state delta `state` alone implies without writing anything or emitting a second `turn` log line. No
      production fallback for a store lacking either method — every real store gains both in this same schema
      bump. Add both methods to `tests/unit/test_adaptive_graph_state.py`'s own `StubStore` (plan.md's
      pre-existing-test-edit list), the one pre-existing test this specific change touches (014/FR-012).
- [ ] T007 [P] Unit test `tests/unit/test_durability_sync.py` (`FEATURE = "014"`): a saver whose write step sleeps
      briefly before writing; invoking the checkpointed graph with synchronous durability against it proves step
      *N*'s checkpoint read-back is durable before step *N+1*'s own node starts (assert via a shared, timestamped
      log); the library's **default** durability mode, run once for contrast in the same test, demonstrably lets
      several steps start before any checkpoint commits. **Durability is never passed to a checkpointer-free
      call**: invoking the bare module-level `LIVE_GRAPH` (no checkpointer attached) with an explicit durability
      argument logs the library's own "has no effect" warning — assert the experiment harness's own call site never
      passes one (014/FR-003, SC-012, research D3).
- [ ] T008 Wire synchronous durability into every call site that invokes a checkpointed live graph (`run_adaptive`'s
      own invocation, and the resume/decision/stop paths added below) in `src/kestrel/attack/graph.py` and
      `runs.py` — never into a call against the bare, checkpointer-free graph the experiment harness uses. The live
      run-start path's own `claim_run` call passes `is_checkpointed=True` (research D22) (014/FR-003, FR-001).
- [ ] T009 [P] Unit test `tests/unit/test_live_graph_copy.py` (`FEATURE = "014"`): `LIVE_GRAPH.copy(update=
      {"checkpointer": saver})` produces an object whose `.checkpointer is saver`, the **same node set** as
      `LIVE_GRAPH`, and leaves `LIVE_GRAPH.checkpointer is None` afterward; calling `LIVE_GRAPH.ainvoke(...)` with
      an empty `config` (no `thread_id`) still succeeds (proving the module-level graph is never mutated); building
      two independent apps (two `create_app` calls) each produce their own copy bound to their own `tmp_path`
      store, and nothing from one leaks into the other (research D2).
- [ ] T010 Implement the per-app checkpointed copy in `src/kestrel/api/main.py`'s `lifespan`: construct the saver
      (T013), run the version guard (T016), build `app.state.live_graph = LIVE_GRAPH.copy(update=
      {"checkpointer": saver})`, before the sweep (T018) and before serving. `run_adaptive`/the new resume/decision/
      stop functions take which compiled graph to run against as a parameter; the experiment harness
      (`experiments/engine.py`) is **not** touched (research D2).
- [ ] T011 [P] Unit test `tests/unit/test_time_spent_accounting.py` (`FEATURE = "014"`): **every** node's own delta
      **sets** (never increments) `time_spent_s` to `time_spent_at_invocation_start + (clock() -
      invocation_start)`, recomputed fresh each time; calling several nodes across several turns within one
      continuous invocation never double-counts (each one's own set is a plain recomputation from the same fixed
      anchor, not an additive nudge); a fresh claim's deadline arithmetic is **byte-identical** to today's
      (`clock() + time_limit_s`, since `time_spent_at_invocation_start` is `0.0`) — an uninterrupted run's own
      timing is unchanged; a simulated gap (advance a fake clock between two invocations against the same thread,
      by more than the configured limit) does **not** cause the resumed run to immediately time out; a run whose
      own `time_spent_s` already exceeds its limit at the moment it is resumed ends at the time-limit cap on its
      very next check. **The approve-node pause case specifically**: cut a checkpointed run right after `attacker`
      returns but before `approve` would next run (simulating the pause itself, no part-2 decision needed to prove
      this at the primitive level), and assert the *attacker* node's own delta already persisted an up-to-date
      `time_spent_s` reflecting the drafting time — never left at the previous turn's own stale value, which would
      let a run paused every turn spend unbounded, unaccounted drafting time (014/FR-016, SC-005).
- [ ] T012 Implement time-spent accounting in `src/kestrel/attack/graph.py` per `data-model.md`: `_State.
      time_spent_s`/`turn_time_spent_at_start`/`turn_attacker_usage`, set fresh by **every** node's own returned
      delta, never only `record`; `time_spent_at_invocation_start`/`invocation_start` move onto the shared `_Deps`
      base (both `_LiveDeps` and `_ReplayDeps` need them, since `send`/`evidence`/`judge` are shared nodes), each
      `@dataclass(kw_only=True)` so a defaulted base field followed by a subclass's own required field is not a
      `TypeError`; `_LiveDeps.deadline` keeps its existing name, type and role unchanged (research D23) — a fresh
      claim computes it exactly as today; a resume/decision/stop's own deps-construction computes it as
      `clock() + (run.time_limit_s - state["time_spent_s"])`, read from the just-loaded checkpoint.
- [ ] T013 Implement `src/kestrel/checkpointing.py`: `KestrelCheckpointSaver(BaseCheckpointSaver)` over a
      `TargetStore`, its five async methods each wrapping a `with store.connect() as db: ...` block in
      `asyncio.to_thread(...)`; `__init__` constructs its own `JsonPlusSerializer(allowed_msgpack_modules=[the
      three Kestrel types])` and passes it to `super().__init__(serde=...)` (research D9 — never a post-construction
      `with_allowlist` call); `aput` stamps `kestrel_graph_version` (imported `CURRENT_GRAPH_VERSION` constant) into
      the checkpoint's own metadata before persisting it (research D18); `aput_writes`'s replace-for-control/
      ignore-for-regular rule, with `task_path` stored and read back (research D10); `thread_config(run_id)`;
      `delete_checkpoint`/`adelete_thread` (014/FR-006, FR-035, FR-048, FR-049).
- [ ] T014 [P] Unit test `tests/unit/test_checkpoint_saver_contract.py` (`FEATURE = "014"`): `aput` then
      `aget_tuple` round-trips exactly, under both the serializer's default mode and an explicitly constructed
      strict-mode-equivalent serializer (`JsonPlusSerializer(allowed_msgpack_modules=...)` built directly in the
      test, since the library's own strict-mode flag is read once at import and cannot be toggled live within one
      test process) — assert the returned types are the real Kestrel classes, not plain `dict`s, in the strict case
      specifically, with **no** deserialization warning in either mode (014/FR-049); every `aput` call's own
      persisted metadata carries `kestrel_graph_version` equal to the saver's own current constant (014/FR-048);
      **`aput_writes` then `aget_tuple` returns those writes in `pending_writes`** before any further `aput` folds
      them in (014/FR-035, owner's first condition); a **regular** write recorded twice (same channel, same
      checkpoint) is stored once, the second call a no-op; a **control** write (an interrupt/resume-shaped channel,
      negative index) recorded twice **replaces**, never duplicates; `alist` returns a thread's checkpoints
      newest-first; `adelete_thread` removes both tables' rows for that thread and is a no-op for an unknown
      thread; a resume through the real production live-graph copy with this saver, in the strict-equivalent
      configuration, correctly reads back the three registered types (014/FR-007, FR-036 — the owner's second
      condition, satisfied here at the saver level; T031 satisfies it again through the full adaptive loop).
- [ ] T015 [P] Unit test `tests/unit/test_checkpoint_version_guard.py` (`FEATURE = "014"`): monkeypatching the
      installed-version lookup to a value outside `SUPPORTED_LANGGRAPH_CHECKPOINT`/`SUPPORTED_LANGGRAPH` fails the
      start-up guard loudly, naming the installed version and the declared range, for each package independently;
      values inside both ranges pass silently; the version parser accepts a two-component bound (`"1.3"`, not only
      `"1.3.0"`) correctly, since `SUPPORTED_LANGGRAPH`'s own declared upper bound has only two components. **The
      `pyproject.toml` agreement**: a `tomllib` read of `pyproject.toml` asserts its `langgraph-checkpoint`/
      `langgraph` specifiers equal the two constants exactly — a deliberately mismatched test fixture file fails
      this assertion, proving the test actually compares the two rather than trivially passing (014/FR-037,
      SC-011).
- [ ] T016 Implement `SUPPORTED_LANGGRAPH_CHECKPOINT`/`SUPPORTED_LANGGRAPH`, `check_supported_versions()` (stdlib
      version comparison accepting two or three components, no `packaging` dependency), and the
      `pyproject.toml`-agreement check in `checkpointing.py`; called once, in `lifespan`, before the saver is
      attached to any app copy.

**Checkpoint (Part 1 foundation)**: `uv run pytest tests/unit/test_store_migration_v12.py
tests/unit/test_state_ask_before_each_turn.py tests/unit/test_record_step_atomic.py
tests/unit/test_durability_sync.py tests/unit/test_live_graph_copy.py tests/unit/test_time_spent_accounting.py
tests/unit/test_checkpoint_saver_contract.py tests/unit/test_checkpoint_version_guard.py` green; every existing
`attack/graph.py`/`runs.py`/`experiments/engine.py` test still green (run the full offline suite before and after
T006/T008/T010/T012, confirm an identical pass/fail set except the four pre-existing-test edits `plan.md` names).

## Phase 3: User Story 1 — An interrupted adaptive run doesn't have to start over (P1)

**Goal**: a live, checkpointed adaptive run interrupted at any of the four step boundaries resumes from its next
unfinished step, never repeating a fully-recorded turn, through one explicit user action; a run that would just
fail again has Stop as its documented way out; the start-up sweep classifies instead of closing unconditionally.

**Independent Test**: per `spec.md`'s own Independent Test for this story.

### Tests for User Story 1

- [ ] T017 [P] [US1] Unit test `tests/unit/test_start_up_sweep_classification.py` (`FEATURE = "014"`): seed
      `in_progress` rows covering every classification outcome — non-`is_checkpointed` rows of every mode
      (single-turn, replay, an `is_checkpointed=False` adaptive row, an experiment repetition's own realistic
      shape); an `is_checkpointed` row with a loadable checkpoint mid-run (no pending task at all, `next`
      non-empty); one whose graph genuinely reached its own end (**no** pending tasks, an outcome already present
      in its state). **The commit-window state, built by fault injection, not by description alone**: monkeypatch
      the saver so its `aput` raises *after* `aput_writes` has already recorded a node's own writes (reproducing
      "a node's writes landed but the following checkpoint commit did not" structurally, never by assuming the
      shape) — read the thread back afterward and confirm it has **one** pending task present with its own result
      already set and `outcome` still `None`, and assert classification reports this as **resumable**, never
      mistaken for the reached-its-own-end case even though both share an empty `next`; also confirm this exercises
      FR-035's pending-writes replay through the full sweep/classify path, not only at the saver's own unit level
      (T014). One paused at an interrupt; one with a version-stamp mismatch; one with no checkpoint at all; one
      whose checkpoint cannot be read at all (`aget_tuple` **and**, separately, `aget_state` each raising on their
      own load — assert both classify the same as no checkpoint, closed exactly as today). Run the sweep and assert
      each classifies and is handled exactly as `data-model.md`'s classification table describes, with
      `run.interrupted` written into the kept log **only** for the `is_checkpointed` rows, never for the others.
      **The reached-its-own-end row's own reconciliation writes back to a `SpyExperienceStore` exactly once**,
      through the same shared finishing function every other path uses (T024) — never skipped because this path is
      the sweep's own, not a request's.
      **`test_from_step_matches_the_compiled_graphs_own_next_node` (FR-052, part-1 topology)**: against the real
      production live-graph copy (never a stand-in), build each commit-window state in turn (`send`, `evidence`,
      `judge`, `record`, `decide` each completed in isolation, plus the one cut before `attacker` ever ran) and
      assert classification's own `from_step` equals that same build's own real next node — read from the
      completed task's own stored routing write (`branch:to:<node>`), never a hand-written table that cannot
      represent `attacker`'s and `send`'s and `decide`'s own conditional branches (a failed send, evidence already
      found, a cap reached, each skip ahead or end the run early) (014/FR-001, FR-013, FR-017, FR-032, FR-043,
      FR-045, FR-048, FR-052, SC-006, SC-015, SC-017).
- [ ] T018 Implement the classifying, async start-up sweep (`src/kestrel/store.py`/`api/main.py`'s `lifespan`,
      after T010's graph copy and T016's version guard, before serving — research D14): for each `is_checkpointed`,
      `in_progress`, `mode == "adaptive"` row, call the classification function and act on its distinct result
      (reconcile-and-close a reached-its-own-end row with its own stored outcome; close a no-checkpoint/unreadable/
      incompatible row exactly as today, naming the incompatible case's own reason; leave a resumable or paused row
      untouched). Every other `in_progress` row is closed by the existing, synchronous logic, unchanged, with no
      `run.interrupted` line for it. Emit one `run.interrupted` line per checkpointed row classified, into that
      run's own kept log, plus the existing stream-level summary (014/FR-013, FR-017).
- [ ] T019 [P] [US1] Unit test `tests/unit/test_execution_lease.py` (`FEATURE = "014"`): acquiring a lease for a
      `run_id` already leased raises immediately (never blocks); releasing it (even via an exception inside the
      `with` block) makes it acquirable again; two concurrent coroutines racing to acquire the same lease result
      in exactly one succeeding; two independent apps' own lease sets never see each other's run ids, even when
      the same integer run id happens to exist in both. **The original start holds the lease, not only
      resume/decision/stop**: while a slowed-down original `POST /api/runs` is still mid-flight (its own lease held
      throughout, per T020), assert `GET /api/runs/{id}` reports `resumable: false, paused: false` (reads as plainly
      executing, no control offered), and that a concurrent `POST .../resume` and a concurrent `POST .../stop`
      against that same, still-executing run both answer `409 run_executing` — never racing the original request,
      and never finding the run falsely resumable before it has even paused or crashed once (014/FR-038, FR-014,
      SC-013).
- [ ] T020 Implement the execution lease (`checkpointing.py` or a new small module) as a plain set of leased run
      ids held on `app.state` (research D12, D17 — never a bare module-level object, and never `asyncio.Lock`,
      which this non-blocking check-and-insert has no use for). **The original run-start path takes this lease
      immediately after `claim_run` succeeds, inside `run_adaptive`, before its first invocation** — not only
      resume, decision, and stop — and holds it for the rest of that request, released only once it returns,
      finishing or not. Classification reports `"running"` (resumable/paused both `false`) while a run's lease is
      held (014/FR-038, FR-014).
- [ ] T021 [P] [US1] Integration test `tests/integration/test_stop_endpoint.py` (`FEATURE = "014"`): `POST
      /api/runs/{id}/stop` on a merely-resumable run (no pending decision, no outcome of its own yet) finishes it
      with `stopping_condition == "stopped_by_user"` and a verdict read from the **last `run_turns` row this run's
      own judge actually reached a verdict on** (`unclear` if none did — never a nonexistent `Run.
      last_judged_verdict` attribute), **preserving that judge's own pinned `judge_model`/`judge_prompt_id`/
      `judge_prompt_version`** (never left `null` by `finish_run`'s own column-writing `UPDATE`), with
      `turns_used`/`tokens_used` taken from the checkpoint's own persisted state, without the graph ever running
      again (assert via the model-request/send counters, never incremented by this call), deletes its checkpoint,
      and releases its target lock (a new run against that target now succeeds). **The reconciled case, both
      shapes**: Stop on a run whose graph already reached its own end (an outcome already decided, row never
      finished), **and separately** Stop on a run whose evidence step found hard evidence, or whose judge already
      succeeded, for a turn `record` had not yet durably written (cut in the commit window after evidence/judge,
      built via the saver fault-injection technique T017 established) — both return **200**, finished with **that**
      outcome, never `stopped_by_user`, never a 409, **and** a `run_turns` row (with its evidence) now exists for
      the previously-unrecorded turn in the second shape, written through the same idempotent call `record` itself
      would have made; its own judge provenance is preserved here too. **Before any of these three are stopped,
      `GET /api/runs/{id}` on each reports `run_state == "stoppable"`** (FR-054) — distinctly from `"resumable"`,
      even though all read `resumable: false, paused: false` alike.
      **`test_stop_does_not_write_a_phantom_duplicate_turn` (FR-051)**: for the cut points where `record` itself
      has *already* run for the pending turn — `record`'s own commit window, `decide`'s commit window, and a clean
      checkpoint taken right after `record` (the next turn not yet begun) — assert Stop leaves **no** `run_turns`
      row beyond the last turn actually, durably recorded (never a phantom `turns_used + 1` built from fields
      `record` already consumed and left in state uncleared); for the evidence and judge commit windows (where
      `record` has *not* yet run), assert Stop records that pending turn **exactly once**. **No usable checkpoint
      at all**: Stop on an unleased, `in_progress`, `is_checkpointed` run with no checkpoint, and separately one
      whose checkpoint cannot be read, both close the row the way the sweep closes this shape — **never** a 409,
      and never `stopping_condition: "stopped_by_user"` for either.
      **`test_stops_no_checkpoint_close_matches_the_sweeps_reason_and_skips_write_back` (FR-056)**: assert the
      reason text Stop records for this shape is the identical string the sweep's own close uses for it (not
      merely a similar one), and that `memory_written` stays `false` — no write-back attempted, matching the
      sweep's own close exactly. On an already-finished run → `409 not_resumable`; on a currently-leased run →
      `409 run_executing`. The request completes synchronously, returning only once Stop's own action is fully
      done (014/FR-025, FR-040, FR-047, FR-051, FR-054, FR-056, SC-014, research D7, D11).
- [ ] T022 Implement `POST /api/runs/{id}/stop` and `runs.py::execute_stop(...)` per `contracts/api.md` and
      `data-model.md`: acquires the lease, classifies, and: for `NoCheckpoint`/`Unreadable`, closes the row the
      same way the sweep closes it — identical reason text, no write-back (FR-056); for a decided outcome
      (`ReachedEnd`, or `Resumable` whose own state already holds one), records the pending turn through
      `add_turn_with_evidence` only when the resume point still names `record` as the next step — never merely
      because `turns_used + 1` looks unwritten, which `record`'s own prior run leaves looking exactly that way
      (FR-051) — then reconciles through `finish_with_outcome` (fixed to pass the run's own pinned judge provenance
      and a reason); otherwise synthesizes `stopped_by_user` from the last durably judged `run_turns` row, the
      checkpoint's own counts, and the run's own pinned judge provenance — no `ainvoke`/`Command` call at all, in
      any branch (research D7) — then calls the shared finishing function (T024) for write-back and checkpoint
      deletion, and releases the lease and the target lock.
- [ ] T023 [P] [US1] Integration test `tests/integration/test_write_back_once.py` (`FEATURE = "014"`): a run resumed
      to a normal finish, a run stopped (the ordinary case), and a run Stop reconciles from its own already-decided
      outcome, each write back to a `SpyExperienceStore` exactly once; a run cut off mid-step and left
      paused/resumable (not yet finished) writes back 0 times at that point.
      **`test_finish_run_is_called_exactly_once_per_finished_run` (FR-055)**: for each of these same finishing
      paths, assert `store.finish_run` (or the real store's own row-level finished marker) is hit exactly once —
      never twice (the API-path finishing function must not re-finish a row `run_adaptive` already finished for
      the original start). **`test_a_start_that_raises_still_releases_its_lease` (FR-055)**: monkeypatch a node to
      raise inside an otherwise-ordinary original start; assert the run's own lease is released despite the
      exception (a subsequent resume or stop is not refused `409 run_executing`) (014/FR-043, FR-055, SC-015).
- [ ] T024 Implement the one shared finishing function (`runs.py`): write-back (skipped if already attempted) →
      checkpoint delete → lease release, for a run **already finished**. Every path finishes its own row itself,
      first — resume/decision via `finish_run` once `ainvoke` returns a terminal outcome, Stop via `finish_run`/
      `finish_with_outcome` in its own branches (T022), the sweep via its own reconciliation, and the original
      start by `run_adaptive`'s own unchanged `finish_run` call (FR-055) — then every one of them passes that
      already-finished run into this one shared function for the three steps on top. `api/main.py::start_run` is
      updated to call it on the finished run `run_adaptive` returns, instead of its own inline write-back call
      (014/FR-043, FR-055, research D19).
- [ ] T025 [P] [US1] Integration test `tests/integration/test_live_checker_rebuild.py` (`FEATURE = "014"`): for an
      override-family run cut off mid-flight and resumed, assert the rebuild constructs the planted-override state
      directly from the run's own stored token and its recorded prompt version (never through the live-claim path,
      which would mint a new token, and never through the replay path's own copied-token rebuild, which never
      regenerates a paragraph at all) — the resumed run's write-back and retrieval query inputs are stripped of the
      run's own planted task text exactly as an uninterrupted run's are. **Two in-flight-message cut points, not
      one**: cut the run *inside* `send`, before it durably commits (classification reports `from_step:
      "send"`, `completed: false`) — assert the resumed checker does **not** yet treat the message as sent (send
      itself still runs, and notes it there); separately, cut the run in `send`'s own commit window (its write
      landed, the checkpoint commit did not — classification reports `from_step: "evidence"`, i.e. past send) —
      assert the resumed checker's echo-rule input **already** includes that in-flight message before send is ever
      invoked again (send does not re-run), so the target echoing it back is never itself counted as evidence; the
      first test task's own node-raises-an-exception technique cannot reach this second shape at all (`send`'s own
      write already landed, so a monkeypatched exception inside it never reproduces a true commit-window cut —
      this variant needs the saver fault-injection technique T017 already established). Assert no disarm event is
      re-emitted for a token already disarmed before the interruption; **test a second override family** and **a
      non-override family** too, asserting the non-override family's resumed checker behaves identically to a live
      one (no planted-override state at all) (014/FR-044, SC-016, research D17).
- [ ] T026 Implement `rebuild_live_checker` in `src/kestrel/evidence/checker.py` per `data-model.md`: looks the
      run's own seed up by its recorded `prompt_id`; regenerates the override paragraph/frame from the stored
      token's recorded prompt version; constructs the checker's planted-override state directly (never via
      `build_checker`'s own live or replay branch) with `recorded=False`, then calls `bind_run(run_id)` (which sets
      the run id unconditionally before its own early-return on `recorded=False`, so no duplicate planted-token row
      is ever inserted); `note_sent` gains `emit_disarm_event` (default `True`), passed `False` for every replayed,
      already-recorded turn and `True` at most once, for the checkpoint's own in-flight message, only when the
      resume point is past that message's own send.
- [ ] T027 [P] [US1] Integration test `tests/integration/test_kept_log_continuity.py` (`FEATURE = "014"`): a run
      resumed twice produces a kept log, read back through `GET /api/runs/{id}/log`, with no numbering collision
      across the three segments and in correct order; `run.interrupted` appears in that same kept log, not only on
      the stream; the final `log.truncated` marker (when the combined segments exceed the cap) reports the true
      total dropped across every segment, never only the last segment's own count (014/FR-017, SC-006, SC-017,
      research D20).
- [ ] T028 Implement kept-log continuity (`logging_setup.py`/`events.py`): seed a resumed/decided segment's kept-
      line counter from the highest one already stored for the run; enforce the kept-line cap over the whole run,
      not per segment; persist the run's own dropped-line count as a whole-run accumulator across segments.
- [ ] T029 [P] [US1] Integration test `tests/integration/test_run_end_once.py` (`FEATURE = "014"`): across a
      checkpointed run interrupted and resumed twice before finishing, exactly one `run.end` line is emitted, only
      at the actual finish, with duration/cost/judge-used/evidence totals covering the *whole* run; a segment that
      ends at a **pause** emits no `run.end` and no `run.interrupted` either (`run.paused` already told that story).
      A segment that ends on an **exception** emits a kept `run.interrupted` line *in place of* `run.end` —
      `resumable: true`, `error` set to the exception's own class name, never its text — never both lines, and
      never neither. A turn resumed mid-way (not re-entering the `attacker` step) still produces lines naming the
      correct turn number and only that turn's own real processing time, reading `_State.turn_time_spent_at_start`
      as the baseline; the attacker call's own tokens/cost for that turn are read from `_State.turn_attacker_usage`,
      never reported as missing when the draft itself was not re-executed.
      **`test_a_first_segment_pause_emits_no_run_end` / `test_a_first_segment_exception_emits_run_interrupted_not_run_end`
      (FR-053)**: both of the above, specifically on a run's own very **first** segment (the original `POST
      /api/runs` request itself, never a resumed one) — a monkeypatched node calling `interrupt()` for the pause
      case (this feature's own generic suppression mechanism, provable here independently of part 2's real approve
      node, which has not shipped yet in this phase), and an ordinary raised exception for the exception case —
      proving the original start's own scope is marked checkpointed from the moment it claims the row, not only a
      later, reopened one. **The narrow scope, proven directly**: a single-turn run, a replay, and an experiment
      repetition each still emit `run.end` on *every* scope exit, unconditionally, exactly as today — including
      when an exception escapes one of them — proving the suppression applies only to a checkpointed, still-
      `in_progress` adaptive run, never more broadly. **No pre-existing test needs editing for this**: every
      existing event-level test that opens a scope with no run bound to it, or one bound to a run that is never
      checkpointed, can never satisfy "checkpointed and still in_progress" in the first place, so it is unaffected
      by construction — assert this directly by running `tests/unit/test_events.py` **and**
      `tests/unit/test_run_log_handler.py` unmodified alongside this feature's own suite (014/FR-046, FR-053,
      SC-018, research D21).
- [ ] T030 Implement `run.end` suppression and turn-context-reopening in `events.py` per
      `contracts/log-records-delta.md`: `RunContext` gains `checkpointed`/`finished` fields — `checkpointed` set at
      entry by `run_scope(run)` itself (which the original run-start path calls with `checkpointed=True` the
      moment it claims a checkpointed row, before `run_adaptive`'s first invocation, never only by a later,
      reopened scope) or by `events.reopened_run_scope(run)` (a resume/decision/stop's own scope, copying
      `checkpointed` from the `Run` it is given); `finished` set by the shared finishing function at exit — never
      read from the store at scope exit either way; a scope's exit withholds `run.end` only when `checkpointed`
      and not `finished`, emitting a kept `run.interrupted` line instead **only when an exception escaped**
      (`resumable=true`, `error=<exception class name>`), and nothing at all for a clean exit (a pause); every
      other combination emits `run.end` exactly as today, unconditionally, with whole-run totals read from
      accumulators carried in the run's own persisted state; a resume/decision explicitly reopens the in-flight
      turn's own context (number, a start time excluding the gap, read against `_State.turn_time_spent_at_start`)
      rather than relying on `events.turn_started`.
- [ ] T031 [P] [US1] Integration test `tests/integration/test_resume_adaptive_run.py` (`FEATURE = "014"`), **the
      core correctness proof for FR-008, FR-009, FR-010, FR-011, FR-012, FR-036, FR-042, and SC-001**: for each of
      the four cut points (attacker drafted-not-sent, send sent-not-recorded, reply recorded-not-checked, judge
      answered-not-recorded — each simulated by monkeypatching the relevant node to raise an ordinary exception
      immediately after its own durable side effect, or before any, per the cut point), start an adaptive run
      through the real production live-graph copy with the real saver attached (never `InMemorySaver` — the
      owner's second condition, FR-036, satisfied here through the full adaptive loop, alongside T014's own
      saver-level proof), cut it. **Immediately after the cut, before resuming, within the same `create_app`
      instance (no restart of any kind)**: assert the run's own row is still `in_progress`, its checkpoint is still
      loadable, and its lease is released (classification reads it as resumable, never as still-executing) — this
      is FR-042's own claim, that an in-process exception needs no restart and no start-up sweep to read as
      resumable, proven directly rather than only inferred from the later resume succeeding. **Also assert the kept
      log now carries a `run.interrupted` line for this exact exit** (`resumable: true`, `error` naming the raised
      exception's own class, never its text) and that no `run.end` was emitted for it, **for every one of the four
      cut points, the first (attacker drafted-not-sent) included** — the original start's own first segment is
      marked checkpointed from the moment it claims the row (FR-053), so this holds from turn 1 on, not only from
      a resumed segment — read back through `GET /api/runs/{id}/log`. Then resume it
      through **a freshly constructed `_LiveDeps`** (never the deps object the first attempt used — proving FR-005
      by construction, not vacuously), and assert: no attacker/judge call is repeated for any turn already durably
      recorded (count `model_transport.model_requests(...)`); exactly one `run_turns` row, one set of evidence
      items, and (for the "recorded but not yet checked" cut specifically, where the record step re-executes
      against an already-written row) no second kept-log `turn` line exist for the cut turn's position; the
      resumed run reaches the **same stopping condition and verdict**
      an uninterrupted run reaches, with the stub attacker, judge and target scripted identically either way
      (SC-001's own measurable wording). **Secret scrub, on the raw stored bytes** (SC-007): configure the stub
      target with a real auth-header secret value **and** a distinctive URL/display name, cut and resume the run,
      then read every `checkpoints`/`checkpoint_writes` row's raw bytes directly from the `tmp_path` database and
      assert none of the three ever appears in them. Also `tests/integration/test_resume_api.py`: `GET
      /api/runs/{id}` on a resumable (not paused, not leased) run reports `resumable: true, paused: false` (both
      `false` while leased), **and `run_state == "resumable"`**; `POST /api/runs/{id}/resume` on it returns **200**
      and completes the run; preconditions (permission, terms, attacker configured, library available) each refuse
      with the documented code/message before anything is sent; on a `finished` run, a non-adaptive run, or a
      currently-leased run → the documented `409`; starting a new run or a replay against the same target while
      the resumable run sits un-resumed → `409 run_in_progress`.
      **`test_a_leased_run_reads_running_and_offers_no_control` (FR-054)**: while a run's lease is held (a slowed
      original start, matching T019's own technique), assert `GET /api/runs/{id}` reports `run_state == "running"`
      — distinctly from `"stoppable"`, which a reached-its-own-end, no-checkpoint, or unreadable run reports
      instead, even though all four combinations share the identical `resumable: false, paused: false` (014/
      FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015, FR-025, FR-033, FR-036, FR-041, FR-042,
      FR-053, FR-054, SC-001, SC-007, SC-008, contracts/api.md).
- [ ] T032 Implement `POST /api/runs/{run_id}/resume` and the `resumable`/`paused`/`pending_turn`/`run_state`
      fields on `RunSummary`/`RunDetail` in `src/kestrel/api/main.py`/`api/schemas.py`, per `contracts/api.md`;
      `run_state` is computed from classification's own result (`Running`→`"running"`, `Paused`→`"paused"`,
      `ReachedEnd`/`NoCheckpoint`/`Unreadable`→`"stoppable"`, `Resumable`→`"resumable"`, a finished row→`"finished"`),
      never reconstructed from `resumable`/`paused` by any caller (FR-054); `GET
      /api/runs/{id}` and the run-list endpoint become `async def` (research D14); `runs.py::execute_resume(...)`
      acquires the lease, reconciles a reached-its-own-end run immediately rather than refusing it, otherwise
      checks preconditions (FR-041) and constructs a fresh `_LiveDeps` pinned to the run's own stored caps/model/
      prompt references (T034), and dispatches through the resume path, calling the shared finishing function
      (T024) on completion.
- [ ] T033 [P] [US1] Integration test `tests/integration/test_resume_pinned_caps.py` (`FEATURE = "014"`): a resumed
      run uses its own stored turn/token/time-limit caps and its own recorded attacker **and judge** models and
      prompt references (`attacker_prompt_id`/`.version`, `judge_model`, `judge_prompt_id`/`.version` — all four
      read from the claimed row, never from current settings); monkeypatching the configured attacker **or judge**
      model between claim and resume does not change what the resumed run uses. **"Unavailable", concretely**: a
      resume whose pinned **prompt-version file** no longer exists, or whose pinned client's **API key** is not
      configured, is refused with a message naming the problem, and Stop still succeeds on that same run; **a
      resume whose own recorded `prompt_id` no longer exists in the current library** (FR-041) is refused
      the same way — `409`, a message naming the problem, Stop still available — never an unhandled error from
      `rebuild_live_checker`'s own seed lookup; a pinned model **slug** that is merely invalid (would only fail on
      an actual call) is *not* detected by this check — assert the resume is *not* refused for that reason alone
      (014/FR-041, FR-047, SC-020, research D16).
- [ ] T034 Implement pinned caps/provenance at resume/decision (`runs.py`): `_LiveDeps` built for a resume/decision
      reads `turn_budget`/`token_budget`/`time_limit_s`/`attacker_model`/`attacker_prompt_id`/`.version`/
      `judge_model`/`judge_prompt_id`/`.version` from the run's own stored row, never from current settings; a
      missing pinned prompt-version file or a missing API key raises a named error the endpoint turns into
      `409 pinned_model_unavailable`; an invalid-but-present model slug is never checked this way.
- [ ] T035 [P] [US1] Integration test `tests/integration/test_checkpoint_gc.py` (`FEATURE = "014"`): after a clean
      finish, a stop, and the sweep's own close/reconcile paths, no checkpoint row remains for that run id; deleting
      a target removes every checkpoint thread for its own runs' ids in the same operation, alongside the existing
      cascade (014/FR-006, FR-045, SC-019).
- [ ] T036 Implement checkpoint reconciliation/deletion call sites per `data-model.md`: the shared finishing
      function (T024) deletes on every clean path; the sweep (T018) deletes an orphan whose row is not
      `in_progress`; the target-delete code path deletes every checkpoint thread for that target's run ids before
      (or as part of) the cascading delete.
- [ ] T037 [P] [US1] Integration test `tests/integration/test_owasp_excludes_in_progress.py` (`FEATURE = "014"`): a
      target's OWASP report excludes a paused run, a resumable run, and a run currently leased/executing, the same
      way it already excludes a replay; generating the report does not change while such a run sits open
      (014/FR-050, research D25).
- [ ] T038 Implement the `status == "finished"` filter in `api/main.py::target_report` (research D25).
- [ ] T039 [P] [US1] Implement the UI: `ui/api_client.py::resume_run(run_id)` using `run_attack`'s own 360s timeout
      (a resume, like a fresh start, can itself drive a run all the way to completion) and `stop_run(run_id)` using
      its own short timeout (Stop never drives a run further, only ends it); `ui/app.py` renders its controls from
      `run_state` alone, never reconstructed from `resumable`/`paused` (FR-054): `run_state == "resumable"` shows
      **"Resume"**/**"Stop"** ahead of `_render_finding`'s own failure-step early return; `run_state == "stoppable"`
      shows **"Stop"** alone (a reached-its-own-end, no-checkpoint, or unreadable run); `run_state == "running"`
      shows neither control; adds `"stopped_by_user"` to the existing `STOPPED` label table; the run list shows a
      resumable run distinctly from an ordinary in-progress or finished one.
      `tests/unit/test_ui_resume.py` (`streamlit.testing.v1.AppTest`, offline):
      **`test_run_state_running_shows_no_control`** and **`test_run_state_stoppable_shows_stop_alone_never_resume`**
      (FR-054) assert exactly this, over all three `run_state` values a part-1 run can read (014/FR-014, FR-054).

**Checkpoint (US1)**: every test above green — a crashed adaptive run can be resumed or stopped end to end, through
the API and the UI, with write-back, logging, caps and evidence all correct.

## Phase 4: User Story 4 (Part 1) — Nothing else changes, the checkpointer half

- [ ] T040 [P] [US4-part1] Integration test `tests/integration/test_other_run_kinds_unaffected_p1.py`
      (`FEATURE = "014"`): interrupt a single-turn run, a replay, and an experiment repetition mid-flight; restart;
      assert each is closed exactly as `close_interrupted_runs` closed it before this feature and none reports
      `resumable: true`. **An adaptive experiment repetition's own cold arm still writes back 0 times**: run one
      through `experiments/engine.py` exactly as `tests/unit/test_experiment_warming.py` already proves for
      `single_turn` — `run_adaptive` itself still calls `finish_run` directly for every caller, live API path and
      experiment harness alike, and returns the finished run; only the live API path's own extra finishing step
      (write-back, checkpoint delete, lease release) sits on top of that, never inside `run_adaptive` itself, so
      the engine's own `if arm.write_back` check is still what decides whether a repetition writes back, unchanged
      and never warmed by this feature's own write-back-once mechanism.
      **`test_consecutive_experiment_repetitions_all_finish_and_next_claim_succeeds` (FR-055)**: run several
      adaptive repetitions back to back on one target through the real experiment harness and assert every one of
      them finishes (none stays `in_progress`) and every next repetition's own claim succeeds — never refused by
      `uq_runs_active`/`RunInProgress` because a prior repetition's row was left open by a finishing function that
      no longer runs for it. Run the **full existing offline suite**, unmodified except the four named
      pre-existing-test edits, before and after every part-1 implementation task, and confirm an identical
      pass/fail set (014/FR-001, FR-032, FR-043, FR-055, SC-002, SC-003).

**Checkpoint (Part 1 complete)**: every part-1 task above green, full offline suite green (modulo the four named
edits), `quickstart.md`'s Part 1 steps pass by hand. Ready for the part-1 pull request (FR-027).

## Phase 5: Part-1 end-to-end

- [ ] T041 [P] Implement the automated SC-010 part-1 scenario, `tests/e2e/test_us014_checkpointer.py`: **two
      separate `create_app` instances sharing one temporary database** (never a browser test, which cannot restart
      Kestrel) — start an adaptive run on instance A, interrupt it (close instance A without finishing the row),
      resume and stop it through instance B, over the real API surface. Separately, attempt the live HS-code e2e;
      expect it to fail at the connection-test step per the known OpenRouter guardrail gotcha (CLAUDE.md, first
      recorded 2026-11-21, recurred 2026-11-24) — confirm with an untouched, pre-existing e2e failing identically
      before concluding this is not a regression of this feature (FR-030, part of SC-010).

## Part-1 Polish (Phase 6)

- [ ] T042 Mark `docs/roadmap.md`'s planned **"Feature 014 — Community prompt feed"** as **"Feature 015 —
      Community prompt feed"** (FR-028), and any other reference to it as 014 in the project's own living
      documentation (the roadmap, the README, CLAUDE.md, `docs/`) — **not** a merged feature's own spec files
      (`specs/011-retrieval-controls/` stays exactly as written). Add a CLAUDE.md "Learned notes" entry for the
      checkpointer (the per-app graph copy, the execution lease taken by the original start too, Stop-never-
      resumes-the-graph and its reached-its-own-end reconciliation, the atomic record step, the claim-time
      `is_checkpointed` classification, the version guard, the pinned provenance columns).

---

## Phase 7: Foundational (Part 2, blocking User Story 2 and User Story 3)

- [ ] T043 [P] Unit test `tests/unit/test_approve_node_probe.py` (`FEATURE = "014"`): compiled against the **real
      production live-graph copy** (T010), with the **real** `KestrelCheckpointSaver` over a `tmp_path` store —
      turn 1 never pauses; the first pause returns a result carrying the exact drafted message; re-invoking with
      nothing to resume reproduces the identical pause with no side effect and no new attacker call; a validated,
      targeted resume (`Command(resume={interrupt_id: "approve"})`) sends and pauses again at the next turn; "Run
      to end" is **seeded once, at claim, never re-read from the stored column on a resume** — assert a run whose
      column still says `True` (because the column is never rewritten) does not pause again after a restart once
      "Run to end" was chosen; the node reads its own flag with a default, so a checkpoint from before this field
      existed is still readable.
      **Reinforcing `test_from_step_matches_the_compiled_graphs_own_next_node` for part 2's own topology**
      (FR-052): with the `approve` node now wired in, build the commit-window state for a completed `attacker`
      task specifically (routing to `approve`, never `send` directly, now that part 2 ships) and assert
      classification's `from_step` still equals the real compiled graph's own next node — proving the routing-write
      mechanism needs no table update at all when the topology gains a node, unlike a hand-written one would
      (research D5, D18, FR-052).
- [ ] T044 Implement `_State.ask_before_each_turn`/`_LiveDeps.ask_before_each_turn` (defaulted, research D23) and
      the new `_approve_node` in `src/kestrel/attack/graph.py` per `data-model.md`: bumps `CURRENT_GRAPH_VERSION`
      to `2`; wires `attacker → approve → send` into `LIVE_GRAPH`'s one topology (which, before this task, has no
      such node at all); reads its own flag via `.get("ask_before_each_turn", False)`, never a bracket subscript;
      seeded into the run's initial state **only at a fresh claim**, never re-seeded by a resume/decision's own
      deps construction; a no-op when the flag is false or `turn == 1`; otherwise `interrupt(...)`, with
      `"run_to_end"` the only branch left in the node itself (`"stop"` never reaches it — research D7).
- [ ] T045 [P] Implement `RunRequest.ask_before_each_turn` (adaptive only, `422` otherwise per `contracts/api.md`
      and T003's store-level rejection); `start_run` passes it to `claim_run` (with `is_checkpointed=True`, already
      wired in T008) and `_LiveDeps`.

**Checkpoint (Part 2 foundation)**: `uv run pytest tests/unit/test_approve_node_probe.py` green; the checkbox
exists end to end (request → row → deps → state) and survives a restart correctly, but nothing yet reads it back
on the run page.

## Phase 8: User Story 2 — Review and decide each attacker turn before Kestrel sends it (P1)

### Tests for User Story 2

- [ ] T046 [P] [US2] Integration test `tests/integration/test_approve_node_live.py` (`FEATURE = "014"`): start an
      adaptive run with the checkbox ticked; assert turn 1 is sent without pausing and the run's own `POST
      /api/runs` response comes back `paused: true, pending_turn: {"turn": 2, "interrupt_id": "...", "message":
      "..."}`; `POST .../decision {"turn": 2, "decision": "approve"}` sends turn 2, scores it, and (if the run
      continues) returns the next pause; `{"turn": N, "decision": "run_to_end"}` on a fresh pause sends that turn
      and runs to a normal conclusion with no further pause — **including after a restart partway through that
      unattended run** (two `create_app` instances, one database); `{"turn": N, "decision": "stop"}` on a fresh
      pause ends the run immediately through the Stop path (T022), no new `run_turns` row for the pending message.
      **The target stays locked while paused**: while paused, a second `POST /api/runs` or `POST
      /api/runs/{other_id}/replay` against the same target → `409 run_in_progress`. Resuming and deciding both stay
      synchronous — each request completes only once its own action is fully done. **Write-back for a decided run**
      (FR-043, SC-015, reinforcing T023/T024 for the two paths only part 2 can reach): an Approve that reaches a
      normal stopping point, and a Run-to-end that runs unattended to one, each write back to a `SpyExperienceStore`
      exactly once; a Stop reached via a decision writes back exactly once too, through the same path T022/T024
      already prove, never a second time (014/FR-015, FR-019, FR-020, FR-021, FR-022, FR-023, FR-024, FR-025,
      SC-004, SC-008).
- [ ] T047 [P] [US2] Integration test `tests/integration/test_decision_api.py`: `POST /api/runs/{id}/decision` with
      a `turn` that does not match the run's actual pending turn → `409 not_paused`, nothing sent (reproducing the
      exact failure shape a bare, un-validated resume value would otherwise silently resolve against the wrong
      turn); a run with no pending decision at all → `409 not_paused`; an invalid `decision` value, or a missing
      `turn` field → `422`; **two concurrent, correctly addressed decision requests for the same pending turn** →
      exactly one succeeds (sends once), the other gets `409 run_executing` (reproducing the exact race a missing
      lease would otherwise let both execute) (014/FR-038, FR-039, contracts/api.md).
- [ ] T048 [P] [US2] `tests/unit/test_events_approve.py`: `run.paused` names the turn, emitted exactly once per
      actual pause (a bare status re-check of the same pause does not re-emit it — research D21); `run.decided`
      names the turn and the decision; `run.stopped` names whether the run was paused or merely resumable when
      stopped, and whether it was the reconciled case; none carries the pending message's text (014/FR-026,
      FR-033).
- [ ] T049 [US2] `tests/unit/test_ui_approve_node.py` (`streamlit.testing.v1.AppTest`): the checkbox on the
      start-run form, off by default; a paused run's page shows the pending message verbatim and exactly
      **Approve**/**Run to end**/**Stop**; clicking each calls the matching API action with the correct `turn`.

### Implementation for User Story 2

- [ ] T050 [US2] Implement `POST /api/runs/{run_id}/decision` in `api/main.py`/`runs.py::execute_decision(...)` per
      `contracts/api.md`: acquires the lease; classifies; refuses (`409 not_paused`) on any mismatch between the
      request's own `turn` and the pending interrupt's actual turn; for `"approve"`/`"run_to_end"`, checks
      preconditions (T034's pinned-caps path) then calls `ainvoke(Command(resume={interrupt_id: decision}), ...)`;
      for `"stop"`, dispatches to the same Stop path T022 implements; emits `run.decided`/`run.paused` per
      `contracts/log-records-delta.md`; calls the shared finishing function (T024) on any stopping point.
- [ ] T051 [P] [US2] Implement the UI: `ui/api_client.py::decide_run(run_id, turn, decision)` using `run_attack`'s
      own 360s timeout (a decision can itself drive a run all the way to completion, e.g. Run to end); the
      start-run form's **"Ask before each turn"** checkbox (off by default, adaptive mode only); the run page's
      pending-turn display and its three buttons, rendered ahead of `_render_finding`'s own early-return branches,
      each button call passing the pending turn's own number.

**Checkpoint (US2)**: every test above green.

## Phase 9: User Story 3 — A paused run survives a restart exactly like a crashed one (P2)

- [ ] T052 [US3] Integration test `tests/integration/test_paused_run_survives_restart.py` (`FEATURE = "014"`):
      pause a run, discard the in-process state entirely (two separate `create_app` instances over the same
      store), confirm the second instance's `GET /api/runs/{id}` reports the identical `pending_turn`; decide it
      and confirm the outcome matches deciding it without the gap. **The decision-cut-off case**: pause a run,
      apply a decision, interrupt the instance before the *next* checkpoint commits (a saver failure right after
      the decision's own writes land), restart, and assert the run now classifies as **resumable, not paused** —
      its already-applied decision is not re-shown and not re-asked again — and resuming it from there continues
      correctly, never re-sending anything (014/FR-014, User Story 3's three acceptance scenarios, SC-004).

**Checkpoint (US3)**: green, with no production code change beyond what Part 1 and T044/T050 already provide — this
story is a proof of composition, per `research.md` D1.

## Phase 10: User Story 4 (Part 2) — Nothing else changes, the approve-node half

- [ ] T053 [P] [US4-part2] Integration test `tests/integration/test_other_run_kinds_unaffected_p2.py`
      (`FEATURE = "014"`): a single-turn run, a replay, and an experiment repetition never pause and never see the
      checkbox, regardless of any request field a hostile or malformed client might send — an experiment
      repetition's own call now runs the `approve` node as part of the shared topology, but always as a no-op,
      since it never sets the flag. An adaptive run with the checkbox left off never pauses, `run.start` omits
      `ask_before_each_turn` entirely (never a visible `false`), and its stored data is identical in shape to before
      this feature beyond the differences FR-031 names. Run the **full existing offline suite** again, before and
      after T044–T051, confirming an identical pass/fail set, modulo only the four pre-existing-test edits (014/FR-002,
      FR-031, FR-032, SC-002, SC-003).

**Checkpoint (Part 2 complete)**: every part-2 task above green, full offline suite green, `quickstart.md`'s Part 2
steps pass by hand. Ready for the part-2 pull request.

## Part-2 Polish (Phase 11)

- [ ] T054 Implement the automated SC-010 part-2 scenario, `tests/e2e/test_us014_approve_node.py` (offline or
      through the browser suite's generic stub target), covering the pending-message/three-button controls;
      attempt the live HS-code e2e too, expecting the same, already-confirmed guardrail failure (FR-030, the rest
      of SC-010).
- [ ] T055 Move `docs/roadmap.md`'s **"LangGraph idioms"** entry to Done, describing what shipped across both
      pull requests (FR-029); add the CLAUDE.md "Learned notes" entry for the approve node (the dedicated-node
      interrupt pattern, the seed-once-never-reseed flag, turn-specific single-use decisions, the lease shared with
      part 1's Stop, the graph-version bump).
- [ ] T056 Rewrite `traceability.md` for the whole feature (both parts covered by real tests now), one id per line
      in the `"014/FR-0xx: <reason>"` form the gate actually parses.
