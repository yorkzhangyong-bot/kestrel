# Phase 1 Data Model: LangGraph Checkpointer and Approve Node (014)

See `research.md` for the reasoning and verified facts behind every shape below.

## One store: the checkpointer's tables live inside `kestrel.db`

*This section's schema is a guide to the shape, not the spec: the binding behaviour is FR-003 to FR-007, FR-035
to FR-037, FR-048, FR-049, and the test functions `tasks.md` names for them.*

`store.py`'s existing database gains, in one additive schema-version bump (no rebuild — nothing here changes a
`CHECK` constraint or a column's identity): five new columns on `runs`, one new index on `run_turns`, and two new
tables for the custom saver.

```sql
-- RUNS_COLUMNS_SQL itself gains all five new columns (not only a later ALTER): a fresh database's CREATE TABLE and
-- every migration both read from this one definition, exactly as every column since schema v3 has.
    ...
    -- Whether this run was started with "Ask before each turn" ticked. Captured once, at claim time; never
    -- rewritten (research D5) — the checkpoint's own state is the only live answer to "is it still asking".
    ask_before_each_turn INTEGER NOT NULL DEFAULT 0,
    -- Whether this run was claimed through the live, checkpointed run-start path (research D22) — never set by a
    -- single-turn claim, a replay claim, or an experiment repetition's claim, and never set by a resume or a
    -- decision, neither of which ever claims a row. The classification the start-up sweep and every status read
    -- use.
    is_checkpointed INTEGER NOT NULL DEFAULT 0,
    -- The attacker prompt reference this run is pinned to, recorded at claim time (research D16) — new columns;
    -- today only run_turns records a per-turn attacker-prompt reference, and only from turn 2. A resumed or decided
    -- run's attacker client is rebuilt against exactly this reference, never whatever is currently active.
    attacker_prompt_id TEXT, attacker_prompt_version TEXT,
    -- This run's idle clock (research D26): set at claim, updated only on an accepted lease release (never a
    -- refused request). Nullable only because a pre-migration row never had one; every row this feature itself
    -- claims always sets it.
    last_activity_at TEXT

-- judge_model / judge_prompt_id / judge_prompt_version already exist as columns (written today only by
-- finish_run); claim_run gains the option to also set them at claim time (research D16), so a resumed or decided
-- run's judge client is rebuilt against the SAME claim-time values finish_run later re-affirms, never a judge that
-- changed in between. No new columns for these three.

-- Migration note: this is a plain ALTER TABLE ADD COLUMN set against the existing `runs` table (no rebuild needed
-- — none of the five changes a CHECK or an existing column's identity), but RUNS_COLUMNS_SQL is still updated too,
-- so a fresh database's CREATE TABLE and every future migration's own column list agree with what an ALTER
-- produces on an existing one.
```

```sql
-- Defense in depth for the record-step idempotency fix (research D6): the atomic write method (below) and its
-- existence check are what actually keep a turn row and its evidence together; this index makes a bug in that
-- guard loud (sqlite3.IntegrityError) instead of a silent duplicate row. Created inside _migrate itself, after the
-- duplicate-row check below — never in the initial schema script, which TargetStore.__init__ runs unconditionally
-- before _migrate ever gets a chance to check for a pre-existing duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_turns_position ON run_turns (run_id, position);
```

```python
# Migration safety, run before the index above (inside _migrate, not the initial schema script): if an existing
# database already holds a duplicate (run_id, position) pair in run_turns (not reachable through any code path this
# project has ever shipped, but not provably impossible either), creating the index above would otherwise fail with
# a bare sqlite3.IntegrityError. _migrate checks for this explicitly first and raises a clear, named error
# identifying the migration and the table ("schema <N> migration found duplicate (run_id, position) rows in
# run_turns and refuses to start — this database needs manual inspection before it can be opened") — the same
# fail-loud posture earlier schema rebuilds already take for a foreign-key violation, never a silent guess at which
# duplicate row to keep.
```

```sql
-- The custom checkpoint saver's own two tables, covering LangGraph's full checkpoint-tuple shape (config,
-- checkpoint, metadata, parent_config, pending_writes). checkpoint_ns is always '' for Kestrel's own graphs (no
-- subgraphs), carried only for contract-correctness (FR-036 exercises the real contract, never a narrowed,
-- Kestrel-specific shortcut).
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,                 -- str(run.id)
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT NOT NULL,                      -- self.serde.dumps_typed(checkpoint)'s own type tag
    checkpoint BLOB NOT NULL,
    metadata BLOB NOT NULL,                  -- includes kestrel_graph_version, added by the saver's own aput
                                              --   (research D18) before this blob is produced
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints (thread_id, checkpoint_ns, checkpoint_id DESC);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,                    -- negative for a control write (error/scheduled/interrupt/resume) ->
                                              --   upserted; >= 0 for a regular write -> inserted only if absent
                                              --   (research D10)
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    task_path TEXT NOT NULL DEFAULT '',      -- ordering only; carries no identity of its own and is not part of
                                              --   the primary key (research D10)
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
```

No foreign key from either checkpoint table to `runs` (`thread_id` is a plain text column) — reconciliation and
deletion (below) are Kestrel's own responsibility, not `ON DELETE CASCADE`'s.

## `store.py` additions

### `Run` (extended)

```python
ask_before_each_turn: bool = False
is_checkpointed: bool = False
attacker_prompt_id: str | None = None
attacker_prompt_version: str | None = None
last_activity_at: str | None = None   # research D26 — this run's own idle clock
# judge_model / judge_prompt_id / judge_prompt_version already existed on Run.
```

### `claim_run`

