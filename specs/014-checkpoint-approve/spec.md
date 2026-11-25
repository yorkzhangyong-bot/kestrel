# Feature Specification: LangGraph Checkpointer and Approve Node

**Feature Branch**: `014-checkpoint-approve`

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: "The rest of the LangGraph-idioms reviewer-feedback item in docs/roadmap.md, after #49's typed
state, reducers and module-level compiled graphs. Two parts, shipped as two pull requests after this spec merges.
Part 1, the checkpointer: an interrupted adaptive run must be able to resume without repeating completed turns; the
spec must say what happens to a step cut off mid-way (for example a message already sent to the target) and how the
start-up sweep of in-progress runs changes. Part 2, the approve node: a checkbox on the start-run form, 'Ask before
each turn', off by default; ticked, the run pauses before each attacker-written message is sent (turn 2 onward) and
shows it on the run page with three buttons — Approve (send it, pause again next turn), Run to end (send it and stop
asking), Stop (end the run); the spec must decide whether the time limit counts while paused, what happens if nobody
answers, and that the target stays locked while paused. Behaviour of existing runs and replays must stay unchanged
when the checkbox is off. The checkpointer may need a new dependency (`langgraph-checkpoint-sqlite`); Principle X
requires the owner's decision, asked during clarify. The live HS-code e2e is known broken (the model the guardrail
allows keeps changing); that is not a failure of this feature. Open a spec-only pull request first."

## Clarifications

### Session 2026-11-25

- Q: The checkpointer needs somewhere to durably persist a live adaptive run's in-progress graph state. Principle X
  requires the owner's decision between: (A) the `langgraph-checkpoint-sqlite` package's `AsyncSqliteSaver` — a
  maintained, LangChain-authored implementation of the checkpoint-saver contract, at the cost of a new required
  dependency (it pulls in `aiosqlite`) and a second, framework-owned schema/migration story living inside the same
  database file as Kestrel's own hand-rolled `store.py` schema; (B) a small custom checkpoint saver written against
  Kestrel's own existing `sqlite3`/`TargetStore` connection pattern, adding Kestrel-owned tables to the existing
  `SCHEMA_VERSION`/`_migrate` story — zero new dependencies, but Kestrel owns correctly implementing the saver
  contract (pending writes, channel versions) itself; or (C) something else the owner names. → **B: a custom
  checkpoint saver, no new dependency.** **Verbatim**: "Custom saver, no new dependency. Its tests must cover
  pending writes and a real interrupt/resume through the compiled graph, and pin the langgraph-checkpoint version
  range it was built against, so an upgrade fails loudly instead of silently." The saver subclasses LangGraph's own
  `BaseCheckpointSaver` and reuses its own default serializer (`langgraph-checkpoint`, already installed as a
  transitive dependency of `langgraph` itself — never a new package); its tables live inside Kestrel's own
  `store.py` schema and `SCHEMA_VERSION` migrations, not a second file or a second migration story. The three
  conditions the owner named are carried as requirements (FR-035 to FR-037). **Rejected**:
  `langgraph-checkpoint-sqlite` (the package named in this question, version `3.1.3` as resolved against this
  worktree) — verified to require `aiosqlite>=0.20`, `sqlite-vec>=0.1.6`, and `langgraph-checkpoint>=4.3.1` (this
  worktree has `4.3.0`, so adopting it would also have forced a `langgraph-checkpoint` bump) — three new or bumped
  dependencies for a package whose own correctness Kestrel would still be trusting sight unseen, against exactly
  the failure mode (a crash) this feature exists to survive.

## User Scenarios & Testing *(mandatory)*

Feature 003 gave Kestrel an adaptive, multi-turn attack loop; #49 (the "LangGraph idioms" roadmap item's first half)
made that loop's state typed and its two graphs (a live run's, a replay's) compiled once at import, with every
per-run value travelling as LangGraph's own runtime context rather than a closure. Today, though, the loop is still
all-or-nothing: if the Kestrel process stops for any reason — a crash, a deploy, a deliberate restart — while an
adaptive run is mid-flight, the run is simply marked `unclear`/`interrupted` at the next start-up and whatever turns
it had already completed are wasted; and there is no way for a human to look at what the attacker is about to say
before Kestrel sends it. This feature closes both gaps by giving the adaptive loop a **checkpointer** — LangGraph's
own mechanism for durably persisting a graph's progress — and building an optional **approve node** on top of it: a
deliberate pause before each attacker-written message, so a user can read it before it goes anywhere.

### User Story 1 - An interrupted adaptive run doesn't have to start over (Priority: P1)

A user is running a long adaptive attack when Kestrel's process stops — the machine restarts, the user redeploys a
new build, or it simply crashes. Today, restarting Kestrel silently closes that run as interrupted; whatever turns it
had already completed, and whatever the attacker had already learned about the target over those turns, are gone,
and re-running it from turn 1 may not even reach the same place twice (the attacker model is not deterministic).
With this feature, the user instead finds the run still sitting there after the restart, visibly marked as
resumable, and a single action continues it from its next unfinished step — never repeating a turn that was already
fully recorded. If resuming it would just fail again (its own crash cause is a deterministic bug, not a one-off), the
user is never trapped: they can stop it outright instead.

**Why this priority**: This is the first of the two reviewer-feedback items the owner asked for by name, and it is
what makes the approve node (User Story 2) safe to build on: both rely on exactly one persistence mechanism.

**Independent Test**: Start an adaptive run against a stub target, let it complete two full turns, kill the process
immediately after each of the four step boundaries a turn can be cut off at (attacker drafted but not sent, sent but
not recorded, recorded but not yet checked, judged but not yet recorded), restart, and for each case confirm: the
run is not auto-closed; resuming it produces exactly one stored turn row and one set of evidence items for the turn
in question; no already-fully-recorded turn is resent or re-judged; and the run reaches the same stopping condition
and verdict an uninterrupted run reaches, with the stub attacker, judge and target scripted identically either way.

**Acceptance Scenarios**:

1. **Given** an adaptive run killed cleanly between two completed turns, **When** Kestrel restarts, **Then** the run
   is not closed by the start-up sweep and is shown as resumable, never auto-continued without a user action.
2. **Given** that resumable run, **When** the user resumes it, **Then** no attacker call and no judge call is
   repeated for any turn that was already fully recorded, and the run continues from its next turn.
3. **Given** an adaptive run killed while the attacker was drafting a turn's message, before it was sent, **When**
   the user resumes it, **Then** that turn's message is drafted again (the attacker may be called again) and is
   sent exactly once.
4. **Given** an adaptive run killed just after a turn's message was sent to the target but before that turn's reply
   was durably recorded, **When** the user resumes it, **Then** the message may reach the target a second time, but
   exactly one turn and one reply are ever recorded for that position.
5. **Given** an adaptive run killed just after a reply was durably recorded but before it was checked or judged,
   **When** the user resumes it, **Then** the message is **not** sent again, and the already-recorded reply is
   checked (and judged, if nothing matched) from where it left off.
6. **Given** an adaptive run killed just after the judge answered but before its verdict was durably recorded,
   **When** the user resumes it, **Then** the judge may be asked again for that turn, but only one verdict is ever
   recorded for it.
7. **Given** a single-turn run, a replay, or an experiment repetition killed mid-flight, **When** Kestrel restarts,
   **Then** it is closed exactly as it is today — never offered as resumable.
