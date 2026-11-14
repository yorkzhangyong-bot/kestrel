# Traceability — 010 Structured Logging and Tracing

Every functional requirement and success criterion is covered by at least one test carrying a `010/FR-###` or
`010/SC-###` token (or a module-level `FEATURE = "010"` marker); no id needs a justification
(`uv run python scripts/check_traceability.py`: 26 of 26 traced).

| id | Covered by |
|----|------------|
| 010/FR-001 | `tests/unit/test_events.py` (the run scope, run.start/run.end); `tests/integration/test_log_records_single_turn.py` |
| 010/FR-002 | `tests/integration/test_log_records_single_turn.py`, `test_log_records_adaptive.py` (one turn line per turn, its totals); `tests/unit/test_events.py` |
| 010/FR-003 | `tests/unit/test_attacker_client.py`, `test_judge_client.py`, `test_retry.py` (attempts, usage); `tests/integration/test_log_records_*.py`, `test_run_log_after_report.py` (the recommender line) |
| 010/FR-004 | `tests/unit/test_tester.py` (the connection and target lines); `tests/integration/test_log_records_*.py` |
| 010/FR-005 | `tests/unit/test_events.py`, `test_log_formatter.py` (scope fields, key order); `tests/integration/test_experiment_events.py` |
| 010/FR-006 | `tests/unit/test_log_formatter.py`, `test_settings_logging.py`, `test_events.py` (no interpolating log call in `src/kestrel`); `tests/integration/test_startup_events.py`, `test_api_manage.py` |
| 010/FR-007 | `tests/unit/test_provenance_source.py`, `test_store_run_turns.py`, `test_attacker_client.py`, `test_judge_client.py`; `tests/integration/test_prompt_provenance_pinned.py`, `test_experiment_events.py`, `test_log_records_single_turn.py` |
| 010/FR-008, SC-006 | `tests/unit/test_request_cost.py`, `test_attacker_client.py` |
| 010/FR-009 | `tests/integration/test_log_redaction.py` (stream, endpoint, spans), `test_run_log_api.py`, `test_ui_run_log.py`, `test_tracing_run.py`, `test_startup_events.py`, `test_api_connection_tests.py`; `tests/unit/test_events.py` (the allow-list), `test_log_formatter.py`, `test_tester.py` |
| 010/FR-010, SC-009 | `tests/unit/test_run_log_handler.py`, `test_store_migration_v8.py`, `test_events.py`; `tests/integration/test_run_log_cap.py`, `test_run_log_after_report.py`, `test_log_resilience.py` |
| 010/FR-011 | `tests/integration/test_run_log_api.py`, `test_log_redaction.py` |
| 010/FR-012, SC-003 | `tests/integration/test_ui_run_log.py`; `test_run_log_api.py` |
| 010/FR-013, SC-004 | `tests/unit/test_tracing.py`, `test_settings_logging.py`; `tests/integration/test_tracing_run.py` |
| 010/FR-014, SC-007 | `tests/unit/test_optional_extra.py`, `test_tracing.py`; the `KESTREL_TEST_BLOCK_OTLP=1` session switch in `tests/conftest.py` |
| 010/FR-015 | `tests/integration/test_log_resilience.py`; `tests/unit/test_run_log_handler.py`, `test_tracing.py`, `test_log_formatter.py` |
| 010/FR-016 | `tests/integration/test_log_records_single_turn.py`, `test_log_records_adaptive.py`, `test_experiment_events.py` |
| 010/FR-017, SC-005 | `tests/integration/test_log_resilience.py` (same outcome with a failing sink or exporter); `tests/unit/test_provenance_source.py` (the one recording change); the moved secret counts in `test_api_connection_tests.py`, `test_api_save.py`, `test_api_manage.py`, `test_experiment_secrets.py`, and `test_writeback.py`, `test_secrets.py`, `test_tester.py` (line-shape changes only) |
| 010/SC-001 | `tests/integration/test_log_records_single_turn.py`, `test_log_records_adaptive.py`, `test_prompt_provenance_pinned.py`; e2e `tests/e2e/test_us010_run_log.py` |
| 010/SC-002 | `tests/integration/test_log_redaction.py`, `test_run_log_api.py`, `test_ui_run_log.py`, `test_tracing_run.py`; e2e `tests/e2e/test_us010_run_log.py` (the real key: zero times in the API's output and the served lines) |
| 010/SC-008 | `tests/integration/test_experiment_events.py`; `tests/unit/test_events.py` |

## Untraced ids (justified)

None.