`claim_run(..., ask_before_each_turn: bool = False, is_checkpointed: bool = False, attacker_prompt_id: str | None =
None, attacker_prompt_version: str | None = None, judge_model: str | None = None, judge_prompt_id: str | None =
None, judge_prompt_version: str | None = None, now: datetime | None = None)` — new optional keywords; raises a
clear `ValueError` when `ask_before_each_turn` is true for a mode other than `"adaptive"` (the API layer turns this
into its own `422`, never leaving the check to be reimplemented there). Only the live run-start path ever passes
`is_checkpointed=True` or the provenance-pin keywords (research D16, D22); every other caller leaves them at their
defaults. `now` defaults to the real wall clock when omitted, so every pre-existing caller (a single-turn claim, a
replay claim, an experiment repetition's claim) is unaffected; the live run-start path passes `now=
app_state.clock()` explicitly, so `last_activity_at` (set to this same value, research D26) agrees with whatever
clock a test has substituted for `app_state.clock()` — never the real wall clock read a second, independent way,
which would silently disagree with a simulated clock in exactly the tests this feature's own idle-stop suite
relies on.

### The atomic turn-plus-evidence write (research D6)

A new method, `add_turn_with_evidence(run_id, *, position, ..., evidence_items)`, wraps `add_turn`'s own `INSERT`
and zero or more `add_evidence`-shaped inserts in **one** transaction — the turn row and its evidence either both
exist or neither does, even under an interruption immediately after. The lifted, shared `record` step (both the
live and replay paths) calls this instead of two separate calls, and first checks `has_turn(run_id, position) ->
bool` (a point lookup against `uq_run_turns_position`); when that is already true, it skips the write entirely and
returns the delta `state` alone already implies, emitting no second `turn` log line for that position.

### Checkpoint reconciliation and deletion (research D11)

- `TargetStore` exposes `delete_checkpoint(run_id)` — wraps `adelete_thread(str(run_id))`'s own two `DELETE`s
  against `checkpoints`/`checkpoint_writes`.
- Called from the one function every finishing path funnels through (below), immediately after `finish_run` and
  write-back.
- Deleting a target's own runs is preceded, in the same request, by deleting every checkpoint thread belonging to
  that target's run ids — the checkpoint tables carry no foreign key of their own, so this is an explicit step.
- The start-up sweep additionally deletes any checkpoint whose own thread's `runs` row is not currently
  `in_progress` at all, and reconciles (finishes using the checkpoint's own recorded outcome, then deletes) a
  thread whose graph reached its own end but whose row is still `in_progress`.

## The custom saver (`src/kestrel/checkpointing.py`)

A `BaseCheckpointSaver` subclass over `TargetStore`'s own connection, five async methods each
`asyncio.to_thread`-wrapped:

- **`__init__(self, store)` calls `super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=[
  ("kestrel.attack.graph", "Outcome"), ("kestrel.evidence.checker", "TurnEvidence"), ("kestrel.evidence.model",
  "EvidenceItem")]))`** (research D9) — never `self.with_allowlist(...)` after construction, which is a no-op in
  the serializer's permissive (non-strict) mode and so leaves the default mode's own warnings in place. This
  explicit serializer is the saver's own object, so it survives `.copy()` (per-app graph copies, below) unchanged —
  a saver-level round trip and a graph-level read through a per-app copy both see the same, correctly registered
  types, under either of the library's serializer modes.
- **`aput` stamps the checkpoint's own metadata with `kestrel_graph_version`** (research D18) before persisting it:
  `metadata = {**metadata, "kestrel_graph_version": CURRENT_GRAPH_VERSION}` — `CURRENT_GRAPH_VERSION` is a plain
  module constant the saver imports from `attack/graph.py` (`1` through part 1; bumped to `2` when part 2 adds the
  `approve` node to the live graph's topology). LangGraph itself never needs to see this key; it is purely data
  Kestrel adds to a dictionary it already owns writing.
- **`aput_writes` replicates LangGraph's own replace/ignore rule and carries `task_path`** (research D10): for
  each `(channel, value)` pair, a negative index (from LangGraph's own index map) upserts (`INSERT OR REPLACE`); a
  non-negative one inserts only if absent (`INSERT OR IGNORE`); `task_path` (already a parameter `aput_writes`
  receives) is stored and read back, used only for ordering.
- **`SUPPORTED_LANGGRAPH_CHECKPOINT`/`SUPPORTED_LANGGRAPH`**: two constants, narrowed to the range actually tested
  — `">=4.3.0,<4.4.0"` and `">=1.2.17,<1.3"`. `check_supported_versions()` reads the installed version of each
  package, parses it with the standard library (accepting a two- or three-component version number — `<1.3`'s own
  bound has only two, so a parser that demands exactly three would fail on its own declared range) against the two
  constants, and raises a clear, named error for whichever package falls outside its range. `pyproject.toml` gains
  two explicit dependency lines at the identical ranges; a test reads `pyproject.toml` with `tomllib` and asserts
  both specifiers equal the two constants exactly.

## Classification (research D13): one function, distinct results

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-052 and FR-054, the
`contracts/`, and the test functions `tasks.md` names for them.*

```python
# The plain, statically single-target edges with no routing write of their own (FR-052) — every other edge is
# read from the completed task's own stored routing write, never a hand-written table.
_STATIC_NEXT_STEP = {"judge": "record", "record": "decide"}

async def classify(graph, run_id: int, *, leased: bool):
    if leased:
        return Running()
    try:
        tup = await graph.checkpointer.aget_tuple(thread_config(run_id))
        if tup is None:
            return NoCheckpoint()
        if tup.metadata.get("kestrel_graph_version") != CURRENT_GRAPH_VERSION:
            return Incompatible()
        snap = await graph.aget_state(thread_config(run_id))
    except Exception:
        return Unreadable()
    if not snap.tasks:
        return ReachedEnd(outcome=snap.values.get("outcome"))
    interrupts = [i for task in snap.tasks for i in task.interrupts]
    if interrupts:
        first = interrupts[0]
        return Paused(interrupt_id=first.id, turn=first.value["turn"], message=first.value["message"])
    task = snap.tasks[0]
    completed = task.result is not None
    if not completed:
        from_step = "attacker" if task.name == "__start__" else task.name
    else:
        routed = next((channel.removeprefix("branch:to:") for task_id, channel, _ in tup.pending_writes
                        if task_id == task.id and channel.startswith("branch:to:")), None)
        from_step = routed or _STATIC_NEXT_STEP[task.name]
    return Resumable(from_step=from_step, completed=completed, snapshot=snap)