8. **Given** a resumable run sitting un-resumed, **When** the user tries to start a new run or a replay against the
   same target, **Then** Kestrel refuses, exactly as it refuses against any other run already in progress.
9. **Given** a resumable run, **When** the user resumes it after a long delay, **Then** the delay between the
   interruption and the resume does not count against the run's own time limit.
10. **Given** a resumable run whose own cause of death keeps recurring (resuming it would just crash it again),
    **When** the user clicks **Stop** instead of Resume, **Then** the run finishes without its graph ever running
    again, its checkpoint is deleted, and its target is unlocked — the documented way out of any resumable run that
    is not paused.
11. **Given** a run that failed while its own request was still being handled (an unhandled error, the Kestrel
    process itself staying up), **When** the user next looks at it — with no restart needed — **Then** it reads
    resumable at once, its checkpoint intact, exactly as if the process itself had died at that same point: Resume
    retries it, and Stop is there if the same failure keeps recurring.

---

### User Story 2 - Review and decide each attacker turn before Kestrel sends it (Priority: P1)

A user wants to watch an adaptive attack unfold one message at a time rather than letting it run unattended. They
tick **"Ask before each turn"** before starting the run. Kestrel sends the opening, library-seeded message as usual,
but before sending anything the attacker model itself writes, it stops and shows the user exactly that drafted
message. The user reads it and picks one of three things to do with it.

**Why this priority**: This is the second of the two reviewer-feedback items the owner asked for by name, and the
headline, user-facing half of this spec.

**Independent Test**: Start an adaptive run with the checkbox ticked; confirm turn 1 (the library seed) is sent
without pausing and the run pauses before turn 2's drafted message is sent, with that message visible and nothing
sent yet; exercise each of the three decisions from a fresh pause and confirm the documented outcome for each;
confirm that a second request for the same already-decided turn, and a request from a second, concurrent decider,
both fail cleanly with nothing additional sent.

**Acceptance Scenarios**:

1. **Given** the checkbox ticked, **When** the run starts, **Then** turn 1 (the library seed) is sent without
   pausing, and the run pauses before turn 2's attacker-drafted message is sent — nothing from turn 2 on is ever
   sent without a decision.
2. **Given** a paused run, **When** the user clicks **Approve**, **Then** that turn's message is sent and scored
   normally, and — if the run continues past that turn — it pauses again before the next turn's drafted message.
3. **Given** a paused run, **When** the user clicks **Run to end**, **Then** that turn's message is sent and the run
   continues, unattended, to its natural stopping point (a success, or a turn/token/time cap) without pausing again
   — including after a restart partway through that unattended run (FR-022's effect is itself a durable, resumed
   fact, never reset by a restart).
4. **Given** a paused run, **When** the user clicks **Stop**, **Then** the run ends immediately without sending the
   pending message, recorded as stopped by the user, distinguishably from a turn/token/time cap being hit.
5. **Given** a paused run, **When** nobody answers for any length of time, **Then** the run simply stays paused —
   its time limit does not advance while it waits — until a decision is made; there is no separate timeout that
   stops it on its own.
6. **Given** a paused run, **When** the user tries to start a new run or a replay against the same target, **Then**
   Kestrel refuses, exactly as it refuses against any other run already in progress.
7. **Given** the checkbox unticked, **When** an adaptive run is started, **Then** it never pauses, and behaves
   exactly as an adaptive run behaves without this feature.
8. **Given** a paused turn, **When** two decision requests for it arrive at once, **Then** exactly one of them is
   acted on — the message is sent (or the run stopped) exactly once — and the other is refused, naming that the
   turn was already decided.
9. **Given** a turn that was already decided, **When** a second, late decision for that same turn arrives, **Then**
   Kestrel refuses it and sends nothing — it MUST NOT be silently applied to whatever turn happens to be pending by
   the time it is processed.

---

### User Story 3 - A paused run survives a restart exactly like a crashed one (Priority: P2)

Kestrel's process stops while a run sits paused, waiting on a user's decision. Because the approve node is built
directly on User Story 1's checkpointer, restarting Kestrel does not lose the pause: the same pending message and
the same three controls are there afterward, exactly as if the restart had never happened.

**Why this priority**: It is the direct, expected consequence of building the approve node on the checkpointer
rather than as a separate mechanism — not a new capability of its own, but worth its own scenarios to prove the two
parts of this feature actually compose, rather than merely coexist.

**Independent Test**: Pause a run, kill the process before a decision is made, restart, and confirm the run shows
the identical pending message and the identical three controls; decide it, and confirm the outcome matches deciding
it without the restart having happened. Separately, kill the process after a decision was acted on but before the
next pause (or finish) was durably recorded, restart, and confirm the run reads as merely resumable (not paused,
and not showing the already-decided turn again) — the same general case User Story 1 already covers, not a new one.

**Acceptance Scenarios**:

1. **Given** a paused run killed before a decision was made, **When** Kestrel restarts, **Then** the run shows
   exactly what it showed before the restart — the same pending message, the same three controls — never silently
   closed and never silently resolved on its own.
2. **Given** that run, **When** the user decides it (any of the three controls), **Then** the outcome is exactly
   what deciding it without the restart would have produced.
3. **Given** a run killed right after a decision was acted on (its message already sent) but before the run's next
   pause or finish was durably recorded, **When** Kestrel restarts, **Then** the run reads as resumable, not paused
   — the decision is not re-shown and not re-applied — and resuming it continues correctly from there.

---

### User Story 4 - Nothing else changes (Priority: P1)

Every other run kind, and an adaptive run with the checkbox left off, must be provably unaffected by this feature —
this is as much a safety property as a feature, the same way feature 012's isolation from the shared pattern pool
was. "Unaffected" does not mean "literally nothing about an adaptive run changes" — part 1 itself changes a few
specific, named things for every adaptive run, checkbox or not (FR-031); this story is about everything *outside*
that named list staying exactly as it is today.

**Why this priority**: Without this, the owner cannot trust that shipping either PR is safe; it is required
alongside both User Story 1 and User Story 2, not after them.

**Independent Test**: Run the existing offline test suite, before and after this feature's code lands, and confirm
an identical pass/fail set except for the pre-existing tests the feature's own plan names as edited (each for a
stated, mechanical reason, never a behaviour change); interrupt a single-turn run, a replay, and an experiment
repetition, and confirm none of them is ever checkpointed, never offered as resumable, and never shows any control
this feature adds.

**Acceptance Scenarios**:

1. **Given** a single-turn run, a replay, or an experiment repetition interrupted mid-flight, **When** Kestrel
   restarts, **Then** it is closed exactly as it is today — no resumable state, no new control shown for it.
2. **Given** an adaptive run with "Ask before each turn" unticked, **When** it runs, **Then** it never pauses, and
   its conversation, scoring and stored turn/evidence data are identical in shape to a run from before this
   feature — the exact, named differences of FR-031 aside.
3. **Given** the existing offline test suite, **When** it is run against this feature's own code, **Then** every
   pre-existing test still passes, except the ones this feature's own plan names as edited.

---

### Edge Cases

- **The target was deleted while a run sat interrupted or paused**: the run is gone too (deleting a target cascades
  its runs, feature 001), so there is nothing left to resume — the same as opening any other deleted run today; its
  checkpoint rows are reconciled away too (FR-045).
