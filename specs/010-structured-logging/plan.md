# Implementation Plan: Structured Logging and Tracing (010)

**Branch**: `010-structured-logging` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-structured-logging/spec.md`

## Summary

Make every run, turn, model request (attacker, judge, recommender) and target request one JSON log line carrying
identifiers, prompt versions, model slugs, latency, tokens and cost — never a secret, URL, target name, attack or
reply text — through the standard-library `logging`/`json` modules, with one structured emission API
(`src/kestrel/events.py`), one JSON (or text) formatter for the whole `kestrel` stream, and a run scope — opened
by the code that starts a run and closed after its write-back — that stamps `run_id` (and `experiment_id`/`arm`)
on every record and makes `run.end` the run's last line. Keep exactly the scope's records in a new `run_log` table
(schema **v8**, cap 1,000 + a `log.truncated` marker; a post-scope line such as the recommender's is stream-only)
so a new `GET /api/runs/{id}/log` endpoint can serve them to a **Log** expander on every opened run. Add optional
OpenTelemetry tracing behind `KESTREL_TRACING=on`: one trace of its own per run (a parentless root span → turn →
model/target request spans, nothing else) from a **private** tracer provider — the web framework's native telemetry
is created off — exported over OTLP/HTTP as configured by the standard `OTEL_*` variables; the packages are an
optional extra, imported lazily, and their absence or an unreachable or refusing collector produces exactly one
warning, a shutdown bounded to 5 s by Kestrel's own join, and never touches a run. Observability only: no attack,
judge, scoring or cap behaviour changes.

Approach and rationale: [research.md](research.md) (D1–D16); shapes: [data-model.md](data-model.md) and
[contracts/](contracts/); validation: [quickstart.md](quickstart.md).

**Spec amendment (plan finding, recorded in the spec's Assumptions)**: ChromaDB and FastAPI — both in the fixed
stack — already depend on the OpenTelemetry API and SDK, and `import chromadb` loads the SDK regardless of any
Kestrel flag. "With the flag off no tracing package is imported" therefore measures **Kestrel's own tracing code**
(FR-014/SC-004 wording), and the optional extra genuinely adds only the OTLP/HTTP exporter.

**Review round 1 (2026-11-13) — a feature-009 recording gap corrected in scope**: today `attack/graph.py` records
the *active* attacker/judge prompt versions as provenance even when an experiment arm pins another version (the
pin reaches only the client's text), and `runs.py` records no judge provenance for a single-turn run. FR-007
requires the log lines to equal the recorded provenance, which cannot hold with that recording; research D15 and
task T046 therefore write the provenance from the same prompt reference the clients use. This changes what is
recorded about a run, never what the run does (FR-017), and is in scope because FR-007 depends on it. The same
review fixed the tracing design to the installed libraries: FastAPI 0.161.1 traces every request natively once a
global tracer provider exists (so Kestrel's provider is private and the app's telemetry is off), and the
OpenTelemetry SDK 1.45.1 ignores its flush timeout and can wait 30 s on shutdown (so the 5 s bound is Kestrel's own
daemon-thread join, and a failure result from the exporter is caught and warned by Kestrel's guard).

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, Streamlit, LangGraph, httpx, ChromaDB, markdown-it-py (all existing). Logging:
stdlib `logging`, `json`, `contextvars`, `time`, `traceback` — **no new runtime dependency**. Tracing (Principle X
justifications, one line each):
- *Optional extra* `kestrel[otel]` = `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http`: the product
  owner asked for OpenTelemetry traces behind a flag, the SDK and OTLP/HTTP exporter are the standard way to emit
  them, and as an optional extra imported only when the flag is on they add nothing to the required stack.
- *Development group* (the same two packages): the suite must drive the real adapter against an in-process span
  collector to prove the span tree and the redaction of attributes (SC-002/SC-004), which no stub can prove; they
  are test tooling like `pytest-cov`, never a runtime requirement.

**Storage**: SQLite (`src/kestrel/store.py`), `SCHEMA_VERSION "7" → "8"`, one new table `run_log` (additive,
cascade-deleted with the run).

**Testing**: pytest — unit + integration offline (no keys; stub targets, attackers, judges, sinks and span
collectors), one `e2e` against the HS-code target. Tests-first (Principle VII).

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell).

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API.

**Performance Goals**: no latency-sensitive path; one dictionary + `json.dumps` per event (≈ 20–40 events per
adaptive run); kept-line writes are single-row inserts; span export is batched on the SDK's background thread
and never blocks the run.

**Constraints**: FR-009 allow-list on every line, span attribute, endpoint response and viewer rendering; FR-015
(a logging/tracing failure is one warning, never a run failure; shutdown flush ≤ 5 s — enforced by Kestrel's own
bounded join, since the SDK's flush and shutdown timeouts are not); FR-013 (a private tracer provider, the
framework's native telemetry off, a parentless root span, explicit span parents, no trace headers to the target);
FR-017 (observability only; the one recording change is the FR-007 provenance correction); per-run kept cap 1,000.

**Scale/Scope**: a few dozen lines per run; `run_log` grows with runs and is deleted with them; no change to run
volume or caps.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — no violations.*

| Principle | Assessment |
|-----------|------------|
| I — security not quality | Observability of security runs; no quality metric introduced. ✓ |
| II — hard evidence over opinion | `turn` lines carry `canary_hit`/`hard_evidence`; a judge line's `hard_evidence` is always false and says so, so no log reader can mistake a judge opinion for a confirmed finding. ✓ |
| III — report states attacker model | Every `run.start`/`turn`/`model.request` names the model slug and the prompt `id@N`, and the recorded provenance now agrees with what was sent (FR-007, D15); the report is unchanged. ✓ |
| IV — secrets never leave the vault | FR-009 allow-list enforced at the single emission API; connection-test line loses URL and name; exceptions and start-up failures logged as class (+ frames) only; redaction test covers lines, spans, endpoint and viewer (SC-002) over the rendered JSON lines; e2e counts the real key (0). ✓ |
| V — learn from every run | Write-back unchanged and now visibly logged (`memory.writeback`). ✓ |
| VI — OWASP-mapped, fix-ready | Unchanged. ✓ |
| VII — tests first, thin slices, one e2e | TDD per story; vertical slice UI → API → store; one e2e (`tests/e2e/test_us010_run_log.py`). ✓ |
| VIII — only attack owned, hard caps | Caps, permission box and token budget untouched; logging adds no call and no tokens (FR-015/FR-017); no trace header is ever sent to the target (FR-013). ✓ |
| IX — simple for a vibe coder | The run page shows the log; no CLI, no YAML; tracing is one flag for those who have a collector. ✓ |
| X — stack fixed; new dep needs justification | **No new required dependency**; the optional extra and the dev-group packages are justified above. ✓ |

Complexity Tracking: none required.

## Project Structure

### Documentation (this feature)

```text
specs/010-structured-logging/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions D1–D16
├── data-model.md        # Phase 1 — record fields, RunContext, run_log (v8), settings, cost, spans, API shapes
├── contracts/           # Phase 1 — log-records.md, api-run-log.md, tracing.md, ui-run-log.md
├── quickstart.md        # Phase 1 — US1–US5 validation
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 — /speckit-tasks
```

### Source code (files this feature touches)

```text
pyproject.toml                       # [project.optional-dependencies] otel; dev group adds the same two packages
.env.example                         # KESTREL_LOG_FORMAT, KESTREL_TRACING, the OTEL_* variables
src/kestrel/
├── events.py                        # NEW — RunContext, run_scope/run_started/run_finished, bind_experiment, bind_run_reference, emit(), per-event helpers, request_cost
├── logging_setup.py                 # NEW — JsonFormatter, TextFormatter, RunLogHandler (in-scope records only; cap + marker + sink_failed), configure_logging
├── tracing.py                       # NEW — no-op/OTel adapters (private provider, guarded exporter, explicit parents), configure_tracing, run_span/span, bounded shutdown, logger bridge
├── settings.py                      # log_format (KESTREL_LOG_FORMAT), tracing (KESTREL_TRACING)
├── store.py                         # schema v8: run_log table, LogLine, add_log_line, list_log_lines, RUN_LOG_CAP
├── retry.py                         # RetryResult gains attempts, prompt_tokens, completion_tokens
├── runs.py                          # run_started/turn/run_finished on single-turn runs (replaces the text line); judge provenance recorded (D15)
├── attack/graph.py                  # run_started/run_finished, turn counter and totals, turn lines, run/turn spans; provenance from the clients' references (D15)
├── attack/attacker.py               # model.request (kind=attacker) with timing/attempts/usage; prompt_ref(); empty-content warning as fields
├── judge/client.py                  # model.request (kind=judge/recommender); judge_prompt_ref/recommender_prompt_ref; pinned (text, ref)
├── connection/tester.py             # target.request / connection.test (no URL, no display name); target_id argument
├── experience/store.py              # retrieve_patterns_with_ids
├── experience/writeback.py          # memory.writeback (inside the run scope)
├── experiments/engine.py            # bind_experiment + run_scope per repetition (enclosing the write-back); experiment.start/cap/end; pinned prompt references
├── report/recommend.py              # recommender call under bind_run_reference (stream only, not kept)
├── api/schemas.py                   # RunLogOut
└── api/main.py                      # FastAPI(telemetry off); configure_logging/configure_tracing/events.configure; run_scope around start_run's run + write-back; lifespan shutdown; GET /api/runs/{id}/log; memory.retrieval in hint_provider; start-up failures as named events; target_id to run_test
ui/
├── api_client.py                    # get_run_log
└── app.py                           # "Log" expander in _render_finding
tests/
├── conftest.py                      # json_log, span_collector and model_transport fixtures (real clients over httpx.MockTransport)
├── unit/test_log_formatter.py       # JSON/text formatters, exc_type+stack, key order (010/FR-006, FR-009)
├── unit/test_events.py              # run_scope/run_started/run_finished, bind_run_reference, experiment inheritance, turn sharing, field building (010/FR-001, FR-005, FR-010)
├── unit/test_request_cost.py        # cost arithmetic and null reasons (010/FR-008, SC-006)
├── unit/test_run_log_handler.py     # keep/cap/marker, sink failure → one warning (010/FR-010, FR-015, SC-009)
├── unit/test_store_migration_v8.py  # v7 → v8 additive (010/FR-010)
├── unit/test_settings_logging.py    # KESTREL_LOG_FORMAT / KESTREL_TRACING parsing (010/FR-006, FR-013)
├── unit/test_tracing.py             # no module-level import, no-op without import, unavailable, in-memory span tree (parentless root, private provider), FAILURE/raise guard, real exporter vs closed port, bounded shutdown (010/FR-013, FR-014, FR-015, SC-004)
├── unit/test_retry.py               # attempts and usage fields (010/FR-003)
├── unit/test_tester.py              # the connection line's fields (updated) (010/FR-004, FR-009)
├── unit/test_attacker_client.py     # model.request fields; prompt_ref; empty-content fields (updated) (010/FR-003, FR-007)
├── unit/test_judge_client.py        # judge/recommender model.request fields; prompt refs (010/FR-003, FR-007)
├── unit/test_store_run_turns.py     # judge reference split into provenance columns (010/FR-007)
├── integration/test_log_records_single_turn.py / _adaptive.py   # event sequence, turn fields, judge_used, retrieval, write-back in scope (010/FR-001..FR-005, FR-007, FR-016, SC-001)
├── integration/test_experiment_events.py                        # experiment_id/arm on every line incl. write-back; start/cap/end (010/FR-005, FR-016, SC-008)
├── integration/test_prompt_provenance_pinned.py                 # pin ≠ active: provenance columns and lines agree (010/FR-007, SC-001)
├── integration/test_log_redaction.py                            # known strings → 0 across stream, spans, endpoint, viewer (010/FR-009, SC-002)
├── integration/test_run_log_api.py                              # endpoint: lines, empty, 404, token (010/FR-011)
├── integration/test_run_log_after_report.py                     # a report leaves the kept log and marker unchanged; recommender line stream-only (010/FR-003, FR-010, SC-009)
├── integration/test_ui_run_log.py                               # viewer states incl. a send-failed run (010/FR-012, SC-003)
├── integration/test_tracing_run.py                              # only kestrel.* spans, one parentless root per run (API + two-run experiment), no trace headers (010/FR-013, SC-004)
├── integration/test_log_resilience.py                           # failing sink/exporter → same outcome (010/FR-015, FR-017, SC-005)
├── integration/test_api_connection_tests.py, test_api_save.py, test_api_manage.py, test_experiment_secrets.py   # secret counts moved to the rendered JSON lines (010/FR-009, SC-005)
└── e2e/test_us010_run_log.py                                    # one e2e: real run's served lines (010/SC-002)
docs/technical-design.md, README.md, CLAUDE.md   # logging/tracing sections, settings, learned note
```

**Structure Decision**: single Python package `src/kestrel/` + `ui/` (existing layout). Three small new modules
(`events.py`, `logging_setup.py`, `tracing.py`) beside `settings.py`; everything else is instrumentation at the
existing boundaries (the two run functions, the two model clients, the tester, the engine, write-back). No
architectural change; no new process or service.

## Phase status

- Phase 0 (research): **complete** — [research.md](research.md); no `NEEDS CLARIFICATION` remains.
- Phase 1 (design): **complete** — [data-model.md](data-model.md), [contracts/](contracts/),
  [quickstart.md](quickstart.md); Constitution re-checked after design → PASS.
- Phase 2 (tasks): run `/speckit-tasks` next.