```

`NoCheckpoint`, `Unreadable`, and `Incompatible` are all handled identically by every caller (close/refuse exactly
as today, with `Incompatible` alone naming its own distinct reason). The distinction between `ReachedEnd` (no
pending tasks, an outcome already decided — the graph genuinely finished) and `Resumable` (one pending task, no
interrupt, `outcome` still unset in the general case — a step's writes landed but its own checkpoint commit did
not) matters precisely because both shapes share an empty `next`; reading `snap.tasks` is what tells them apart,
since a thread that truly reached the graph's end has none, while the commit-window shape still has exactly one,
with its own result already present.

**The pending task's own name is never the resume point.** A pending task whose `result` is `None` has not run
yet in this invocation (a plain crash before it started) — that task's own name *is* where execution resumes
(`"__start__"`, translated to `"attacker"`, for a cut right after the run's own input checkpoint, before
`attacker` ever ran — never surfaced raw). But a pending task whose `result` is already set has *completed*;
LangGraph does not re-run it on `ainvoke(None, ...)` — it folds the task's already-committed result in and
continues from the step after it. **That next step is read from the completed task's own stored routing write —
`tup.pending_writes` carries a `branch:to:<node>` channel naming exactly which of that node's possibly several
conditional destinations was actually taken this run — never a hand-written, topology-specific table, which
cannot represent a single node routing to different destinations on different turns** (FR-052; Kestrel's own live
graph has exactly two edges with no such write at all — `judge → record` and `record → decide`, each always the
same single destination — both covered by `_STATIC_NEXT_STEP`; every other node's own outgoing edge is
conditional and so always carries its own `branch:to:` write). `completed` is carried on `Resumable` so a caller
that needs to know specifically
whether *send* has already happened (FR-044's in-flight-message rule) can define it correctly: **"past send" means
`from_step` is `"evidence"`, `"judge"`, `"decide"`, or `"record"`** — every one of those steps only ever becomes
the resume point once send has already run for the pending turn, whether send itself just completed (its own
commit window) or an earlier step in the same turn did. `"decide"` (the shared `_decide_next` step) is a
legitimate `from_step`/`run.resumed` value like any other, not an omission.

Used by: the start-up sweep (every `in_progress`, `mode == "adaptive"`, `is_checkpointed` row — everything else
closes exactly as today, with no call into this function at all); `GET /api/runs/{id}` and the run-list endpoint
(both now `async def`), which derive `run_state` from this result (FR-054); the decision-validation step, which
additionally compares the paused interrupt's own turn against what the request named; and Stop, which reads
`Resumable.snapshot.values`/`ReachedEnd.outcome` for the fields it records (below).

**`run_state`, one classification-derived field replacing a reconstruction from `resumable`/`paused` alone**
(FR-054): `Running` → `"running"`; `Paused` → `"paused"`; `ReachedEnd`, `NoCheckpoint`, or `Unreadable` →
`"stoppable"`; `Resumable` → `"resumable"`; not `is_checkpointed`, or a finished row → `"stoppable"` is never
reached (the live classification path is not even entered) and the field reads `"finished"` once `status ==
"finished"`, else the run's own mode-appropriate value outside this feature's reach is left to the existing
`status` field alone to describe (this feature's own five values only ever apply to an `is_checkpointed` row).
`resumable`/`paused` stay on the response, still computed from the same classification, for backward
compatibility with anything already reading them — but the UI's own control logic reads `run_state` alone, never
reconstructing it from `resumable`/`paused`, which cannot tell a leased run (`"running"`) apart from a reached-END,
no-checkpoint, or unreadable one (`"stoppable"`): all four combinations read `resumable: false, paused: false`
identically.

## The execution lease (research D12)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-038, FR-055, and the test
functions `tasks.md` names for them.*

```python
# Held on app.state, never a bare module-level object — two unrelated apps (e.g. two test apps over different
# databases) must never share lease keys.
app.state.leases: set[int] = set()
app.state.accepted_exits: set[int] = set()   # research D26 — which held leases are about to release on ACTIVITY

@contextmanager
def lease(app_state, store, run_id: int):
    if run_id in app_state.leases:
        raise RunLeased(run_id)   # -> 409, "This run is currently executing."
    app_state.leases.add(run_id)
    try:
        yield
    finally:
        app_state.leases.discard(run_id)
        if run_id in app_state.accepted_exits:         # set.discard() itself always returns None — never branch
            app_state.accepted_exits.discard(run_id)   # on its own return value; check membership first
            store.touch_last_activity(run_id, now=app_state.clock())

def mark_active(app_state, run_id: int) -> None:
    app_state.accepted_exits.add(run_id)   # called once a handler's own preconditions pass, just before it acts —
                                            # by every accepted-exit caller except the automatic idle check itself,
                                            # which must never call this (research D26)
```

Every request that starts, resumes, decides, or stops a run acquires this lease before doing anything else that
could race with another such request, and releases it in a `finally`. **The original start takes it immediately
after `claim_run` succeeds**, inside `run_adaptive` itself, before the first graph invocation — not only resume,
decision, and stop (research D12) — and holds it for the rest of that request, including the shared finishing
function (below) when it is the request that finishes the run. This includes calling `mark_active` on its own
exit, exactly like a later resume or decision does on its (research D26) — the original start is not a
special case here, only the first caller to ever hold this particular run's lease at all. **`mark_active` is what
tells an accepted exit from a refused one** (research D26): a handler calls it only once its own preconditions
have already passed and it is about to actually invoke the graph or perform the stop — never before, so a request
refused by a precondition (a `409` of any kind) never marks itself active, and the lease's own release then never
touches `last_activity_at` for it. The automatic idle check (below) is the one caller that deliberately never
calls `mark_active` at all, whether its own stop attempt succeeds or fails — an automatic stop is not one of
FR-059's own accepted-exit kinds.

## The approve node (`attack/graph.py`, added to `LIVE_GRAPH`'s topology when part 2 ships; research D4, D7)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-018 to FR-024, and the
test functions `tasks.md` names for them.*

```python
async def _approve_node(state: _State, runtime: Runtime[_LiveDeps]) -> _State:
    spent = {"time_spent_s": _time_spent(runtime)}   # every return on a path that actually completes sets it too
    turn = state["turns_used"] + 1
    if not state.get("ask_before_each_turn", False) or turn == 1:
        return spent
    decision = interrupt({"turn": turn, "message": state["pending_message"]})   # suspends here, no return, on the
                                                                                  # pausing pass itself (research D24)
    if decision == "run_to_end":
        return {**spent, "ask_before_each_turn": False}
    return spent   # "approve" (validated and resolved one layer up, research D8): proceed to send
```

No `"stop"` branch (Stop never reaches the graph, research D7). Wired as `attacker → approve → send`, replacing
the #49 edge `attacker → send`, on `LIVE_GRAPH`'s one topology. `REPLAY_GRAPH` keeps the #49 edge unchanged; the
experiment harness keeps calling bare, checkpointer-free `LIVE_GRAPH` directly — once part 2 ships, that call does
pass through the new node, but always as the no-op branch, since an experiment repetition never sets
`ask_before_each_turn`.

## Decision validation and resume (research D8)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-038, FR-039, and the test
functions `tasks.md` names for them.*

```python
class DecisionRequest(BaseModel):
    turn: int              # the pending turn this decision answers
    decision: Literal["approve", "run_to_end", "stop"]
