# Phase 0 Research: LangGraph Checkpointer and Approve Node (014)

All decisions respect the clarification recorded in `spec.md` (session 2026-11-25: a **custom checkpoint saver, no
new dependency** — the owner's own, verbatim answer; see `spec.md`'s Clarifications for the exact wording and the
three conditions the owner attached, carried here as FR-035 to FR-037). Every fact below was verified directly
against the installed `langgraph`/`langgraph-checkpoint` (1.2.17 / 4.3.0) and Kestrel's own source, not assumed.

## Code facts this builds on

- **The #49 foundation** (`src/kestrel/attack/graph.py`): `LIVE_GRAPH`/`REPLAY_GRAPH` are `StateGraph` instances
  compiled once, at import, with no checkpointer attached. Every per-run value travels as the frozen
  `_LiveDeps`/`_ReplayDeps` runtime context, read by every node as `runtime.context` — never a closure. `_State`/
  `_ReplayState` are `TypedDict`s (`total=False`, so an omitted key is simply absent, not an error); `conversation`
  (and a replay's `turn_results`) are reducer-appended. `_wire(graph)` adds the six shared nodes and their edges;
  `_compile_live()`/`_compile_replay()` each add their own `attacker`/`record` node before calling `_wire`.
- **The start-up sweep** (`api/main.py:113-115`, `store.py::close_interrupted_runs`): today, one unconditional
  `UPDATE runs SET status = 'finished', ... WHERE status = 'in_progress'`, run inside `create_app(...)`, before the
  app or its lifespan exists.
- **`add_turn`/`add_evidence`** (`store.py:947-963`, `866-875`) are separate transactions, called one after the
  other (`graph.py:347-355`), with no uniqueness constraint on `(run_id, position)` today.
- **`runs`'s existing provenance columns**: `attacker_model` is already settable at `claim_run` time
  (`store.py:791`). `judge_model`, `judge_prompt_id`, `judge_prompt_version` exist as columns but are written only
  by `finish_run` (`store.py:825-830`) — never at claim. `attacker_prompt_id`/`attacker_prompt_version` exist only
  on `run_turns` (per turn, from turn 2 onward) — `runs` itself has no such columns, and `claim_run` takes no
  prompt-reference parameters at all today.
- **The evidence checker's own state is not graph state** (`evidence/checker.py`): `_sent.texts`, `_override`
  (armed/disarmed), `_kinds_found`/`_items_count` are plain instance attributes. A replay's own rebuild
  (`_copied_override`, `checker.py:313-321`) sets `paragraph=None`, so `planted_task_texts()` returns `[]`
  (`checker.py:188-193`) — correct for a replay (it resends the source's own stored text verbatim, never
  regenerating a paragraph), wrong for a live resume: a live run's own task text must still be stripped from the
  shared pattern pool and retrieval queries, which needs the paragraph and frame regenerated, not left absent.
  `bind_run(run_id)` sets `self._run_id = run_id` **unconditionally, before** checking whether to insert a planted-
  token row — so calling it with a `_Planted` already marked `recorded=False` both binds the run id (enabling a
  later disarm to persist) and skips the insert, with no special casing needed.
- **`_LiveDeps` is never part of a checkpoint** — confirmed from `Checkpoint.channel_values`'s own shape: it holds
  only the graph's own channels, never the runtime context object.
- **Installed versions**: `langgraph==1.2.17`, `langgraph-checkpoint==4.3.0` (ships `BaseCheckpointSaver`,
  `InMemorySaver`, `serde.*` — no SQLite saver). The rejected alternative (`langgraph-checkpoint-sqlite`) resolves
  to `3.1.3` against this project and itself requires `aiosqlite>=0.20`, `sqlite-vec>=0.1.6`, and
  `langgraph-checkpoint<5.0.0,>=4.3.1` (this project's installed `4.3.0` does not satisfy that bound) — three new or
  bumped dependencies the owner's own decision rejected in favour of the custom saver.
- **A checkpointer makes `thread_id` mandatory on every call against the compiled graph it is attached to**: an
  attached copy invoked with no `thread_id` raises `ValueError: Checkpointer requires one or more of the following
  'configurable' keys: thread_id, checkpoint_ns, checkpoint_id`; an unattached instance needs no `configurable`
  entry at all.
- **`Pregel.copy(update=...)` produces a fully independent compiled object**: giving it a new `checkpointer` leaves
  the original object's own `checkpointer` at `None` and keeps the same node set — one copy per app, taken from the
  one already-compiled `LIVE_GRAPH`, is sufficient; there is no need for a second, separately *compiled* instance.
  **What `.copy()` does not carry over**: the compile-time, schema-derived msgpack allowlist LangGraph computes
  under strict mode (`_serde_allowlist`) is reset to `None` on the copy. This allowlist is a *compiled-graph*-level
  mechanism, separate from whatever serializer object the attached checkpointer itself carries as `.serde` — so it
  only matters for code that would otherwise have relied on it; the saver's own, explicitly constructed serializer
  (below) is unaffected by it either way, since that serializer already carries its own allowlist, independent of
  anything the graph's own compile-time inspection computes.
- **Durability is a per-call argument (`ainvoke(..., durability=...)`), never a property of the compiled object**:
  the same compiled graph behaves differently under the library's own default versus `durability="sync"`. Under the
  default, a full turn's worth of nodes (attacker, send, evidence, judge, record — five steps) and the next turn's
  own first two steps can all start before a single checkpoint has been durably written — the default mode lets
  execution run arbitrarily far ahead of what is actually saved. Under `"sync"`, each node's own writes and the
  following checkpoint commit land before the next node starts — this is why FR-010/FR-011's "only the one in-flight
  step may repeat" guarantee needs `durability="sync"` specifically: under the default, several already-completed
  steps could be behind the last durable checkpoint, each one a candidate for an unwanted repeat. Passing
  `durability=` to a graph invocation that has **no** checkpointer attached at all logs a warning that the argument
  has no effect — so it is passed only on calls against a checkpointed, per-app graph copy, never on the experiment
  harness's own call against the bare module-level graph.
- **A node whose writes were stored, but whose own checkpoint commit was interrupted before landing, is not
  re-run on resume under `durability="sync"`**: resuming from a freshly built graph and saver object over the same
  file (simulating a real restart) does not re-run the node whose writes already landed — the run reaches its
  natural conclusion normally, with no node's own count showing a duplicate for that step. This is the positive half
  of the durability decision: `durability="sync"` plus LangGraph's own pending-writes replay is what makes "the
  in-flight step may repeat, nothing earlier does" actually hold.
- **An interruption during the record step's own two writes risks exactly the gap FR-012 forbids**: if a turn's row
  and its evidence were still two separate writes, an interruption between them would leave a turn recorded with no
  evidence, silently, and a later resume's own existence check (keyed on the turn row alone) would then skip writing
  the evidence forever — the turn and its evidence must be one atomic write, not two guarded calls.
- **A node that raises an ordinary exception while the process stays alive leaves the checkpoint in the same shape
  a process death would**: the failed step is next in line to run again; resuming without first finishing the row
  re-runs exactly that step. This is the basis of this feature's unified rule for any interruption of a checkpointed
  run (FR-042): both a process death and an in-process exception leave the same resumable shape, so both are
  handled by the same mechanism — there is no separate "finish it at once" handler for the in-process case, and
  deliberately so: a handler like that would have to be bypassed for exactly the exceptions that mean the process
  itself is going away (a cancellation, a keyboard interrupt, a `SystemExit`), which defeats the purpose of having
  one at all. The simplest correct rule is to have no such handler, and let the lease's own release (below) be the
  only thing that happens when any exception propagates.
- **`interrupt()`/`Command(resume=...)` mechanics**: turn 1 never pauses; the first pause returns a result carrying
  `__interrupt__` with the exact drafted message, at the cost of nothing beyond what that turn already did; a bare
  re-invoke with nothing to resume reproduces the identical interrupt and writes no new checkpoint — a read-only
  status re-check is genuinely free; a validated `Command(resume=...)` sends and (if the run continues) pauses
  again at the next turn, never advancing the turn counter past the last turn actually sent when the decision is
  "stop".
- **A decision that is not validated against the specific interrupt it targets can resolve silently against the
  wrong one**: after one real decision correctly resolves a turn and the run pauses again at the next one, a second,
  stale decision meant for the turn already decided is, if sent as a bare value rather than `Command(resume={the
  exact interrupt id: value})`, simply applied to whatever is pending *now* — sending a message nobody actually
  approved. Requiring the request to name the turn (and resuming only via `Command(resume={interrupt_id: decision})`,
  never a bare value) closes this: LangGraph's own interrupt `id` is reused as that identifier, needing nothing
  Kestrel invents and stores itself, and even a validated-then-somehow-delayed request cannot resolve a different
  interrupt than the one it was validated against.
- **A decision sent as a bare `Command(resume=...)` to a thread with no pending interrupt at all is not refused —
  it is simply ignored as a resume value, and the graph continues running from its last checkpoint**: sent to a run
  that is merely cut off (not paused), it resumes the ordinary loop, which can send a message and reach a *new*
  pause — the opposite of what "stop this run" was supposed to do. This is why Stop must never be a graph
  operation at all, under any classification: finishing the row directly, from outside the graph, is the only way
  to guarantee it never has this effect.
- **Two concurrent decisions on one paused thread, with no application-level lock, both execute**: a deliberately
  slowed send step widens the race window enough to show both concurrent calls completing, both sending. LangGraph
  provides no per-thread execution lock of its own; Kestrel's own `uq_runs_active` does not help either, since the
  row is already `in_progress` — only an application-level execution lease closes this.
- **Resuming a thread whose graph already reached its own end, but whose row was never finished, is safe to read
  (no node re-executes) but is easy to misclassify**: such a thread's checkpoint has an empty `next` and no pending
  interrupt — which, read carelessly, looks identical to an ordinary "merely cut off mid-step" resumable thread.
  The two are **not** the same shape once `snap.tasks` (the Pregel-internal record of the super-step just
  attempted) is inspected too: a thread that truly reached the graph's end has **no** tasks at all, and a decided
  `Outcome` already sitting in its state; a thread cut off mid-commit (a node's writes landed, but the checkpoint
  recording that fact did not) still has exactly one task, with its own result present, and `outcome` still `None`.
  Both shapes share `next == ()`, so `next` being empty is not by itself enough to tell them apart — the full
  classification below uses `snap.tasks` for exactly this.
- **An exact instance of the mid-commit shape**: a decision is applied (the node resolving the interrupt runs and
  returns), but the checkpoint committing that fact never lands. Reading the thread afterward shows `next=()`
  (looks finished), **one task present with its result** (not truly finished — the mid-commit shape above), and the
  decision's own effect (for example, a message already sent) already real. A graph-based "stop" sent to a thread in
  exactly this shape (the old, now-discarded way to implement Stop) does not stop anything: since there is no
  pending interrupt for it to resolve, it is ignored as a resume value and the run simply continues — sending yet
  another message and pausing again further on. This is the clearest demonstration of why Stop must finish the row
  directly rather than ever touching the graph, in every classification, not only the obviously-paused one.
- **The serializer does not round-trip Kestrel's own dataclasses silently**: left at its class-level default, the
  serializer logs one warning per unregistered type on every read ("this will be blocked in a future version"), to
  a logger outside Kestrel's own stream; under the library's strict mode, those same types instead come back as
  **plain `dict`s**, silently losing their class — a correctness hazard for any code that expects
  `isinstance(state["outcome"], Outcome)`. Calling `.with_allowlist([...])` on an already-permissive saver (the
  class-level default, when strict mode is off) is a documented no-op: it returns the very same saver and the very
  same serializer object, unchanged, so the warnings persist regardless of calling it. It only has an effect when
  the serializer was already in its strict, non-permissive mode to begin with — exactly backwards from what is
  needed, since the point is to fix the *permissive* mode's warnings too. Constructing the serializer directly with
  its own `allowed_msgpack_modules` keyword, instead, fixes both: the three named types round-trip as themselves,
  with no warning, under the library's default mode and its strict mode alike, since that explicit allowlist is
  baked into the serializer object itself, independent of whichever global mode the library's own strict-mode flag
  happens to be in. That flag is read once, at import time, so a single test process cannot toggle it and observe a
  live difference — a test that must prove strict-mode behaviour either runs in a subprocess with the flag set
  before import, or constructs the equivalent serializer directly (`JsonPlusSerializer(allowed_msgpack_modules=
  [...])`) to exercise the same restriction without needing the process-wide flag at all.
- **A loaded, resumed conversation's entries come back as two-element lists, not tuples** — read through the
  compiled graph after a restart, confirmed directly: a property of the serializer this feature relies on, not a
  bug, and not something that differs between reading through the graph versus the saver directly (both show
  lists).

## Decisions

- **D1 — One checkpointer, two uses, not two mechanisms.** The same custom saver, attached to one per-app copy of
  `LIVE_GRAPH` (D2), backs both plain crash/restart resume and pause-for-approval, including a pause that survives
  a restart. A paused run **is** a resumable run whose loaded checkpoint happens to hold a pending interrupt; there
  is no separate "approval state" store.
- **D2 — Each app gets its own checkpointed copy of `LIVE_GRAPH`; the module-level graph is never mutated.**
  `app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": saver})`, built once per app inside its
  `lifespan`, after the saver is constructed (D9) and the version guard passes (D18). Every real, user-facing call
  (start, resume, decision, stop) runs against `app.state.live_graph`; the experiment harness keeps calling the
  bare module-level `LIVE_GRAPH` directly, exactly as before this feature — it needs no checkpointer, no
  `thread_id`, and no change of its own, since `LIVE_GRAPH` itself is never touched. `durability="sync"` is passed
  only on calls against a checkpointed copy (never against the bare module-level graph, which would otherwise log a
  warning that the argument has no effect with no checkpointer present). This also keeps the test suite's own
  isolation intact: each test's own app gets its own copy and its own saver bound to its own temporary database, so
  nothing is left mutated on the shared, module-level object for a later, unrelated test to trip over.
- **D3 — Every invocation of a checkpointed live graph passes `durability="sync"`.** This is the only mode under
  which a crash cannot leave the durable checkpoint more than one in-flight step behind the side effects those
  steps already caused — under the library's own default, several already-completed steps could be behind the last
  durable checkpoint, breaking FR-010/FR-011's "only the one in-flight step may repeat" guarantee outright.
- **D4 — A new, dedicated `approve` node, added to `LIVE_GRAPH`'s one topology when part 2 ships, between
  `attacker` and `send`.** Its entire body: if the run's own `ask_before_each_turn` state field is not set, or this
  is turn 1, return `{}` (no-op; read with `state.get("ask_before_each_turn", False)`, never a bracket subscript,
  so a checkpoint from a build that predates this field is still safely readable, D18/D23). Otherwise, call
  `interrupt({"turn": ..., "message": state["pending_message"]})` and, once resumed with a decision already
  validated one layer up (D8), act on it: `"approve"` → `{}` (the next turn's own call to this node interrupts
  again on its own); `"run_to_end"` → `{"ask_before_each_turn": False}` (D5). This node has no `"stop"` branch at
  all (D7): Stop never reaches the graph. Before part 2 ships, `LIVE_GRAPH` has no such node at all (the same
  six-node topology #49 left it with) — part 1's own checkpointed runs are never routed through it, since nothing
  in part 1 can set `ask_before_each_turn`.
- **D5 — "Ask before each turn" is seeded into `_State` exactly once, at claim, and never re-seeded on a resume or
  decision.** `_LiveDeps.ask_before_each_turn` is read from `runs.ask_before_each_turn` (the column set once at
  claim time) **only when building the very first initial state for a run** — a resume or a decision builds its
  `_LiveDeps` fresh (FR-005) but constructs no new initial state at all; it loads the checkpoint's own state, whose
  `ask_before_each_turn` field already reflects whatever "Run to end" may have flipped it to. Re-seeding from the
  column on every resume would silently turn pausing back on after a restart, breaking FR-022 outright — the
  column is read exactly once, by the one code path that claims a run.
- **D6 — The `record` step is made idempotent by one existence check over one atomic write, not a guard over two
  separate writes.** A new store method writes the turn row and its evidence items (when any) in a single
  transaction; the lifted, shared `record` step checks for an existing row at `(run_id, position)` before calling
  it, and when one exists, returns the same state delta an uncut execution would have returned — computed from
  `state` alone, never re-read from the row — and emits no second `turn` log line for that position. A
  `UNIQUE(run_id, position)` index on `run_turns` is kept as defense in depth, but the atomic write plus the
  existence check is what actually prevents a turn row ever existing without its evidence, or vice versa.
- **D7 — Stop is never a graph operation, for any resumable run, paused or not; it reconciles an already-decided
  outcome — the graph's own end, or a turn the deterministic checks/judge already decided on — instead of
  discarding it, and it closes an unreadable or missing checkpoint exactly the way the sweep does, not merely
  similarly.** A graph-based "stop" (resuming with a `"stop"` value) is unsafe exactly because `Command(resume=...)`
  sent to a thread with no pending interrupt is simply ignored and the ordinary loop continues (code facts, above)
  — so Stop instead: (1) acquires the run's execution lease, refusing if already held; (2) classifies the run
  (D13); (3) for `NoCheckpoint`/`Unreadable`, closes the row with the identical reason text the sweep's own close
  uses for this shape (`unclear`, `"interrupted"`) and attempts no write-back — never a 409, since nothing readable
  needs to survive for Stop to do this; (4) for a decided outcome — whether `ReachedEnd` or a `Resumable` whose own
  loaded state already holds one, because the evidence step or the judge decided it for a turn `record` had not
  yet durably written — first records that pending turn and its evidence through the same idempotent write
  `record` itself would have made, but **only when the resume point still names `record` as the step that runs
  next** (never merely because the next turn number looks unwritten, which `record`'s own prior run leaves looking
  exactly that way too, FR-051), then finishes the row with **that** outcome (the same reconciliation the start-up
  sweep performs for the `ReachedEnd` shape, D11), preserving the run's own pinned judge provenance and stating a
  reason — never `stopped_by_user`, and never silently discarding a deterministic confirmation already reached
  (Principle II); (5)
  otherwise, finishes the row with the verdict of the last **durably judged** `run_turns` row (read from the
  store, never a field that does not exist on `Run` itself), its own pinned judge provenance, and
  `turns_used`/`tokens_used` read from the checkpoint's own state, `stopping_condition = "stopped_by_user"`; (6)
  either way (steps 4/5), writes back once (D19), deletes the checkpoint (D11), and releases the lease and the
  target lock. No `ainvoke`/`Command` call is made at all, in any branch. This is the exact same function for a
  paused run (the approve node's own Stop control) and a merely-resumable one (the general way out) — one code
  path, not two.
- **D8 — A decision is validated against the run's actual pending turn before any `Command` is issued, and an
  execution lease makes the whole request atomic.** The API layer, holding the lease (D12), first runs the same
  read-only classification the sweep and the run-detail endpoint use, to learn the currently pending turn's
  identifier; a request whose own named turn does not match is refused with nothing sent — never passed to the
  graph to "see what happens," which (code facts, above) resolves silently against the wrong turn. LangGraph's own
  interrupt `id` is reused as this identifier; `Command(resume={interrupt_id: decision})` targets that exact
  interrupt, so even a validated-then-somehow-stale request cannot resolve a different interrupt than the one it
  was validated against.
- **D9 — The custom saver's own shape: a `BaseCheckpointSaver` subclass over `TargetStore`'s own sqlite3
  connection, `asyncio.to_thread`-wrapped, constructed with its own explicit serializer.** Five async methods
  overridden (`aput`, `aput_writes`, `aget_tuple`, `alist`, `adelete_thread`); each wraps a synchronous `with
  store.connect() as db: ...` block in `asyncio.to_thread(...)`. The saver's `__init__` calls
  `super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=[("kestrel.attack.graph", "Outcome"),
  ("kestrel.evidence.checker", "TurnEvidence"), ("kestrel.evidence.model", "EvidenceItem")]))` — never
  `self.with_allowlist(...)` after the fact, which is a no-op in the serializer's permissive (non-strict) mode
  (code facts, above). Because this explicit serializer is the saver's own object (not something derived from the
  compiled graph it happens to be attached to), it survives `.copy()` unchanged along with the rest of the saver —
  a saver-level round trip and a graph-level read through the per-app copy both see the same, correctly registered
  types, under either of the library's serializer modes.
- **D10 — The pending-writes table replicates LangGraph's own replace/ignore rule, and carries a `task_path`
  column.** A control write (an error, a scheduled task, an interrupt, or a resume) gets a negative index from
  LangGraph's own index map; such a write is upserted so a second one of the same kind overwrites the first, never
  duplicating it. A regular write's index is its own position in the node's return value (always `>= 0`); such a
  write is inserted only if absent — idempotent under a retried node. `task_path` (a parameter the real method
  already receives, used by LangGraph's own internal ordering of concurrent tasks' writes) is a plain column,
  included in every read and in the write's own ordering, but not part of the primary key — the same shape the
  library's own in-memory saver uses.
- **D11 — Checkpoint deletion and reconciliation, by cause.** The checkpoint is deleted from every code path that
  finishes a run's row — a clean finish, a resume's finish, a decision reaching a stopping point, and Stop (D7) —
  immediately after `finish_run` commits, in the same request. For the cases that can still leave an orphaned
  checkpoint behind: a thread whose graph reached its own end but whose row was never finished is reconciled by
  classifying it (D13), reading the outcome already decided in its state, and finishing the row with that outcome
  before deleting the checkpoint — never offered as "Resume," which would do nothing useful; a checkpoint whose own
  `runs` row is not `in_progress` at all (a delete that silently failed to complete on an already-finished row) is
  deleted outright by the sweep; deleting a target's own runs is extended to delete every checkpoint thread
  belonging to those run ids in the same operation, since the checkpoint tables carry no foreign key to `runs` (no
  automatic cascade would otherwise reach them); an unreadable checkpoint still has its own rows deleted when the
  run it belongs to is closed, even though nothing could be loaded from it.
- **D12 — The execution lease is a single in-process registry, held per app, matching the start-up sweep's own
  existing single-API-process assumption.** A plain `set[int]` of currently-leased run ids, kept on `app.state` (not
  a bare module-level dict shared by every app in the process, which would let two unrelated test apps collide on
  the same run id) — acquiring it is a non-blocking check-and-insert, never awaited, and a lease already held
  refuses the second attempt immediately rather than queuing it; releasing happens in a `finally`. The **original
  start** takes this lease too, immediately after `claim_run` succeeds and before the first `ainvoke` — not only
  resume, decision, and stop — since the run id does not exist before that point and the lease would otherwise have
  nothing to protect; the lease is then held for the rest of that same request, released only once it returns
  (whether by finishing the run or by returning at a pause). Without this, the original request driving a run would
  itself be unleased for its entire duration, letting a concurrent resume or stop collide with it — a stop in
  particular could finish the row, delete the checkpoint, and release the target lock while the original request is
  still mid-flight, after which that request's own eventual finish would find its row already gone. This is
  explicitly an in-process lock, not a database-level or cross-process one — consistent with the start-up sweep's
  own existing assumption of a single API process.
- **D13 — Classification is a read-only status check, with the result kinds a reader actually needs to tell apart,
  reused by the sweep, the run-list, the run-detail endpoint, and the decision-validation step alike.** Leased →
  *running* (nothing else reported). Not leased: no loadable checkpoint → *no checkpoint* (close exactly as today).
  A checkpoint whose own version stamp does not match the running build → *incompatible* (close with its own
  distinct reason, never resumed against mismatched code). A checkpoint that cannot be read at all (any error from
  loading or deserializing it) → *unreadable* (close exactly as today — the same outcome as no checkpoint, since
  either way nothing can be resumed). Otherwise, read the checkpoint's own snapshot: **no pending tasks at all, and
  an outcome already present** → *reached its own end* (carries that outcome; reconciled rather than offered as
  "Resume," D11). **A pending task with no interrupt** (the commit-window shape: a node's writes landed, but the
  checkpoint recording that fact did not) → *resumable*. **The resume point is never the pending task's own name,
  and is never read from a hand-written step-order table either (FR-052)**: a task whose `result` is `None` has
  not run yet (it is itself the resume point — its own name, translated from `"__start__"` to `"attacker"` for the
  one cut that can name it, never surfaced raw); a task whose `result` is already set has *completed* — LangGraph
  folds its result in and continues from the step *after* it on `ainvoke(None, ...)`, and that next step is read
  from **the completed task's own stored routing write** (`branch:to:<node>`, among that task's `pending_writes`)
  — the real compiled graph's `attacker`, `send`, and `decide` nodes each conditionally route to more than one
  possible next node depending on the turn (a cap reached, a failed send, evidence already found), so only the
  routing write actually taken this run names the true next step; a hand-written table mapping each node to one
  fixed successor cannot represent this and was wrong on four of seven entries when checked against the real graph.
  `completed` is carried so a caller needing to know specifically whether *send* has already happened (FR-044) can
  define "past send" correctly: the resume point is `"evidence"`, `"judge"`, `"decide"`, or `"record"`. **A pending
  task whose own interrupt is set** → *paused*, carrying that interrupt's own id, turn, and message. Nothing about
  this check ever mutates anything or calls `ainvoke`; reconciling a reached-its-own-end thread (which does
  mutate, by finishing the row) is something a *caller* does upon seeing that result, never classification itself.
- **D14 — The sweep moves into `lifespan`, after the saver is attached and the version guard passes, before the
  app begins serving.** `create_app`'s own synchronous body no longer runs it at all (it cannot: the saver's methods
  are async-only, and `create_app` runs inside uvicorn's already-running event loop, where a nested `asyncio.run`
  would fail). The run endpoints that need live classification (`GET /api/runs/{id}`, the run-list endpoint) become
  `async def`, awaiting the classification check per adaptive, checkpointed `in_progress` row; a test that builds
  an app without entering its `lifespan` no longer sweeps at all — every such test already goes through the
  existing test client helper, which does enter it.
- **D15 — Preconditions on resume and decision (never on Stop).** Resuming or deciding checks, before anything is
  sent and in the same order a fresh run already does: permission confirmed, terms current, an attacker model
  configured, the attack library available — the same codes and messages. Stop checks none of these, since it
  never sends anything and must remain the universal way out regardless of any of them having lapsed.
- **D16 — Caps and provenance at resume are pinned to values stored at claim time, with a concrete, checkable
  definition of "unavailable."** `attacker_model` is already a `claim_run` parameter today; this feature adds
  `attacker_prompt_id`/`attacker_prompt_version` (new columns — nothing on `runs` records these today, only
  per-turn on `run_turns`) and gives `claim_run` the option to also set `judge_model`/`judge_prompt_id`/
  `judge_prompt_version` (columns that already exist, but today are written only by `finish_run`) — a resumed or
  decided run's clients are rebuilt against exactly these claim-time values, never whatever Kestrel is currently
  configured with, and `finish_run` continues to write the same three judge columns at the end, now simply
  re-affirming values that were already pinned rather than setting them for the first time. The **judge** model is
  pinned for the identical reason the **attacker** model already is: `runs.judge_model` is one value for the whole
  run, so if a resume silently used a different, currently-configured judge for its later turns, that one column
  would misattribute the run's earlier, judge-scored turns to a model that never actually scored them. "Unavailable"
  is defined narrowly, to what is actually checkable without making a live model call: the prompt-version file the
  pinned reference names no longer exists, or the API key the pinned client would need is not configured. A model
  *slug* by itself cannot be validated this way — any string builds a client successfully, and only an actual call
  would reveal whether the provider accepts it — so an invalid-but-syntactically-fine pinned model slug is not
  something this check catches; it is caught the same way any other model error is, by the call itself failing.
- **D17 — A resumed live run's checker is rebuilt from its own stored token, directly — never through the
  live-claim code path (which would mint a new token) and never through the replay rebuild (which never regenerates
  text at all).** The stored token's own recorded prompt version is used to regenerate the override paragraph
  exactly as the original claim produced it (the same template, the same token — only the paragraph/frame derived
  from it is recomputed), by constructing the checker's planted-override state directly: the existing token value,
  its existing prompt reference, the freshly regenerated paragraph and frame (looked up against the run's own
  stored seed, found via the run's own recorded `prompt_id`), the token's existing disarmed-turn value, and marked
  as already recorded — so binding it to the run sets the run id (enabling a future disarm to persist) without
  attempting to insert a second planted-token row for a token that is already there. This is deliberately not the
  same construction the live-claim path uses (which mints a brand-new token) and not the replay path's own rebuild
  (which must never regenerate text, since a replay resends the source's own stored bytes verbatim) — a resumed
  live run needs the third shape: the same token, a freshly regenerated paragraph, bound without a duplicate
  insert. After replaying "this message was sent" over every already-recorded turn (without emitting a disarm
  event for any of them — they already happened once, before the interruption), one more call notes the
  checkpoint's own in-flight message as sent, but only when the resume point is past the point that message was
  actually sent — never for a turn still awaiting its own send, since in that case nothing has reached the target
  yet. This is the one call allowed to actually disarm the token, if that in-flight message is what disarms it for
  the first time.
- **D18 — Checkpoint version compatibility is a stamp the saver itself writes, plus defensive reads, not either
  alone.** The saver's own `aput` adds one extra key to the metadata dictionary it is given, before persisting it —
  the current graph/state-shape version, a constant it already has access to (the same constant `attack/graph.py`
  itself uses and bumps). LangGraph never needs to know this key exists; it is purely Kestrel's own addition to
  data Kestrel already owns writing. Classification (D13) reads it back from the stored metadata (never through the
  graph) and treats any value other than the running build's own current version as incompatible — the coarse gate
  for a structural change (a different node topology: a part-1 checkpoint has no `approve` node to resume into at
  all, which is exactly the shape of shipping part 2 after part 1 — the constant moves from `1` to `2` at that
  point). Reading this metadata key through the saver is not in tension with "checkpointed *state* is always read
  through the compiled graph" — that rule (FR-049) is specifically about the three registered dataclasses, which
  must only ever come back as themselves; a plain version integer in the checkpoint's own metadata carries no such
  risk and is read wherever it is convenient to read it. Independently, and in addition to the stamp, every node
  reads a key this feature ever adds to the state with a default (`state.get(key, default)`, never `state[key]`) —
  a purely additive change within one compatible version then needs no stamp bump at all, and this same discipline
  is what keeps the existing runtime-context and initial-state construction backward compatible for pre-existing
  tests that build them directly, without a version bump for every small addition.
- **D19 — Write-back happens exactly once, wherever a live run actually finishes through the API — the extra
  finishing step is never inside `run_adaptive` itself, which keeps calling `finish_run` directly for every
  caller, as it always has (FR-055).** The single function every API-driven finishing path (`api/main.py::start_run`
  reading a terminal outcome back from `run_adaptive`, a resume reaching one, a decision reaching one, Stop, and
  the sweep's own reconciliation of a thread that reached its own end) takes a run **already finished by its own
  caller** — never calling `finish_run` itself — and owns write-back, immediately before the checkpoint delete and
  the lease release, not left to each call site to remember on its own. `run_adaptive` itself keeps calling
  `finish_run` directly, exactly as it does today, and returns the finished run to its own caller — it never calls
  this *extra* finishing function, because the experiment harness calls this exact same `run_adaptive` for a cold
  arm that must never write back (007); an extra finishing function reachable from inside `run_adaptive` would
  write back twice for a warm arm and silently warm a cold one, corrupting the A/B comparison and breaking FR-032.
  A pause is
  explicitly not this function either — reaching an interrupt returns control to the caller without ever calling
  it, so a paused run's write-back status stays unset, exactly as a run that has not finished should read; neither
  is an exception exit, which leaves the run `in_progress` (FR-042) rather than finishing it.
- **D20 — The run's kept log continues across a resume, and `run.interrupted` is itself a kept line — only for a
  checkpointed row.** The per-run kept-line counter a new request's own lines continue from is read from the
  highest one already stored for that run, never reset to the start by a fresh request; the kept-line cap is
  enforced over the whole run's accumulated count, not per request. The run's own dropped-line count (today scoped
  to one request) is likewise carried in the run's persisted, whole-run accumulators (alongside cost and token
  totals, D21), so a multi-segment run's final truncation marker still reports an accurate total rather than only
  what its last segment alone dropped. `run.interrupted` (the sweep's own classification line) is written into the
  run's own kept log at classification time, not only emitted to the stream — but only for a row the sweep actually
  checkpoints-and-classifies; a row closed by the pre-existing, unconditional path gains no such line, keeping that
  path's behaviour exactly as it is today.
- **D21 — `run.end` keeps its existing rule for every run and every exit, except one narrow, explicitly guarded
  case.** The existing rule (a scope's exit emits `run.end` once, naming whatever class of exception escaped if one
  did) is the correct behaviour for a single-turn run, a replay, an experiment repetition, and a checkpointed
  adaptive run that actually finished this request — none of these needs to change, and none of them does.
  The one case that must not emit it: a **checkpointed** adaptive run whose scope is ending while its row is
  **still `in_progress`** — a pause, or any interruption (a process death or an in-process exception, which now
  leave the same resumable shape, FR-042) — **including the run's own very first segment, not only a resumed one**
  (FR-053): the original run-start path passes `checkpointed=True` into `run_scope()` itself the moment it claims
  a checkpointed row, before `run_adaptive`'s first invocation, so this rule governs a pause or an exception in
  that first segment exactly as it does any later one. **The check reads fields bound to the scope itself, never
  the store at exit**: `RunContext` gains `checkpointed`/`finished`, set once at entry (by `run_scope()` itself for
  an original start, or by `events.reopened_run_scope(run)` for a resume/decision/stop, which copies it from the
  `Run` it is given instead of emitting a second `run.start`) and flipped by the shared finishing function the
  moment it actually finishes the row — withholding `run.end` is then a plain check of these two fields, never a
  fresh read of `is_checkpointed`/`status` that would otherwise require `tests/unit/test_run_log_handler.py`'s own
  minimal `FakeStore` (which implements only `add_log_line`) to gain methods it has no other reason to have — it
  binds both a store and a run, but one whose checkpointed status this exit check never reads either way. A scope
  whose own run is never checkpointed (every pre-existing event-level test) leaves `checkpointed` at its default
  `false` and is unaffected by construction, keeping `run.end` on every exit, unchanged, exception or not — this is
  deliberately narrow enough that no pre-existing test needs to change.
  **Withholding `run.end` is not the same as leaving no trace**: a clean exit at a pause emits nothing in
  its place (`run.paused` already told that story), but an exit on an **exception**, with the row still
  `in_progress`, emits a kept `run.interrupted` line instead — `resumable: true`, `error` naming the exception's
  own class, never its text — the only way the reversed FR-042 still leaves something on the run's own kept log
  for a crash the next request has not yet touched. The one `run.end` that **is** emitted for a multi-segment
  checkpointed run reads whole-run totals (duration, cost, tokens, judge usage, evidence, dropped-line count) from
  accumulators carried in the run's own persisted state (D20), never only what the finishing request's own segment
  saw. A
  resume or a decision that continues an already-started turn re-opens that turn's own context explicitly (its
  number, and a start time that discounts the gap) rather than relying on the attacker step's own turn-started
  signal, which does not fire again for a turn that does not re-enter that step. `run.paused` is emitted by the
  caller, once, immediately after the graph invocation returns a result carrying an interrupt — never from inside
  the `approve` node itself, which may be re-executed harmlessly by a bare status re-check and must not re-emit
  anything each time that happens.
- **D22 — A `runs` column records, at claim time, that a run was claimed through the live run-start path — never
  set by a resume, which claims nothing.** `runs.is_checkpointed`, set to true only by the one `claim_run` call the
  live run-start path itself makes, and left at its default false by every other caller (single-turn, replay, the
  experiment harness) with no change needed to any of them. An experiment repetition's own link to its experiment
  is written only after that repetition finishes — an `in_progress` repetition is never linked yet, so a check
  keyed on that link can never exclude the row it is supposed to exclude while that row is still open, which is
  exactly when classification runs. `is_checkpointed` has no such timing gap: it is set at the same moment the row
  is created, and a resume or decision never calls `claim_run` again, so there is only ever one place this column
  is written.
- **D23 — Backward compatibility for pre-existing tests is achieved by giving every new field a default, not by an
  edit list alone.** `_LiveDeps.ask_before_each_turn: bool = False` — a plain dataclass default, so every existing
  construction site keeps working unmodified. `_LiveDeps.deadline` keeps its existing name, type and role
  (`remaining() = deadline - clock()`) entirely unchanged — the new time-spent accounting (D24) is computed by the
  caller that builds `_LiveDeps` for a fresh claim versus a resume, never by changing what `deadline` itself means
  or how a test may set it directly. Any new state key is read everywhere with `.get(key, default)` (D18), so a
  hand-built state dict from an older test that omits the new keys never raises a key error. What genuinely cannot
  avoid changing: the schema-version literal pinned in the existing migration tests, the same class of edit every
  prior schema bump in this project has already made to its own predecessors.
- **D24 — Time spent is set, not accumulated, in every node's own delta, anchored to when the current invocation
  began.** The state gains one field, the run's own total time spent executing so far; it is **set** (never
  incremented) by **every** node in the turn loop (`attacker`, `approve`, `send`, `evidence`, `judge`, `record`),
  each computing it fresh as `time already spent before this invocation began + (now − when this invocation
  began)` — a plain recomputation from a fixed anchor, never a running total nudged forward, which would
  double-count whatever time had already elapsed since the anchor every time it ran. Every node, not only
  `record`, is what closes the approve-node pause gap: `approve` cannot return a delta at all on the pass where it
  actually pauses (`interrupt()` suspends the node function before its own `return`), so if only `record` ever set
  this field, a turn that pauses before reaching `send`/`evidence`/`judge`/`record` would never persist any of its
  own attacker-drafting time, and a run paused every single turn could spend an unbounded amount of real,
  unaccounted time drafting messages — exactly the failure mode this design must avoid, since drafting time is
  real, deliberate executing time, not downtime. Because `attacker` always completes and returns its own delta
  *before* `approve` ever runs, and synchronous durability commits that delta first, the drafted turn's own time
  is already durable by the time a pause can happen, whether or not `approve` itself gets to run again before the
  decision resolves it. Within one continuous invocation, nothing about a live run's own deadline arithmetic needs
  this value at all — `_LiveDeps.deadline` is computed once, when the invocation begins, and stays fixed for the
  rest of it, so an uninterrupted run's own timing is byte-identical to today's regardless of how often the
  state's own time-spent field is recomputed along the way. The value only matters when a *new* invocation begins
  after a gap: a fresh claim computes the deadline exactly as today (time spent starts at zero); a resume or
  decision computes it as `now + (the run's configured limit − time already spent, as of the last node that
  durably completed)`. The one accepted consequence, stated plainly rather than left implicit: a crash strictly
  *inside* a node, before even that node's own delta is produced, leaves that fraction of a step's time neither
  counted nor refunded — nothing durable exists yet to reflect it from. A gap between invocations (the downtime
  after an interruption, or the wait while a run sits paused) is excluded in full, which is the actual requirement;
  losing a strictly in-node fraction of a second on top of that is an accepted simplification, not a goal in
  itself. The two anchors (`time_spent_at_invocation_start`, `invocation_start`) live on the shared `_Deps` base,
  not only `_LiveDeps`: `send`/`evidence`/`judge` are shared nodes, run by `REPLAY_GRAPH` too, so `_ReplayDeps`
  needs them set the same fixed way a fresh live claim does (a replay never reads a stored `time_spent_s`, having
  none of its own) — every `_Deps`-derived dataclass is declared `kw_only`, since a defaulted base field followed
  by a subclass's own required field is otherwise a plain `TypeError` at class-definition time. A resumed
  or decided mid-turn's own carry-over (`log-records-delta.md`) is named, not left implicit: the `attacker` node's
  own delta additionally sets `turn_time_spent_at_start` (the baseline a later line subtracts to report only this
  turn's share) and `turn_attacker_usage` (that turn's own tokens/cost, read back unchanged by a later step that
  does not re-run the attacker).
- **D25 — The OWASP report excludes every `in_progress` run, the same way it already excludes a replay.** The
  report's own input is filtered one call site earlier, to runs whose status is `finished` — a paused, resumable, or
  otherwise still-executing run has reached no verdict yet and must not show up as an `unclear` finding just
  because it has sat open for a long time.
- **D26 — A run's idle clock is one stored timestamp, updated only on an accepted exit at the one place every such
  exit already passes through: lease release.** `runs` gains `last_activity_at` (nullable `TEXT`, an ISO
  timestamp) — set at claim time to the claim's own moment, and updated to `now()` whenever this run's execution
  lease is released **and** the request actually reached a point of doing something (pausing, an in-process error
  the process survives, or a resume/decision/stop that was not itself refused) — never on a refused exit, which
  never gets far enough to count as activity in the first place. The lease itself (research D12) gains a small
  `mark_active()` method, called by the handler only after its own preconditions pass and it is actually about to
  invoke the graph or perform the stop; the lease's own `finally` block touches `last_activity_at` only if that
  flag was set, never unconditionally — this is what makes "an accepted request resets the idle state; a refused
  one does not" true structurally, rather than relying on every call site to remember it. A genuine process death
  updates nothing at all (nothing runs to record it); this is deliberate, and is exactly why a restart needs its
  own short, bounded grace period (D27) rather than trusting `last_activity_at` alone the instant a new process
  comes up. **Two callers of `mark_active` named explicitly, since both are easy to miss**: the original run-start
  path (`run_adaptive`'s own first segment) calls it on its own exit, exactly like a later resume or decision does
  on its — the original start is not a special case here, only the first caller to ever hold this particular run's
  lease at all. The automatic idle check (D27) is, conversely, the one caller that deliberately **never** calls it,
  whether its own stop attempt succeeds or fails: an automatic stop is not one of FR-059's own accepted-exit kinds,
  so it must never reset the very clock it is itself reading.
- **D27 — The automatic check is one function, called periodically only, gated by a start-up grace period, each
  run re-verified fresh under its own lease, failures isolated per run and per iteration.** The same function the
  start-up sweep already calls per `is_checkpointed` row (classify, then act) gains one more branch: for a row
  whose classification is `"paused"`, `"resumable"`, or `"stoppable"`, compute wall-clock idle time as `clock() -
  last_activity_at` (no `max()` with anything); if it has elapsed past the configured window (D28), attempt the
  lease and call `stop_run` with `triggered_by="idle_timeout"` (D29). This is **not** run as a separate pass during
  the start-up sweep at all (there is nothing left for a start-up-only pass to find: every reached-end,
  no-checkpoint, and unreadable row the sweep itself would reconcile or close has already been handled by the
  sweep's own classification before any idle check could run, and a genuinely resumable/paused row's idle time,
  measured this way, is unaffected by whether the process just started) — only `lifespan` starting a plain
  `asyncio` background task, after the sweep completes, looping `await asyncio.sleep(interval)` then this same
  check, for as long as the app stays up; the task is cancelled **and awaited** in `lifespan`'s own teardown,
  before any tracing shutdown runs. Before doing anything else on a given tick, the loop checks a **grace period**:
  if less than `min(1 hour, configured window)` has elapsed since `app.state.started_at`, the tick is a pure no-op
  for every row, deliberately — this is the one and only place the process's own start time matters, bounding how
  long a stuck run can stay locked after a restart without granting it anything like a fresh window. Because
  seconds to minutes pass between a tick first reading a run and that run's own lease actually being acquired,
  the row MUST be **read again, reclassified, and re-measured for idleness fresh, under the lease**, immediately
  before acting — never trusting the snapshot the tick's own initial listing read; a row no longer `in_progress`,
  no longer one of the three idle-eligible classifications, or no longer idle by that fresh read is left alone, no
  different from one the lease found already held. A `RunLeased` from another request already holding it is caught
  and skipped, never retried within the same tick. This check holds no scope of its own until it actually proceeds
  to stop a row (D29) — it never calls `mark_active` either way (D26): an automatic stop is not an accepted exit,
  whether it succeeds or fails, so a failed one is retried, with no backoff, at every subsequent check for which it
  is still due. Beyond that, the loop catches plain `Exception` **per run**
  (logging one catalogued `ERROR` line carrying `run_id` and the exception's own class name, never its text, then
  continuing to the next row) and **per iteration** (so one tick's own uncaught failure does not end the loop
  task for good) — `CancelledError` is let through either way, since that is exactly teardown asking the task to
  stop. The per-run line and the per-iteration one share one event name (`idle_stop.check_failed`,
  `contracts/log-records-delta.md`) but not one shape: the per-run line carries `run_id`; the per-iteration line (a
  failure outside any single row's own handling, such as the listing call itself raising) carries none, since no
  row is implicated — `run_id` is the one field that is optional on this line, never a literal `null`, omitted
  instead exactly the way every other optional event field already is. Teardown's own cancel-and-await is itself
  guarded against both outcomes (`CancelledError` expected and discarded; any other exception already logged above
  and never re-raised), so neither can escape and interrupt tracing shutdown. `IDLE_CHECK_INTERVAL_S` is a small constant (a few minutes) chosen short against the default 24-hour
  window; both it and `check_idle_runs`'s own notion of "now" are parameters with that constant and a real clock as
  their defaults, never hard-coded, so a test can drive many ticks and arbitrary clock values without a real sleep
  or a real wall clock. Neither call site returns anything to a caller or blocks any request; the lease is held
  for no longer than that one `stop_run` call takes, for the one run being checked at a time.
- **D28 — The setting is a new, narrower parser: strictly positive, finite, bounded, no "off" sentinel.**
  `KESTREL_RESUME_IDLE_HOURS` is read by its own small function (distinct from `settings.non_negative_float_or_off`,
  which permits zero and an `"off"` string this setting has no use for — the owner's own wording says "a positive
  number of hours," not "or disabled") — parses a float, refuses to start if it is not finite, not a number at
  all, `<= 0`, or above `87,600` (ten years) — not chosen for any arithmetic limit (`idle_stop_at`'s own addition
  does not overflow until far past this point), but as a deliberate policy ceiling: a value that large has no
  honest use as "a configurable number of hours" and is really an attempt to disable the stop outright, which this
  setting does not offer. The parsed value lives on `Settings` as `resume_idle_hours: float`, reported on
  `GET /api/config` as `idle_hours` in its own new `resume` group — never folded into the existing `adaptive`
  group, which `test_api_config_adaptive.py` already asserts as an exact, closed object with no room for a new key.
- **D29 — The automatic outcome reuses `stop_run` itself, parameterised only by why, never by what it does; each
  of its three branches keeps its own, already-distinct reason and `stopping_condition`; the lease and the logging
  scope both belong entirely to whichever caller reaches it, never to `stop_run` itself.** `stop_run(store, graph,
  app_state, run_id, *, triggered_by: Literal["user", "idle_timeout"] = "user")` — every branch's own fields are
  unchanged by `triggered_by`, since each branch already has its own correct `stopping_condition` and reason from
  research D7/D11: the ordinary branch still composes its reason only once it knows whether this is a manual or an
  automatic stop (the automatic sentence, reading `hours` from the currently configured setting at the moment of
  the stop, never a value captured at claim time, since the setting could change in between); the reconciled branch
  keeps the decided outcome's own `stopping_condition` and reason exactly as D7 already produces them, completely
  untouched by `triggered_by`; the no-checkpoint-or-unreadable branch keeps the sweep's own fixed `"interrupted"`
  reason text (FR-056) exactly as D7 already produces it too. **`stop_run` neither acquires nor releases the
  execution lease, and neither opens nor closes a logging scope — opening one unconditionally would silently nest
  a second scope inside the decision handler's own, for a `"stop"` decision.**
  There are exactly three callers, each already holding the lease and already inside its own open scope before it
  calls in: the `/stop` endpoint handler and `check_idle_runs` (research D27) each acquire the lease and open
  `events.reopened_run_scope(run)` themselves, immediately around their own call into this function, since neither
  has any other scope open at that point; the decision handler (research D8), deciding `"stop"`, already holds the
  lease and already has its own scope open for the whole decision (`run.decided` emitted first) before it reaches
  this same call, and opens no second, nested one for it — nesting one there would let an exception after this
  call emit a second `run.interrupted`/`run.end` pair for a row already finished, which FR-046's "exactly once"
  already forbids. Only a **user**-triggered caller (the endpoint handler, or the decision handler) calls
  `mark_active` before calling in, never `check_idle_runs` (research D26): an automatic stop is not one of
  FR-059's own accepted-exit kinds, whether it succeeds or fails. `run.stopped` (`contracts/log-records-delta.md`)
  gains `trigger` (`"user"` or `"idle_timeout"`, always present, the same bar `run.decided`'s own small
  fixed-string fields already hold themselves to) and `idle_hours` (present only when `trigger == "idle_timeout"`,
  the configured value that elapsed) — both added to `events.CATALOGUE`; neither field is read by anything that
  decides `stopping_condition` or the stored `reason`, which stay exactly what D7/D11 would already produce for
  that branch — `trigger`/`idle_hours` are the *only* place an automatic stop is actually named as such.
- **D30 — `idle_stop_at` is computed, not stored, from the same inputs the check itself uses, and itself respects
  the restart grace period; "at the top of its own target's list" is what "prominent" means, since at most one
  `in_progress` run exists per target; the run list's own grouping is a UI concern, not a wording a test pins.**
  `idle_stop_at = max(last_activity_at + resume_idle_hours, app_state.started_at + min(1 hour, resume_idle_hours))`
  whenever classification currently reads `"paused"`, `"resumable"`, or `"stoppable"`; `null` otherwise — the
  second term matters precisely because, without it, a run already overdue before a
  restart shows a time already in the past throughout the grace period FR-059 itself grants it, exactly when a
  returning user most needs an honest deadline to act against. Computed alongside `run_state` (research D13/
  FR-054), from the same classification call, never a second read of the store; it is the *earliest* time an
  automatic stop may happen, never a promise of exactly when — the actual stop happens at whichever periodic tick
  first finds the run idle past it, up to one check interval later. Because `uq_runs_active` already limits a
  target to one `in_progress` run, a target's own run list showing this run "at the top" (the coordinator's own
  label for the owner's "prominently" — never asserted as the owner's verbatim words) is necessarily a list of at
  most one; a stuck run on some *other* target is made visible a different way — a small cue on the target
  selector itself naming that a target has a run waiting on a person (D31) — never invented as a cross-target
  single list this feature does not otherwise have. CLAUDE.md's "no test pins wording or headings in docs" rule
  does not reach UI label text one way or the other, but the UI test proving this feature (T063/T064 below) checks
  structurally — this run surfaces ahead of the rest of its own target's list, and shows its own `idle_stop_at` —
  never a hard-coded exact heading string, so a later wording change to either label does not break it; it also
  never seeds two `in_progress` runs on one target, since `uq_runs_active` already forbids that shape outright.
- **D31 — The target-selector cue is backed by a real API field, computed exactly like `idle_stop_at`, never a UI
  guess.** `GET /api/targets`'s own `TargetSummary` gains `needs_attention: bool` (FR-062) — `true` when that
  target's one possible `in_progress` run currently classifies `"paused"`, `"resumable"`, or `"stoppable"`; `false`
  when it has none, or that run is currently leased. Computed by calling the identical classification function
  (D13) already used for `run_state`/`idle_stop_at`, over that one run if it exists — never a second, independent
  check, so the three fields can never disagree about the same run. `GET /api/targets` becomes `async def` to make
  this call, the same change D14 already made to the run-detail and run-list endpoints for the identical reason.
  The UI reads this field alone for its cue — never a per-target `GET /api/targets/{id}/runs` call on every rerun
  (which `GET /api/targets` already being one list call makes unnecessary), and never a guess from a field
  `TargetSummary` already carried, since the UI holds no logic of its own (CLAUDE.md).
