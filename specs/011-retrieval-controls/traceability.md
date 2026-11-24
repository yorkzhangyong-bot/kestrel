# Traceability — 011 Retrieval Controls for the Experience Store

Every functional requirement and success criterion is covered by at least one test carrying a `011/FR-###` or
`011/SC-###` token (or a module-level `FEATURE = "011"` marker); no id needs a justification
(`uv run python scripts/check_traceability.py`: 30 of 30 traced).

| id | Covered by |
|----|------------|
| 011/FR-001 | `tests/unit/test_retrieval_query.py` (attacker role only, the last two, label first, the seed on turn 2) |
| 011/FR-002, SC-001 | `tests/integration/test_retrieval_query_isolation.py` (two API-started warm runs and an experiment-executed run on one target: the reply, judge, purpose and secret markers 0 times in every query; label and attacker messages every time) |
| 011/FR-003 | `tests/unit/test_retrieval_selection.py` (the floor), `test_experience_store_controls.py` (`query_patterns`); `tests/integration/test_retrieval_lines.py` (a floor nothing passes) |
| 011/FR-004 | `tests/unit/test_retrieval_selection.py` (the near-identical threshold, the skipped duplicate spends no slot, the bounded pool) |
| 011/FR-005 | `tests/unit/test_retrieval_selection.py` (nearest first, at most k, within the floor, pairwise distinct), `test_experience_store_controls.py`; `tests/integration/test_runs_experience.py` (the hints block in selection order) |
| 011/FR-006 | `tests/unit/test_experience_store_controls.py` (merge into the nearest same-family pattern, library seeds eligible, family scope); `tests/integration/test_retrieval_lines.py`, `test_delete_clears_memory.py` |
| 011/FR-007 | `tests/unit/test_experience_store_controls.py` (`hit_count` 1 when added, a pattern without the key counts as 1, counts survive re-seeding) |
| 011/FR-008 | `tests/unit/test_experience_store_controls.py` (de-duplication off → always added); `tests/integration/test_retrieval_lines.py` (a non-success writes no pattern), `test_delete_clears_memory.py` |
| 011/FR-009 | `tests/unit/test_experience_store_model.py` (the explicit `l2` index, the model name and the space recorded beside the version) |
| 011/FR-010, SC-006 | `tests/unit/test_experience_store_model.py` (`EmbeddingModelMismatch`, `SpaceMismatch`, `store_error_kind`, `describe_store_error`); `tests/integration/test_startup_model_mismatch.py` (the `experience.unavailable` line with both values and the constant remedy, the store disabled, runs recorded as not written back) |
| 011/FR-011 | `tests/unit/test_experience_store_model.py`, `tests/integration/test_startup_model_mismatch.py` (a feature-004 store opens, is stamped once, a recorded name is never overwritten, a non-`l2` store is never stamped) |
| 011/FR-012 | `tests/unit/test_settings_experience.py` (defaults, `off`, invalid values, `Settings.retrieval`); `tests/integration/test_api_base.py` (`GET /api/config`) |
| 011/FR-013, SC-007 | `tests/unit/test_events.py` (the catalogue fields); `tests/integration/test_retrieval_lines.py` (every retrieval line carries the settings and counts that add up; the write-back outcome fields; no text on the stream) |
| 011/FR-014, SC-005 | `tests/unit/test_retrieval_recall.py` (the fixture: recall@k, the no-relevant query, the duplicate pair, the published distances and margins, the vocabulary); `tests/unit/test_support_embedding.py` (the lexical stub) |
| 011/FR-015, SC-009 | `tests/integration/test_runs_experience.py` (a cold run and a single-turn run unchanged; the same turns and tokens), `test_retrieval_query_isolation.py`, `test_retrieval_lines.py`, `test_delete_clears_memory.py` (the one changed expectation, named); `tests/unit/test_experiment_engine.py`, `test_experiment_warming.py` (the doubles keep every assertion) |
| 011/FR-016, SC-008 | `tests/unit/test_optional_extra.py` (the required dependencies are exactly the fixed stack; the `otel` extra unchanged); `tests/unit/test_support_embedding.py` (the offline embedding) |
| 011/FR-017 | `tests/integration/test_retrieval_query_isolation.py` (no auth value, URL or name in a query), `test_retrieval_lines.py` (none on the stream), `test_startup_model_mismatch.py` (the exception's own text never reaches a line) |
| 011/FR-018, SC-010 | e2e `tests/e2e/test_us011_retrieval.py` (the HS-code target, the real model: the shipped settings on every retrieval line, a seedless turn-4 selection, added/merged/added at the shipped threshold, the stamped model and space, the default embedding and ONNX MiniLM agreeing on a probe) |
| 011/SC-002 | `tests/unit/test_retrieval_selection.py` (every selected hit within the floor, far hits never selected; both controls off → the k nearest) |
| 011/SC-003 | `tests/unit/test_retrieval_selection.py` (no two selected within the threshold; short of k only when the pool is exhausted); `tests/integration/test_retrieval_lines.py` |
| 011/SC-004 | `tests/unit/test_experience_store_controls.py` (N near-identical successes → one pattern with hit count N; N distinct → N patterns) |

## Untraced ids (justified)

- 011/FR-019: documentation requirement (the implementation pull request moved Retrieval controls into the
  roadmap's Done section and renumbered the planned items), verified in the 011 PR review; no test pins doc
  wording (CLAUDE.md rule, 2026-11-24 — `tests/unit/test_roadmap.py` was removed under it).
- 011/SC-011: the roadmap's wording after the 011 PR (Retrieval controls under Done as 011, planned items 012–014
  with no stale former number), verified in the 011 PR review; same rule as FR-019.

None.