```

The handler: acquire the lease; **before opening any scope**, check the run's own plain columns —
`mode == "adaptive"`, `is_checkpointed`, and `status == "in_progress"` — refusing (`409 not_paused`) at once, with
no scope ever opened, if any of these fails: a request against a run that was never checkpointed, or one already
finished, must never bind a scope whose later exit would write something that refusal never earned — a stray
`run.end` for a run that was never checkpointed in the first place, or a stray `run.interrupted` if that same
refusal were instead raised as an exception inside an already-checkpointed scope. Only past this does it open
**one** `events.reopened_run_scope(run)` for the whole decision (never a
second, nested one later, including for `"stop"` — research D29); classify. If the result is not `Paused`, refuse
(`409 not_paused`). If `request.turn != result.turn`, refuse (`409 not_paused`, "This run's pending turn has
already moved on.") and send nothing. Past validation, emit `run.decided` once. For `"stop"`, call `mark_active`
(this is a user-triggered exit, research D26) then call `stop_run(..., triggered_by="user")` — **within this same,
already-open scope**, never opening another — instead of any `Command` call. For `"approve"`/`"run_to_end"`, check
preconditions (research D15/D16), call `mark_active`, then call `ainvoke(Command(resume={result.interrupt_id:
request.decision}), thread_config(run_id), context=deps, durability="sync")`.

**`/resume`'s own handler follows the identical shape, for the identical reason**: acquire the lease;
**before opening any scope**, check the same plain columns (`mode == "adaptive"`, `is_checkpointed`,
`status == "in_progress"`) and refuse `409 not_resumable` at once, nothing bound, if any fails — a request
against a run never checkpointed, or already finished, must never bind a scope whose exit would then write a
`run.end` or `run.interrupted` a refusal never earned, exactly as above. Only past this does it classify. A
`ReachedEnd` result is **not** a 409 here (`contracts/api.md`): it is reconciled on the spot by calling the
identical shared mechanism `/stop` itself calls — `stop_run(..., triggered_by="user")` — never a second,
parallel reconciliation of its own; this is why classification's own doc (above) names only "Stop" as the reader
of `Resumable.snapshot.values`/`ReachedEnd.outcome`, not a separate resume-side reader. `run.stopped` is what
this emits in that case (`reconciled=True`, `trigger="user"`), the same as any other caller reaching this
mechanism — never `run.resumed`, since nothing is, in fact, resumed. A `Resumable` or `Paused` result opens
**one** `events.reopened_run_scope(run)` before calling `mark_active` and invoking the graph (`ainvoke(None,
thread_config(run_id), context=deps, durability="sync")` for a plain resume; `Command(resume=...)` only when the
loaded state itself already holds one, which `/resume` never constructs on its own — that is `/decision`'s job).

## Stop (research D7, D11, D29): no graph call, for any resumable run — and no lease or scope of its own

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-040, FR-051, FR-055,
FR-056, FR-058, the `contracts/`, and the test functions `tasks.md` names for them.*

**`stop_run` is reached by three callers, each already holding `run_id`'s execution lease and each already inside
its own open logging scope before it calls in** — the `/stop` endpoint handler acquires the lease, **validates
the run's own plain columns (`mode == "adaptive"`, `is_checkpointed`, `status == "in_progress"`) before opening
any scope** — refusing at once, with nothing bound, if the row is not a genuine candidate (the same validation the
decision handler above performs for itself) — and only then opens `events.reopened_run_scope(run)`, immediately
around its own call into this function, since it has no other scope open at that point; `check_idle_runs`
(research D27) needs no such validation of its own — its own listing query
(`store.list_in_progress_checkpointed_runs`) already returns only `is_checkpointed`, `in_progress` rows, so every
row it ever reaches this far with is already a genuine candidate by construction — and, like the endpoint handler,
opens its own scope immediately around its own call, having none already open; the decision handler (above),
deciding `"stop"`, already holds the lease, already passed this same column validation, and already has its own
scope open for the whole decision (`run.decided` emitted first) before it reaches this same call, and opens no
second, nested one for it. `stop_run` itself
therefore **neither acquires nor releases the lease, nor opens nor closes a scope, nor performs any validation of
its own**
— all three are the caller's own job, done before `stop_run` is ever reached. Only a **user**-triggered caller (the
endpoint handler, or the decision handler) calls `mark_active` before calling in — never `check_idle_runs` (research
D26, D27): an automatic stop is not one of FR-059's own accepted-exit kinds, whether it succeeds or fails.

```python
async def stop_run(store, graph, app_state, run_id: int, *, settings,
                    triggered_by: Literal["user", "idle_timeout"] = "user") -> Run:
    # The caller already holds run_id's lease and already has its own scope open; this function touches neither.
    status = await classify(graph, run_id, leased=False)
    if isinstance(status, (NoCheckpoint, Unreadable)):
        # FR-056: the exact close the sweep itself performs for this shape, same reason text, no write-back —
        # never a 409 that would otherwise trap the target until a restart; triggered_by changes nothing here.
        run = store.finish_run(run_id, verdict="unclear", judge_used=False, stopping_condition="interrupted",
                                reason="Kestrel stopped while this run was in progress, so it was interrupted.")
        store.delete_checkpoint(run_id)   # a no-op if nothing readable actually exists
        events.run_stopped(was_paused=False, reconciled=False, trigger=triggered_by,
                            idle_hours=(settings.resume_idle_hours if triggered_by == "idle_timeout" else None))
        return run
    if isinstance(status, Incompatible):
        raise NotStoppable(status)   # 409 — unreachable without a restart in between (the version stamp is
                                      # this same build's own), so the sweep always resolves it first
    run = store.get_run(run_id)
    state = (status.snapshot.values if isinstance(status, Resumable)
             else (await graph.aget_state(thread_config(run_id))).values if isinstance(status, Paused)
             else None)
    # an outcome already decided — whether the graph reached its own end (ReachedEnd), or the deterministic
    # checks/judge already decided one for a turn `record` has not yet durably written (Resumable,
    # state["outcome"] set) — is reconciled, never discarded as stopped_by_user, and never renamed by triggered_by.
    decided = status.outcome if isinstance(status, ReachedEnd) else (state or {}).get("outcome")
    if decided is not None:
        # FR-051: write the pending turn only when `record` itself has not run for it — never key this on
        # `turns_used + 1` alone, which `record` leaves already incremented (with the same turn's own pending
        # fields still populated, uncleared) and so would re-write as a phantom turn `turns_used + 2`.
        # `record` has not run for the pending turn exactly when the resume point names `record` itself
        # (pending, not yet completed — `from_step` is the task's own name in that case) or names a completed
        # `evidence`/`judge` task whose own routing goes to `record` — both collapse to one simple check:
        # `status.from_step == "record"`. `record`'s own commit window (`from_step == "decide"`), `decide`'s
        # (`from_step == "attacker"` or later), and the clean checkpoint after `record` all have `record`
        # already run for this turn, so none of them writes anything here.
        if state is not None and status.from_step == "record":
            turn = state["turns_used"] + 1
            store.add_turn_with_evidence(run_id, position=turn, **_pending_turn_fields(state))
        # finish_with_outcome (shared with the sweep's own reconciliation, below) passes the run's own
        # already-pinned judge_model/judge_prompt_id/judge_prompt_version through to finish_run whenever the
        # outcome it is recording was judge-decided, and states a reason — never leaves either to finish_run's
        # own column-writing UPDATE to silently null out. This is a fix to the one shared function, not
        # something Stop does differently from the sweep — and, like the shape above, untouched by triggered_by.
        run = finish_with_outcome(store, run_id, decided)
        events.run_stopped(was_paused=isinstance(status, Paused), reconciled=True, trigger=triggered_by,
                            idle_hours=(settings.resume_idle_hours if triggered_by == "idle_timeout" else None))
    else:
        last_judged = last_durably_judged_turn(store.list_turns(run_id))   # the last run_turns row with a
                                                                             # non-null judge_verdict
        # FR-060: only this, ordinary, branch's own reason text depends on triggered_by; stopping_condition is
        # "stopped_by_user" either way.
        reason = ("stopped_by_user" if triggered_by == "user" else
                  f"Kestrel stopped this run automatically after {settings.resume_idle_hours:g} hours with "
                  "nobody acting on it.")
        run = store.finish_run(run_id, verdict=(last_judged.judge_verdict if last_judged else "unclear"),
                               judge_used=last_judged is not None,
                               # Stop pins the SAME claim-time judge provenance finish_run's own UPDATE always
                               # writes every column of — never left at NULL, which would misattribute an
                               # already-judged turn to no judge at all (FR-047, Principle III).
                               judge_model=(run.judge_model if last_judged else None),
                               judge_prompt_id=(run.judge_prompt_id if last_judged else None),
                               judge_prompt_version=(run.judge_prompt_version if last_judged else None),
                               turns_used=(state or {}).get("turns_used"), tokens_used=(state or {}).get("tokens_used"),
                               stopping_condition="stopped_by_user", reason=reason)
        events.run_stopped(was_paused=isinstance(status, Paused), reconciled=False, trigger=triggered_by,
                            idle_hours=(settings.resume_idle_hours if triggered_by == "idle_timeout" else None))
    write_back_once(run)
    store.delete_checkpoint(run_id)
    return run