- **The attacker or judge became unconfigured, a pinned model or prompt version is no longer available, or the
  run's own recorded library seed no longer exists, between the interruption/pause and the resume/decision**:
  resuming or deciding is refused with a message naming the problem (FR-041, FR-047); Stop remains available
  regardless, since it never needs any of them.
- **A resumed run's deterministic checks must see every turn already recorded, and must see them as a live run's
  own checker would, never a replay's**: the override token's armed/disarmed state, the exact planted task text
  (stripped from the shared pattern pool and retrieval queries exactly as an uninterrupted run's is), and the
  unsafe-output echo rule are all rebuilt from the run's own stored turns and planted tokens at resume time, never
  reset to a blank slate and never missing the in-flight message of a turn cut off after it was sent (FR-044); a
  token already disarmed stays disarmed, and no disarm event is re-emitted for it.
- **The target's connection settings or canaries changed while a run was interrupted or paused**: resuming or
  deciding uses the target's *current* connection settings and canaries, the same "current, not as it was" meaning
  regression replay (012) already established — but its own turn/token/time caps, attacker model and recorded
  prompt references stay exactly as they were when the run was claimed (FR-047), never read fresh.
- **A run is leased while it executes, and every other request about it is refused meanwhile**: while any request
  (the original start, a resume, a decision, or a stop) is actively driving a run's graph, that run reads as
  neither resumable nor paused to anyone else; a second resume, a second decision (for the same turn or any other),
  or a concurrent stop all fail cleanly — never two requests both driving the same run's graph at once, and never
  a decision silently landing on a turn other than the one it actually named (FR-038, FR-039).
- **A resumed run was already at its turn, token or time cap the moment it was interrupted**: resuming it ends it
  immediately at that cap, exactly as a live run hitting a cap does — resuming never grants extra turn, token or
  wall-clock budget, though tokens actually spent re-drafting a turn or re-asking the judge after a cut are not
  separately refunded or re-counted beyond what was already spent.
- **Stop, versus a turn/token/time cap, versus the start-up sweep's own interrupted-and-not-resumable close**: these
  end a run without a success for distinct reasons, each its own distinct, visible value — a reader of the run's own
  record must never have to guess which one happened. An unhandled error that leaves a run resumable (FR-042) is not
  itself one of these endings: the run has not ended at all yet, by design.
- **Stop on a run whose own persisted state already holds a decided outcome, but whose row was never finished** —
  whether because the graph reached its own natural end, or because the deterministic checks or the judge already
  decided one for a turn `record` had not yet durably written: Stop records that pending turn first if needed, then
  finishes the row with that already-decided outcome, the same way the start-up sweep would reconcile the first
  shape — never with `stopped_by_user`, which is reserved for a run Stop actually cuts off before it reached a
  decided outcome of its own.
- **Stop on an unleased, `in_progress` run whose checkpoint is missing or unreadable**: Stop closes it the same way
  the start-up sweep would close this shape — `unclear`, `stopping_condition: "interrupted"` — never a 409 that
  would otherwise trap the target until a restart.
- **A paused run must not read as a failed send**: the run page's pending-decision display is distinct from the
  existing failed-to-send error display; a user must never confuse "waiting for your decision" with "the attack
  could not be sent."
- **A replay never sees the checkbox, the flag, or a pause at all** — it runs its own, separate graph, which has
  none of this feature's additions. **An experiment repetition shares the live adaptive graph's own topology once
  part 2 ships**, so it does run the same steps a live run's pause check runs — it simply never has the flag set,
  so every one of those checks is a no-op for it, the same as a live run with the checkbox left off.
- **A checkpoint written by a different build of Kestrel is read by this one** (part 2's code reading a part-1-only
  checkpoint is exactly this case, and is the expected shape of "the user redeploys a new build"): it is not
  resumable, and is closed by the start-up sweep with its own distinct reason — never resumed against mismatched
  code, and never a crash.
- **A loaded, resumed conversation's entries come back as two-element lists, not tuples** — a property of the
  serializer this feature relies on, not a bug; no part of this feature's own logic MUST assume a tuple
  specifically where a list behaves identically.
- **A paused or resumable run that simply sits for a long time** must not appear in the target's OWASP report as if
  it had reached a verdict: an `in_progress` run (paused, resumable, or merely still executing) is excluded from
  that report entirely, the same way a replay already is (feature 012) — it has not finished, so it has nothing
  to report yet (FR-050).
- **Nothing persisted for this feature may ever contain a secret**: an auth header value, the target's URL, or its
  display name must never appear in a checkpoint, the run log, or any event line this feature adds — the same bar
  every other store and log boundary in this project already holds itself to (Principle IV).

## Requirements *(mandatory)*

### Definitions

- **Durably recorded**, as used below, means two different things depending on what it is said of, because a cut
  can fall between the two stores involved: for a turn's attacker-drafted message, its send and reply, and a judge
  verdict (FR-008 to FR-011), it means committed to the run's **checkpoint** (FR-003); for a stored turn row or its
  evidence items (FR-012, User Story 1), it means committed to the run's own `run_turns`/evidence storage — the
  database rows the rest of Kestrel already reads through the existing API. The two can disagree for a single step
  (FR-010's "recorded but not yet checked" case is exactly a reply durably in the checkpoint but not yet in
  `run_turns` at all).

### Functional Requirements

**Scope: which runs this feature touches**

- **FR-001**: Resumability (the checkpointer) MUST apply only to a live adaptive run — one started through the
  normal run action with `mode = adaptive`. A single-turn run, a replay, and an adaptive repetition run by the
  experiment harness (007) MUST NOT be checkpointed and MUST continue to be closed by the start-up sweep exactly as
  they are today, regardless of anything else this feature adds.
- **FR-002**: The **"Ask before each turn"** checkbox MUST appear only on the start-run form, only for an adaptive
  attack, defaulting to **off**. With it off, a live adaptive run MUST behave exactly as an adaptive run behaves
  without this feature's approve-node half — it MUST still be checkpointed and resumable per FR-001, but it MUST
  never pause. A single-turn run and a replay MUST NOT offer this checkbox at all. An experiment repetition MUST
  NOT offer it either, and MUST NOT ever pause — its own run never sets the flag, so wherever the adaptive loop's
  shared steps check it, that check simply finds it unset and does nothing further, the same no-op outcome as the
  checkbox being left off on a live run.

**Persisting enough to resume (the checkpointer)**

- **FR-003**: Kestrel MUST durably persist a live adaptive run's progress after each one of the turn loop's
  completed steps (drafting the attacker's message, sending it and recording a reply, running the deterministic
  checks, calling the judge, recording the turn, deciding the next step), so that resuming continues from the last
  completed step rather than from the beginning of the run. Every invocation of the checkpointed live graph MUST
  request synchronous durability (LangGraph's `durability="sync"`, never its own default): the step that just ran
  MUST be durably committed before the next step begins, so that a crash never leaves the persisted progress more
  than one in-flight step behind the side effects it already caused.
- **FR-004**: What is persisted MUST be nothing of a kind the run's own stored turns and evidence do not already
  hold, masked the same way they already are — the turn loop's own conversation-so-far, its turn/token/time-spent
  counters, and its current in-flight per-turn values. It MUST NOT include a secret (an auth header value, the
  target's URL, its display name); the configuration Kestrel passes to look up a checkpoint MUST carry nothing but
  the run's own thread identifier.
- **FR-005**: Everything a resume additionally needs that is **not** part of that persisted progress — the target's
  resolved connection settings and secrets, the attacker and judge clients, the deterministic evidence checker and
  everything it has planted or already seen, the retrieval provider, the run's own logging and tracing scope — MUST
  be rebuilt fresh, at resume time, from the run's own stored target, settings, and already-recorded turns and
  planted tokens. None of it MUST ever be read back from the persisted progress itself.
- **FR-006**: A run's persisted progress MUST be removed once the run reaches a terminal state — finished by any
  stopping condition, through whichever request actually finishes it (the original start, a resume, a decision, or
  a stop), or closed by the start-up sweep as not resumable. No finished run MUST leave a loadable checkpoint
  behind it; FR-045 covers reconciling one that was somehow left behind anyway.
- **FR-007**: Kestrel's durable mechanism for a live adaptive run's in-progress graph state is a checkpoint saver
  Kestrel owns and maintains itself (the Clarifications decision above), not a third-party package: it subclasses
  LangGraph's own checkpoint-saver interface, reuses that library's own default serializer, and stores its data
  inside Kestrel's existing database and schema-migration story. The three conditions the owner attached to this
  decision are FR-035 to FR-037.

**A step cut off mid-way**

- **FR-008**: A turn cut off before its attacker-drafted message was durably recorded MUST, on resume, have that
  message drafted again — the attacker model MAY be called again for that turn, and the message it drafts MAY
  differ from any earlier, uncommitted attempt — but it MUST be sent to the target exactly once, since nothing from
  the earlier attempt was ever sent.
- **FR-009**: A turn cut off after its message was already sent to the target but before that turn's reply was
  durably recorded MUST, on resume, send that turn's message again. Kestrel MUST NOT assume the target never
  received the earlier attempt, and MUST NOT invent a reply instead of sending. Regardless of how many times the
  message actually reached the target, exactly one turn row and one reply MUST be recorded for that position.
- **FR-010**: A turn cut off after its reply was durably recorded but before the deterministic checks or the judge
  ran on it MUST, on resume, run the deterministic checks (and the judge, if nothing matched) on that already
  recorded reply — without sending anything again.
- **FR-011**: A turn cut off after a judge call returned but before its verdict was durably recorded MUST, on
  resume, call the judge again for that turn. The judge MAY be asked twice and MAY answer differently each time,
  but only the verdict that is actually, durably recorded is the one that decides the turn.
- **FR-012**: A turn's stored row and its evidence items (when it has any) MUST be recorded together, as one unit,
  never one without the other even under a crash between them. Resuming MUST NOT, under any of the cuts above,
  produce two stored turn rows for the same position, two sets of stored evidence items for the same turn, a second
  kept log line recording an already-recorded turn, or any other duplicate record — regardless of how many times a
  step's own side effect (a model call, a send, a judge call) had to be repeated to reach a durably recorded result.

**Executing a run exactly once at a time**

- **FR-038**: Kestrel MUST hold an execution lease on a run for as long as any single request (the original start,
  a resume, a decision, or a stop) is actively driving its graph or finishing its row. While a run is leased, it
  MUST read as neither resumable nor paused to any other request — a concurrent attempt to resume it, decide it, or
  stop it MUST be refused outright, never queued and never silently ignored.
- **FR-039**: A decision MUST be single-use and specific to the exact pending turn it was issued for: the request
  MUST name the turn it is deciding, and Kestrel MUST refuse — sending nothing — any decision that does not match
  the run's actual, currently pending turn, including a second, later decision for a turn that was already decided
  and a decision that arrives after the run has moved on to a different pending turn.
- **FR-040**: Kestrel MUST offer a way to end any resumable run — paused or not — without resuming its graph at
  all: it MUST finish the run's row directly, recording the verdict its last durably judged turn already reached
  (or `unclear` if none), with its turn and token counts as the run's own persisted progress already shows them, and
  a stopping condition distinct from every other one; it MUST delete that run's checkpoint (FR-006) and release its
  execution lease and its target lock. **Exception**: when that persisted progress already holds a decided outcome
  — whether because the graph reached its own natural end, or because the deterministic checks or the judge already
  decided one for the pending turn but that turn was cut off before it could be durably recorded — Stop MUST first
  record that pending turn and its evidence (through the same idempotent write FR-012 already requires, a no-op if
  it was somehow already recorded) and MUST then finish the row with that already-decided outcome, the same way the
  start-up sweep would reconcile a thread that reached its own end, never with a fresh `stopped_by_user` verdict:
  a deterministic confirmation already reached MUST NOT be silently discarded just because Stop was the path that
  ended the run (Principle II). This MUST be the one documented way out of a resumable run that is not paused —
  resuming one whose own crash cause keeps recurring would otherwise have no escape short of deleting its target.
- **FR-041**: Resuming or deciding a run MUST be refused, before anything is sent, by the same preconditions a
  fresh run already enforces — the target's permission box confirmed, its terms of service current, an attacker
  model configured, and the attack library available — using the same codes and messages `POST /api/runs` already
  uses, plus one resume/decision-specific precondition: the run's own recorded seed MUST still exist in the current
  library (its rebuilt evidence checker needs it, FR-044), refused with a message naming the problem when it does
  not, rather than an unhandled error. Stopping a run needs none of these, since it never sends anything and never
  rebuilds a checker.
- **FR-042**: An interruption of a checkpointed live run — whether the Kestrel process itself dies, or an unhandled
  error simply propagates out of the request driving it while the process stays up — MUST be handled identically:
  the run MUST stay `in_progress`, its checkpoint MUST stay intact, and its execution lease MUST be released. It
  MUST read as resumable immediately afterward — an in-process error needs no restart and no start-up sweep for
  this, since the row and its checkpoint are already there for the very next request to see. Resuming it MUST retry
  from the last durably committed step, under the same rules FR-008 to FR-011 already define for any other cut (a
  message the target already saw MAY be sent again; exactly one turn MUST ever be recorded for it); Stop MUST
  remain the way out when the same failure keeps recurring. A run this feature does not checkpoint (a single-turn
  run, a replay, an experiment repetition) MUST be unaffected by this: an in-process failure there MUST continue to
  behave exactly as it does today.

**The start-up sweep and triggering a resume**

- **FR-013**: At start-up, before Kestrel begins serving requests, it MUST classify every run its own previous
  process left `in_progress`: a live adaptive run whose persisted progress (FR-003) Kestrel can still load MUST be
  left open and visibly marked resumable, never silently closed. Every other `in_progress` row — every non-adaptive
  mode, every row not claimed through the live run-start path (FR-001), and an adaptive run whose persisted progress
  is missing, unreadable, from an incompatible build (FR-048), or was never kept — MUST be closed exactly as today:
  `unclear`, `stopping_condition = "interrupted"`, with no behaviour change for that case, and no new kept log line
  for it (FR-032) — the new line FR-017 requires naming the classification MUST be written only for a row this
  sweep actually checkpoints-and-classifies, never for one closed by the unconditional, pre-existing path.
- **FR-014**: Resuming a run MUST always be a deliberate action a user takes on that run's own page, never automatic
  and never silent. What that run's page shows MUST depend on exactly what its loaded progress holds — a run
  currently leased (FR-038) reads as plainly in progress, offering no control at all; a run interrupted while it
  was paused awaiting a decision (FR-021 to FR-023) MUST show the same pending message and the same three controls
  a live pause shows (User Story 3); a run merely cut off mid-step, with no decision pending, MUST show exactly two
  controls labelled **"Resume"** (continue it — to its next pause, if that run's own "Ask before each turn" setting
  was on, or to completion otherwise) **and "Stop"** (FR-040) — never a draft decision to approve or reject, since
  nothing is awaiting approval in that case. A run that is not leased and not offered as resumable or paused only
  because its graph already reached its own end, or because its checkpoint is missing or unreadable, MUST still
  show **"Stop"** alone (never "Resume," since there is nothing to resume into) — the same control FR-040 already
  defines, reconciling the first case with its own already-decided outcome and closing the second exactly as the
  start-up sweep would — so that none of these shapes is ever left with no control at all, reachable only by a
  restart.
- **FR-015**: A run sitting resumable or paused MUST keep its target locked for the entire time it sits
  `in_progress` — including the time between an interruption and its resume, or a pause and its decision — so that
  no other run or replay may be claimed against that target meanwhile. This MUST be the same mechanism that already
  locks a target for any `in_progress` run today (one active run per target), not a new one; Stop (FR-040) is what
  releases it when nobody intends to continue the run.
- **FR-016**: A run's time limit MUST be measured as the wall-clock time actually spent executing it — the sum of
  every invocation's own elapsed time, from when that invocation started running the graph to when it next stopped
  (a finish, a pause, or a cut) — never wall-clock time elapsed since the run was first claimed. Only the gaps
  *between* invocations — the downtime after an interruption, or the wait while a run sits paused — MUST be
  excluded; an uninterrupted run (one invocation, start to finish) MUST be timed exactly as it is today. A node cut
  off before it durably commits its own share of this accounting MUST have that fraction of a step's time neither
  counted now nor refunded later — it is simply never reflected, the same way any other effect of that node never
  durably happened.
- **FR-017**: That a run was interrupted, and that it was later resumed, MUST each be visible on the run's own kept
  log and through the structured-event stream — naming, at minimum, that the process stopped (never a wording that
  could be read as the agent's own behaviour) and which step the resume continued from. A resumed or decided run's
  kept log MUST continue the same run's own sequence (never restart its own numbering, and never let a later
  segment silently overwrite or crowd out an earlier one under the run's overall kept-line cap). Neither line MUST
  carry a secret, attack text, or reply text beyond what the run's existing per-turn events already carry.

**Logging across a pause or resume**

- **FR-046**: A run's `run.end` line MUST be emitted exactly once, only when the run actually finishes — never at a
  pause, and never for a segment that merely stops at a cut point — and MUST report totals for the whole run, not
  just its last segment. A run resumed or decided mid-turn MUST re-open that turn's own context (its number, and a
  start time that excludes the interruption or pause gap), so every line produced for that turn still names it and
  still reports only that turn's own real processing time, exactly as an uninterrupted turn's lines do.

**The approve node**

- **FR-018**: The start-run form MUST offer the checkbox labelled exactly **"Ask before each turn"**, for an
  adaptive attack only, defaulting to off (FR-002).
- **FR-019**: With the checkbox ticked, the run MUST send turn 1 (the library-seeded opening message) exactly as
  today, without pausing — it is not attacker-written. From turn 2 onward, the run MUST pause after the attacker
  drafts that turn's message and before it is sent, every single turn, until the run ends.
- **FR-020**: A paused run's own page MUST show the pending turn's drafted message, in full, exactly as it would be
  sent, alongside exactly three controls labelled **"Approve"**, **"Run to end"**, and **"Stop"** — no other
  control decides a pending turn.
- **FR-021**: **Approve** MUST send the pending message, score it exactly as any live turn is scored, and — if the
  run continues past that turn — pause again before the next turn's drafted message, repeating FR-019's pause for
  every subsequent turn.
- **FR-022**: **Run to end** MUST send the pending message, score it exactly as any live turn is scored, and then
  continue the run, unattended, through every remaining turn to its natural stopping point (a success, or a
  turn/token/time cap) — never pausing again for the remainder of that run, even if the run is itself interrupted
  and resumed again before it reaches that stopping point.
- **FR-023**: **Stop** on a paused run MUST use the same mechanism FR-040 defines for any resumable run: the run's
  row is finished directly, without ever resuming its graph (so the pending message is never sent), recorded with
  its own distinct stopping condition, and with whatever verdict the run had already reached from an earlier,
  judged turn, if any — `unclear` otherwise.
- **FR-024**: While a run is paused and nobody has yet decided it, it MUST simply remain paused, for any length of
  time, with no separate timeout of its own that resolves it automatically — consistent with FR-016, its time limit
  does not advance while it waits. Only a user's own decision, or an explicit Stop, ends the wait.
- **FR-025**: Starting an adaptive run MUST stay synchronous, exactly as it is today: the request completes once the
  run reaches its first stopping point — a pause (FR-019), a finish, or a refusal — with no separate
  poll-for-progress step. Resuming (FR-014), deciding a paused turn (FR-021 to FR-023), and stopping (FR-040) MUST
  each be equally synchronous, completing once that one request's own action is done.
- **FR-026**: That a run paused, and which of the three decisions was made and on which turn, MUST each be visible
  on the run's own kept log and through the structured-event stream, named distinctly from a plain
  interruption/resume pair (FR-017) — each emitted exactly once, when that pause or that decision actually
  happens, never re-emitted by a later, unrelated re-check of the same run's status. None of these lines MUST carry
  a secret, attack text, or reply text beyond what the run's existing per-turn events already carry.

**Write-back**

- **FR-043**: Every live, checkpointed adaptive run started through the API (an original start, a resume, a
  decision, or a stop, including the start-up sweep's own reconciliation) MUST write back to the shared experience
  store exactly once — at the moment it finishes — and MUST NOT write back while it is merely paused, cut off
  mid-step, or otherwise not yet finished; an exception that leaves it `in_progress` (FR-042) MUST NOT finish it and
  so MUST NOT write back either. The run's recorded write-back status and its `run.end` line MUST reflect that one
  write-back attempt, never an earlier or a missing one. This requirement is scoped to the API-driven live path: it
  MUST NOT be read as reaching into a replay (which never writes back at all, feature 012) or an experiment
  repetition (whose own harness decides whether a cold arm writes back, feature 007) — neither of those is this
  requirement's concern, and this feature changes neither.

**The live checker rebuild**

- **FR-044**: A resumed live run's evidence checker MUST be rebuilt distinctly from how a replay's is: it MUST
  regenerate the planted override's exact paragraph and quoting frame from the stored token and its recorded prompt
  version, so the run's exact filled task text is stripped from the shared pattern pool and retrieval queries
  exactly as an uninterrupted run's is (the stripping rule feature 013 established) — never left in, as a replay's own copied-token rebuild
  correctly does for itself but would wrongly do here. If the resume point is past the point a message was already
  sent, the rebuild MUST also treat that in-flight message as sent before the run continues, so the unsafe-output
  echo rule does not mistake the target echoing Kestrel's own words for the target's own hard evidence. Replaying
  the run's already-recorded turns through this rebuild MUST NOT re-emit a disarm event for a turn whose disarm was
  already recorded before the interruption.

**Caps and provenance at resume**

- **FR-047**: A resumed or decided run MUST keep using its own stored turn, token and time-limit caps and its own
  recorded attacker model, judge model, and attacker/judge prompt references, exactly as they were when the run was
  claimed — the attacker and judge clients MUST be rebuilt pinned to those same values, never read fresh from
  whatever Kestrel is currently configured with. The judge model is pinned for the same reason the attacker model
  already is: it is one value for the whole run, so a resume silently using a different, currently-configured judge
  for its later turns would misattribute the run's earlier, judge-scored turns to a model that never actually
  scored them. If a pinned model or prompt version is no longer available, resuming or deciding MUST be refused
  with a message naming the problem; Stop MUST remain available regardless.

**Checkpoint compatibility and cleanup**

- **FR-048**: Every checkpoint MUST carry a graph/state version stamp. A checkpoint whose stamp does not match the
  version the running build of Kestrel understands MUST be treated as not resumable and closed by the start-up
  sweep with its own distinct reason — never resumed against mismatched code, and never a crash; a node reading a
  key this feature added after that stamp's own version MUST still read it with a default, so an additive change
  within one compatible version never needs its own stamp bump.
- **FR-045**: Kestrel MUST reconcile and delete a checkpoint whose thread does not belong to a currently
  in-progress, checkpointed adaptive run — including one left behind by a run that reached its own natural end but
  whose row was never finished (closed using the checkpoint's own recorded outcome, before the checkpoint itself is
  deleted), one left behind by a finished run whose delete call did not complete, and one belonging to a deleted
  target's run. This reconciliation MUST happen whether or not the checkpoint itself can still be read.
- **FR-049**: Kestrel's state types that a checkpoint may carry (`Outcome`, `TurnEvidence`, `EvidenceItem`) MUST be
  explicitly registered with the checkpoint serializer, so they read back as those same types, without a
  deserialization warning, under both the serializer's default mode and its strict mode. Checkpointed **state**
  MUST always be read back through the compiled graph in this feature's own code, never through the saver
  directly — this rule is about those three registered types specifically, which MUST only ever come back as
  themselves; it does not extend to the checkpoint's own **metadata** (FR-048's version stamp), which carries no
  such risk (a plain integer) and MAY be read directly through the saver wherever that is simpler.

**The OWASP report**

- **FR-050**: A target's OWASP report MUST exclude every `in_progress` run — paused, resumable, or merely still
  executing — the same way it already excludes a replay (feature 012); an unfinished run has no verdict to report
  yet, and MUST NOT appear as an `unclear` finding just because it has sat open for a long time.

**Stop's own correctness, classification's own source, and scope across a run's first segment**

- **FR-051**: When Stop finds the checkpointed state already holds a decided outcome for a turn not yet durably
  recorded, it MUST write that turn only when the deterministic checks' or the judge's own completed step has not
  yet been followed by the step that durably records a turn — never merely because the next unused turn number
  looks free. That recording step itself already advances the run's own turn counter without clearing the
  just-recorded turn's in-flight fields, so a write keyed on the counter alone would recreate an already-recorded
  turn as a phantom duplicate the moment that step had, in fact, already run for it — violating FR-012's "no
  duplicate record" the same way an unrelated cut would.
- **FR-052**: `run.resumed`'s `from_step`, and any other reader of a completed step's own resume point, MUST be
  derived from the compiled graph's own record of which step actually runs next for that specific execution —
  never from a hand-written table mapping each node to one fixed successor, since more than one of this feature's
  own nodes conditionally routes to different successors on different turns (a failed send, or evidence already
  found, each skip ahead), and a static table cannot represent that correctly.
- **FR-053**: The original run-start path MUST mark its own logging scope checkpointed at the moment it claims a
  checkpointed row — not only a resume's, a decision's, or Stop's own reopened scope — so that a pause or an
  unhandled error within a run's very first segment is governed by the same rules (FR-046, FR-042) as every later
  segment, never only from the second segment on.
- **FR-054**: `RunSummary`/`RunDetail` MUST expose one classification-derived field naming exactly what control, if
  any, the run's own page should offer right now — distinctly identifying a currently-leased run (no control) from
  a run that is not leased, not resumable, and not paused only because its graph already reached its own end, or
  because its checkpoint is missing or unreadable (Stop alone) — since `resumable`/`paused` alone cannot tell these
  shapes apart (`false`/`false` for all of them). The UI MUST derive its own controls from this field alone, never
  reconstruct it from `resumable`/`paused` by itself.
- **FR-055**: `run_adaptive` MUST keep finishing its own row directly, through the same call it makes today, and
  return the finished run to whichever caller invoked it — for every caller, the live API path and the experiment
  harness alike — never leaving that to something only the live API path reaches: the experiment harness calls
  this same function for every repetition, including a cold arm that MUST NOT write back, so moving the finish
  itself out of `run_adaptive` would leave an experiment repetition's own row permanently `in_progress`. Whatever
  adds write-back, checkpoint deletion, and execution-lease release on the live API path MUST do so for a row
  `run_adaptive` has already finished, never finish it a second time. The execution lease `run_adaptive` itself
  takes MUST be released on every exit from it, an unhandled exception included, regardless of whether the row was
  finished, left paused, or left `in_progress`.
- **FR-056**: Stop's own close of a run whose checkpoint is missing or unreadable MUST match the start-up sweep's
  own close of that identical shape exactly — the same recorded reason text, and no write-back attempt — never
  merely a close that is similar in spirit.

**Delivery: two pull requests, one spec**

- **FR-027**: This feature MUST ship as two pull requests after this spec merges: the checkpointer (part 1, User
  Story 1 and the parts of User Story 4 that concern it) first, the approve node (part 2, User Story 2, User Story
  3, and the rest of User Story 4) second — each independently tested and independently mergeable, with no
  user-facing change to existing behaviour from part 1 alone beyond what User Story 1 and FR-013/FR-014 describe.
- **FR-028**: Part 1's own documentation task MUST rename the roadmap's planned **"Feature 014 — Community prompt
  feed"** entry to **"Feature 015"**, and any other reference to it as 014 in the project's own living documentation
  (the roadmap, the README, CLAUDE.md, and the rest of `docs/`), since this spec claims the number 014 for itself.
  This MUST NOT extend to a merged feature's own spec files (for example feature 011's), which stay exactly as
  written — those are a historical record, not living documentation.
- **FR-029**: Part 2's own documentation task MUST move the roadmap's "LangGraph idioms" entry to Done, describing
  what shipped across both pull requests.
- **FR-030**: One end-to-end scenario per project norm runs against the owned HS-code target; the live HS-code e2e
  is currently broken by an OpenRouter guardrail change unrelated to this feature (CLAUDE.md gotcha, first recorded
  2026-11-21, recurred 2026-11-24). This feature's own verification MUST rely on the offline test suite and an
  offline, in-process restart scenario instead (SC-010), and that guardrail failure MUST NOT be scored as a failure
  of this feature.

**Unchanged when the checkbox is off, and for every other run kind**

- **FR-031**: With "Ask before each turn" off, a live adaptive run's conversation, scoring, and stored turn and
  evidence data MUST be unchanged from before this feature's approve-node half existed; `run.start` MUST omit
  `ask_before_each_turn` whenever it is false, exactly as every other optional field on that line is already
  omitted when absent — never a visible, always-present `false`. This is **not** a claim that nothing at all about
  an adaptive run changed: part 1 alone already changes exactly these things, for every live adaptive run, checkbox
  or not, and none of them is hidden by this requirement:
  - it is now checkpointed and, if interrupted — by a process death or by an unhandled in-process error alike —
    resumable at once rather than left stuck `in_progress` until the next restart, or closed unconditionally by one
    (FR-001, FR-013, FR-042);
  - above all, **its target now stays locked across a restart until someone explicitly resumes or stops it**
    (FR-015, FR-040), where today a restart always released it immediately;
  - its time limit is now measured as time actually spent executing, excluding any interruption or pause gap,
    rather than wall-clock time since claim (FR-016);
  - `RunSummary`/`RunDetail`, for every run of every mode, gain the fields FR-014/contracts/api.md define
    (`resumable`, `paused`, `pending_turn`), always present — `false`/`false`/`null` for a run this feature's pause
    mechanism never touches, never omitted;
  - the target's OWASP report now excludes every `in_progress` run, of any mode, from its findings, not only a
    replay (FR-050);
  - `run.end` keeps today's rule — emitted on every scope's own exit — for every run **except** a checkpointed
    adaptive run whose scope ends without the row being finished (a pause, or any interruption): for that one case
    only, `run.end` is withheld until whichever later request actually finishes the run (FR-046).
  A swept `in_progress` row that is **not** checkpointed (a single-turn run, a replay, an experiment repetition)
  gains none of this: it is closed exactly as today, with no new kept line and no new field behaviour beyond the
  always-present, always-`false` fields above.
- **FR-032**: A single-turn run, a replay, and an experiment repetition MUST be entirely unaffected by this
  feature — no checkbox, no checkpoint, no pause, no new control — and, interrupted mid-flight, MUST be closed by
  the start-up sweep exactly as they are today (FR-001, FR-013).

**Hard rules**

- **FR-033**: No secret — an auth header value, the target's URL, or its display name — MUST ever be written into a
  checkpoint, the run log, or any event line this feature adds (Principle IV), under any of FR-003 to FR-026.
- **FR-034**: No attack-prompt text MUST appear in this feature's own code, tests, fixtures, or commits; tests MUST
  use neutral placeholder messages, exactly as every other feature's tests do.

**The custom checkpoint saver's own correctness (the owner's three conditions, Clarifications)**

- **FR-035**: The checkpoint saver's own tests MUST cover its pending-writes mechanism directly: a regular write
  recorded but not yet folded into a completed checkpoint MUST be ignored if a duplicate of it already exists and
  otherwise correctly replayed on the next resume; a control write of the kind LangGraph itself uses to track an
  error, a scheduled task, an interrupt, or a resume MUST instead be replaced by a later write of that same kind,
  never duplicated or silently dropped. This MUST be proved directly, not merely assumed from the saver's
  happy-path checkpoint read/write.
- **FR-036**: At least one test MUST exercise a real pause-and-resume (or crash-and-resume) through the actual
  compiled live graph with the real saver attached — never a saver tested only in isolation, disconnected from
  LangGraph's own checkpointer contract as the compiled graph actually calls it.
- **FR-037**: The exact range of `langgraph-checkpoint` and `langgraph` versions this saver is tested against MUST
  be declared as one constant kept beside the saver's own code; the project's dependency declarations MUST name
  that identical range for both packages; and a test MUST read those dependency declarations and assert they match
  the constant, and MUST fail loudly whenever either package's installed version falls outside its declared range,
  rather than letting an incompatible upgrade silently change the saver's behaviour.

### Key Entities

- **Checkpoint**: a live adaptive run's durably persisted progress at a point between two of its turn-loop's steps,
  stamped with the graph/state version it was written under; loading it resumes the run from exactly that point.
  Deleted once the run finishes, or reconciled away if it is ever found orphaned (FR-006, FR-045).
- **Execution lease**: held for as long as a single request is actively driving a run's graph or finishing its row;
  while held, that run is neither resumable nor paused to anyone else (FR-038).
- **Resumable run**: an `in_progress` run, not currently leased, whose checkpoint Kestrel can still load under the
  running build (FR-013, FR-048).
- **Pending turn / pending message**: the attacker-drafted message for the next turn, held back from sending while a
  run is paused awaiting a decision; a decision names exactly this turn (FR-039).
- **Decision**: one of Approve, Run to end, or Stop — what a user does with a paused run's pending turn; single-use,
  and specific to the turn it was issued for.
- **Paused run**: a resumable run currently sitting at a pending turn, awaiting a decision — every paused run is
  resumable; not every resumable run is paused (a plain crash mid-step has no pending decision at all).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across the offline test suite, simulating an interruption at each of the four step boundaries a turn
  can be cut off at (drafted-not-sent, sent-not-recorded, recorded-not-checked, judged-not-recorded) and resuming,
  the resumed run reaches the same stopping condition and verdict an uninterrupted run reaches, with the stub
  attacker, judge and target scripted identically either way, and with exactly one stored turn row and one set of
  evidence items per turn position, 100% of the time.
- **SC-002**: Across the offline test suite, an interrupted single-turn run, replay, or experiment repetition is
  closed by the start-up sweep exactly as it is today, 100% of the time — never offered as resumable.
- **SC-003**: Across the offline test suite, running it before and after this feature's code lands produces an
  identical pass/fail set except for the pre-existing tests the feature's own plan explicitly lists as edited —
  each edited for a stated, mechanical reason: a schema-version literal, a construction site extended with a new,
  defaulted field, or a test stub gains a store method the feature's own `record` step now calls — never a
  behaviour change to what that test exercises.
- **SC-004**: Across the offline test suite, pausing a run and exercising each of Approve / Run to end / Stop
  produces its documented outcome 100% of the time, including after a simulated restart between the pause and the
  decision (User Story 3), and including after a restart partway through an unattended Run-to-end run (no further
  pause appears).
- **SC-005**: Across the offline test suite, the elapsed time between an interruption and its resume, and between a
  pause and its decision, is excluded from the run's time-limit accounting 100% of the time — a run that still had
  time remaining when it stopped never times out solely because of that gap — while an uninterrupted run's own
  timing is unchanged.
- **SC-006**: 0 lines logged by this feature, across the offline test suite, carry a secret (an auth header value,
  the target's URL or display name) or attack/reply text beyond what an ordinary turn line already carries.
- **SC-007**: 0 persisted checkpoints, across the offline test suite, carry a secret Kestrel holds about the target
  (an auth header value, the target's URL, or its display name) — verified by scanning the raw stored checkpoint
  bytes, not inferred from the code, against a stub target configured with a real secret value and a reply that
  echoes it.
- **SC-008**: A target with a resumable or a paused run in progress refuses a new run or a replay against it 100% of
  the time, exactly as it refuses against any other run already in progress.
- **SC-009**: The Principle X dependency decision (Clarifications) is reflected in the plan's Constitution Check
  before implementation begins, naming exactly one chosen mechanism — never left ambiguous in the shipped plan.
  (Verified by review of the plan, not by a test: it is a property of the document, not of running code.)
- **SC-010**: One scenario per part exercises this feature's own controls end to end. Part 1's is an offline,
  in-process scenario — two separate `create_app` instances sharing one temporary database: no actual process
  boundary is crossed (both instances run in the same Python process, and share the one module-level `LIVE_GRAPH`
  template both independently build their own checkpointed copy from — that template carries nothing run-specific,
  so sharing it is harmless). What the scenario actually proves is a real **application** boundary: the two
  instances' execution leases are independent (`app.state`, never module-level), and everything that decides
  whether a run's own progress and lock survive the "restart" — its checkpoint, its row, its target lock — lives
  in the shared database file, never in either instance's own process memory; exercising the resumable-run controls
  (Resume, Stop) across that boundary is what proves a resume is genuinely rebuilt fresh (FR-005), not carried over
  from the instance that paused or interrupted it. A browser-driven scenario cannot do this (the browser suite's
  own house rule forbids restarting Kestrel mid-scenario) and is not used for it. Part 2's scenario exercises the
  pending-message/three-button controls, offline or through the browser suite's own generic stub target. The live
  HS-code e2e's own guardrail failure is never counted against this feature.
- **SC-011**: A test reads the project's dependency declarations and asserts they name the identical
  `langgraph-checkpoint`/`langgraph` version range the saver's own code declares, 100% of the time; a test that
  installs (or simulates) either package at a version outside that declared range fails loudly and names the
  mismatch, 100% of the time (FR-037).
- **SC-012**: A test using a deliberately slow checkpoint write proves that the step just completed is durably
  committed before the next step begins — never several steps or turns ahead of what is durably recorded (FR-003).
- **SC-013**: Across the offline test suite: resuming or deciding a currently leased run is refused, 100% of the
  time; two concurrent resume requests for one run result in exactly one succeeding; two concurrent decisions for
  one pending turn result in exactly one message sent (or one stop), never two; and a stale decision for a turn
  already moved past is refused, sending nothing, 100% of the time (FR-038, FR-039).
- **SC-014**: Across the offline test suite, Stop ends every kind of resumable run (paused or not) without its
  graph ever running again, deletes its checkpoint, and releases its target lock, 100% of the time (FR-040).
- **SC-015**: Across the offline test suite, a run resumed to completion, decided to completion (Approve reaching a
  stopping point, or Run to end), and stopped, each writes back to the experience store exactly once, and a run
  that merely pauses writes back 0 times, 100% of the time (FR-043).
- **SC-016**: For an override-family run resumed after being cut off mid-turn, the resumed run's write-back and
  retrieval inputs are stripped of its planted task text exactly as an uninterrupted run's are, and an echo of the
  run's own in-flight message is never itself counted as evidence, 100% of the time across the offline test suite
  (FR-044).
- **SC-017**: Across the offline test suite, a resumed or decided run's kept log, read back through the run's own
  log endpoint, shows every line from every segment in order with no numbering collision, and includes the line
  recording its own interruption, 100% of the time (FR-017).
- **SC-018**: Across the offline test suite, a run's `run.end` line is emitted exactly once, only once the run
  actually finishes, and its totals cover the whole run rather than only its last segment, 100% of the time
  (FR-046 is covered by this and SC-017 together — see note below).
- **SC-019**: Across the offline test suite, after every path that finishes or closes a run (a clean finish, a
  stop, the start-up sweep's own close, or a deleted target), no checkpoint row for it remains, 100% of the time
  (FR-045).
- **SC-020**: Across the offline test suite, a resumed or decided run uses its own stored caps and recorded
  attacker/judge provenance, never a changed current configuration, 100% of the time; a resume or decision whose
  pinned model or prompt version is no longer available is refused with a message naming the problem, and Stop
  still succeeds in that case (FR-047).

*Note on FR-046*: the requirement that `run.end` is emitted exactly once, with whole-run totals, and that a
resumed turn reopens its own context, is measured by SC-017 and SC-018 together — no separate SC is needed beyond
them.

## Assumptions

- Builds on #49 (typed `_State`/`_ReplayState` with reducers, module-level compiled `LIVE_GRAPH`/`REPLAY_GRAPH`, and
  the frozen `_LiveDeps`/`_ReplayDeps` runtime context) as the foundation the checkpointer attaches to; this feature
  adds a checkpointer and an interrupt to the existing graphs, not a further restructuring of them.
- "Current settings/configuration" at resume or decision time applies only to the target's connection settings and
  canaries, carrying the same meaning feature 012 already established for a replay: configured **now**, not as they
  were when the run started. It does **not** apply to the run's own caps, attacker model, or recorded prompt
  references, which stay pinned to what they were at claim time (FR-047) — unlike a replay's "current judge, current
  caps" rule, a resume is continuing the *same* run, not creating a new one.
- A paused run and a merely-interrupted (crashed) run share one mechanism — the checkpointer — and differ only in
  whether the loaded checkpoint holds a pending decision (User Story 3); the approve node is built on the
  checkpointer, not beside it.
- Kestrel's primary user runs it single-user (Principle IX); an unanswered pause has no invented server-side
  timeout of its own because there is no second user it would be protecting from the wait — the user's own Stop
  action is the only bound, by design (FR-024). This is independent of whether a given deployment runs in local or
  hosted mode (`KESTREL_MODE`); nothing about this feature assumes one or the other.
- The custom-saver decision (Clarifications) and its one-line Principle X justification are carried into
  `plan.md`'s Constitution Check and Technical Context.
- The roadmap bookkeeping the owner specified (renaming the planned "014 — Community prompt feed" to "015"; moving
  "LangGraph idioms" to Done once part 2 ships) is delivery process, carried as documentation tasks (FR-028,
  FR-029), the same way features 012 and 013 carried their own roadmap edits — scoped to living documentation, never
  to a merged feature's own historical spec files.

## Out of Scope

- Resuming a replay, an experiment repetition, or a single-turn run (FR-001, FR-032).
- Any change to how the experiment harness's own batch loop handles a crashed repetition.
- A configurable timeout for an unanswered pause (FR-024) — Stop is the only bound there. For how long an
  execution lease itself is held, there is no configurable timeout either, but Stop is **not** the bound in this
  case: Stop is itself refused (`409 run_executing`) while a run's lease is held, exactly like any other request
  about that run, so a request that hangs while holding the lease is bounded only by whatever per-call timeouts
  and turn/token/time caps already apply to it, or by a restart — never by Stop.
- Editing, skipping ahead by more than one turn, or regenerating a pending message from the approval controls —
  Approve, Run to end and Stop are the only three decisions; there is no "edit and resend."
- A UI control for choosing or configuring the checkpoint storage mechanism — that is an environment/settings
  concern (if any), never a per-run form field.
- Extending resumability or the approve node to the HS-code target's own conversational loop — that target's agent
  is what is being attacked, not Kestrel's own attacker.
- Any new history, time-travel, or audit view over a run's own sequence of checkpoints — the saver implements the
  full checkpointer contract correctly (FR-035, FR-049), but nothing in this feature's own UI or API exposes more
  than the run's single current status.
- Judge-evaluation, UI-polish, deployment, capstone-docs, and the other roadmap items beside "LangGraph idioms" —
  each is its own separate feature.
