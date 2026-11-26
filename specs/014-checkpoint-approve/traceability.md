# Traceability — 014 LangGraph Checkpointer and Approve Node (part 1)

Part 1 of this feature ships as its own pull request (FR-027). Every part-1 id carries a `014/FR-###`/`014/SC-###`
token or a bare id in a test file marked `FEATURE = "014"`; the ids a test cannot carry, and every part-2 id, are
justified below, **one id per line**, in the exact form `scripts/check_traceability.py` parses
(`"014/FR-0xx: <reason>"` / `"014/SC-0xx: <reason>"`, the id immediately followed by a colon, never grouped with
another id or separated from it by a parenthetical, which the gate's own regex cannot match). Part 2's own
implementation pull request rewrites this file for the whole feature, mirroring 013's own T068.

## Part 1 — covered by tests

| id | Covered by |
|----|------------|
| FR-001, FR-032 | `tests/integration/test_other_run_kinds_unaffected_p1.py` (T040 — single-turn/replay/experiment repetitions never checkpointed or resumable); `tests/unit/test_live_graph_copy.py` (T009 — the experiment harness's own bare `LIVE_GRAPH` call needs no `thread_id`, the per-app copy does); reinforced for the approve node's own surface by part 2's `test_other_run_kinds_unaffected_p2.py` (T053 — not a separate coverage claim here) |
| FR-002 | `tests/unit/test_state_ask_before_each_turn.py` (T003 — the store itself rejects `ask_before_each_turn=True` for a non-adaptive claim) |
| FR-003, FR-004 | `tests/unit/test_store_migration_v12.py` (T002); `tests/unit/test_durability_sync.py` (T007 — every checkpointed call is `durability="sync"`); `tests/integration/test_resume_adaptive_run.py` (T031 — only the conversation/counters persist, nothing from `_LiveDeps`, the config carries only the thread id) |
| FR-005 | `tests/integration/test_resume_adaptive_run.py` (T031 — a resume built from an entirely fresh `_LiveDeps`, never reusing the first attempt's object) |
| FR-006 | `tests/unit/test_checkpoint_saver_contract.py` (T014 — `adelete_thread`); `tests/integration/test_checkpoint_gc.py` (T035 — deleted on every finishing path) |
| FR-007, FR-035, FR-037, SC-011 | `tests/unit/test_checkpoint_saver_contract.py` (T014 — pending-writes replace/ignore, the owner's first condition); `tests/unit/test_checkpoint_version_guard.py` (T015 — the narrowed version range, the `pyproject.toml`/constant agreement, the owner's third condition) |
| FR-036 | `tests/unit/test_checkpoint_saver_contract.py` (T014 — a resume through the real production live-graph copy with this saver correctly reads back the three registered types, the owner's second condition satisfied at the saver level); `tests/integration/test_resume_adaptive_run.py` (T031 — satisfied again through the full adaptive loop, never `InMemorySaver`) |
| FR-008, FR-009, FR-010, FR-011, SC-001 | `tests/integration/test_resume_adaptive_run.py` (T031 — the four cut points, each resumed correctly, the same stopping condition and verdict as an uninterrupted run) |
| FR-012 | `tests/unit/test_record_step_atomic.py` (T005 — the atomic write and its existence-check guard, no duplicate turn or evidence row at the store level); `tests/integration/test_resume_adaptive_run.py` (T031 — no second kept-log `turn` line when the record step re-executes against an already-written row) |
| FR-013, FR-048 | `tests/unit/test_start_up_sweep_classification.py` (T017 — every classification outcome, including the reached-`END`-but-unfinished case and the version-stamp mismatch) |
| FR-014 | `tests/integration/test_resume_api.py` (T031 — the resumable-run display and `POST .../resume`); `tests/unit/test_ui_resume.py` (T039 — the "Resume"/"Stop" labels); `tests/integration/test_paused_run_survives_restart.py` (T052, part 2 — the same classification correctly shows a paused run too, and the decision-cut-off case — not a new claim here) |
| FR-015, SC-008 | `tests/integration/test_resume_api.py` (T031 — a new run or replay refused against a resumable run's target); reinforced for the paused case by part 2's `test_approve_node_live.py` (T046) |
| FR-016, SC-005 | `tests/unit/test_time_spent_accounting.py` (T011 — the deadline recompute; an uninterrupted run's own timing byte-identical to today's; a gap does not cause an immediate timeout; a run already over budget ends at the cap) |
| FR-017, SC-006, SC-017 | `tests/unit/test_start_up_sweep_classification.py` (T017 — `run.interrupted`); `tests/integration/test_kept_log_continuity.py` (T027 — `run.resumed`; no `seq` collision across segments; `run.interrupted` readable through `GET /api/runs/{id}/log`; no secret or attack text across the stream) |
| FR-025 | `tests/integration/test_resume_api.py` (T031 — resume's own synchronicity); `tests/integration/test_stop_endpoint.py` (T021 — stop's own synchronicity); reinforced for the decision case by part 2's `test_approve_node_live.py` (T046) |
| FR-030, SC-010 | `tests/e2e/test_us014_checkpointer.py` (T041 — part 1's own offline, in-process "restart" scenario, two `create_app` instances over one database, since a browser test cannot restart Kestrel; the live e2e's own known, confirmed guardrail failure); part 2 adds its own scenario (T054), mirroring 013's own SC-010 split |
| FR-033, SC-007 | `tests/integration/test_resume_adaptive_run.py` (T031 — the raw checkpoint-byte secret scrub, covering the auth value, the target's URL, and its display name) |
| FR-038, SC-013 | `tests/unit/test_execution_lease.py` (T019 — acquire/release, two concurrent acquisitions resolving to exactly one); reinforced for the decision-specific race by part 2's `test_decision_api.py` (T047 — two concurrent decisions for the same pending turn) |
| FR-040, SC-014 | `tests/integration/test_stop_endpoint.py` (T021 — a resumable (not paused) run stopped without its graph running again, checkpoint gone, lock released; `test_stop_run_never_reacquires_a_lease_its_caller_already_holds` — `stop_run` succeeds when called by a caller already holding the lease, never raising `RunLeased` against itself) |
| FR-041 | `tests/integration/test_resume_api.py` (T031 — the resume preconditions); `tests/integration/test_resume_pinned_caps.py` (T033 — the seed-specific precondition, a missing recorded `prompt_id` refused with a 409, never an unhandled error); reinforced for the decision case by part 2's `test_decision_api.py`/`test_approve_node_live.py` (T046, T047) |
| FR-042 | `tests/integration/test_resume_adaptive_run.py` (T031 — each of the four cut points is simulated by an ordinary in-process exception, never a killed process, and resumes exactly like the process-death case, proving the two are handled identically) |
| FR-043, SC-015 | `tests/integration/test_write_back_once.py` (T023 — a resumed and a stopped run each write back exactly once; a paused/not-yet-finished run writes back 0 times; the sweep's own reached-end reconciliation, T017); reinforced for the two decision-reachable paths by part 2's `test_approve_node_live.py` (T046 — an Approve or Run-to-end reaching a stopping point, and a decision-routed Stop, each exactly once); reinforced for the scope boundary itself (never reaching into a replay or an experiment's cold arm) by `test_other_run_kinds_unaffected_p1.py` (T040) |
| FR-044, SC-016 | `tests/integration/test_live_checker_rebuild.py` (T025 — the override family's task text stripped after a resume; an echoed in-flight message is not evidence) |
| FR-045, SC-019 | `tests/integration/test_checkpoint_gc.py` (T035 — no checkpoint row survives any finishing or closing path, or a deleted target) |
| FR-046, SC-018 | `tests/integration/test_run_end_once.py` (T029 — exactly one `run.end`, whole-run totals, a reopened turn context); reinforced for the decision-routed Stop path (no second, nested scope) by part 2's `test_events_approve.py` (T048) |
| FR-047, SC-020 | `tests/integration/test_resume_pinned_caps.py` (T033 — a resumed run's own stored caps/model/prompt references, never a changed current configuration; a refusal naming an unavailable pinned value, Stop still working) |
| FR-049 | `tests/unit/test_checkpoint_saver_contract.py` (T014 — both serializer modes round-trip the three registered Kestrel types as themselves, with no warning) |
| FR-050 | `tests/integration/test_owasp_excludes_in_progress.py` (T037) |
| FR-051 | `tests/integration/test_stop_endpoint.py` (T021 — `test_stop_does_not_write_a_phantom_duplicate_turn`: no extra `run_turns` row for `record`'s/`decide`'s own commit windows or the clean checkpoint after `record`; exactly one write for the evidence/judge windows) |
| FR-052 | `tests/unit/test_start_up_sweep_classification.py` (T017 — `test_from_step_matches_the_compiled_graphs_own_next_node`, part-1 topology); reinforced for part 2's own topology (the `approve` node) by `tests/unit/test_approve_node_probe.py` (T043) |
| FR-053 | `tests/integration/test_run_end_once.py` (T029 — `test_a_first_segment_pause_emits_no_run_end` / `test_a_first_segment_exception_emits_run_interrupted_not_run_end`); reinforced by `tests/integration/test_resume_adaptive_run.py` (T031 — the first of the four cut points emits `run.interrupted`/no `run.end` too) |
| FR-054 | `tests/integration/test_resume_api.py` (T031 — `test_a_leased_run_reads_running_and_offers_no_control`); `tests/integration/test_stop_endpoint.py` (T021 — a reached-end/no-checkpoint/unreadable run reads `run_state == "stoppable"`); `tests/unit/test_ui_resume.py` (T039 — `test_run_state_running_shows_no_control`, `test_run_state_stoppable_shows_stop_alone_never_resume`) |
| FR-055 | `tests/integration/test_write_back_once.py` (T023 — `test_finish_run_is_called_exactly_once_per_finished_run`, `test_a_start_that_raises_still_releases_its_lease`); `tests/integration/test_other_run_kinds_unaffected_p1.py` (T040 — `test_consecutive_experiment_repetitions_all_finish_and_next_claim_succeeds`) |
| FR-056 | `tests/integration/test_stop_endpoint.py` (T021 — `test_stops_no_checkpoint_close_matches_the_sweeps_reason_and_skips_write_back`) |
| FR-057 | `tests/unit/test_resume_idle_hours_setting.py` (T057 — default, valid/invalid values, `GET /api/config`) |
| FR-058, SC-021 | `tests/integration/test_idle_auto_stop.py` (T061 — no stop before the window, a stop after it for all three Stop branches compared against a manual Stop, a leased run skipped and reconsidered next check, the re-check-under-lease race, one run's failure not silencing the check, `test_not_yet_due_run_is_never_leased`, `test_stop_run_called_by_the_idle_check_succeeds_under_its_own_already_held_lease`, `test_a_failed_automatic_stop_is_retried_without_backoff`, `test_a_failure_outside_any_single_runs_handling_does_not_end_the_loop`); `tests/unit/test_idle_clock.py` (T059 — SC-021's own restart/grace-period clause); reinforced for a genuinely paused run by part 2's `test_idle_auto_stop_paused.py` (T065) |
| FR-059 | `tests/unit/test_idle_clock.py` (T059 — `last_activity_at` set at claim and updated only on an accepted lease release, never a refused one — including `run_adaptive`'s own first-segment exit; `claim_run`'s own `now=` agreeing with `app_state.clock()`; the restart grace period — `check_idle_runs` is a complete no-op for `min(1 hour, configured window)` after `started_at`, regardless of how overdue any run already is, then catches it at the next check); `tests/integration/test_idle_auto_stop.py` (T061 — `test_a_failed_automatic_stop_is_retried_without_backoff`: a failed automatic stop never updates `last_activity_at`, on success or failure alike) |
| FR-060 | `tests/integration/test_idle_auto_stop.py` (T061 — outcome identical to a manual Stop in every field for the reconciled and no-checkpoint-or-unreadable shapes; for the ordinary shape, every field but `reason` (`stopping_condition` unchanged); `run.stopped`'s `trigger`/`idle_hours` the one place every shape differs from a manual Stop); reinforced by T065 |
| FR-061, SC-022 | `tests/integration/test_idle_stop_at_api.py` (T063 — `idle_stop_at` present/`null` correctly on the API, including the grace-aware case where an already-overdue run's deadline is never shown in the past); `tests/unit/test_ui_needs_attention.py` (T063 — the run's own target's run list, at its top, and the run page's own time, structurally, never a pinned heading string) |
| FR-062 | `tests/integration/test_idle_stop_at_api.py` (T063 — `test_get_api_targets_reports_needs_attention`: `GET /api/targets`'s own `needs_attention` field, computed from the identical classification `run_state`/`idle_stop_at` already use, and `GET /api/targets/{id}`'s own `TargetDetail` reporting the identical value); `tests/unit/test_ui_needs_attention.py` (T063 — the target-selector cue reads this field directly, never a separate derivation) |
| SC-002, SC-003 | `tests/integration/test_other_run_kinds_unaffected_p1.py` (T040 — the full offline suite's identical pass/fail set, modulo the five named pre-existing-test edits `plan.md` lists); reinforced for the checkbox-off case by part 2's own `test_other_run_kinds_unaffected_p2.py` (T053) |
| SC-012 | `tests/unit/test_durability_sync.py` (T007) |

## Reviewed properties — for the implementation pull request's reviewer

- **The record step's returned delta on the already-recorded path** (research D6): `tests/unit/test_record_step_atomic.py`
  (T005) proves the *outcome* (no duplicate row, no duplicate evidence), but a reviewer should confirm the delta
  itself is computed only from `state`, never re-read from the existing row — a distinction the test's own
  assertions check the result of, not the source, of that returned delta.
- **The per-app graph copy is the only thing that changes between apps** (research D2): a reviewer should confirm
  `experiments/engine.py` is touched nowhere by this feature — the shared node bodies (`_wire`, `_approve_node`,
  the lifted `record`/`judge`/`send`/`evidence`/`decide` steps) are identical code regardless of which compiled
  object (the bare module-level graph, or an app's own checkpointed copy) a given call runs against.

## Justified outside tests — part 1

- 014/FR-027: the two-pull-request delivery split is process, satisfied by this feature actually shipping as two pull requests (verified at merge time, not by a test) — the same way 013's own part-1/part-2 delivery split was justified.
- 014/FR-028: `docs/roadmap.md`'s rename of "014 — Community prompt feed" to "015" is a documentation task (`tasks.md`, T042), scoped to living documentation only (never a merged feature's own spec files), verified in the part-1 pull request's own review, never asserted on prose (CLAUDE.md's "no test pins documentation wording" rule).
- 014/FR-034: no attack-prompt text anywhere in this feature's own code, tests, fixtures or commits — a process/authoring rule checked by inspection, the same bar every other feature's tests already hold themselves to (012's own precedent); covers both parts, not re-justified separately below.
- 014/SC-009: a property of the plan's own Constitution Check, verified by review when the implementation pull request is read against it — not a property any test can honestly assert.

## Justified outside tests — part 2 (implemented by the part-2 pull request)

Every id below belongs to the approve node (`tasks.md` Phases 7–11, T043–T056), none of which part 1 ships. Each
is "part 2 — implemented by the part-2 pull request", which replaces these lines with its own tests.

- 014/FR-018: part 2 — implemented by the part-2 pull request (the checkbox's own placement, default and off-behaviour; `tests/unit/test_ui_approve_node.py`, T049).
- 014/FR-019: part 2 — implemented by the part-2 pull request (turn 1 never pauses; turn 2 onward does; `tests/integration/test_approve_node_live.py`, T046).
- 014/FR-020: part 2 — implemented by the part-2 pull request (the pending-turn display and the three controls; T046, T051).
- 014/FR-021: part 2 — implemented by the part-2 pull request (Approve; T046).
- 014/FR-022: part 2 — implemented by the part-2 pull request (Run to end, including surviving a restart; T046).
- 014/FR-023: part 2 — implemented by the part-2 pull request (Stop for a paused run, reusing the part-1 Stop path; T046, T022).
- 014/FR-024: part 2 — implemented by the part-2 pull request (an unanswered pause stays paused; T046).
- 014/FR-026: part 2 — implemented by the part-2 pull request (`run.paused`/`run.decided`/`run.stopped`; `tests/unit/test_events_approve.py`, T048).
- 014/FR-029: part 2 — implemented by the part-2 pull request (the roadmap's "LangGraph idioms" entry moved to Done; `tasks.md` T055).
- 014/FR-031: part 2 — implemented by the part-2 pull request (the off-checkbox unchanged-behaviour case, comparable only once the checkbox itself exists; `tests/integration/test_other_run_kinds_unaffected_p2.py`, T053).
- 014/FR-039: part 2 — implemented by the part-2 pull request (turn-specific, single-use decisions, a request naming a turn that has already moved on refused with nothing sent; `tests/integration/test_decision_api.py`, T047).
- 014/SC-004: part 2 — implemented by the part-2 pull request (the three decisions' documented outcomes, including across a restart; T046, T052).
- 014/SC-010: part 2 — implemented by the part-2 pull request (`tests/e2e/test_us014_approve_node.py`, T054 — part 1's own half is already covered by tests, above).
- 014/SC-013: part 2 — implemented by the part-2 pull request (the decision-specific concurrent-request race; T047 — part 1's own lease half is already covered by tests, above).