```

Identical for a paused run (the approve node's own Stop control) and a merely-resumable one (the general way out)
— one function, reached from `POST /api/runs/{id}/stop`, the decision handler's own `"stop"` branch, and
`check_idle_runs`. A run whose graph reached its own end, or whose pending turn's outcome was already decided but
not yet recorded, is **finished with that outcome**, never `stopped_by_user` — the same reconciliation path the
sweep performs, so Stop is never refused for either shape. `_pending_turn_fields` reads exactly the state fields
`record` itself would read to make this same call under normal operation (the drafted message, the reply, the
evidence items, the judge verdict if any) — Stop constructs no call `record` would not already make for the
identical turn, and constructs it only when `record` has not already made it (FR-051) — `status.from_step ==
"record"`, never `turns_used` alone, which `record`'s own increment makes indistinguishable from "one turn further
along."

## Write-back exactly once (research D19)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-043, FR-055, and the test
functions `tasks.md` names for them.*

**`run_adaptive` keeps calling `finish_run` directly and returns the finished `Run` to whichever caller invoked
it, exactly as it does today — this never changed; only who calls the *finishing function* on top of that did**
(FR-055). This matters because `run_adaptive` is shared code: the API's own original start calls it, and so does
the experiment harness, for a cold arm that must never write back (007) and a warm one whose own `write_back`
decision `experiments/engine.py` still makes for itself, unchanged. If `run_adaptive` itself called the finishing
function, a warm arm would write back twice (once there, once in `engine.py`) and a cold arm would be warmed —
corrupting the A/B comparison and breaking FR-032. So the API-path finishing function every other finishing path
calls (a resume reaching a stopping point, a decision reaching one, Stop, and the sweep's own reconciliation; the
original start's own equivalent is `api/main.py::start_run`, reading the already-finished `Run` back from
`run_adaptive`) adds only three things **on top of** an already-finished row: `write_back(...)` (skipped if
`run.memory_written is not None`, i.e. already attempted) → `store.delete_checkpoint(run.id)` → lease release —
it never calls `finish_run` a second time. A pause returns a still-`in_progress` row, which the function returns
untouched (a `status != "finished"` guard): nothing is written back and the checkpoint is not deleted yet, so the
run's write-back status stays unset (FR-043, FR-006). **The lease taken at the start of any of these five paths is
released on every exit, an exception included** — the lease's own `with` block (above) already guarantees this
structurally, regardless of whether the row it wraps was finished, paused, or left `in_progress` by an exception;
nothing about this function's own addition changes that.

## The live checker rebuild (research D17)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-044, and the test
functions `tasks.md` names for it.*

```python
def rebuild_live_checker(store, library, run: Run, stored_turns: list[Turn]) -> EvidenceChecker:
    planted = [t for t in store.list_planted_tokens(run.id) if t.kind == "override"]
    override = None
    if planted:
        stored = planted[0]
        seed = library.get(run.prompt_id)   # the run's own recorded seed, looked up by the id it was claimed with
        paragraph, _ref = override_module.override_task_paragraph_for_version(stored.prompt_version,
                                                                              OverrideToken.from_joined(stored.token))
        insertion = override_module.insertion_point(seed.family, seed.id, seed.text)
        override = _Planted(token=OverrideToken.from_joined(stored.token), prompt_ref=stored.prompt_ref,
                            paragraph=paragraph, task_text=insertion.frame(paragraph) if insertion else paragraph,
                            disarmed_turn=stored.disarmed_turn, recorded=False)
    checker = EvidenceChecker(canaries=store.list_canaries(run.target_id), family=run.family, store=store,
                              unsafe_output=True, override_planted=override, mask=[...])
    checker.bind_run(run.id)   # sets _run_id unconditionally; recorded=False skips the insert (research D17)
    for turn in stored_turns:
        checker.note_sent(turn.attacker_message, turn.position, emit_disarm_event=False)
    return checker
