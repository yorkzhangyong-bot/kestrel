# Traceability — 009 Versioned Prompts

Every functional requirement and success criterion is covered by at least one test carrying a `009/FR-###` or
`009/SC-###` token (or a module `FEATURE = "009"` marker), except the id justified below.

| id | Covered by |
|----|------------|
| 009/FR-001, FR-002, FR-005, FR-009, FR-011 | `tests/unit/test_prompt_registry.py` (the file registry and the file format) |
| 009/FR-005, FR-006, SC-002 | `tests/unit/test_prompt_guard.py`; `tests/unit/test_bump_prompt.py` (the bump flow) |
| 009/FR-003, SC-001 | `tests/integration/test_provenance_recorded.py`; `tests/unit/test_report_header_prompts.py` (the versions in the report header); e2e `tests/e2e/test_us009_provenance.py` |
| 009/FR-004 | `tests/integration/test_provenance_migration.py` |
| 009/FR-007, SC-004 | `tests/integration/test_config_prompts.py`, `tests/integration/test_ui_prompt_versions.py` |
| 009/FR-008, FR-009, SC-005 | `tests/integration/test_prompt_arm.py` |
| 009/FR-010, SC-006, SC-003 | `tests/eval/test_judge_accuracy.py` (marker `judge_eval`) |
| 009/FR-011, FR-012, SC-007 | `tests/integration/test_prompt_no_secrets.py` |

## Untraced ids (justified)

- 009/FR-013: with every prompt at its seeded version 1, recording and displaying prompt versions must not
  change any attack, judge, recommendation or scoring behaviour — a whole-feature invariant, not a single
  behaviour, so it carries no dedicated test token. It is demonstrated by 009/SC-003
  (`tests/eval/test_judge_accuracy.py` — the judge recall floor holds unchanged) and the quickstart's "no behaviour
  drift" step, and by the full offline suite (749 tests after the PR #19 review round) continuing to pass unchanged after the feature; the e2e
  009/SC-001 run exercises a real run whose verdict stays in the normal `succeeded|failed|unclear` range.
