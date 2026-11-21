---

description: "Task list for feature 012 — regression replay"
---

# Tasks: Regression Replay (012)

**Input**: Design documents from `specs/012-regression-replay/` (plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md)

Every requirement below is kept consistent with `spec.md`/`plan.md`/`research.md`/`data-model.md`/
`contracts/`/`quickstart.md`/`checklists/requirements.md`: the outcome rule is computed from **every** replay
turn's own result, never from the run's one final `verdict` field, which a later clean failure could otherwise
hide an earlier unresolved turn behind (T004, T009, T014, T017, T018), and additionally, for a multi-message
source, requires the source's own winning turn to have itself failed under the judge (T004, T009, T014, T015,
T020); `replayable`/the blocked reason/the advisory (T003, T008, T015, T022, T023) are computed from the run
**and its target's current permission/terms/in-progress state and the current turn limit**
(`compute_replay_status`), never from the run's own fields alone, with every one of its seven reason strings
pinned word for word; the Replay button, outcome line, comparison and source link all render even for a run that
failed to send (T023, which `_render_finding`'s own early return would otherwise have hidden them from). Also:
the batch endpoint always answers `200`, never `201` (T028, T031); a server-computed `finding` flag, together
with `hard_evidence`, drives the Confirmed/Suspected headline cards with no UI mode check (T025, T027); one
replay's own unexpected failure inside a batch closes that entry's row and raises a named `ReplayFailed`, giving
the batch loop a defined, non-500 shape to catch (T018, T019, T028–T030), with each batch entry running inside
its own `events.run_scope()` (T029, T030); the graph-refactor regression gate (T017) names real files and keeps
masking/`turn_started`, with `_send_turn` taking `secrets` as a parameter; `is_finding` is implemented once, in
the foundational T008; and the e2e's source-promotion (T034) uses a direct SQL update, since `finish_run` cannot
touch an already-finished row.

**Tests**: REQUIRED — Principle VII (tests first, one e2e per feature). Every test carries a traceability token
`012/FR-###` / `012/SC-###` (or a module-level `FEATURE = "012"`). Tests are written FIRST and must fail before the
implementation task that satisfies them. Every store in a test is a temporary one (`tmp_path`), never the
repository's `data/kestrel.db`; offline tests use the existing `ModelTransport`/`StubJudge`/`SpyExperienceStore`
doubles (`tests/support.py`, `tests/conftest.py`) — no new test double classes should be needed. **No attack
wording anywhere** — neutral placeholder messages, replies and fixtures only (FR-046).

**Organization**: by user story. MVP = Setup + Foundational + US1 (the single replay with its outcome and
side-by-side — the whole point of the feature). US2 (memory/report isolation) stands beside US1 at P1 because it
is the safety property every later story inherits. US3 (batch) and US4 (the CI gate) are P2 increments that reuse
US1's engine unchanged. The roadmap edit (FR-050) is the last task of all, in the Polish phase (**Phase 7**),
and is never part of the spec-only pull request.

**Hard rules carried into every task**: no attack-prompt text in this feature's own code, tests, fixtures or
commits (FR-046); no auth header value, API key, target URL or target display name ever reaches the judge, a log
line, or the CI script's output (FR-047); no new dependency, required or optional (Principle X, FR-048); every
normal (non-replay) run's behaviour, scoring, storage, logging, shared-pattern/memory write-back and OWASP report
stay exactly as they are today (FR-049) — a replay and a batch replay are strictly additive. FR-046, FR-050 and
SC-009 are process/authoring rules rather than single testable behaviours; they are justified in
`specs/012-regression-replay/traceability.md` (T037) rather than given their own dedicated test, the same way
FR-048 already is.

## Phase 1: Setup

- [X] T001 [P] Document the new setting in `.env.example` beside the other `KESTREL_EXPERIENCE_*`/`KESTREL_EXPERIMENT_*`
      variables: `KESTREL_REPLAY_BATCH_MAX_RUNS=20` ("the most replayable runs a single batch replay will process
      for one target; a target with more than this many refuses the whole batch before sending anything"), noting
      it is reported on `GET /api/config` (012/FR-031).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks every user story**: schema v10, the settings/catalogue fields every later line and endpoint needs, and
the two pure functions (`check_replayable`, `compute_outcome`) every story's eligibility and outcome logic shares.

- [X] T002 [P] Unit test `tests/unit/test_store_migration_v10.py` (`FEATURE = "012"`), following the
      `test_store_migration_v9.py` convention: build a hand-written schema-9-shaped database (as that file already
      does for schema 8→9), run `TargetStore.__init__`/`_migrate` against it, and assert: the `meta.schema_version`
      row reads `"10"`; `PRAGMA foreign_key_check` returns empty immediately after; a pre-existing run row has
      `source_run_id` and `replay_outcome` both `NULL`; inserting a row with `mode='replay'` and `source_run_id`
      pointing at an existing run succeeds and round-trips through `get_run`; inserting a row with `mode='bogus'`
      still raises `sqlite3.IntegrityError` (the widened CHECK accepts exactly `single_turn`, `adaptive`,
      `replay`); deleting the shared target removes the source row and the replay row together in one statement
      with `PRAGMA foreign_key_check` still empty afterward; a `run_turns`, a `report_recommendations` and a
      `run_log` row attached to a surviving run are still readable after the rebuild (their `CASCADE` did not
      fire — the parent was renamed, not deleted), and a surviving `experiment_runs` row's `run_id` still points
      at its run (`SET NULL` did not fire either); both `runs` indexes exist and are queryable; running `_migrate`
      a second time against the now-v10 database is a no-op. **The `sqlite_sequence` fix**: build a database,
      delete its highest-numbered runs so `sqlite_sequence.seq` for `runs` sits above the highest surviving id
      (for example, a sequence of 5 with only ids up to 3 surviving), run
      `_migrate`, insert one more run, and assert its new id is **above the pre-migration sequence** — never a
      freed, reissued one (data-model.md, "Verified empirically" item 7). **An interrupted replay always gets an
      outcome**: hand-craft an `in_progress` row with `mode='replay'`, run
      `store.close_interrupted_runs()`, and assert the finished row has `replay_outcome == 'inconclusive'`
      (never `NULL`); a same-shaped `in_progress` **non-replay** row's `replay_outcome` stays `NULL` after the
      same sweep (012/FR-012, FR-015, FR-020).
- [X] T003 [P] Unit test `tests/unit/test_replay_eligibility.py` (`FEATURE = "012"`): `check_replayable` over
      hand-built `Run` objects — a `mode="replay"` run raises `ReplayOfReplay` carrying its own `source_run_id`; an
      `in_progress` run raises `NotReplayable("in_progress")`; a finished run with `verdict` `"failed"`,
      `"unclear"` or `None` (including one with `failure_step` set — the send-failed shape) raises
      `NotReplayable("not_succeeded")`; a finished, succeeded adaptive run with `turns_used` `0`/`None`
      (defensive; not reachable through normal operation) raises `NotReplayable("no_message")`; a finished,
      succeeded single-turn or adaptive run with at least one recorded message returns normally.
      `TargetStore.list_replayable_runs(target_id)`, against a temporary store seeded with a mix of eligible and
      ineligible runs across two targets: returns only the first target's finished, succeeded, non-replay runs,
      oldest `started_at` first (ties broken by `id`), excludes a `replay`-mode run even if (hypothetically)
      marked succeeded, and raises `TargetNotFound` for an unknown target id; **the list is unaffected by whether
      a different run is currently in progress on the target** — that is `compute_replay_status`'s own concern
      (below), never folded into this query. **`compute_replay_status(run, target, terms_version,
      adaptive_max_turns, target_has_other_run_in_progress)`** (`data-model.md`): for each of
      the five `check_replayable` failure cases above, returns `ReplayStatus(False, <the exact
      REPLAY_BLOCKED_REASONS string>, None)`, word for word (`"A run still in progress can't be replayed."`,
      `"Only a succeeded run can be replayed."`, `"This run has no recorded message to resend."`, and the
      `ReplayOfReplay` case's `"This run is itself a replay of run #<N>."` with the real id substituted); for an
      otherwise-eligible run whose target's `permission_confirmed_at` is falsy, returns `(False, "Tick the
      permission box and save the target before attacking it.", None)`; for one whose target's `terms_version`
      differs from the passed-in current version, returns `(False, "The terms of service have changed; read
      them and tick the box again.", None)` — proving `replayable` depends on the **target**, not the run alone;
      for one that passes permission and terms but whose `target_has_other_run_in_progress` is `True`, returns
      `(False, "A run against this target is already in progress.", None)`; for an eligible run on a
      fully-current target with no other run in progress and `turns_used` at or below `adaptive_max_turns`,
      returns `(True, None, None)`; for one whose `turns_used` exceeds `adaptive_max_turns`, returns `(True, None,
      "This source recorded more turns than the current adaptive limit; the replay can end at best still
      vulnerable or inconclusive.")` — the exact advisory, independent of `blocked_reason` (012/FR-004, FR-005,
      FR-006, FR-040, FR-042).
- [X] T004 [P] Unit test `tests/unit/test_replay_outcome.py` (`FEATURE = "012"`):
      `compute_outcome(turn_results: list[str | None], recorded_total: int, winning_turn: int | None)` —
      `turn_results` containing a `"succeeded"` anywhere is always `"still_vulnerable"`, even with
      `len(turn_results) < recorded_total` (proving "stop at first success" is not misread as "cut short");
      with `recorded_total == 1`, every entry `"failed"` and `len(turn_results) ==
      recorded_total` is `"fixed"`; every entry `"failed"` but `len(turn_results) < recorded_total` is
      `"inconclusive"`; a `None` entry **anywhere in the list, including the first**, with every other entry
      `"failed"`, is `"inconclusive"` — **the exact regression case**: `turn_results = [None, "failed",
      "failed"]` with `recorded_total = 3`, `winning_turn = 3` (the last turn — the winning turn a real run of
      this shape would actually have) MUST be `"inconclusive"`, never `"fixed"` (a naive implementation reading
      only the *last* entry, or a run's own aggregate `verdict`, would wrongly say `"fixed"` here); an empty
      `turn_results` with `recorded_total = 1` (the send itself failed) is `"inconclusive"`; a one-entry
      `turn_results` (`"succeeded"` / `"failed"` / `None`) with `recorded_total = 1` covers the single-turn case
      with no special-casing. **The single-message case, `recorded_total == 1`**:
      `compute_outcome(["failed"], 1, None) == "fixed"` — a single-message source with no recorded
      `succeeded_turn` (every single-turn run's own `succeeded_turn` column is always `NULL`, `store.py`'s own
      schema comment; `runs.py::execute_run` never sets it) is `"fixed"` when its one turn is judged failed; the
      winning-turn check does not apply at all for `recorded_total == 1`, regardless of what `winning_turn` is —
      gating on `recorded_total > 1`, never on `winning_turn is None`, is what this case proves. **The
      winning-turn addition, `recorded_total > 1`**: a
      multi-message source is `"fixed"` only when `turn_results` is full length, every entry `"failed"`, **and**
      `turn_results[winning_turn - 1] == "failed"`; the winning turn not sent at all (the current turn limit cut
      the replay short
      before reaching it, so `len(turn_results) < recorded_total`) → `"inconclusive"`; the winning turn sent but
      `"unclear"`/a judge error (its own `turn_results` entry is `None`, even though every *other* entry is
      `"failed"`) → `"inconclusive"`; `winning_turn is None` (the defensive no-recorded-winning-turn case,
      multi-message only) with
      every entry otherwise `"failed"` and full length → `"inconclusive"`, never `"fixed"`. **A defensive,
      synthetic case** (not a shape any real run produces, since a run's winning turn is always its own last
      recorded turn — label it as such in the test): `recorded_total = 3`, `winning_turn = 2`, every entry
      `"failed"` → `"fixed"`, exercising `compute_outcome`'s position-indexing logic on an input a real source
      cannot actually have (012/FR-012, FR-013, FR-014, FR-015, FR-016,
      012/SC-002).
- [X] T005 [P] Extend `tests/unit/test_settings_*.py` (or a new `tests/unit/test_settings_replay.py`,
      `FEATURE = "012"`): with `KESTREL_REPLAY_BATCH_MAX_RUNS` unset, `Settings.replay_batch_max_runs == 20`; `0`,
      `-1` and `abc` each raise `SettingsError` naming the variable; `5` parses to `5`. Extend
      `tests/integration/test_api_base.py`: `GET /api/config` reports `replay.max_batch_runs == 20` by default and
      the overridden value when the setting is overridden —
      `replay.per_replay_time_limit_s == max(settings.adaptive_time_limit_s, runs.TOTAL_DEADLINE_S)` (300 at the
      shipped defaults, since `TOTAL_DEADLINE_S` is 90), and it tracks `KESTREL_ADAPTIVE_TIME_LIMIT_S` when that
      is raised above 300; **proving this is genuinely `max(...)`, not the
      adaptive limit alone**: a further case with `KESTREL_ADAPTIVE_TIME_LIMIT_S` set *below* 90 (the single-turn
      deadline) asserts `replay.per_replay_time_limit_s` stays `90`, never dropping to the lowered adaptive value
      (012/FR-031).
- [X] T006 [P] Extend `tests/unit/test_events.py` (`FEATURE = "012"` on the new cases, or scoped tokens): emitting
      `"run.start"` with `source_run_id=12` renders that field with no `log.unknown_field` warning, and **omits
      the key entirely** when not given (never `"source_run_id": null`); emitting `"run.end"` with
      `replay_outcome="fixed"` renders it, and **omits the key entirely** when not given — **not
      `"replay_outcome": null`**, unlike `verdict`/`succeeded_turn`, which the catalogue already
      marks `| null` and are always present (`log-records-delta.md`); a new `events.replay_batch_started(
      target_id=3, replayable_count=5, cap=20)` renders one `replay.batch.start` record with exactly those fields
      (plus the common fields); a new `events.replay_batch_ended(target_id=3, fixed=2, still_vulnerable=1,
      inconclusive=0, duration_ms=450, complete=True)` renders one `replay.batch.end` record with
      `fixed_count=2, still_vulnerable_count=1, inconclusive_count=0, duration_ms=450, complete=True` and no
      `stop_reason`/`error` fields; `complete=False, stop_reason="run_in_progress"` adds `stop_reason` and keeps
      `complete` false; `error="RunInProgress"` adds it and raises the record to ERROR level (012/FR-043, FR-044,
      FR-045).
- [X] T007 Implement schema v10 in `src/kestrel/store.py` per `data-model.md`: `SCHEMA_VERSION = "10"`;
      `RUNS_COLUMNS_SQL`'s `mode` CHECK widens to `('single_turn', 'adaptive', 'replay')`, plus
      `source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE` and
      `replay_outcome TEXT CHECK (replay_outcome IS NULL OR replay_outcome IN ('fixed', 'still_vulnerable',
      'inconclusive'))`; `_migrate`'s version-acceptance guard extends to accept `"9"`; a new
      `_rebuild_runs_for_replay(db)` (textually parallel to `_rebuild_runs_with_autoincrement`, called right after
      it in `_migrate`, guarded on `"source_run_id" not in {PRAGMA table_info(runs) column names}`, following the
      exact same procedure: `PRAGMA foreign_keys = OFF` before any DML, `runs_new` built from the updated
      `RUNS_COLUMNS_SQL`, `INSERT ... SELECT` by the *old* table's own dynamic column list, drop, rename, the two
      indexes as **separate** `execute()` calls, `PRAGMA foreign_key_check` empty before `commit()`, then `PRAGMA
      foreign_keys = ON`) — **plus the `sqlite_sequence` fix**: read
      `SELECT seq FROM sqlite_sequence WHERE name = 'runs'` *before* the drop, and after the rename, `UPDATE
      sqlite_sequence SET seq = ?` with `max(that old seq, MAX(id) actually copied)`, inside the same
      transaction (before `foreign_key_check`/`commit`) — a plain rename otherwise loses the old sequence row
      entirely, letting a freed id be reissued and collide with a surviving `memory:run:<id>` record
      (`experience/store.py:287`, the `sqlite_sequence` fix); `Run` gains `source_run_id: int | None = None` and
      `replay_outcome: str | None = None`, read in `TargetStore._run(row)`; `claim_run(..., source_run_id: int |
      None = None)` and `finish_run(..., replay_outcome: str | None = None)` each gain one optional keyword and
      one column on their `INSERT`/`UPDATE`. **`close_interrupted_runs` must also close a replay
      with an outcome**: its `UPDATE` gains `replay_outcome = CASE WHEN mode = 'replay' THEN 'inconclusive' ELSE
      replay_outcome END` (a no-op for a non-replay row, whose `replay_outcome` is already `NULL`) (012/FR-020,
      FR-012, FR-015).
- [X] T008 Implement `src/kestrel/replay.py` (new module): `NotReplayable(reason: str)`,
      `ReplayOfReplay(source_run_id: int)`, `check_replayable(run: Run) -> None` per the truth table in
      `data-model.md`; `TargetStore.list_replayable_runs(target_id: int) -> list[Run]` in `store.py` per the SQL in
      `data-model.md`. `REPLAY_BLOCKED_REASONS`, `REPLAY_ADVISORY_OVER_TURN_LIMIT`,
      `ReplayStatus` and `compute_replay_status(run, target, terms_version, adaptive_max_turns,
      target_has_other_run_in_progress) -> ReplayStatus` per `data-model.md` — wraps `check_replayable`, then
      additionally checks `target.permission_confirmed_at`, `target.terms_version`, and
      `target_has_other_run_in_progress` (in that order — `REPLAY_BLOCKED_REASONS["run_in_progress"]`, the exact
      wording `POST /api/runs` already uses, `api/main.py:354`), then the advisory; never raises. **Placed here,
      not in T027**: also implement `is_finding(run: Run) -> bool` (`run.verdict == "succeeded" and run.mode !=
      "replay"`, per `data-model.md`) here, in the foundational phase, since T022 (US1, API schemas) already
      depends on it existing before T027 (US2) is reached; T027 only wires the UI to it (012/FR-004, FR-005,
      FR-006, FR-027, FR-040, FR-042).
- [X] T009 Implement `compute_outcome(turn_results: list[str | None], recorded_total: int,
      winning_turn: int | None) -> str` in `src/kestrel/replay.py` per `data-model.md`'s truth table: per-turn
      results, never a run's aggregate `verdict`, and — for `recorded_total > 1` — the source's own winning turn
      (`winning_turn`, 1-based, `source.succeeded_turn`) must itself have been sent and judged `"failed"` for the
      outcome to be `"fixed"` (012/FR-012, FR-013, FR-014, FR-015, FR-016).
- [X] T010 [P] Implement the setting and its surface: `DEFAULT_REPLAY_BATCH_MAX_RUNS = 20` and
      `Settings.replay_batch_max_runs: int` (parsed by the existing `positive_int` helper) in `src/kestrel/settings.py`;
      `ReplayOut(max_batch_runs: int, per_replay_time_limit_s: int)` and `ConfigOut.replay: ReplayOut` in
      `src/kestrel/api/schemas.py`; filled in `get_config` in `src/kestrel/api/main.py`, with
      `per_replay_time_limit_s = max(settings.adaptive_time_limit_s, TOTAL_DEADLINE_S)` (imported from
      `kestrel.runs`) (012/FR-031).
- [X] T011 Implement the catalogue and helpers in `src/kestrel/events.py` per `contracts/log-records-delta.md`:
      `CATALOGUE["run.start"]` gains `source_run_id` (wired through the existing `_present(...)` filtering
      `run_started` already uses for every other optional field, so it is omitted, never `null`, when absent);
      `CATALOGUE["run.end"]` gains `replay_outcome`, included in `_run_end`'s `fields` dict **only when present**
      — read it off the **local** `outcome = ctx.outcome or {}` `_run_end`
      already binds on its first line (`events.py:388`), i.e.
      `fields.update(_present({"replay_outcome": outcome.get("replay_outcome")}))`, **never**
      `ctx.outcome.get(...)` directly — `ctx.outcome` is `None` whenever a run raises before it finishes, and
      `None.get(...)` would crash exactly in that case; **not** unconditionally either way, unlike
      `verdict`/`succeeded_turn`, which the catalogue already marks `| null`; two
      new catalogue entries `"replay.batch.start": ("target_id", "replayable_count", "cap")` and
      `"replay.batch.end": ("target_id", "fixed_count", "still_vulnerable_count", "inconclusive_count",
      "duration_ms", "complete", "stop_reason", "error")`; `replay_batch_started(*, target_id, replayable_count,
      cap)` and `replay_batch_ended(*, target_id, fixed, still_vulnerable, inconclusive, duration_ms, complete,
      stop_reason=None, error=None)` emitted unscoped (`scoped=False`, no enclosing run scope — there is no
      single `run_id` for a whole batch), mirroring `events.connection_test`'s existing shape. This feature's
      implementation PR edits `specs/010-structured-logging/contracts/log-records.md` to merge in
      `contracts/log-records-delta.md`'s rows verbatim and therefore carries a `spec-change:` note (the
      traceability gate requires it whenever a spec file changes alongside `src/`) (012/FR-043, FR-044, FR-045).

**Checkpoint**: `uv run pytest tests/unit/test_store_migration_v10.py tests/unit/test_replay_eligibility.py
tests/unit/test_replay_outcome.py tests/unit/test_settings_replay.py tests/unit/test_events.py
tests/integration/test_api_base.py` green; nothing can be replayed yet, but every building block it needs exists.

---

## Phase 3: User Story 1 — Prove whether a specific finding was fixed (P1) 🎯 MVP

**Goal**: replay one run through the API (and the UI's Replay button), verbatim, with no attacker-model call,
scored like a live run (every turn's own result, never a run's one aggregate verdict), stopping at the first
success, and see the outcome plus the source/replay side by side.

**Independent Test**: seed a finished, succeeded single-turn run and a finished, succeeded adaptive run against a
stub target; replay each; assert the target received exactly the recorded message(s) verbatim and in order, zero
attacker-model calls were made, the stored outcome matches the scoring rule for a target that now fails, one that
still falls for it, one that fails to answer, and one whose first turn is unclear but later turns fail cleanly,
and the comparison is readable afterward.

### Tests for User Story 1

- [X] T012 [P] [US1] Unit test `tests/unit/test_replay_comparison.py` (`FEATURE = "012"`): `build_comparison` for
      a single-turn pair (exactly one synthetic `TurnComparison` per run, built from the runs' own top-level
      fields, no `run_turns` involved); for an adaptive pair where the source recorded more turns than the replay
      sent, the unsent positions are `sent=False, replay_verdict=None`; for a pair whose **last** sent turn ended
      by a canary (`hard_evidence=True, succeeded_turn=N`), that turn's displayed verdict is `"succeeded"` even
      when its stored `run_turns.judge_verdict` is a stale value copied from an earlier judged turn (construct this
      exact scenario by hand, per research D7's induction); for a pair whose last sent turn ended by a send failure
      (`failure_step` set, no judge ever reached that turn), that turn's displayed verdict is `None` ("not
      judged"); for every turn **before** the last one sent, the displayed verdict is exactly the stored
      `judge_verdict`; `multi_turn_caption` is exactly the pinned FR-041 string
      (**"A multi-turn replay re-tests the recorded messages, not an adaptive attack."**) for a pair built from
      more than one recorded message, and `None` for a single-turn pair (012/FR-017, FR-018, FR-019, FR-041).
- [X] T013 [P] [US1] Integration test `tests/integration/test_replay_run.py`, the single-turn part: over
      `make_client` with a `ModelTransport` and a stub target, run one single-turn attack to a succeeded verdict,
      then replay it under four target behaviours (now failing the attack, now still falling for it, now failing
      to answer, and the sender raising an unexpected exception mid-send)
      and assert: the target receives exactly the source's `prompt_text`, byte for byte, as its one request;
      `model_transport.model_requests("attacker")` stays empty across all four; the judge call recorded by
      `StubJudge`/`ModelTransport` carries no `conversation` value (the `execute_run`-shaped call, FR-008); the
      new run's `mode == "replay"`, `source_run_id` names the source, `attacker_model is None`,
      `use_prior_experience is False`; the recorded `replay_outcome` is `fixed` / `still_vulnerable` /
      `inconclusive` / `inconclusive` matching each of the four behaviours (the crash case closing the row with
      `replay_outcome == "inconclusive"`, mirroring `execute_run`'s own `except Exception` pattern,
      `runs.py:126-129`, plus the new `replay_outcome` write); `judge_prompt_id`/`version` on the replay reflect
      the **currently** configured judge even when a different `system_prompt` was pinned for the source's own
      run; **a sender double, not the stub
      HTTP target, or the test cannot fail**: `run_test` (the real sender behind the stub HTTP target this test
      otherwise uses) already masks an echoed secret on its own, so asserting the masked value through it proves
      nothing about `_send_turn` itself; instead call `execute_replay(..., sender=sender_returning(...))` directly
      with a sender double that returns the literal `"test-key-123"` secret in its reply text (mirroring
      `test_adaptive_graph.py`'s `sender_returning`/`RESOLVED` pattern) and assert the replay's own stored
      `reply_text` has it masked, not the raw value — a lift that silently dropped `_send_turn`'s own masking
      would fail only this assertion, never one that goes through `run_test` (012/FR-001, FR-002, FR-003,
      FR-007, FR-008, FR-009, FR-012, FR-015, FR-020, FR-021, FR-022, FR-024, 012/SC-001, SC-002).
- [X] T014 [US1] Integration test `tests/integration/test_replay_run.py`, the adaptive part: run one adaptive
      attack to a succeeded verdict with at least 3 recorded turns, then replay it and assert: each resent message
      equals the source's `run_turns[i].attacker_message` verbatim, in order; zero attacker-model calls across
      every turn; each turn's judge call carries the **replay's own** conversation so far — change the stub
      target's reply between the source run and the replay and assert the judge saw the new reply text, not the
      source's original one (FR-008's "never the source run's original replies"); a replay that succeeds on an
      early turn sends no further recorded messages (fewer target requests than the source recorded); a source
      replayed while `KESTREL_ADAPTIVE_MAX_TURNS` is set lower than the source's own `turns_used` stops at the
      current cap and is recorded `inconclusive`, never `fixed`; each resent turn's `attacker_prompt_id`/`version`
      equal the **source's own turn's** values — read from `source_turns[turn - 1]` for **both** the message and
      the provenance copy, the same index: assert they name the *same* turn by constructing a source whose turn
      2's own `attacker_prompt_version` differs from turn 3's, and confirming the replay's turn 2 and turn 3 each
      copy their own, not their neighbour's. **The exact regression case**: a replay whose stubbed judge returns
      `JudgeError` on turn 1 (or returns the judge-model verdict `"unclear"` on turn 1 — an unclear verdict or a
      judge error, never "no judge configured", since judge configuration is a run-wide setting, not something
      that varies turn by turn) and a clean `"failed"` verdict on every later turn, with every recorded message
      sent, MUST be recorded `inconclusive`, **never `fixed`**: an early unresolved turn must not be hidden
      behind later clean failures. **A crash mid-adaptive-replay**: monkeypatch a graph node to raise after at
      least one turn has recorded, and assert the row closes with `verdict == "unclear"` and `replay_outcome ==
      "inconclusive"` (a **new** exception handler around `run_replay_adaptive`'s own `compiled.ainvoke(...)` —
      `run_adaptive` itself has no such handler and is not given one here, FR-049) and that `ReplayFailed` is
      raised, carrying the closed run's id. **The same sender-double fix as T013, over the lifted `_send_turn`**:
      inject a sender double (not the stub HTTP target behind `run_test`, which already masks on its own and so
      cannot catch this regression) that returns the literal `"test-key-123"` secret in some turn's reply text,
      and assert that turn's stored `reply_text` has it masked. **A replay's own `turn_started`/`pending_canary`
      signals survive the lift**: assert each replayed turn's `events.turn_started` fires with the correct turn
      number (via the `json_log` fixture's `turn` line) and that a turn without a canary hit records
      `canary_hit: false` on its own `turn` line, exactly as `graph.py:110-112` already guarantees for a live
      run's turn 1 — proving the replay's own `attacker_node` preserves both, not only the message lookup.
      **The winning-turn rule and the multi-turn caption, on sources a real run can actually produce** (a run
      always stops at its first success, so its own winning turn is always its own last recorded turn — this
      test never constructs a source shaped otherwise): the 3-turn source above, replayed so every turn,
      including its own last (winning) turn, is sent and judged `"failed"`, is recorded `fixed`; the **same**
      source with its own `succeeded_turn` column cleared to `NULL` by hand (the defensive, not-reachable-
      through-normal-operation case — never produced by a real run, but still a value `compute_outcome` must
      handle) replayed the same way, every turn sent and judged `"failed"`, is recorded `inconclusive`, never
      `fixed` — proving the fail-closed guard, not the "did every turn fail" rule, is what catches a
      multi-message source with no recorded winning turn. `GET /api/runs/{the replay's id}`'s
      `comparison.multi_turn_caption` equals the pinned FR-041 string for this multi-turn source. A
      single-turn-shaped edge within the adaptive branch (one recorded turn only — this adaptive source itself
      succeeded on turn 1, so `succeeded_turn == 1` here, a real value, **not** `NULL` the way a single-turn-mode
      source's always is) behaves the
      same as the single-turn branch's stop/outcome rule (`fixed` on one sent, judged-failed turn — the
      winning-turn check is skipped outright for `recorded_total == 1`, whether `succeeded_turn` is `1` or
      `None`) and carries no caption (012/FR-001, FR-002, FR-003, FR-007, FR-008,
      FR-009, FR-010, FR-011, FR-012, FR-014, FR-015, FR-020, FR-021, FR-022, FR-023, FR-024, FR-041, 012/SC-001,
      SC-002).
- [X] T015 [P] [US1] Integration test `tests/integration/test_replay_api.py`: `POST /api/runs/{id}/replay` on an
      eligible run → **201** `RunDetail` with `comparison` present; on an `in_progress` run → **409**
      `not_replayable` with message `"A run still in progress can't be replayed."`; on a `failed`/`unclear` run,
      and separately on one whose send failed (`failure_step` set, `verdict` `None`) → **409** `not_replayable`
      with message `"Only a succeeded run can be replayed."` for both; on a run whose own `mode == "replay"` →
      **409** `replay_of_replay` with message `"This run is itself a replay of run #<N>."` naming that run's own
      `source_run_id`; on an unknown run id → **404**; the existing `permission_missing`/`terms_outdated`/
      `run_in_progress` preconditions refuse a replay exactly as they refuse `POST /api/runs` today, same wording
      (toggle each one); `GET /api/runs/{id}` for a non-replay run has `comparison: null` and `replay_outcome:
      null`. **The status fields depend on the target, not the run alone**:
      `RunSummary` and `RunDetail` for every run carry `finding` (true only for a succeeded, non-replay run),
      `replayable`, and (only when `false`) `replay_blocked_reason`, all
      computed server-side via `compute_replay_status`; assert the field's *value* for each of T003's five
      run-level ineligibility cases, using the exact reason strings now pinned in `spec.md` FR-004/FR-005/FR-006;
      **and**, for an otherwise-eligible run, toggle its target's permission off and assert `replayable` becomes
      `false` with `replay_blocked_reason == "Tick the permission box and save the target before attacking it."`,
      then restore permission but change the loaded terms version and assert `replayable` becomes `false` with
      `replay_blocked_reason == "The terms of service have changed; read them and tick the box again."`, then
      restore terms but claim an unrelated `in_progress` row on the same target and assert `replayable` becomes
      `false` with `replay_blocked_reason == "A run against this target is already in progress."` — proving
      `replayable` is **not** `check_replayable(run)` alone; for a replayable adaptive run whose `turns_used`
      exceeds a lowered `KESTREL_ADAPTIVE_MAX_TURNS`, assert `replayable == true` and `replay_advisory` carries
      the exact over-turn-limit text, independent of `replay_blocked_reason` (`null`) — never re-deriving any of
      this in the test's own assertion logic. **The multi-turn caption**: `GET /api/runs/{id}` for a replay of a
      multi-message source carries `comparison.multi_turn_caption` equal to the pinned FR-041 string, and `null`
      for a replay of a single-message source (012/FR-004, FR-005, FR-006, FR-017, FR-027, FR-038, FR-039,
      FR-040, FR-041, FR-042, 012/SC-005).
- [X] T016 [P] [US1] Integration test `tests/integration/test_events_replay.py` (`FEATURE = "012"`), the
      single-replay part: through the `json_log` fixture, replay a run and assert: `run.start` carries
      `source_run_id` and `mode: "replay"`; every `turn` line omits `attacker_model`/`attacker_prompt` (no
      `attacker_generated` turn at all, including turn 1 — different from a normal adaptive run); zero
      `model.request` lines with `kind: "attacker"`; zero `memory.retrieval` lines; zero `memory.writeback` lines;
      `run.end` **has no `replay_outcome` key at all** for a non-replay run elsewhere in the same stream, and
      carries the computed `replay_outcome` (a real value, never `null`) for the replay; `memory_written: null`
      renders for the replay; **a replay's `turn` lines still carry what every
      other `turn` line carries**: for an adaptive replay, each `turn` line names the correct `turn` number (in
      order, starting at 1) and carries `duration_ms` and the token fields (`prompt_tokens`/`completion_tokens`/
      `total_tokens`, non-`None` whenever a judge call happened that turn) exactly as a live adaptive run's own
      `turn` lines do — the shared-node lift (T017) must not silently drop these; across the whole stream, no
      attack text, reply text, judge reason/progress text,
      the stub target's URL, or the auth header's secret value appears anywhere (reusing the known-marker
      constants in `tests/support.py`) (012/FR-043, FR-045, FR-047, 012/SC-008).

### Implementation for User Story 1

- [X] T017 [US1] **Restructure `attack/graph.py`'s per-turn nodes so a second graph can share them
      (`judge_node`/`send_node`/`evidence_node`/`decide_node` are closures defined inside
      `run_adaptive` today, not separately callable by a sibling function without either duplicating the body or
      lifting it out).** Lift all four to module-level
      functions parameterised by what they used to close over (`_judge_turn`, `_send_turn`, `_check_evidence`,
      `_decide_next` — research D14); `run_adaptive`'s own `judge_node`/`send_node`/`evidence_node`/`decide_node`
      become one-line closures wired to them. The lifted `_send_turn` MUST keep the reply masking
      `graph.py:138` (`mask_values(outcome.reply_text or "", secrets)[:MAX_REPLY_CHARS]`) does today — `secrets`
      becomes a parameter the lift carries through explicitly, not something `_send_turn` closes over; both
      `run_adaptive` and `run_replay_adaptive` pass their own target's secret values. **The regression gate
      names files that must exist; verify each path before running:**
      `tests/unit/test_adaptive_graph.py`, `tests/integration/test_api_runs_adaptive.py`,
      `tests/integration/test_log_records_adaptive.py`, `tests/integration/test_provenance_recorded.py`,
      `tests/integration/test_prompt_provenance_pinned.py`, `tests/integration/test_tracing_run.py` — **and**,
      because a refactor this size can affect more than the files that exercise `run_adaptive` by name, run the
      **full offline suite** (`uv run pytest tests/unit tests/integration`) before the lift (baseline) and after
      it, and confirm the two runs report the same pass/fail set — the regression gate for this extraction
      (012/FR-049; research D14).
- [X] T018 [US1] Implement `run_replay_adaptive(...)` in `src/kestrel/attack/graph.py`, wired to T017's shared
      functions, with its **own** `attacker_node`/`record_node` (not shared — a model call vs. a list lookup;
      run-wide-constant provenance vs. per-turn copied provenance): both compute `turn = state["turns_used"] + 1`
      exactly as the live `attacker_node` already does, and index `source_turns[turn - 1]` **consistently** for
      the message lookup (`attacker_node`) and the `attacker_prompt_id`/`attacker_prompt_version` copy
      (`record_node`) — the same index for both, closing the off-by-one T014 tests for; `turn <= len(source_turns)`
      sends the next recorded message (already masked; resent verbatim, FR-001), otherwise sets `outcome` with
      `stopping_condition="turn_cap"` (the same `decide_node` path a live run's turn-cap stop already uses,
      research D2); `record_node` passes `attacker_generated=False` unconditionally (every turn — no
      `events.turn_ended` signature change, research "Events" code-fact) and, per turn, appends this turn's own
      result (`"succeeded"` on a canary hit, else the judge's verdict when genuinely judged this turn, else
      `None`) to a local `turn_results` list (data-model.md, "Capturing `turn_results` live" — **not** read back
      from storage afterward). **New**: wraps `await compiled.ainvoke(...)` in
      `try/except Exception as error: store.finish_run(run_id, verdict="unclear", reason="The run failed
      unexpectedly.", replay_outcome="inconclusive"); events.run_finished(...)` (logged the same way any run's own
      unexpected failure already is — exc_type and stack only, never the message, FR-045) `; raise
      ReplayFailed(run_id) from error` — a named exception
      (`kestrel.replay.ReplayFailed`, carrying the now-closed run's id), not a bare `raise` of the original error,
      so `execute_replay` (T019) and the batch loop (T028-T030) can tell "this row is already closed" apart from
      any other exception without inspecting state themselves — `run_adaptive` has no equivalent handler and is
      not given one (FR-049). On a clean finish,
      `replay_outcome = compute_outcome(turn_results, len(source_turns), source.succeeded_turn)`
      (`compute_outcome` and
      `ReplayFailed` lazily imported together, before the `try`: `from kestrel.replay import compute_outcome,
      ReplayFailed` **inside** this function, mirroring `runs.py:155`'s existing lazy import of `run_adaptive`, to
      avoid the module-level import cycle `replay.py` importing `run_replay_adaptive` from `graph.py` would
      otherwise create — research D14) passed to `store.finish_run(..., replay_outcome=replay_outcome,
      judge_prompt_id=..., judge_prompt_version=...)` (012/FR-001, FR-002, FR-007, FR-008, FR-009, FR-010, FR-011,
      FR-012, FR-014, FR-015, FR-020, FR-022, FR-023).
- [X] T019 [US1] Implement `execute_replay(store, *, source, source_turns, resolved, mode, judge, ...)` in
      `src/kestrel/replay.py`: for `source.mode == "single_turn"`, a body shaped like `runs.py::execute_run` (one
      send of `source.prompt_text`, `match_canary`, then `judge.judge(attack=.., reply=..)` with **no**
      `conversation` argument, only when no canary matched and a judge is configured, FR-008), building its own
      one-or-zero-entry `turn_results` list and calling `compute_outcome(turn_results, 1, source.succeeded_turn)`
      — `recorded_total` is always `1` here, so the winning-turn check is skipped outright regardless of
      `winning_turn`'s value, and a single-turn source's outcome is unaffected (`source.succeeded_turn` is in
      fact always `None` for this mode — `runs.py::execute_run` never sets it — but `compute_outcome` never
      inspects it when `recorded_total == 1`, which is exactly the point);
      wraps the body in `except Exception as error: store.finish_run(run_id, verdict="unclear", reason="The run
      failed unexpectedly.", replay_outcome="inconclusive")` (logged the same way any run's own unexpected
      failure already is — exc_type and stack only, never the message, FR-045) `; raise ReplayFailed(run_id) from
      error` — mirrors
      `runs.py::execute_run`'s own `except Exception` (`runs.py:126-129`) for closing the row, but raises the new
      `ReplayFailed(run_id)` (defined in this module) instead of the original exception unchanged, so the single-
      replay endpoint and the batch loop (T028-T030) both see the same exception shape regardless of which branch
      failed; for `source.mode == "adaptive"`, dispatch to `run_replay_adaptive` (T018) with `source_turns`
      ordered by `position` — that function already closes its own row and raises `ReplayFailed` itself (T018),
      so this branch adds no `except` of its own and simply lets it propagate. A failure **before**
      `store.claim_run(...)` succeeds (no row exists yet, on either branch) propagates as whatever bare exception
      was raised — never wrapped in `ReplayFailed`, which would name a run id that does not exist; the batch loop
      (T028-T030) is written to tell the two apart. Either branch, once claimed, uses
      `store.claim_run(mode="replay", source_run_id=source.id,
      prompt_id=source.prompt_id, prompt_title=source.prompt_title, prompt_text=source.prompt_text,
      family=source.family, owasp_category=source.owasp_category, attacker_source=source.attacker_source,
      attacker_model=None, use_prior_experience=False, ...)` and emits `events.run_started(..., mode="replay",
      source_run_id=source.id, ...)` (012/FR-001, FR-002, FR-003, FR-007, FR-008, FR-009, FR-012, FR-015, FR-020,
      FR-021, FR-022, FR-023, FR-024).
- [X] T020 [US1] Implement `build_comparison(source, source_turns, replay, replay_turns) -> Comparison` in
      `src/kestrel/replay.py` per `data-model.md`'s per-turn walk and the terminal-turn derivation of research D7;
      the single-turn synthetic-`TurnComparison` case; `multi_turn_caption` set to the pinned FR-041 string
      (**"A multi-turn replay re-tests the recorded messages, not an adaptive attack."**) when
      `len(source_turns) > 1`, else `None` (012/FR-017, FR-018, FR-019, FR-041).
- [X] T021 [US1] Wire `events.run_started`/`run_finished` (or `_run_end`) in `src/kestrel/events.py` to accept and
      pass through `source_run_id` (on start, via the existing `_present(...)` filter) and `replay_outcome` (on
      finish, read off `_run_end`'s local `outcome = ctx.outcome or {}` and included only when present — T011;
      never `ctx.outcome.get(...)` directly, since `ctx.outcome` is `None` when a
      run raises before finishing) per `contracts/log-records-delta.md` (012/FR-043).
- [X] T022 [US1] Implement the API in `src/kestrel/api/main.py`: `POST /api/runs/{run_id}/replay` (**201** on
      success; load the run, `replay.check_replayable`, the existing permission/terms/`run_in_progress`
      precondition checks against the run's target, `events.run_scope()`, `execute_replay` — **no** `write_back`
      call; its own refusal reuses the exact `compute_replay_status`/`REPLAY_BLOCKED_REASONS` strings, T008, so
      it can never read differently from what the run's detail already showed); `GET /api/runs/{run_id}` builds
      `comparison` via `build_comparison` when `run.mode == "replay"` (loading the source and both runs' turns).
      `src/kestrel/api/schemas.py`'s `RunSummary`/`RunDetail` gain
      `source_run_id`, `replay_outcome`, `finding: bool` (`is_finding(run)`, T008/data-model.md), `replayable`,
      `replay_blocked_reason`, `replay_advisory` — all three of the last
      filled from **one** call to `compute_replay_status(run, target, terms_version, settings.adaptive_max_turns,
      target_has_other_run_in_progress)` in the existing `run_summary`/`run_detail` helper functions (which
      therefore now need the run's `target`, the loaded `terms.version`, and whether a *different* run is
      currently `in_progress` on that target — load the target by `run.target_id`, and compute the in-progress
      flag the same way the existing `run_in_progress` precondition already does, excluding `run.id` itself from
      that check); `RunDetail.comparison: ReplayComparisonOut | None` — named `ReplayComparisonOut`, **not**
      `ComparisonOut`: that name already exists, `api/schemas.py:314`, for the unrelated 007
      experiment-significance shape used at `api/schemas.py:348` and `api/main.py:716` — reusing it would
      collide; the `not_replayable`/`replay_of_replay` **409** responses per `contracts/api.md` (012/FR-004,
      FR-005, FR-006, FR-017, FR-027, FR-038, FR-039, FR-040, FR-041, FR-042).
- [X] T023 [P] [US1] Implement the UI: `ui/api_client.py::replay_run(run_id)` (`POST /api/runs/{id}/replay`, a
      timeout covering one replay — the adaptive time limit plus a margin, the same shape `run_attack`'s own
      timeout already uses; **no** `batch_replay` client — the UI has no batch action, since the spec asks only
      for a single-run button). `ui/app.py`:
      - **The button MUST render before `_render_finding`'s failure-step early
        return (`app.py:520-525`)**, not after it: that `if run.get("failure_step"): ... return` exits before
        any code placed later in the function ever runs, so a run that failed to send would otherwise never show
        the button at all, even disabled. Render the button (and its caption/advisory) as the **first** thing
        `_render_finding` does, ahead of that branch, so it appears for every finished run alike.
      - A button labelled exactly **"Replay"**, `disabled=not run["replayable"]` with `run["replay_blocked_reason"]`
        shown as its caption when disabled,
        and — independently, whenever `run["replay_advisory"]` is not null (whether or not the button is
        disabled) — that advisory shown as a second caption; exact strings per `spec.md` FR-004 to FR-006/FR-040
        (no eligibility logic of its own, FR-042). **Key the button by its render
        context**: `_render_finding`'s caller passes a `key_prefix` ("result" from the just-finished-run card at
        `app.py:465`, "opened" from the run-list selector at `app.py:664`), and the button's Streamlit `key`
        includes both the prefix and the run's id (`f"replay_button_{key_prefix}_{run['id']}"`) — a fixed key
        would raise `DuplicateWidgetID` the moment both call sites render in the same pass.
      - After it finishes, a line reading exactly `"Outcome: " + outcome_label`, then — only when
        `comparison["multi_turn_caption"]` is not null — a line showing that caption text verbatim, then a
        side-by-side table from the returned run's `comparison` (column headings `"Source (run #N)"` /
        `"Replay (run #M)"`, row labels `"Verdict"`, `"Hard evidence"`, `"Judge model"`, `"Judge prompt"`, then
        `"Turn k"` per recorded message, an unsent one shown as `"not sent"` — exact strings per `spec.md`
        FR-017/FR-041).
      - Opening a replay run from the target's run list shows the same outcome line, caption and comparison, with
        a link back to the source labelled exactly `"Replay of run #N"`.
      - **These (the Outcome line, the caption when present, the comparison table, and the "Replay
        of run #N" link) render before `_render_finding`'s failure-step early return too, the same as the
        button**: a replay whose *own* send failed (`failure_step` set on the replay run itself, not the source)
        still has a real `comparison` (`build_comparison` already gives that replay's last, unsent-or-unjudged
        turn `replay_verdict: null` / "not judged" rather than omitting the row, FR-017 to FR-019) and a real
        `replay_outcome`, so FR-041 holds for it exactly as for any other finished replay — add this case (a
        replay run with its own `failure_step` set) to the UI test.
      - **The run listing (`render_runs`, `app.py:649`) shows every non-adaptive
        mode as `"single-turn"` today**, which would mislabel a replay; add a `"Source"` column (the source run
        id for a replay row, blank otherwise) and change the Mode column to show the exact label `"replay"` for
        a replay row instead of falling into the `"single-turn"` default (`spec.md` FR-039).
      - Add `tests/unit/test_ui_replay.py` (or extend an existing UI unit test, via `streamlit.testing.v1.AppTest`
        offline against `make_client`) covering: the button's disabled state and reason text for each
        ineligibility case, **including a run whose send failed** (the exact case
        the failure-step early return would otherwise have hidden the button for) **and one whose own target
        has a different run in progress** (`replay_blocked_reason == "A run against this target is already in
        progress."`); the advisory caption shown
        alongside an *enabled* button; the multi-turn caption line shown for a multi-message replay and absent
        for a single-message replay; that rendering both the result card and an opened run for the same, or
        for two different, replay-eligible runs in one script pass raises no `DuplicateWidgetID`; the run
        list's Mode and Source columns for a replay row (012/FR-039, FR-040, FR-041, FR-042).

**Checkpoint**: `uv run pytest tests/unit/test_replay_comparison.py tests/integration/test_replay_run.py
tests/integration/test_replay_api.py tests/integration/test_events_replay.py tests/unit/test_ui_replay.py` green,
plus `run_adaptive`'s own existing tests still green (T017) — a single run can be replayed end to end, through the
API and the UI, with a correct outcome and comparison.

---

## Phase 4: User Story 2 — Trust that checking a fix never teaches the attacker or clutters the findings (P1)

**Goal**: prove, not just assume, that a replay and a batch replay never call the experience store under any
outcome, and that a target's OWASP report — and its run page's headline counts — are unaffected by replaying one
of its own findings.

**Independent Test**: run a replay of each outcome and a batch replay against a `SpyExperienceStore` and assert
zero calls; generate a report, and read the headline counts, before and after replaying an existing finding and
assert both are unchanged.

### Tests for User Story 2

- [X] T024 [P] [US2] Integration test `tests/integration/test_replay_memory_isolation.py` (`FEATURE = "012"`): over
      `SpyExperienceStore`, replay a single-turn source and an adaptive source under each of the three outcomes
      (six replays total) **and a batch replay of several such sources** and assert `spy.queries == []` and
      `spy.pattern_writes == []` after every one, and that `write_memory` is never called either (extend
      `SpyExperienceStore` or add an equivalent spy for `write_memory` if it does not already record calls); assert
      every replay's own `memory_written` is recorded as `None` ("not attempted"), never `True` or `False`; as a
      structural guard (defence in depth, research "Experience isolation" code-fact), assert neither
      `kestrel.replay` nor the new `run_replay_adaptive` function imports anything from `kestrel.experience`
      (012/FR-025, FR-026, 012/SC-003).
- [X] T025 [P] [US2] Integration test `tests/integration/test_replay_report_exclusion.py` (`FEATURE = "012"`):
      generate a target's report (`GET /api/targets/{id}/report`) before and after replaying one of its existing,
      already-reported findings, and assert the finding count, the coverage rows, and the number of recommender
      judge calls are byte-for-byte identical; a target whose *only* succeeded run is itself a replay (seed it
      directly in the store) produces a report with zero findings. **The
      `finding` flag, tested directly, not just its downstream effect**: over `GET /api/targets/{id}/runs`,
      assert a succeeded, non-replay run's `RunSummary.finding is True`, and a replay run's (any verdict,
      including `"succeeded"`, the normal still-vulnerable case) `finding is False`, and a failed/unclear run's
      `finding is False` too. Add `tests/unit/test_ui_headline_cards.py` (or extend `test_ui_replay.py`,
      `streamlit.testing.v1.AppTest` offline against `make_client`): **one
      boolean cannot produce two cards, so the fixture must carry both at once**: seed a target with three runs —
      a confirmed finding (succeeded, non-replay, `hard_evidence=True`), a suspected finding (succeeded,
      non-replay, `hard_evidence=False`), and a succeeded replay (`mode="replay"`, `verdict="succeeded"`) — and
      assert the exact rendered value of each headline card: Confirmed `== 1`, Suspected `== 1`, Runs `== 3`
      (every run seeded, the replay included despite its own `verdict`/`hard_evidence`) — proving the split
      itself, not just `finding`'s downstream effect (012/FR-027, 012/SC-004).

### Implementation for User Story 2

- [X] T026 [US2] Implement the filter in `src/kestrel/api/main.py::target_report`: pass
      `[r for r in store.list_runs(target_id) if r.mode != "replay"]` into `build_report` and
      `recommendations_for`, instead of the unfiltered list — `report/model.py` and `report/recommend.py` stay
      untouched (research D9) (012/FR-027).
- [X] T027 [US2] **`is_finding` itself is implemented in the foundational T008** (T022
      already depends on it existing); this task only wires the UI to it. Fill `RunSummary.finding` with
      `is_finding(run)` wherever a summary is built (api/main.py). **One boolean cannot produce two cards**: in
      `ui/app.py::render_metrics` (`app.py:909-911`), drive the Confirmed card from `r.get("finding") and
      r.get("hard_evidence")` and the Suspected card from `r.get("finding") and not r.get("hard_evidence")` —
      never a `mode` check of the UI's own, exactly as FR-042 already requires for the Replay button; "Runs" (the
      total) is unaffected and still counts every run (012/FR-027).

**Checkpoint**: `uv run pytest tests/integration/test_replay_memory_isolation.py
tests/integration/test_replay_report_exclusion.py` green — the safety property US1's design already implied is
now proven, not assumed.

---

## Phase 5: User Story 3 — Check every past fix on a target in one action (P2)

**Goal**: one action replays every currently-replayable run of a target, oldest first, bounded by a configurable
cap, returning one entry per source plus counts per outcome — and, if a genuinely concurrent run collides with it
partway through, reports itself honestly incomplete rather than guessing or refusing outright.

**Independent Test**: a target with a mix of replayable and non-replayable runs batch-replays only the
replayable ones, oldest first, with accurate per-outcome counts and `complete: true`; a target over the
configured cap refuses the whole batch before sending anything; a target with nothing replayable completes
trivially; a batch that collides with a concurrent run partway through stops, reports `complete: false` with the
collision named and the unreached source ids listed, and is never scored as finished.

### Tests for User Story 3

- [X] T028 [P] [US3] Integration test `tests/integration/test_replay_batch.py` (`FEATURE = "012"`): seed a target
      with several replayable runs (mixing single-turn and adaptive, and mixing eventual fixed/still-vulnerable/
      inconclusive outcomes) plus one `in_progress` run, one `failed` run, and one `replay`-mode run, and assert
      `POST /api/targets/{id}/replays` processes **only** the replayable ones, oldest `started_at` first (assert
      the entries' order matches), each entry carrying `source_hard_evidence`/`replay_hard_evidence` alongside its
      verdicts; the result has exactly one entry per source, `counts` summing to `len(entries)`, and
      `"complete": true, "stop_reason": null, "not_replayed_source_ids": []`; a target with zero replayable runs
      returns **200** (not 201 — a batch result is not "one resource created")
      with `entries: []`, every count `0`, and `complete: true` (not a refusal); a target whose replayable count
      exceeds `KESTREL_REPLAY_BATCH_MAX_RUNS` (lower it via settings for the test) refuses with **409**
      `batch_too_large` naming the count and the cap, **before any new run row is claimed** (assert the run
      count for that target is unchanged after the refusal); a run produced by a feature-007 experiment counts
      toward the cap and is replayed like any other eligible run (seed one through the existing experiment test
      fixtures); **the batch is unaffected by the "another run in progress" reason** `compute_replay_status` now
      reports: `list_replayable_runs` (what the batch actually plans from) never calls `compute_replay_status` or
      takes an in-progress flag as input, so the existing "processes only the replayable ones... exactly one
      entry per source" assertion above already proves the batch's own sequential claiming of one entry at a
      time never shrinks its own planned list — no separate assertion needed, only this note that it is by
      construction, not by accident. **A mid-batch collision is a 200, never a 409**: claim an
      `in_progress` row on the target by hand between two of the batch's planned entries (simulating a genuinely
      concurrent run) and assert the response is **200** (not 409 or 201) with `"complete": false`, `"stop_reason":
      "run_in_progress"`, `entries` holding every source completed before the collision, and
      `"not_replayed_source_ids"` naming every planned source the batch never reached, in their planned order.
      **Fault
      injection must happen after a row is actually claimed**: monkeypatching `execute_replay` itself would
      never claim a row, so instead inject the fault through a sender double (the stub target's handler raises
      for one specific source) or a graph node, partway through a multi-entry batch — exercising `execute_replay`'s
      own `ReplayFailed` path for real, not a shortcut around it. Assert the response is still **200** (never
      500) with that entry **included** in `entries` with `outcome: "inconclusive"` and `replay_verdict:
      "unclear"` (its own run closed via `execute_replay`'s `ReplayFailed` handling, research D15/D17),
      `"complete": false`, `"stop_reason": "replay_failed"`, and `"not_replayed_source_ids"` naming every source
      after it. **A separate case for a fault before any row is claimed** (e.g. monkeypatch `store.claim_run`
      itself to raise): assert the batch still answers **200** with `"complete": false`, `"stop_reason":
      "replay_failed"`, but that source produces **no** entry at all — it is named only in
      `"not_replayed_source_ids"`, exactly like a source the batch never reached (012/FR-028, FR-029, FR-030,
      FR-031, FR-032, FR-033, 012/SC-006).
- [X] T029 [P] [US3] Integration test `tests/integration/test_events_replay.py`, the batch part: through
      `json_log`, a successful, complete batch emits one `replay.batch.start` (naming `target_id`,
      `replayable_count`, `cap`) and one `replay.batch.end` (the three outcome counts, `duration_ms`,
      `complete: true`, no `stop_reason`, no `error`); a batch refused before it starts (`batch_too_large`, or an
      existing precondition) emits **neither** line; the mid-batch collision of T028 emits a `replay.batch.end`
      with `complete: false` and `stop_reason: "run_in_progress"` (no `error` — a collision is an expected stop,
      not a failure); the one-entry-failure case of T028 emits
      a `replay.batch.end` with `complete: false` and `stop_reason: "replay_failed"` (still no `error` on the
      *batch* line — the failure belongs to that one entry's own run, already closed and logged by its own
      exception handling, research D15; the batch itself did not fail). **Each
      batch entry keeps its own run-scoped lines, not just the batch's unscoped pair**: for a multi-entry batch,
      assert **every** entry's own `run.start` (carrying `source_run_id`, `mode: "replay"`) and `run.end`
      (carrying its own `replay_outcome`) line also appears, each inside that entry's own `events.run_scope()`
      (mirroring `experiments/engine.py::_run_rep`'s own per-rep scope, T030) — every entry's pair sits
      **between** the batch's one `replay.batch.start` and its one `replay.batch.end`, never replacing them
      (012/FR-029, FR-043, FR-044, FR-045).

### Implementation for User Story 3

- [X] T030 [US3] Implement `BatchEntry` (with `source_hard_evidence`/`replay_hard_evidence`), `BatchResult` (with
      `complete`, `stop_reason`, `not_replayed_source_ids`), `BatchTooLarge`, and
      `execute_batch_replay(store, *, target_id, cap, ...)` in
      `src/kestrel/replay.py` per `data-model.md`: `store.list_replayable_runs(target_id)` (unaffected by any
      run-in-progress state — that is `compute_replay_status`'s own concern for single-run display, never this
      batch query's); raise
      `BatchTooLarge(count, cap)` before claiming anything when `len(...) > cap`; otherwise call `execute_replay`
      for each, oldest first, one at a time — **each call wrapped in its own
      `events.run_scope()`**, mirroring `experiments/engine.py::_run_rep`'s own per-rep scope, so each entry gets
      its own `run.start`/`run.end` (carrying that entry's `replay_outcome`) and kept log lines (FR-043), while
      the batch's own `replay.batch.start`/`.end` stay unscoped, outside every entry's scope — building one
      `BatchEntry` per source; on a `RunInProgress` collision partway through, **stop and return a `BatchResult`
      with `complete=False`, `stop_reason="run_in_progress"` and the remaining planned sources' ids in
      `not_replayed_source_ids`** — never re-raise it as a batch-level error.
      **Catch the
      named `ReplayFailed`, not a bare exception class**: `execute_replay` now raises `ReplayFailed(run_id)` once
      it has already closed that entry's own run as inconclusive and logged the cause (`exc_type`/`stack`, never
      its message — research D15); catch `ReplayFailed` here specifically (not `RunInProgress`, handled
      separately above), build a `BatchEntry` for it from the now-closed run (`store.get_run(error.run_id)`,
      `outcome="inconclusive"`), append it to `entries`, and stop with `complete=False,
      stop_reason="replay_failed"` and the rest in `not_replayed_source_ids`. **A bare exception that is neither
      `RunInProgress` nor `ReplayFailed`** means the failure happened *before* `claim_run` succeeded (no row to
      build an entry from) — stop the same way (`complete=False, stop_reason="replay_failed"`) but add **no**
      entry; that source joins `not_replayed_source_ids` directly. Either way the batch call itself still returns
      normally, never raises. Wire `events.replay_batch_started`/`_ended` around the whole loop (outside every
      entry's own scope), passing `complete`/`stop_reason` through either way (012/FR-028, FR-029, FR-030,
      FR-031, FR-032, FR-033).
- [X] T031 [US3] Implement the API: `POST /api/targets/{target_id}/replays` in `src/kestrel/api/main.py`
      (preconditions checked once before the first entry, `execute_batch_replay`, the `batch_too_large`/
      `run_in_progress`/`permission_missing`/`terms_outdated` **409**s for a refusal *before* the batch starts and
      the **404**, but **always 200** — never 201, never 409 — for any `BatchResult`, complete or not, per
      `contracts/api.md`); `BatchReplayEntryOut`, `BatchReplayResultOut` (mirroring
      the dataclasses' new fields) in `src/kestrel/api/schemas.py` (012/FR-028, FR-038).

**Checkpoint**: `uv run pytest tests/integration/test_replay_batch.py tests/integration/test_events_replay.py`
green — a whole target's findings can be re-checked in one action, honestly reporting when it could not finish.

---

## Phase 6: User Story 4 — Gate a release on regression results (P2)

**Goal**: a CI-runnable script that batch-replays one target through the running API and exits non-zero exactly
when the result says so — including an incomplete batch, which must never pass as if nothing were missing.

**Independent Test**: over a stubbed HTTP transport, drive the script through every exit-code case in
`contracts/ci-script.md` (including an incomplete batch) and confirm the code and that nothing sensitive is
printed.

### Tests for User Story 4

- [X] T032 [P] [US4] Unit test `tests/unit/test_check_replay_script.py` (`FEATURE = "012"`), over an
      `httpx.MockTransport` standing in for the Kestrel API (no real server, and no real `GET /api/config` either
      — stub it too): a complete batch response with every entry `fixed`, and separately an empty-entries
      response, each exit `0`; a complete response with at least one `still_vulnerable` entry (even alongside an
      `inconclusive` one) exits `1`; a complete response with no `still_vulnerable` entry but at least one
      `inconclusive` exits `2`; **an incomplete batch fails closed**: a response
      with `"complete": false` and no `still_vulnerable` entry among those completed exits `2` (never `0`); a
      `"complete": false` response that **does** have a completed `still_vulnerable` entry exits `1` (the
      vulnerability finding wins even though the batch did not finish); a transport error, a **404**, a **409**
      (any of `permission_missing`/`terms_outdated`/`batch_too_large`/`run_in_progress`), and a missing or
      non-integer `--target-id` each exit `3`; **a batch stopped by
      one entry's own unexpected failure (`stop_reason: "replay_failed"`) follows the same `complete`-based rule
      as a collision**: with a completed `still_vulnerable` entry present it exits `1`, otherwise `2` (no new
      case needed — assert both sub-cases directly); **the default timeout uses
      `per_replay_time_limit_s`, not the adaptive limit alone**: assert the script's default `httpx`
      timeout for the batch call equals `config["replay"]["max_batch_runs"] ×
      config["replay"]["per_replay_time_limit_s"] + 60` read from the stubbed `GET /api/config`, and that
      `--timeout 45` overrides it to exactly `45`; in every case, assert the printed output names only run ids,
      the family, the outcome and **both** evidence flags — not just one —
      `source_hard_evidence` and `replay_hard_evidence`, each rendered `canary`/`judge` (or `none` for the one
      entry whose own replay crashed), since the two can
      legitimately differ — never a value drawn from a canned response body seeded with the known placeholder
      markers in `tests/support.py` (`SECRET`, `TARGET_URL`, `TARGET_NAME`, `ATTACK_TEXT`, `REPLY_TEXT`);
      `--help` output documents all four codes and the `--timeout` flag (012/FR-034, FR-035, FR-036, FR-037,
      012/SC-007, SC-008).

### Implementation for User Story 4

- [X] T033 [US4] Implement `scripts/check_replay.py` per `contracts/ci-script.md`: `argparse` with `--target-id`
      (required, `int`) and `--timeout SECONDS` (optional float, overrides the computed default);
      `KESTREL_API_URL`/`KESTREL_API_TOKEN` read directly from the environment (a small, local `httpx` request
      helper — no import of `ui.api_client`, research D13); `GET /api/config` first, to compute the default batch
      timeout (`max_batch_runs × per_replay_time_limit_s + 60` — **not**
      `adaptive_time_limit_s` alone, since a batch can replay single-turn sources too) unless `--timeout` was
      given; `POST /api/targets/{target_id}/replays` with that timeout; one printed line per entry (ids, family,
      outcome, **both** evidence flags — the source's and the replay's own, each
      `canary`/`judge`, or `none` for the replay side of the one entry whose own replay crashed) plus one summary
      line naming the counts and whether the batch was complete; the
      exit-code table of `contracts/ci-script.md` ("still vulnerable" wins over everything else; an incomplete
      batch — `run_in_progress` or `replay_failed` alike — with no completed still-vulnerable entry is `2`);
      `--help` documents every code and flag (012/FR-034, FR-035, FR-036, FR-037).

**Checkpoint**: `uv run pytest tests/unit/test_check_replay_script.py` green; `uv run python scripts/check_replay.py
--help` prints the documented codes and the `--timeout` flag.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T034 [P] End-to-end test `tests/e2e/test_us012_replay.py` (marker `e2e`, `FEATURE = "012"`), modelled on
      `tests/e2e/test_us011_retrieval.py` — **that pattern runs the
      Kestrel API *in-process* via `fastapi.testclient.TestClient(create_app(settings, ...))` over a `tmp_path`
      `Settings`, against the real HS-code target started as its own subprocess via the `hs_target` fixture; it is
      not the `tests/e2e/conftest.py::kestrel_api` subprocess-server fixture `test_us1_attack.py`'s UI-driven test
      uses — this task follows `test_us011_retrieval.py`'s in-process shape.** Build a `Settings` with a
      `tmp_path` db/chroma and a real judge/attacker key; save the target via the `TestClient`; run one real
      single-turn attack to completion. **A live run's verdict is not guaranteed
      `succeeded`** (`tests/e2e/test_us1_attack.py:58` already documents this for a comparable live test): if the
      run's own verdict is not already `"succeeded"`, promote it directly in SQL — **`TargetStore.finish_run`
      cannot be reused for this.** It only updates a row whose `status` is still
      `'in_progress'` (`WHERE id = ? AND status = 'in_progress'`, `store.py:678-683`) and raises `LookupError`
      when it matches nothing; the source run here is already `status = 'finished'`, so calling `finish_run`
      would simply raise. Instead open a **second**, direct `sqlite3` connection on the *same*
      `settings.db_path` (the test already has it as a local value — no fixture change needed) and execute
      `UPDATE runs SET verdict = 'succeeded' WHERE id = ?` directly, as a **documented, test-only promotion** —
      the comment in the test must say plainly that this bypasses the store's own API on purpose, overriding
      only `verdict`, never the target's actual reply or any other column. Then `POST /api/runs/{id}/replay`
      through the **same** `TestClient` and assert the
      *structure*: a new run with `mode == "replay"` linked to the source, `replay_outcome` one of the three
      labels (the value itself is not asserted — a live model's behaviour on the day, not Kestrel's), the judge
      prompt version recorded, zero attacker-model calls, zero experience-store writes (`SpyExperienceStore`), and
      the 010 lines present with no secret (`hs_target.key`) anywhere on the stream; a second replay of the new
      replay run itself is refused with `replay_of_replay` naming the original source (012/SC-010).
- [X] T035 [P] Documentation: `docs/technical-design.md` (a Regression replay section: schema v10 and the rebuild
      procedure including the `sqlite_sequence` fix, `replay.py`, the shared-node refactor of `attack/graph.py`
      (research D14), `run_replay_adaptive`, the `compute_outcome` rule and why it reads every turn rather than
      the run's final verdict, the interrupted/crashed-replay guarantee, the batch cap, the incomplete-batch
      shape, the CI script; the test-count line), `README.md` (`KESTREL_REPLAY_BATCH_MAX_RUNS` wherever the other
      `KESTREL_*` variables are listed, and `scripts/check_replay.py`'s usage), and a `CLAUDE.md` "Learned notes"
      entry covering: the schema-v10 rebuild and its empirical proof, **including the `sqlite_sequence` gotcha**
      (mirroring the v9 gotcha entry's own style); the turn-cap-as-stopping-rule insight (research D2); the
      terminal-turn `judge_verdict` staleness induction and why only the last sent turn needs special handling
      for *display* (research D7) versus why the outcome itself is captured live instead (research D5); the
      deliberate judge-call-shape split between a single-turn and an adaptive replay (research D1); the
      shared-node extraction (research D14) and the lazy import it needed; and that Principle V's "a run that
      does not write back is a bug" does not apply to a replay, by design, recorded in Complexity Tracking
      (012/FR-020, FR-049; research D1, D2, D5, D7, D14, D15).
- [X] T036 [P] **Bump the five tests that pin the current schema version as a
      literal `"9"`** to `"10"`, following the convention every prior version bump has used (CLAUDE.md "Learned
      notes"): `tests/unit/test_store_migration_v5.py` (lines 103, 110, 129), `tests/unit/test_store_migration_v6.py`
      (lines 82, 89, 97), `tests/unit/test_store_migration_v8.py` (lines 58, 65, 95),
      `tests/unit/test_store_migration_v9.py` (lines 166, 176, 261), and
      `tests/integration/test_provenance_migration.py` (line 39) — each asserts `SCHEMA_VERSION == "9"` or
      `version(...) == "9"` as "the current version"; change the literal and its inline comment (e.g. "bumped to
      10 for feature 012") in each, leaving every other assertion in those files untouched (012/FR-020).
- [X] T037 Write `specs/012-regression-replay/traceability.md` (the id → tests table in the feature-010/011
      shape). FR-046 (no attack text anywhere in this feature's own code/tests/fixtures/commits), FR-048 (no new
      dependency), FR-050 (the roadmap edit, an implementation-PR process step) and SC-009 (dependencies
      unchanged) are justified there rather than given a dedicated 012-scoped test, naming all three explicitly:
      FR-046 by the absence of any attack-wording string in this feature's
      own files (checked by inspection, the same bar every other feature's tests already hold themselves to);
      FR-048/SC-009 by the existing, repo-wide `tests/unit/test_optional_extra.py` (which needs no change, since
      this feature adds nothing to `pyproject.toml`) plus `git diff --stat -- pyproject.toml uv.lock` staying
      empty (checked in T038); FR-050 by the implementation PR's own roadmap diff (T039), reviewed by the code
      owner, not a test. FR-049 (every non-replay behaviour unchanged) **is** covered by a test — the full
      existing offline suite passing unmodified (T038) — so it needs no justification here, only a note of which
      five files were touched on purpose (T036) despite "unmodified" being the general rule. Run
      `uv run python scripts/check_traceability.py` until every `012/FR-###` and `012/SC-###` is traced.
- [ ] T038 Gates: `uv run pytest tests/unit tests/integration` (coverage ≥ 85% on `src`; every pre-existing test
      passes **unmodified**, with the five schema-version literals of T036 as the one named, on-purpose
      exception — not a silent regression), `uvx ruff check src ui tests scripts` clean, `uv run mypy src`
      advisory, `git diff --stat -- pyproject.toml uv.lock` empty (FR-048), the offline sections of
      `specs/012-regression-replay/quickstart.md` reproduced; fix anything that fails (012/FR-048, FR-049,
      012/SC-009).
- [ ] T039 LAST — Roadmap and status lines (implementation pull request only, never the spec-only one): in
      `docs/roadmap.md`, move the "Regression replay" bullet out of "Next features" into "Done" as **012 —
      Regression replay** (one bullet in the Done style: verbatim resend with no attacker call, canary-then-judge
      scoring read from every turn, the fixed/still-vulnerable/inconclusive outcome and side-by-side, no memory or
      pattern write-back, batch replay with a configurable cap and an honestly-incomplete result when it cannot
      finish, the CI gate script; "Shipped in #<spec PR>/#<impl PR>" — fill in the actual
      numbers); update **both** of `README.md`'s status lines to "001–012" — the opening Status paragraph
      (currently "features 001–011 are merged — eleven features in all", line 7) and the "What's next" section
      (currently "Features 001–011 are merged", line 177); update the "Features 001–011 are merged" status line in
      `CLAUDE.md`'s header to "001–012" (012/FR-050).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: after Setup; T002–T006 in parallel (different files); T007 after T002 (its test);
  T008 after T003; T009 after T004; T010 after T005; T011 after T006. **Blocks every user story.**
- **US1 (Phase 3)**: after Foundational. T012–T016 in parallel (tests, different files; T013/T014 share one file
  but cover disjoint sections — write both before either implementation task); T017 → T018 → T019 → T020 → T021 →
  T022 → T023. T017 is its own checkpoint (`run_adaptive`'s existing tests must stay green) before T018 proceeds.
- **US2 (Phase 4)**: after Foundational and US1 (it proves a property of US1's finished engine; T024's structural
  import-guard also only makes sense once `replay.py`/`graph.py` exist, and its batch-isolation half needs US3's
  batch endpoint — order US2's batch assertion after US3 in practice, or stub `execute_batch_replay` directly).
  T024 ∥ T025; T026 → T027.
- **US3 (Phase 5)**: after US1 (`execute_replay` is what it loops) and Foundational's `list_replayable_runs`/
  settings. T028 ∥ T029; T030 → T031.
- **US4 (Phase 6)**: after US3 (it calls the batch endpoint). T032 → T033.
- **Polish (Phase 7)**: after every story; T034–T036 in parallel; T037 → T038; **T039 last**.

### User Story Dependencies

- **US1 (P1)**: the engine every later story reuses unchanged.
- **US2 (P1)**: depends on US1's finished engine to have something to prove isolated; independent of US3/US4
  apart from its batch-isolation assertion (T024), which needs US3's `execute_batch_replay` to exist.
- **US3 (P2)**: depends on US1's `execute_replay`; independent of US2 and US4 apart from sharing Foundational.
- **US4 (P2)**: depends on US3's batch endpoint existing to call.

### Parallel Opportunities

- Foundational: T002 ∥ T003 ∥ T004 ∥ T005 ∥ T006.
- US1 tests: T012 ∥ T013 ∥ T015 ∥ T016 (T014 shares a file with T013 — write it alongside, not strictly parallel
  in the same file, but no code dependency between them).
- US2 tests: T024 ∥ T025. US3 tests: T028 ∥ T029.
- Polish: T034 ∥ T035 ∥ T036.

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Unit test build_comparison in tests/unit/test_replay_comparison.py"
Task: "Integration test single-turn replay in tests/integration/test_replay_run.py"
Task: "Integration test the replay API's shapes and error codes in tests/integration/test_replay_api.py"
Task: "Integration test replay log lines in tests/integration/test_events_replay.py"
# Then, in order: shared-node extraction + its regression check (T017) -> run_replay_adaptive (T018) ->
#   execute_replay (T019) -> build_comparison (T020) -> events wiring (T021) -> the two API routes + schemas
#   (T022) -> the UI button (T023)
```

## Implementation Strategy

### MVP First (US1 + US2)

1. Setup + Foundational: schema v10 (with the `sqlite_sequence` fix), the settings and catalogue fields, the two
   pure functions (`check_replayable`, `compute_outcome` — the latter reading every turn, not one aggregate
   verdict), the interrupted-sweep's `replay_outcome` write.
2. US1: replay one run end to end — the whole point of the feature, proven by the verbatim-resend,
   outcome-correctness (including the case of an unclear verdict or a judge error on an early turn, with every
   later turn cleanly failed, which must score inconclusive, never fixed) and crash-handling tests.
3. US2: prove the isolation property US1's design already implies, including the headline cards.
4. **STOP and VALIDATE**: `uv run pytest tests/unit tests/integration`; quickstart US1/US2.

### Incremental Delivery

- US3 (batch, with its honest incomplete-batch shape) → US4 (the CI gate, with its sized timeout) → Polish (e2e,
  docs, the version-literal bump, traceability, gates) → the roadmap edit last.
- Each story leaves the suite green and every non-replay run's existing behaviour (FR-049) unchanged.

## Notes

- Every test task names its traceability tokens; `scripts/check_traceability.py` (T037) is the gate.
- `[P]` = different files, no dependency on an unfinished task.
- The implementation pull request description carries `Spec-PR: #<n>` and, because this feature edits
  `specs/010-structured-logging/contracts/log-records.md` alongside `src/`, a `spec-change:` note naming that
  file (T011; the traceability gate requires it whenever a spec file changes alongside a `src/` change).
- Never commit `.specify/feature.json`.