```

This is deliberately **not** `build_checker`'s own live branch (which would mint a brand-new token via
`generate_override_token()`) and **not** its replay branch (`_copied_override`, which never regenerates a
paragraph at all) — a resumed live run needs the third shape sketched above: the existing token, a freshly
regenerated paragraph, bound without a duplicate insert. `note_sent` gains an `emit_disarm_event` keyword (default
`True`, unchanged for a live run's normal, first-time call); the rebuild passes `False` for every replayed,
already-recorded turn, and (only when classification's own `Resumable.from_step` reports past send — `"evidence"`,
`"judge"`, `"decide"`, or `"record"`, never read off the raw, untranslated pending-task name) `True` for the
checkpoint's own in-flight `pending_message`, noted once more after the loop — the one call allowed to actually
disarm, if that in-flight message is what disarms it for the first time. For a family that plants nothing (`planted` is empty),
`override` stays `None` and the rebuild behaves exactly like any other family's checker, live or resumed.

## Time-spent accounting (research D24)

*This section's prose is a guide to the shape, not the spec: the binding behaviour is FR-016, and the test
functions `tasks.md` names for it.*

`_State` gains `time_spent_s: float`. **Every** node in the turn loop (`attacker`, `approve`, `send`, `evidence`,
`judge`, `record`) includes it in its own returned delta, recomputed fresh each time as
`deps.time_spent_at_invocation_start + (deps.clock() - deps.invocation_start)` — never an increment, and never
left to `record` alone. This is not redundant: the `approve` node cannot return a delta at all on the pass where
it actually pauses (`interrupt()` suspends the node function before it reaches its own `return`), so if only
`record` set this field, a turn that pauses would never persist any of its own attacker-drafting time — the
exact bug this design avoids. Because `attacker` always completes and returns its own delta *before* `approve`
runs, and synchronous durability commits that delta before `approve` is even invoked, the time spent drafting a
turn's message is already durable by the time a pause can happen, regardless of whether `approve` itself ever
gets to run again. Every field is anchored to values fixed when this invocation's own `_LiveDeps` was built:
`time_spent_at_invocation_start` is `0.0` for a fresh claim, or the checkpoint's own stored `time_spent_s` for a
resume/decision; `invocation_start` is `clock()` called once when that `_LiveDeps` was constructed.
`_LiveDeps.deadline` is unchanged in name, type and role: a fresh claim computes it exactly as today (`clock() +
time_limit_s`); a resume or decision computes it as `clock() + (run.time_limit_s - time_spent_at_invocation_start)`.
The one case still genuinely uncounted: a crash strictly *inside* a node, before that node's own delta is
produced at all (never reaching even that node's own update) — that fraction of a step's time is neither counted
nor refunded, the one accepted consequence FR-016 itself names.

**The two time anchors live on the shared `_Deps` base, not only `_LiveDeps`** (research D23): `send`, `evidence`,
and `judge` are shared between `LIVE_GRAPH` and `REPLAY_GRAPH`, so `time_spent_at_invocation_start` and
`invocation_start` are fields of `_Deps` itself, inherited by both `_LiveDeps` and `_ReplayDeps` — a replay's own
construction site sets them the same fixed way a fresh live claim does (`0.0`/`clock()`), never reads a stored
`time_spent_s` (a replay has none). Because `_Deps` gives both fields a default and a subclass may still need its
own *non*-defaulted fields afterward, every `_Deps`-derived dataclass is `kw_only=True` (`@dataclass(kw_only=True)`
or per-field `field(kw_only=True)`) — a defaulted base field followed by a required subclass field is otherwise a
plain `TypeError` at class-definition time, independent of anything this feature does at runtime.

**Per-turn carry-over, named**: a resumed or decided mid-turn's own lines must report only that turn's own
real processing time, and must carry over the attacker call's already-recorded tokens/cost when that call is not
re-executed (`contracts/log-records-delta.md`). `_State` gains two further fields the `attacker` node's own delta
sets alongside `time_spent_s` whenever it actually runs: `turn_time_spent_at_start: float` (a copy of
`time_spent_s` as it stood *before* this turn's own elapsed time was added — the baseline a later `record`/`run.end`
line subtracts to report only this turn's own share) and `turn_attacker_usage: {"tokens": int, "cost": float}`
(the attacker call's own tokens and cost for this turn, read back unchanged by every later step of the same turn
that does not itself call the attacker again). A segment that resumes mid-turn without re-entering `attacker`
reads both straight from the loaded checkpoint, exactly as it would any other already-set state field — never
re-derived, and never reported as missing.

## Provenance pinning (research D16)

*This section's prose is a guide to the shape, not the spec: the binding behaviour is FR-041, FR-047, and the
test functions `tasks.md` names for them.*

A resumed or decided run's `_LiveDeps` reads `attacker_model`, `attacker_prompt_id`/`.version`, `judge_model`,
`judge_prompt_id`/`.version`, and the turn/token/time-limit caps from the run's own stored row — never from
whatever Kestrel is currently configured with — and constructs its attacker/judge clients against exactly those
values. "Unavailable" is checked narrowly: the pinned prompt-version file no longer exists (`prompt_registry
.text_for` cannot find it), or the API key the pinned client needs is not configured; either one refuses the
request with `409 pinned_model_unavailable`, naming the missing value. A pinned model *slug* itself is never
validated this way (nothing short of an actual call could confirm it) — Stop remains available regardless, since
it builds no client at all.

## The OWASP exclusion (research D25)

*This section's prose is a guide to the shape, not the spec: the binding behaviour is FR-050, and the test
function `tasks.md` names for it.*

`api/main.py::target_report`'s own input is filtered one call site earlier, to `[r for r in
store.list_runs(target_id) if r.status == "finished"]` — replacing today's unfiltered list the same way the
existing replay exclusion already narrows it.

## `run.end` suppression (research D21): narrow and defensively guarded, never a store read at exit

*This section's prose is a guide to the shape, not the spec: the binding behaviour is FR-046, FR-053, and the
test functions `tasks.md` names for them.*

`RunContext` (the scope's own bound state) gains two plain fields, **never** read from the store at scope exit:
`checkpointed: bool`, and `finished: bool`, starting `False` and flipped to `True` by the one shared finishing
function (write-back exactly once, above) the moment it actually finishes that run's row, if it does so before the
scope exits. **`checkpointed` is set once when the scope opens, and `run_scope()` itself is where every scope —
including the original start's own, FR-053 — sets it, not only a later helper**: the original run-start path
passes `checkpointed=True` into `run_scope()` (via `events.run_started(store, ..., checkpointed=True)`) the
moment it claims a checkpointed row, before `run_adaptive`'s first invocation — never left for a *later* request
to set, since the very first segment of a checkpointed run is exactly where a pause or an in-process exception
can happen first, and it must be governed by this same rule from that first segment on. A resume, a decision, or
Stop opens its own logging scope with **`events.reopened_run_scope(run)`** instead of `run_scope()`, since none of
them is a fresh start and none should emit a second `run.start` for the same run id; it binds the run exactly as
`run_scope()` does, copying `checkpointed` straight from the `Run` it is already given, never a fresh store
lookup, but emits no `run.start` line of its own. The scope-exit code that today unconditionally emits `run.end`
branches on these two fields alone:

- not `checkpointed`, or `checkpointed` and `finished`: emits `run.end` exactly as it does today, for every exit —
  a clean return, a cap, Stop, or an exception escaping — including naming the class of any exception that escaped.
  This is every single-turn run, every replay, every experiment repetition, and a checkpointed adaptive run whose
  scope *did* finish the row.
- `checkpointed` and not `finished`, exiting **cleanly** (a pause — `run.paused` already names it, below): emits
  neither `run.end` nor `run.interrupted` — nothing "interrupted" happened, the run is exactly where it meant to
  stop, and its own pause is already on the kept log.
- `checkpointed` and not `finished`, exiting on an **exception**: emits a kept `run.interrupted` line in place of
  `run.end` — `resumable: true` (the row is still `in_progress`, its checkpoint still intact, by FR-042's own
  guarantee) and `error` set to the exception's class name, **never its text** (the same bar `run.end` already
  holds itself to) — so the run's own kept log and the stream both still say *that* this segment ended and why,
  even though the row itself has not finished and no `run.end` fires for it. This is the only place `run.interrupted`
  is written outside the start-up sweep (`contracts/log-records-delta.md`), and the only way an in-process failure
  under the reversed FR-042 leaves any trace at all before the run is next touched. Because `checkpointed` is now
  set from the very first segment on (FR-053), this applies to the original start's own scope too, not only a
  reopened one.

A scope that never sets `checkpointed` to `true` — whether because it was opened with no run bound at all, or
because the run it is bound to is not checkpointed — is unaffected by construction: `checkpointed` defaults
`false`, and the exit code never calls into the store to find out. `tests/unit/test_run_log_handler.py`'s own
`FakeStore` (which implements only `add_log_line`) binds both a store and a run, but one whose checkpointed status
this exit check never reads either way, for the same reason — no pre-existing test needs a new store method it
does not already have.

## Automatic stop after idle time (research D26 to D31; owner review, PR #55)

*This section's code is a guide to the shape, not the spec: the binding behaviour is FR-057 to FR-062, the
`contracts/`, and the test functions `tasks.md` names for them.*

```python
def idle_hours(run: Run, app_state) -> float:
    last_activity = datetime.fromisoformat(run.last_activity_at)   # stored as ISO text (store.py) — parsed once
                                                                     # here: never subtract a str from a datetime
    return (app_state.clock() - last_activity).total_seconds() / 3600.0   # wall-clock only, no max()

