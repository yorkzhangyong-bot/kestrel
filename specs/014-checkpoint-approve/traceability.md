# Traceability — 014 LangGraph Checkpointer and Approve Node

The whole feature (parts 1 and 2), shipped as two pull requests (FR-027). Every id carries a `014/FR-###`/
`014/SC-###` token or a bare id in a test file marked `FEATURE = "014"`; the five ids a test cannot carry (the
delivery split, the two documentation tasks, the no-attack-text rule, and the plan's own Constitution Check) are
justified below, **one id per line**, in the exact form `scripts/check_traceability.py` parses
(`"014/FR-0xx: <reason>"`, the id immediately followed by a colon, never grouped with another id).

## Covered by tests

| id | Covered by |
|----|------------|
| FR-001, FR-032 | `tests/integration/test_other_run_kinds_unaffected_p1.py` (T040) and `_p2.py` (T053 — single-turn/replay/experiment repetitions never checkpointed, never pause, never resumable); `tests/unit/test_live_graph_copy.py` (T009 — the experiment harness's own bare `LIVE_GRAPH` call needs no `thread_id`) |
| FR-002 | `tests/unit/test_state_ask_before_each_turn.py` (T003 — the store rejects a non-adaptive `ask_before_each_turn` claim); `tests/integration/test_other_run_kinds_unaffected_p2.py` (T053 — the checkbox is refused for a single-turn run, never offered to a replay or experiment) |
| FR-003, FR-004 | `tests/unit/test_store_migration_v12.py` (T002); `tests/unit/test_durability_sync.py` (T007 — every checkpointed call is `durability="sync"`); `tests/integration/test_resume_adaptive_run.py` (T031 — only the conversation/counters persist, the config carries only the thread id) |
| FR-005 | `tests/integration/test_resume_adaptive_run.py` (T031 — a resume built from an entirely fresh `_LiveDeps`) |
| FR-006 | `tests/unit/test_checkpoint_saver_contract.py` (T014); `tests/integration/test_checkpoint_gc.py` (T035) |
| FR-007, FR-035, FR-037, SC-011 | `tests/unit/test_checkpoint_saver_contract.py` (T014 — pending-writes replace/ignore); `tests/unit/test_checkpoint_version_guard.py` (T015 — the narrowed version range and the `pyproject.toml` agreement) |
| FR-036 | `tests/unit/test_checkpoint_saver_contract.py` (T014); `tests/integration/test_resume_adaptive_run.py` (T031 — the full adaptive loop, never `InMemorySaver`) |
| FR-008, FR-009, FR-010, FR-011, SC-001 | `tests/integration/test_resume_adaptive_run.py` (T031 — the four cut points, the same stopping condition and verdict as an uninterrupted run) |
| FR-012 | `tests/unit/test_record_step_atomic.py` (T005); `tests/integration/test_resume_adaptive_run.py` (T031) |
| FR-013, FR-048 | `tests/unit/test_start_up_sweep_classification.py` (T017 — every classification outcome, the version-stamp mismatch); `tests/unit/test_approve_node_probe.py` (T043 — the approve node reads its flag with a default, so a state without the field is readable) |
| FR-014 | `tests/integration/test_resume_api.py` (T031); `tests/unit/test_ui_resume.py` (T039); `tests/integration/test_paused_run_survives_restart.py` (T052) |
| FR-015, SC-008 | `tests/integration/test_resume_api.py` (T031); `tests/integration/test_approve_node_live.py` (T046 — a paused run's target stays locked) |
| FR-016, SC-005 | `tests/unit/test_time_spent_accounting.py` (T011) |
| FR-017, SC-006, SC-017 | `tests/unit/test_start_up_sweep_classification.py` (T017); `tests/integration/test_kept_log_continuity.py` (T027) |
| FR-018 | `tests/unit/test_approve_node_probe.py` (T043); `tests/unit/test_ui_approve_node.py` (T049 — the checkbox, off by default, adaptive only) |
| FR-019, FR-021, FR-022, FR-023, FR-024, FR-025, SC-004 | `tests/unit/test_approve_node_probe.py` (T043); `tests/integration/test_approve_node_live.py` (T046 — turn 1 sent without pausing, Approve sends and pauses again, Run to end runs unattended, Stop never sends the pending message, an unanswered pause stays paused, each request synchronous); `tests/integration/test_paused_run_survives_restart.py` (T052) |
| FR-020 | `tests/integration/test_approve_node_live.py` (T046 — `pending_turn` and the three controls); `tests/unit/test_ui_approve_node.py` (T049 — the pending message verbatim and exactly Approve/Run to end/Stop) |
| FR-026 | `tests/unit/test_events_approve.py` (T048 — `run.paused`/`run.decided`/`run.stopped`, each once, none carrying the message text) |
| FR-030, SC-010 | `tests/e2e/test_us014_checkpointer.py` (T041) and `tests/e2e/test_us014_approve_node.py` (T054 — the two offline, in-process "restart" scenarios; the live e2e's own known, confirmed guardrail failure) |
| FR-031, SC-002, SC-003 | `tests/integration/test_other_run_kinds_unaffected_p2.py` (T053 — an off-checkbox run never pauses, `run.start` omits `ask_before_each_turn`, the full offline suite's identical pass/fail set) |
| FR-033, SC-007 | `tests/integration/test_resume_adaptive_run.py` (T031 — the raw checkpoint-byte secret scrub); `tests/unit/test_events_approve.py` (T048 — no approve event takes a message parameter) |
| FR-038, SC-013 | `tests/unit/test_execution_lease.py` (T019); `tests/integration/test_decision_api.py` (T047 — two concurrent decisions for one pending turn resolve to exactly one success) |
| FR-039 | `tests/integration/test_decision_api.py` (T047 — a turn mismatch is refused with nothing sent, single-use) |
| FR-040, SC-014 | `tests/integration/test_stop_endpoint.py` (T021 — `test_stop_run_never_reacquires_a_lease_its_caller_already_holds`); `tests/integration/test_approve_node_live.py` (T046 — a decision-routed Stop) |
| FR-041 | `tests/integration/test_resume_api.py` (T031); `tests/integration/test_resume_pinned_caps.py` (T033); `tests/integration/test_decision_api.py` (T047 — the decision's own preconditions, never for Stop) |
| FR-042 | `tests/integration/test_resume_adaptive_run.py` (T031 — each cut point is an ordinary in-process exception, resumed like the process-death case) |
| FR-043, SC-015 | `tests/integration/test_write_back_once.py` (T023); `tests/integration/test_approve_node_live.py` (T046 — an Approve/Run-to-end/Stop-reached-via-decision each writes back exactly once) |
| FR-044, SC-016 | `tests/integration/test_live_checker_rebuild.py` (T025) |
| FR-045, SC-019 | `tests/integration/test_checkpoint_gc.py` (T035) |
| FR-046, SC-018 | `tests/integration/test_run_end_once.py` (T029); `tests/unit/test_events_approve.py` (T048 — a stop decision opens exactly one scope) |
| FR-047, SC-020 | `tests/integration/test_resume_pinned_caps.py` (T033) |
| FR-049 | `tests/unit/test_checkpoint_saver_contract.py` (T014) |
| FR-050 | `tests/integration/test_owasp_excludes_in_progress.py` (T037) |
| FR-051 | `tests/integration/test_stop_endpoint.py` (T021 — `test_stop_does_not_write_a_phantom_duplicate_turn`) |
| FR-052 | `tests/unit/test_start_up_sweep_classification.py` (T017, part-1 topology); `tests/unit/test_approve_node_probe.py` (T043 — the completed attacker task routes to `approve`, never `send`) |
| FR-053 | `tests/integration/test_run_end_once.py` (T029); `tests/integration/test_resume_adaptive_run.py` (T031) |
| FR-054 | `tests/integration/test_resume_api.py` (T031); `tests/integration/test_stop_endpoint.py` (T021); `tests/unit/test_ui_resume.py` (T039) |
| FR-055 | `tests/integration/test_write_back_once.py` (T023); `tests/integration/test_other_run_kinds_unaffected_p1.py` (T040) |
| FR-056 | `tests/integration/test_stop_endpoint.py` (T021 — `test_stops_no_checkpoint_close_matches_the_sweeps_reason_and_skips_write_back`) |
| FR-057 | `tests/unit/test_resume_idle_hours_setting.py` (T057) |
| FR-058, FR-060, SC-021 | `tests/integration/test_idle_auto_stop.py` (T061); `tests/integration/test_idle_auto_stop_paused.py` (T065 — a genuinely paused run is stopped by the same mechanism) |
| FR-059 | `tests/unit/test_idle_clock.py` (T059); `tests/integration/test_idle_auto_stop.py` (T061) |
| FR-061, SC-022 | `tests/integration/test_idle_stop_at_api.py` (T063); `tests/unit/test_ui_needs_attention.py` (T063); `tests/unit/test_ui_approve_node.py` (T049 — `idle_stop_at` shown beside the paused run's controls) |
| FR-062 | `tests/integration/test_idle_stop_at_api.py` (T063); `tests/unit/test_ui_needs_attention.py` (T063) |
| SC-012 | `tests/unit/test_durability_sync.py` (T007) |

## Justified outside tests

- 014/FR-027: the two-pull-request delivery split is process, satisfied by this feature actually shipping as two pull requests (verified at merge time, not by a test) — the same way 013's own part-1/part-2 delivery split was justified.
- 014/FR-028: `docs/roadmap.md`'s rename of "014 — Community prompt feed" to "015" is a documentation task (`tasks.md`, T042), scoped to living documentation only, verified in the part-1 pull request's own review, never asserted on prose (CLAUDE.md's "no test pins documentation wording" rule).
- 014/FR-029: `docs/roadmap.md`'s move of "LangGraph idioms" to Done is a documentation task (`tasks.md`, T055), verified in the part-2 pull request's own review, never asserted on prose.
- 014/FR-034: no attack-prompt text anywhere in this feature's own code, tests, fixtures or commits — a process/authoring rule checked by inspection, the same bar every other feature's tests already hold themselves to (012's own precedent).
- 014/SC-009: a property of the plan's own Constitution Check, verified by review when the implementation pull request is read against it — not a property any test can honestly assert.
