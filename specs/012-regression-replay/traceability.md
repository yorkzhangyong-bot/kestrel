# Traceability — 012 Regression Replay

55 of 60 ids carry a `012/FR-###`/`012/SC-###` token or a bare id in a test file marked `FEATURE = "012"`; the
remaining 5 are justified below (`uv run python scripts/check_traceability.py`).

| id | Covered by |
|----|------------|
| FR-001, SC-001 | `tests/integration/test_replay_run.py` (byte-for-byte prompt/turn resend, single-turn and adaptive, under all four target behaviours) |
| FR-002 | `tests/integration/test_replay_run.py` (`execute_replay`/`run_replay_adaptive` accept no attacker parameter at all); `tests/integration/test_events_replay.py` (zero `model.request kind=attacker` lines) |
| FR-003 | `tests/integration/test_replay_api.py`, `test_replay_batch.py` (the replay is sent to the source's own target, resolved from the target's current stored settings) |
| FR-004, SC-005 | `tests/unit/test_replay_eligibility.py` (`check_replayable`'s truth table, the three reasons); `tests/integration/test_replay_api.py` (the 409s, word for word) |
| FR-005 | `tests/unit/test_replay_eligibility.py`; `tests/integration/test_replay_api.py` (`replay_of_replay`, naming the source); `tests/e2e/test_us012_replay.py` |
| FR-006 | `tests/integration/test_replay_api.py::test_permission_missing_refuses_a_single_replay`/`test_terms_outdated_refuses_a_single_replay` (the single replay's own 409s); `test_replay_batch.py::test_permission_missing_refuses_the_whole_batch`/`test_terms_outdated_refuses_the_whole_batch` (the batch's own 409s); both against the exact existing wording; `test_run_in_progress_precondition_refuses_a_replay` (the third reason) |
| FR-007, FR-008, FR-009 | `tests/integration/test_replay_run.py` (canary-then-judge; the single-turn no-`conversation` call; the adaptive per-turn conversation; the currently configured judge, not the source's) |
| FR-010 | `tests/integration/test_replay_run.py` (stops at the first success, sends no further messages); `tests/unit/test_replay_comparison.py` (the unsent positions) |
| FR-011 | `tests/integration/test_replay_run.py` (a lower current turn limit stops the replay short) |
| FR-012, FR-015 | `tests/unit/test_replay_outcome.py`; `tests/unit/test_store_migration_v10.py` (an interrupted replay is closed inconclusive, never left null) |
| FR-013 | `tests/unit/test_replay_outcome.py` (any `"succeeded"` wins) |
| FR-014 | `tests/unit/test_replay_outcome.py` (the winning-turn rule); `tests/integration/test_replay_run.py` (on a real multi-turn source) |
| FR-016 | `tests/integration/test_replay_api.py` (`replay_outcome` values); `tests/integration/test_ui_replay.py` (`OUTCOME_LABELS`, the exact "Outcome: " line) |
| FR-017, FR-018 | `tests/unit/test_replay_comparison.py` (`build_comparison`'s per-turn walk, the terminal-turn derivation, the pinned row labels); `tests/integration/test_ui_replay.py` (the rendered table, including the exact "Source (run #N)"/"Replay (run #N)" column headings, `test_clicking_replay_shows_the_outcome_line_and_comparison_headings`) |
| FR-019 | `tests/integration/test_replay_api.py::test_a_replays_own_get_renders_the_same_fields_any_finished_run_does` (status, verdict, prompt/reply text, attacker_model, reason — not only its replay-specific fields) |
| FR-020 | `tests/unit/test_store_migration_v10.py` (the schema); `tests/integration/test_replay_run.py` (`mode == "replay"`, `source_run_id`) |
| FR-021 | `tests/integration/test_replay_run.py::test_family_owasp_category_and_prompt_fields_are_copied_from_the_source`/`test_an_adaptive_replays_family_owasp_category_and_prompt_fields_are_also_copied` (family, OWASP category, prompt id, title and text asserted equal to the source's own, never recomputed) |
| FR-022 | `tests/integration/test_replay_run.py` (no attacker model recorded; judge/judge-prompt provenance from the judge active at replay time) |
| FR-023 | `tests/integration/test_replay_run.py` (each sent message its own turn; attacker-prompt provenance copied from the source's matching turn, same index as the message lookup) |
| FR-024 | `tests/integration/test_replay_memory_isolation.py` (`memory_written` is always `None`) |
| FR-025, FR-026, SC-003 | `tests/integration/test_replay_memory_isolation.py` (zero queries/writes under every outcome, single and batch; the AST-based structural import guard) |
| FR-027, SC-004 | `tests/integration/test_replay_report_exclusion.py` (identical finding count/coverage/recommender calls; the `finding` flag); `tests/integration/test_ui_headline_cards.py` (the Confirmed/Suspected/Runs split) |
| FR-028 | `tests/integration/test_replay_batch.py` (excludes replay-mode runs) |
| FR-029 | `tests/integration/test_replay_batch.py` (preconditions once, oldest first, stop partway without a 409; `test_an_unknown_target_404s_a_batch_replay`, `test_permission_missing_refuses_the_whole_batch`, `test_terms_outdated_refuses_the_whole_batch` for the batch's own refusals); `tests/integration/test_events_replay.py` (the batch log lines) |
| FR-030 | `tests/integration/test_replay_batch.py` (one entry per processed source, counts summing to the entry count; `failed_source_run_id` naming the crashed source explicitly in both the after-claim and before-claim cases) |
| FR-031 | `tests/unit/test_settings_replay.py`; `tests/integration/test_api_base.py` (`GET /api/config`); `tests/integration/test_replay_batch.py` (the cap refusal) |
| FR-033 | `tests/integration/test_replay_batch.py` (zero replayable runs completes trivially) |
| FR-034, FR-035 | `tests/unit/test_check_replay_script.py` (calls the batch endpoint; per-entry and summary lines; no secret markers) |
| FR-036 | `tests/unit/test_check_replay_script.py` (the full exit-code table, "still vulnerable" winning) |
| FR-037 | `tests/unit/test_check_replay_script.py` (`--help` documents every code and `--timeout`) |
| FR-038 | `tests/integration/test_replay_api.py`, `test_replay_batch.py` (both actions answer synchronously, no poll endpoint) |
| FR-039 | `tests/integration/test_ui_replay.py` (the exact "replay" Mode label and the Source column) |
| FR-040 | `tests/integration/test_ui_replay.py` (the button always renders, disabled+reason or the advisory, including for a run that failed to send; `test_clicking_replay_shows_the_outcome_line_and_comparison_headings` for US1 scenario 7) |
| FR-041 | `tests/integration/test_ui_replay.py`, `test_replay_api.py` (the Outcome line, the multi-turn caption present only for a multi-message source; `test_a_replay_run_whose_own_send_failed_still_shows_outcome_comparison_and_source_link` for T023's required case; `test_clicking_the_source_link_opens_the_source_run` for the source link itself) |
| FR-042 | `tests/unit/test_replay_eligibility.py` (`compute_replay_status` computes everything server-side); `tests/integration/test_ui_replay.py` (the UI only displays given fields) |
| FR-043, FR-044 | `tests/integration/test_events_replay.py` (`run.start`/`run.end` fields; `replay.batch.start`/`.end`) |
| FR-045, FR-047, SC-008 | `tests/integration/test_events_replay.py` (no secret/URL/name/text anywhere on the stream; `test_the_sources_own_attack_text_never_appears_on_a_replays_stream`/`..._on_a_batch_replays_stream` for the attack-text marker, single and batch); `tests/unit/test_check_replay_script.py` (the script's own output) |
| SC-002 | `tests/unit/test_replay_outcome.py` (every branch, including the unresolved-early-turn and winning-turn cases); `tests/integration/test_replay_run.py` (the same cases on a real multi-turn source; `test_no_judge_configured_gives_inconclusive_unless_a_canary_matched` and `test_an_adaptive_replay_with_no_judge_configured_gives_inconclusive_unless_a_canary_matched` for no judge configured at all, single-turn and adaptive) |
| SC-006 | `tests/integration/test_replay_batch.py` (N entries oldest-first, the cap refusal, the two incomplete-batch shapes) |
| SC-007 | `tests/unit/test_check_replay_script.py` (every exit code, including the incomplete-batch and "still vulnerable wins" cases) |
| SC-010 | `tests/e2e/test_us012_replay.py` |

## Untraced ids (justified)

- 012/FR-050: documentation requirement (the implementation pull request, never the spec-only one, marked
  regression replay done in the roadmap and removed it from the planned items), verified in the 012 PR review;
  no test pins doc wording (CLAUDE.md rule, 2026-11-24 — `tests/unit/test_roadmap.py` was removed under it).

- 012/FR-032: a batch replay's per-run turn and time limits are the same `adaptive_max_turns`/`adaptive_token_budget`/`adaptive_time_limit_s` values `execute_batch_replay` forwards unchanged to `execute_replay` for each entry (`src/kestrel/replay.py::execute_batch_replay`) — there is no batch-specific cap logic of its own to exercise beyond what FR-011 already proves at the single-replay level (`tests/integration/test_replay_run.py::test_a_lower_current_turn_limit_stops_the_replay_short_and_is_inconclusive_never_fixed`). A dedicated batch-level timing test would duplicate that assertion through an extra HTTP round trip without exercising any additional code path.
- 012/FR-046: no attack-prompt text anywhere in this feature's own code, tests, fixtures, or commits — a process/authoring rule checked by inspection (every test in this feature uses neutral placeholder messages, e.g. `"<seed message>"`, `"<turn N>"`, `"a harmless reply"`), the same bar every other feature's tests already hold themselves to; not a single testable behaviour.
- 012/FR-048: this feature adds no new dependency, required or optional. Covered by the existing, repo-wide `tests/unit/test_optional_extra.py` (unchanged by this feature, since nothing was added to `pyproject.toml`) and confirmed directly in the implementation PR by `git diff --stat -- pyproject.toml uv.lock` staying empty (T038).
- 012/SC-009: Kestrel's required dependencies are unchanged after this feature ships. Same evidence as FR-048 immediately above: `tests/unit/test_optional_extra.py` unchanged, `git diff --stat -- pyproject.toml uv.lock` empty.
- 012/FR-049: every non-replay run's behaviour, scoring, storage, logging, shared-pattern/memory write-back and OWASP report stay exactly as they are today. Covered by the full existing offline test suite passing **unmodified**, none of its tests carrying a `012/` token, which is exactly the point: this feature is strictly additive (a literal count is not pinned here — it goes stale the moment either suite gains a test; run `uv run pytest tests/unit tests/integration` for the current one). Two named, on-purpose exceptions touch pre-012 test files: the five schema-version-literal tests `test_store_migration_v5.py`/`v6.py`/`v8.py`/`v9.py` and `test_provenance_migration.py` (T036), each bumped from pinning `"9"` to `"10"` as "the current version" — a necessary consequence of FR-020's own schema change; and `tests/unit/test_roadmap.py` (feature 011's own test, T039), which dropped its "012 still in Next features" assertion and gained `test_012_is_listed_under_done_and_no_longer_planned` (FR-050) — a necessary consequence of this feature's own roadmap entry moving 012 into Done. Neither is a behaviour change to a non-replay run.