async def check_idle_runs(store, graph, app_state, settings) -> None:   # D27: the periodic task only, never the sweep
    now = app_state.clock()
    if now - app_state.started_at < min(timedelta(hours=1), timedelta(hours=settings.resume_idle_hours)):
        return   # the restart grace period: a pure no-op tick, deliberately, for every row
    for run in store.list_in_progress_checkpointed_runs():
        try:
            if idle_hours(run, app_state) < settings.resume_idle_hours:
                continue   # not yet due by the listing's own last_activity_at alone — never even attempt a lease
                           # for it: last_activity_at only ever moves forward, so this can only under-count idle
                           # time, never wrongly skip a row that is genuinely due; a live user's own
                           # resume/decision/stop on a not-yet-due row must never be refused by a check that was
                           # never going to stop it anyway. This read sits inside the per-row try below, so a row
                           # whose own last_activity_at cannot even be parsed is that row's own failure, never
                           # the whole tick's.
            with lease(app_state, store, run.id):   # raises RunLeased immediately if already held
                # re-read, re-classify, re-measure idleness fresh, under the lease — never trust the listing above
                fresh = store.get_run(run.id)
                if fresh.status != "in_progress":
                    continue
                status = await classify(graph, fresh.id, leased=False)
                if run_state_for(status) not in ("paused", "resumable", "stoppable"):
                    continue
                if idle_hours(fresh, app_state) < settings.resume_idle_hours:
                    continue
                # this check has no request-scope of its own, unlike the /stop endpoint handler or the decision
                # handler — it opens its own, immediately around this one call; it never calls mark_active: an
                # automatic stop, successful or not, is not an accepted exit (research D26)
                failure: Exception | None = None
                with events.reopened_run_scope(fresh):
                    try:
                        await stop_run(store, graph, app_state, fresh.id, settings=settings,
                                        triggered_by="idle_timeout")
                    except Exception as exc:
                        # caught here, before the scope closes, so a failed attempt writes nothing kept to this
                        # run's own log — never a kept run.interrupted for a mere stop attempt that failed, which,
                        # with no backoff, would otherwise repeat every tick and fill the run's own log toward its
                        # cap. Re-raised below, once the scope has already exited cleanly, so the per-row handler
                        # beneath still logs it.
                        failure = exc
                if failure is not None:
                    raise failure
        except RunLeased:
            continue   # skipped; reconsidered at the next tick, never waited for
        except Exception as exc:
            events.emit("idle_stop.check_failed", logging.ERROR, scoped=False, run_id=run.id,
                         exc_type=type(exc).__name__)
            continue   # this run's own failure never stops the rest of the tick, or a later tick

async def idle_stop_loop(app_state, store, graph, settings, interval_s: float = IDLE_CHECK_INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await check_idle_runs(store, graph, app_state, settings)
        except asyncio.CancelledError:
            raise   # teardown asking the task to stop — never swallowed, never logged as a failure
        except Exception as exc:
            # a failure outside any single run's own handling (for example, the listing call itself raising) —
            # named with no run_id at all, since none is implicated (never a literal null); the loop task itself
            # still survives for the next interval — a per-row catch alone cannot reach a failure this far outside it
            events.emit("idle_stop.check_failed", logging.ERROR, scoped=False, exc_type=type(exc).__name__)
        # teardown's own cancel()+await is itself guarded the same way: neither a clean CancelledError nor any
        # other exception (already logged above) is left to escape and interrupt tracing shutdown
```

**The idle clock (D26)**: `runs.last_activity_at` is set once at claim (to the claim's own moment) and updated
only on an **accepted** exit from this run's execution lease — a pause, an in-process error the process survives,
or a resume/decision/stop whose own preconditions passed and which therefore actually invoked the graph or
performed the stop. The lease itself carries a `mark_active()` flag, set by the handler immediately before it
acts (never before its preconditions are checked); its own exit touches `last_activity_at` only if that flag was
set, so a refused request (which never calls `mark_active()`) structurally cannot reset the clock — this is the
fix for a request that takes the lease, fails a precondition, and would otherwise look like activity. A run's
idle time is plain wall-clock `now - last_activity_at`, with **no** `max()` against anything — a genuine process
death updates nothing (nothing runs to record it), which is exactly why the grace period below exists, rather
than trusting this timestamp the instant a new process starts.

**The check (D27)**: `check_idle_runs` runs **only** from the periodic `asyncio` background task (`lifespan`,
started after the sweep, for as long as the app stays up, cancelled **and awaited** at teardown, before tracing
shuts down) — **never** as a separate pass during the start-up sweep itself, which has nothing left for it to
find (every reached-end/no-checkpoint/unreadable row the sweep would itself reconcile or close is already handled
before any idle check could run, and a genuinely resumable/paused row's wall-clock idle time does not depend on
whether the process just started). Before touching any row, each tick checks the **restart grace period**: if
less than `min(1 hour, configured window)` has elapsed since `app.state.started_at`, the whole tick is a no-op.
Past that, for each `is_checkpointed`, `in_progress` row, inside that row's own per-row handling: **first** a
cheap, lock-free check against the listing's own `last_activity_at` alone (parsing it first can itself raise, so
this sits inside the same per-row handling as everything else, never ahead of it): a row not yet idle by that
reading is skipped **without ever attempting its lease** — `last_activity_at` only ever moves forward, so this can
only under-count idle time, never wrongly skip a row that is genuinely due, and it keeps a live user's own
resume/decision/stop on a not-yet-due row from ever being refused by a check that was never going to stop it
anyway. Only a row that already looks overdue proceeds: skip outright if already leased; otherwise take the lease
and, **under it**, re-read the row, re-classify it, and recompute its idleness fresh — never trusting the listing
read before the lease was acquired, since a resume or decision can be accepted in between — skipping if the row is
no longer `in_progress`, no longer `"paused"`/`"resumable"`/`"stoppable"`, or no longer idle by that fresh read.
Past all of that, this check opens its **own** `events.reopened_run_scope(run)` (it has no request-scope of its
own to reuse, unlike the `/stop` endpoint handler or the decision handler) and calls `stop_run` with
`triggered_by="idle_timeout"` — **never** `mark_active` (research D26): an automatic stop, successful or not, is
not one of FR-059's own accepted-exit kinds, so it must never reset the very clock it is itself reading. **A
failed stop attempt is caught inside that scope, before it closes**, so the scope exits cleanly and writes nothing
kept to the failing run's own log (never a kept `run.interrupted` for a mere stop attempt — which, with no
backoff, would otherwise repeat on every retry and fill that run's own log toward its cap); the caught failure is
then re-raised once the scope has already closed, reaching the same per-row handler any other row's own failure
would. Any exception **raised by one run's own
handling** is caught **per run**, logged as one catalogued `ERROR` line naming `run_id` and the exception's own
class (never its text), and the tick continues to the next row. A failure **outside** any single run's own
handling — the listing call itself raising, for instance — is caught **per iteration**, one level up in
`idle_stop_loop`, logged the same way but with no `run_id` at all (never a literal `null`, since none is
implicated); either way the background task itself survives for the next interval, never ending for the rest of
the process's uptime — only `CancelledError` (teardown asking the task to stop) is let all the way through, never
caught or logged as a failure, and teardown's own cancel-and-await is itself guarded the same way, so neither a
clean cancellation nor an already-logged failure can escape and interrupt tracing shutdown. A run whose own stop
attempt fails is retried, with no backoff, at every subsequent check for which it is still due — `mark_active` is
never called for it either way, so a failed attempt never looks like fresh activity. `IDLE_CHECK_INTERVAL_S` is a
small constant (a few minutes);
`idle_stop_loop`'s own interval and `app_state.clock()` are both parameters with that constant and a real clock as
their defaults — the one seam a test needs to drive many ticks and arbitrary idle times without a real sleep.

**The setting (D28)**: `KESTREL_RESUME_IDLE_HOURS` is parsed by a new, narrower function than the existing
`non_negative_float_or_off` (which permits zero and an `"off"` sentinel this setting has no use for) — strictly
positive, finite, numeric, and no larger than `87,600` (ten years), or Kestrel refuses to start.
`Settings.resume_idle_hours: float`, default `24`, reported on `GET /api/config` as `idle_hours` in its own new
`resume` group — never folded into the existing `adaptive` group, which `test_api_config_adaptive.py` already
asserts as an exact, closed object with no room for a new key.

**The outcome (D29)**: `stop_run` gains `triggered_by: Literal["user", "idle_timeout"] = "user"` but **neither
acquires a lease nor opens a scope of its own** — both belong entirely to whichever of its three callers reaches
it (the `/stop` endpoint handler, the decision handler's own `"stop"` branch, or `check_idle_runs`), each already
holding the lease and already inside its own open scope before calling in (the endpoint handler and
`check_idle_runs` each open one immediately around their own call, having none already open; the decision handler
reuses the one scope it already opened for the whole decision, `run.decided` included, rather than opening a
second, nested one for a `"stop"` decision specifically) — so a manual Stop and an automatic one still log
identically, a kept `run.stopped` and the scope's own eventual `run.end` either way, without `stop_run` itself
needing to know which caller it was reached from. Each of the three branches keeps its own, already-correct
`stopping_condition` and reason exactly as research D7/D11 define them — `triggered_by` only changes the
**ordinary** branch's own reason text (the automatic sentence, reading `resume_idle_hours` at the moment of the
stop, never a value captured at claim time, since the setting could change in between); the **reconciled** branch
and the **no-checkpoint-or-unreadable** branch are completely untouched by it. `run.stopped`
(`contracts/log-records-delta.md`) gains `trigger` (`"user"`/`"idle_timeout"`, always present) and `idle_hours`
(present only when `trigger == "idle_timeout"`) — these two fields are the *only* place an automatic stop is
actually named as such; nothing about `stopping_condition` or the stored `reason` changes shape because of them.

**Visibility (D30)**: `idle_stop_at = max(last_activity_at + resume_idle_hours, app_state.started_at + min(1 hour,
resume_idle_hours))` whenever classification currently reads `"paused"`, `"resumable"`, or `"stoppable"`, computed
alongside `run_state` from the same classification call (never a second store read); `null` otherwise — the
*earliest* time an automatic stop may happen, never a promise of exactly when (the real stop waits for the first
tick that finds it idle past this, up to one check interval later). The second term of that `max()` matters
precisely when a run is already overdue before a restart: without it, `idle_stop_at` would show a time already
in the past throughout the grace period FR-059 itself grants it — exactly when a returning user most needs an
honest deadline, not one that looks already missed. Because `uq_runs_active` limits a target to at most one
`in_progress` run, a target's own run list shows this run, if it has one, **at the top of that one target's own
list** — never a cross-target grouping, which this feature does not build; a stuck run on a *different* target is
surfaced through a small cue on the target selector itself instead (D31). The UI test proving this (T063/T064)
checks structurally — this run appears ahead of the rest of its own target's list, and shows its own
`idle_stop_at` — never a hard-coded exact heading string, so a later wording tweak to either label does not break
it, and never seeds two `in_progress` runs on one target, a shape `uq_runs_active` already forbids.

**The selector cue is backed by a real API field, not a UI guess (D31)**: `GET /api/targets`'s own `TargetSummary`
gains `needs_attention: bool` (FR-062) — `true` when that target's one possible `in_progress` run currently
classifies `"paused"`, `"resumable"`, or `"stoppable"`; `false` when it has none, or that run is currently leased.
Computed by calling the identical classification function (research D13) already used for `run_state`/
`idle_stop_at`, over that one run if it exists — never a second, independent check, so the three fields can never
disagree about the same run. `GET /api/targets` becomes `async def` for this, the same change research D14 already
made to the run-detail and run-list endpoints for the identical reason. The UI reads this field alone for its cue
— never a per-target `GET /api/targets/{id}/runs` call on every rerun, and never a guess from a field
`TargetSummary` already carried, since the UI holds no logic of its own (CLAUDE.md). The cue is a caption rendered
directly beneath the selector, **never part of an option label**: Streamlit's selectbox round-trips the *formatted*
option string, so a label that changed between passes — the cue flipping when the run finishes — deserializes into
a stale string and silently resets the picker to "New target", blanking the form; the option labels stay exactly
`name · url` for this reason (found live: approving the final turn blanked the form, disabled "Run attack", and
made the next connection test 422).
