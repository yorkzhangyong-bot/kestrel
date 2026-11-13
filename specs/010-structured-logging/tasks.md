---

description: "Task list for feature 010 — structured logging and tracing"
---

# Tasks: Structured Logging and Tracing (010)

**Input**: Design documents from `specs/010-structured-logging/` (plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md)

**Tests**: REQUIRED — Principle VII (tests-first, one e2e per feature). Every test carries a traceability token
`010/FR-###` / `010/SC-###` (or module-level `FEATURE = "010"`). Tests are written FIRST and must fail before the
implementation task that satisfies them. **Test realism (research D10)**: a test that asserts on `model.request`
lines drives the real `AttackerClient`/`JudgeClient` over `httpx.MockTransport` (canned OpenAI-style JSON bodies
with a `usage` object, no attack text) — the `StubJudge`/`StubAttacker` doubles bypass the clients that emit those
lines and are used only where outcomes alone matter (resilience, cap). Secret counts are asserted over the
rendered JSON lines (`json_log`), never over `caplog.text`, which shows only event names once values are fields.

**Organization**: by user story. MVP = Setup + Foundational + US1 + US2 (the P1 stories that make the lines exist
and keep them clean). US3 (viewer) and US4 (tracing) are P2 increments; US5 (P1, "logging can never harm a run")
comes last in execution order because its failing-sink and failing-exporter scenarios exercise what US3 and US4
build. Phase 9 holds the tasks added by the spec review (round 1); each states where it executes. No attack text
anywhere: tests use placeholder messages and replies.

**Hard rules carried into every task**: no new required dependency (Principle X); nothing from the FR-009
deny-list in any line, span attribute, endpoint response or viewer rendering (Principle IV); observability only
(FR-017) — the one recording change is the provenance correction of T046.

## Phase 1: Setup

- [X] T001 Declare the optional tracing extra and the development-only install: in `pyproject.toml` add
      `[project.optional-dependencies] otel = ["opentelemetry-sdk>=1.45", "opentelemetry-exporter-otlp-proto-http>=1.45"]`
      and list the same two packages in the `dev` group; run `uv lock` and `uv sync`; `[project] dependencies`
      stays byte-identical. Add `tests/unit/test_optional_extra.py` asserting (with stdlib `tomllib`) that no
      `opentelemetry*` package is in `[project] dependencies`, that the `otel` extra names exactly those two, and
      that the `dev` group contains them (010/FR-014, 010/SC-007).
- [X] T002 [P] Document the settings in `.env.example`: `KESTREL_LOG_FORMAT` (`json` default, `text`),
      `KESTREL_TRACING` (`on`/`off`, default `off`), and the standard `OTEL_EXPORTER_OTLP_ENDPOINT` /
      `OTEL_EXPORTER_OTLP_TIMEOUT` / `OTEL_SERVICE_NAME` lines (none overridden by Kestrel) with the
      `uv sync --extra otel` note (010/FR-006, 010/FR-013).
- [X] T003 [P] Shared test fixtures in `tests/conftest.py`: `json_log` (attaches the real `JsonFormatter` from
      `kestrel.logging_setup` to a `StringIO` handler on the `kestrel` logger and returns a function yielding the
      parsed records in order), `span_collector` (an `InMemorySpanExporter` from
      `opentelemetry.sdk.trace.export.in_memory_span_exporter`, passed to `configure_tracing(..., exporter=)`),
      `model_transport` (an `httpx.MockTransport` answering the attacker/judge/recommender POSTs with canned
      OpenAI-style JSON bodies carrying a `usage` object **and** the stub target's sends, routed by host, recording
      every request's headers, so the real clients — injected, or built by the experiment engine's own factories
      over the app's `transport` — run offline), the known-string constants (`SECRET`, `TARGET_URL`, `TARGET_NAME`,
      `ATTACK_TEXT`, `REPLY_TEXT`) the redaction tests reuse, an autouse reset of the module-level logging/tracing/
      price state between tests, and the SC-007 switch: when `KESTREL_TEST_BLOCK_OTLP=1` is set, conftest places
      `None` in `sys.modules` for `opentelemetry.exporter.otlp.proto.http.trace_exporter` before any test runs and
      the tests marked as needing the real exporter are skipped (010/SC-001, 010/SC-002, 010/SC-007).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks every user story**: the emission API, the formatter and the settings are what every line is made of.
T046 (Phase 9) also executes here, after T010 and before any user story.

- [X] T004 [P] Unit test `tests/unit/test_settings_logging.py`: `KESTREL_LOG_FORMAT` unset → `log_format ==
      "json"`, `text` accepted, any other value raises `SettingsError`; `KESTREL_TRACING` unset → `tracing is
      False`, `on`/`off` accepted, other values raise (010/FR-006, 010/FR-013).
- [X] T005 [P] Unit test `tests/unit/test_log_formatter.py`: every formatted record is exactly one JSON object
      with no embedded newline; key order is common fields (`ts`, `level`, `logger`, `event`), then run/turn/
      experiment scope, then event fields; a record without `kestrel_event` becomes `{"event": "message",
      "message": …}`; an attached exception renders `exc_type` and `stack` (`file:line in function` frames) and
      never the exception message; the text formatter renders the same fields as `ts level event key=value …`;
      fields not in the catalogue are dropped and counted once as a `log.unknown_field` warning
      (010/FR-006, 010/FR-009).
- [X] T006 [P] Unit test `tests/unit/test_events.py`: `run_scope()` emits nothing by itself; `run_started(ctx,
      …)` inside it emits `run.start` and from then on every record carries `run_id`, `target_id`, `mode`,
      `family` and `kestrel_keep` true; the scope's exit emits `run.end` as the last record — after whatever the
      scope body did (a fake write-back sets `memory_written`) — with the outcome stashed by `run_finished`,
      `judge_used == (judge requests made > 0)`, `memory_written`, `duration_ms`, cost totals, and `error` = the
      class name when an exception escaped; a scope whose body never called `run_started` (a failed claim) emits
      nothing; `bind_experiment(id, arm)` makes `experiment_id`/`arm` appear on every record of a scope opened
      inside it; `bind_run_reference(run)` binds the identifiers, emits neither `run.start` nor `run.end` and marks
      records `kestrel_keep` false; called with no scope open, `run_started` raises nothing and emits `run.start`
      with `run_id` null and `kestrel_keep` false, and `run_finished` is a no-op (no `run.end`); `turn` set on the
      shared context object is seen by a record emitted from an `asyncio` child task; the per-turn token/cost
      accumulators reset on each new turn; fields are omitted (not null) when not applicable (010/FR-001,
      010/FR-005, 010/FR-010, 010/SC-005).
- [X] T007 [P] Unit test `tests/unit/test_request_cost.py`: `request_cost(908, "m", {"m": 0.0015})` equals
      `908 / 1000 * 0.0015` within 1e-9 (the `pricing.arm_cost` arithmetic); no price → `(None, "unavailable (no
      configured price for m)")`; `total_tokens=None` → `(None, "no usage reported by the provider")`; never `0.0`
      when tokens > 0 and no price; the turn total and the run total each sum priced requests or carry the first
      reason (010/FR-008, 010/SC-006).
- [X] T008 [P] Unit test `tests/unit/test_retry.py` (extend): `RetryResult` carries `attempts` (HTTP posts made),
      and `prompt_tokens`/`completion_tokens`/`total_tokens` summed over every attempt, `None` when no attempt
      reported usage, while `tokens` keeps its integer budget semantics (010/FR-003).
- [X] T009 Implement `src/kestrel/events.py`: mutable `RunContext` (identifiers, `experiment_id`, `arm`, `keep`,
      `turn`, `turn_started_at`, `started_at`, the model slugs and prompt references in play, per-turn and per-run
      token/cost accumulators, `judge_requests`, `memory_written`, `outcome`, `run_span`/`turn_span`) in a
      `contextvars.ContextVar`; `run_scope()` (opened by the callers; `run.end` on exit after the body, only when
      `run.start` was emitted), `run_started(ctx, …)` (receives the run's store and puts it on the context for the
      `RunLogHandler`; emits `run.start`; null-safe with no scope open: `run_id` null, not kept, no error),
      `run_finished(ctx, run)` (stashes the outcome; a no-op with no scope open),
      `bind_experiment(...)`, `bind_run_reference(run)` (non-emitting, `keep` false); `emit(event,
      level=INFO, **fields)` → `log.log(level, event, extra={"kestrel_event", "kestrel_fields", "kestrel_keep"})`
      with the context merged in; the per-event helpers of `contracts/log-records.md` (`run_started`, `turn`,
      `model_request`, `target_request`, `connection_test`, `run_ended`, `memory_retrieval`, `memory_writeback`,
      `experiment_started`, `experiment_cap`, `experiment_ended`) each building exactly the catalogue's fields; the
      field catalogue as the allow-list; `configure(prices=...)` and `request_cost(...)`; every emission wrapped so
      a failure becomes one warning per cause and never raises (010/FR-001, 010/FR-005, 010/FR-008, 010/FR-010,
      010/FR-015).
- [X] T010 Implement `src/kestrel/logging_setup.py` (`JsonFormatter`, `TextFormatter`, `configure_logging(settings)`
      installing the stderr handler with the chosen formatter on the `kestrel` logger, idempotent; `emit(...,
      message=<constant text>)` keeps a converted line's constant text as the record's message, research D1)
      and replace `_configure_logging` in `src/kestrel/api/main.py` with it; add `log_format` and `tracing` to
      `src/kestrel/settings.py` (`KESTREL_LOG_FORMAT`, `KESTREL_TRACING`, `SettingsError` on other values); extend
      `src/kestrel/retry.py` `RetryResult` with `attempts`, `prompt_tokens`, `completion_tokens` summed over
      attempts (010/FR-003, 010/FR-006, 010/FR-013).

**Checkpoint**: `uv run pytest tests/unit -k "settings_logging or log_formatter or events or request_cost or retry"`
green; the stream is JSON; nothing is instrumented yet. Then T046 (provenance source), then the stories.

---

## Phase 3: User Story 1 — Follow a run line by line (P1) 🎯 MVP

**Goal**: every run, turn, model request and target request is one JSON line with ids, prompt versions, model
slug, latency, tokens and cost; the write-back line sits inside the run's scope and `run.end` is last; experiment
runs carry experiment id and arm; operational lines in scope.
**Independent Test**: stub-target single-turn and adaptive runs with the real model clients over
`model_transport`, an experiment and a report generation produce the contract's event sequence with the contract's
fields.

- [X] T011 [P] [US1] Integration test `tests/integration/test_log_records_single_turn.py` (real `JudgeClient` over
      `model_transport`): with `json_log`, a stub-target single-turn run yields, in order, `run.start` (prompt_id,
      attacker_source, judge_model, `judge_prompt == "judge@1"`, caps, use_prior_experience), `target.request`
      (latency_ms, ok, status, step, reply_chars, reply_truncated; no URL field), `model.request` kind=judge (model,
      `prompt == "judge@1"`, latency_ms, status, attempts, tokens, cost, verdict, `hard_evidence is False`), `turn`
      (turn 1, `source == "library:<prompt_id>"`, `duration_ms`, the turn's prompt/completion/total tokens equal to
      the judge request's, cost, `judge_model`/`judge_prompt` present and no `attacker_model`/`attacker_prompt`,
      message_chars, reply_chars, canary_hit, hard_evidence, judged, verdict), `memory.writeback` carrying the
      `run_id` and `written`, and `run.end` last (verdict, hard_evidence, stopping_condition, `judge_used True`,
      turns_used, tokens_used, `memory_written`, duration_ms, cost_usd/cost_note); no attacker line exists; with
      no judge configured there is no judge line, the turn carries no judge fields, and `run.end.judge_used` is
      false; a canary hit yields `canary_hit`/`hard_evidence` true, no judge line and a null `judge_prompt` on the
      turn line (010/FR-001, 010/FR-002, 010/FR-003, 010/FR-004, 010/FR-007, 010/FR-016, 010/SC-001).
- [X] T012 [P] [US1] Integration test `tests/integration/test_log_records_adaptive.py` (real `AttackerClient` and
      `JudgeClient` over `model_transport`): a stub adaptive run of N turns yields one `turn` per turn with its
      number, `duration_ms`, token totals summed over that turn's requests, cost, `attacker_model`/
      `attacker_prompt == "attacker:<family>@1"` on turns ≥ 2 only, `judge_model` on every turn and
      `judge_prompt` equal to the judge request's reference on every judged turn (null on a canary-decided turn)
      while a judge is configured; attacker `model.request` lines for turns ≥ 2 with `message_chars`; one judge
      line per judge call; one `target.request` per send; `memory.retrieval` on each turn from turn 2 of a warm
      run — turn 1 sends the library seed and never asks — (`warm` true with ids when a seeded pattern matches;
      `warm` false, zero counts and an empty id list against an empty store) and none on a run with prior
      experience off; `memory.writeback` with the `run_id` before `run.end`;
      an adaptive run with no judge configured yields no judge line, no judge fields on its turns and
      `run.end.judge_used` false; an attacker error yields a `model.request` with `ok false`, `error` = class name,
      no tokens, and `run.end.stopping_condition == "attacker_failed"`; a provider retry yields `attempts == 2`
      with tokens summed; every line parses as JSON (010/FR-002, 010/FR-003, 010/FR-004, 010/FR-016, 010/SC-001).
- [X] T013 [P] [US1] Integration test `tests/integration/test_experiment_events.py` (real clients over
      `model_transport`): a two-arm stub experiment emits `experiment.start` (arms, caps), every record of its runs
      — `memory.writeback` included — carries `run_id`, `experiment_id` and `arm`, an arm that pins `judge@1`
      shows `prompt == "judge@1"` on its judge lines, a cap stop emits `experiment.cap` (cap, completed_runs,
      tokens_used), and `experiment.end` carries status and stopped_reason; each run's `run.end` is its last record and
      follows its `memory.writeback` (010/FR-005, 010/FR-007, 010/FR-016, 010/SC-008).
- [X] T014 [P] [US1] Unit tests in `tests/unit/test_attacker_client.py` and `tests/unit/test_judge_client.py`
      (extend): a model call emits one `model.request` with kind, model, prompt reference, `latency_ms ≥ 0`,
      status, attempts, prompt/completion/total tokens and cost (null + note when unpriced); a judge call adds
      `verdict` and `hard_evidence False`; `recommend()` emits kind=recommender with the bound run id; the clients
      expose the reference they used (`prompt_ref(family)`, `judge_prompt_ref`, `recommender_prompt_ref`: the
      active `id@N`, or the pinned one when an arm supplied `(text, ref)`); the empty-content warning is the
      `model.empty_content` event with `attempt`, `finish_reason`, `completion_tokens`, `reasoning_tokens`,
      `total_tokens`, `reasoning_chars` as fields (update the existing `finish_reason=length` text assertion)
      (010/FR-003, 010/FR-007, 010/FR-008).
- [X] T015 [US1] `src/kestrel/connection/tester.py`: `run_test`/`refused` emit `target.request` (turn from the
      run context) when a run is bound and `connection.test` otherwise, with `latency_ms`, `ok`, `status`, `step`,
      `reply_chars`, `reply_truncated`, and `target_id` from a new optional `target_id` argument; `display_name`
      stays accepted but is no longer logged; `_loggable_url` is retired from logging; `src/kestrel/api/main.py`
      passes `target_id=body.target_id` from the connection-test endpoint (010/FR-004, 010/FR-009).
- [X] T016 [US1] `src/kestrel/attack/attacker.py`: time `next_message` end to end (`time.perf_counter`), count
      attempts across the empty-content loop and `RetryResult.attempts`, read prompt/completion/total usage, and
      emit `model.request` kind=attacker in a `finally` (status or `error` class name, `message_chars` on success);
      carry and expose the prompt reference (`prompt_ref(family)`: `load_prompt(...)[1]`, or the arm's pinned
      `"<id>@<version>"` — `system_overrides` becomes `{family: (text, ref)}`); the empty-content warning becomes
      `model.empty_content` with fields (010/FR-003, 010/FR-007).
- [X] T017 [US1] `src/kestrel/judge/client.py`: the same for `judge()` (kind=judge, `verdict`, `hard_evidence
      False`, `ctx.judge_requests += 1`) and `recommend()` (kind=recommender), attempts summed across
      `_structured_call`'s schema retry and `RetryResult.attempts`; `system_prompt` also accepts `(text, ref)` (a
      plain text, the feature-009 form, keeps working with an unknown reference) and the client exposes
      `judge_prompt_ref`/`recommender_prompt_ref`; `src/kestrel/experiments/engine.py::_prompt_overrides` returns the
      references alongside the texts; `api/main.py::_schedule_experiment`'s injected-double factories accept the pin
      keywords (010/FR-003, 010/FR-007).
- [X] T018 [US1] `src/kestrel/runs.py` and `src/kestrel/api/main.py`: `start_run` opens `events.run_scope()`
      around the run function **and** `write_back(...)`; `execute_run` calls `run_started(...)` right after
      `claim_run` (single-turn deadline as `time_limit_s`, the judge model and `judge.judge_prompt_ref`, falling
      back to the registry's active reference when the judge double has no accessor; `run_started`/`run_finished`
      are null-safe when no scope is open, so the existing direct-call tests keep passing), emits the
      one `turn` line (`source == "library:<prompt_id>"`, duration, the turn's token totals and cost, judge fields,
      `canary_hit`, `hard_evidence`) and calls `run_finished(...)` after `_finish`, replacing the free-text
      "attack run" line; the unexpected-failure path still closes the row and the scope's `run.end` carries
      `error`; `write_back` is reached inside the scope so `memory.writeback` carries the run id and `run.end`
      carries `memory_written` (010/FR-001, 010/FR-002, 010/FR-008, 010/FR-016).
- [X] T019 [US1] `src/kestrel/attack/graph.py`: `run_adaptive` calls `run_started(...)` after `claim_run` (attacker
      model, the references from `attacker.prompt_ref(family)` and `judge.judge_prompt_ref` — T046 — with the
      registry's active reference as the fallback when a client double has no accessor, and null-safe with no
      scope open so the existing direct-call tests keep passing; caps), sets
      `ctx.turn`/`turn_started_at` in `attacker_node`, emits `turn` in `record_node` (source `library:<prompt_id>`
      on turn 1, `attacker:<family>@N` after; `duration_ms`, the turn's token totals and cost, model slugs and
      prompt references in play, message/reply lengths, canary_hit, hard_evidence, judged, verdict) and calls
      `run_finished(...)` after `finish_run`, replacing the free-text "adaptive run" line (010/FR-001, 010/FR-002).
- [X] T020 [US1] `src/kestrel/experience/store.py` `retrieve_patterns_with_ids(family, query_text, k) ->
      list[tuple[str, str]]`; the hint providers in `src/kestrel/api/main.py` (`start_run.hint_provider`) and
      `src/kestrel/experiments/engine.py` (`_hint_provider`) use it and emit `memory.retrieval` whenever they ask
      the store (prior experience on, store available): `pattern_count`, `memory_count` (zero when nothing came
      back), `pattern_ids` (empty when none), `warm = pattern_count > 0`; a run with prior experience off asks for
      nothing and emits no line; `src/kestrel/experience/writeback.py` emits `memory.writeback` (`written`,
      `pattern_written`, `error` class name on failure; a direct call with no scope for that run binds the run as a
      reference so the line still names it, stream-only) and records `memory_written` on the run context; a failed
      flag write is `memory.flag_failed` (010/FR-016).
- [X] T021 [US1] `src/kestrel/experiments/engine.py`: `bind_experiment(experiment.id, arm.label)` and, inside it,
      `events.run_scope()` around each `_run_rep`'s run function **and** its `write_back(...)`, so every record of
      the run — the write-back line included — carries the experiment id and arm and `run.end` is last; emit
      `experiment.start` (campaign, caps, arms with their pinned prompt), `experiment.cap` (cap, completed_runs,
      tokens_used, elapsed_s) and `experiment.end` (status, stopped_reason, completed_runs, tokens_used, duration_ms,
      `error` on failure, replacing the free-text exception line's message with class + frames)
      (010/FR-005, 010/FR-016).
- [X] T022 [US1] `src/kestrel/report/recommend.py`: bind the finding's run with `events.bind_run_reference(run)`
      (non-emitting, not kept) around each `judge.recommend(...)` so the recommender line carries `run_id`,
      `target_id`, `mode` and `family` on the stream only; the "No recommendation" warning becomes an event with
      `error` = class name, no message text (010/FR-003, 010/FR-009, 010/FR-010).

**Checkpoint**: US1 tests green; `uv run pytest tests/unit tests/integration` still green (the text-line
assertions updated in T014 and later T024/T026).

---

## Phase 4: User Story 2 — The log never leaks (P1) 🎯 MVP

**Goal**: no auth value, URL, target name, attack text, reply text, judge free text or error message text in any
line, span attribute, endpoint response or viewer rendering — proven by tests with known strings.
**Independent Test**: a stub target with known secret/URL/name and a run with known message/reply → zero
occurrences across every surface that exists at this point (stream; spans/endpoint/viewer join in US3/US4).

- [X] T023 [P] [US2] Integration test `tests/integration/test_log_redaction.py` (real clients over
      `model_transport`): register a target with `SECRET` header value, `TARGET_URL` and `TARGET_NAME`, run a
      single-turn and an adaptive run whose attacker message is `ATTACK_TEXT` and whose reply is `REPLY_TEXT` (the
      mocked judge returning a reason that quotes the reply); assert each known string, the judge reason and the
      progress note appear zero times in the `json_log` records (serialised) and that a failing model request
      shows `error` as a class name only; extend in US3/US4 with the endpoint response, the viewer rendering and
      the span attributes (010/FR-009, 010/SC-002).
- [X] T024 [P] [US2] Unit test `tests/unit/test_tester.py` (update): the connection line is a `connection.test`
      record with `target_id` (when given), `latency_ms`, `ok`, `status`, `step`, and carries neither the URL (in
      any form) nor the display name; `SECRET` appears zero times in the rendered JSON line; `refused()` logs the
      same shape (010/FR-004, 010/FR-009).
- [X] T025 [US2] Structural enforcement in `src/kestrel/events.py` and `src/kestrel/logging_setup.py`: the
      catalogue is the allow-list (unknown fields dropped, one `log.unknown_field` warning per name); the judge
      and attacker helpers accept lengths and categories only (no `reason`/`progress`/text parameters exist);
      exceptions render as `exc_type` + `stack` only; a unit assertion in `tests/unit/test_events.py` that no
      catalogue field name is `url`, `name`, `reason`, `progress`, `message_text`, `reply_text`, `prompt_text` or
      `value` (010/FR-009).
- [X] T026 [US2] Audit and convert every pre-existing `log.*` call for the deny-list and the fields rule: in
      `src/kestrel/api/main.py` the three start-up lines that interpolate exception text become named events with
      `exc_type` and no message text — `library.unavailable`, `experience.unavailable` (`exc_type`, `reason_kind`
      from the categories `describe_store_error` distinguishes) and `experience.seed_failed` — plus the
      key-mismatch error line (the constant "encryption key doesn't match" message → `key.mismatch`, no exception)
      and the delete-target memory failure (`logger.exception("could not delete experience memory …")` →
      `experience.delete_failed` with `exc_type` and `target_id`), while the start-up lines carrying only paths and
      counts stay `message` events with their values as fields (`path`, `count`, versions) and a constant
      `message`; `src/kestrel/secrets.py`, `src/kestrel/experience/store.py` (version warning),
      `src/kestrel/experience/writeback.py` and `src/kestrel/attack/graph.py` (`log.exception` →
      `memory.retrieval_failed` with `exc_type`/`stack`, no message), `src/kestrel/report/recommend.py`
      (`recommendation.unavailable`). Move the existing secret-count assertions of
      `tests/integration/test_api_connection_tests.py`, `test_api_save.py`, `test_api_manage.py` and
      `test_experiment_secrets.py` from `caplog.text` to the rendered JSON lines (`json_log`), so they keep
      counting values rather than event names; delete or weaken none of them (010/FR-006, 010/FR-009,
      010/SC-005).

**Checkpoint**: the MVP — lines exist for everything and carry nothing sensitive.

---

## Phase 5: User Story 3 — Read a run's log on the run page (P2)

**Goal**: in-scope lines are kept with the run (schema v8, cap 1,000 + marker) and served by
`GET /api/runs/{run_id}/log` to a "Log" expander on every opened run.
**Independent Test**: kept lines come back in order through the endpoint and render in the viewer; empty, 404,
token, send-failed and truncated states behave as the contracts say; a report leaves the kept log unchanged.
T048 (Phase 9) executes with this story's tests, after T033.

- [ ] T027 [P] [US3] Unit test `tests/unit/test_run_log_handler.py`: the handler keeps only records marked
      `kestrel_keep` (a live run scope) — a record with a run id but `kestrel_keep` false (a `bind_run_reference`
      emitter) is ignored: no row, no `seq`, no counter change; it writes `seq` 1..n in order with the exact JSON
      line, keeps the first `RUN_LOG_CAP == 1000` records of a scope and drops the rest from the table, writes one
      `log.truncated` row (`seq == kept + 1`, `kept`, `dropped`) on the scope's `run.end` only when something was
      dropped and then forgets the run's counters, and on a store that raises emits exactly one `log.sink_failed`
      warning per error kind (with `for_run`, no `run_id`) and never raises (010/FR-010, 010/FR-015, 010/SC-009).
- [ ] T028 [P] [US3] Unit test `tests/unit/test_store_migration_v8.py` (the `test_store_migration_v6.py` pattern
      with a version-7 fixture database): migrates to `"8"` additively, `run_log` exists with
      `UNIQUE (run_id, seq)`, `add_log_line`/`list_log_lines` round-trip in `seq` order, deleting the target
      removes the lines (cascade), an unknown version is still refused (010/FR-010).
- [ ] T029 [P] [US3] Integration test `tests/integration/test_run_log_api.py`: after a stub run, `GET
      /api/runs/{id}/log` returns `RunLogOut` with the kept records in order — `run.start` first, `memory.writeback`
      before `run.end`, `run.end` last — `kept`, `dropped == 0`, `truncated False`; a run row inserted without lines
      returns `lines == []`; an unknown id → 404 `not_found`; hosted mode without the token → 401; a run in
      progress (background experiment) returns the lines so far; no line carries a deny-list string (010/FR-011,
      010/SC-002, 010/SC-003).
- [ ] T030 [P] [US3] Integration test `tests/integration/test_ui_run_log.py` (AppTest, `api_client` stubbed as in
      `test_ui_prompt_versions.py`): opening a run shows a "Log" expander; its dataframe has the columns Time,
      Event, Turn, Model, Prompt, Latency ms, Tokens, Cost and one row per line; the raw JSON `st.code` block is
      present; a run whose send failed (`failure_step` set) shows its failure message **and** the expander with its
      lines; an empty list shows "No log lines were recorded for this run."; a truncated log shows the dropped
      count caption; no known secret/URL/name/message/reply string appears in any element (010/FR-012,
      010/SC-002, 010/SC-003).
- [ ] T031 [US3] `src/kestrel/store.py`: schema v8 — the `run_log` table (`id`, `run_id REFERENCES runs ON
      DELETE CASCADE`, `seq`, `ts`, `event`, `record TEXT`) and `uq_run_log_seq`; `SCHEMA_VERSION = "8"`;
      `_migrate` accepts `"7"`; `LogLine` dataclass; `add_log_line(run_id, *, seq, ts, event, record)`;
      `list_log_lines(run_id)`; `RUN_LOG_CAP = 1000` (010/FR-010).
- [ ] T032 [US3] `src/kestrel/logging_setup.py`: `RunLogHandler()` (keeps `kestrel_keep` records only, through the
      store on the record's own run context — `run_started(store, …)` puts it there; per-run `seq`/`kept`/`dropped`
      counters on that context under the handler's lock, cap, marker on the scope's `run.end`, `handleError` → one
      `log.sink_failed` per error kind), installed once by `configure_logging(settings)` from `create_app`
      (010/FR-010, 010/FR-015).
- [ ] T033 [US3] `src/kestrel/api/schemas.py` `RunLogOut(run_id, lines: list[dict[str, Any]], kept, dropped,
      truncated)`; `src/kestrel/api/main.py` `GET /api/runs/{run_id}/log` (404 `not_found` like `get_run`; parses
      each kept `record`; `truncated = dropped > 0` from the marker row) (010/FR-011).
- [ ] T034 [US3] `ui/api_client.py` `get_run_log(run_id)`; `ui/app.py` `_render_finding` adds the collapsed
      `st.expander("Log")` **before its early return for a send-failed run**, so every opened run shows it: the
      dataframe (blank cells for missing fields), the raw `st.code(..., language="json")`, the truncated caption
      and the empty-state caption; errors through `api_message` (010/FR-012).

**Checkpoint**: open any run on the screen → its log.

---

## Phase 6: User Story 4 — Trace a run, optionally (P2)

**Goal**: `KESTREL_TRACING=on` gives one trace of its own per run (parentless `kestrel.run` → `kestrel.turn` →
model/target request spans, nothing else) over OTLP/HTTP as the standard `OTEL_*` variables configure; absent
packages or an unreachable or refusing collector mean exactly one warning and a bounded shutdown.
**Independent Test**: in-process span collector shows the tree for API-started and experiment-started runs;
blocked import shows the single warning; the real exporter against a closed port leaves the run unchanged within
the bound; no trace header reaches the target.

- [ ] T035 [P] [US4] Unit test `tests/unit/test_tracing.py`: a static check that `src/kestrel/tracing.py` has no
      module-level `opentelemetry` import (parse it with `ast`); flag off → `configure_tracing` returns the no-op
      without touching `opentelemetry.exporter.otlp.proto.http.trace_exporter` (the module is blocked with
      `sys.modules[...] = None`; no error, no warning, `enabled False`); flag on + blocked import → exactly one
      `tracing.unavailable` warning (`cause package_missing`, `extra kestrel[otel]`) and the no-op; flag on +
      `span_collector` → `run_span`/`span(parent=…)` produce `kestrel.run` with `kestrel.run_id` and **no parent**,
      children `kestrel.turn`, `kestrel.model_request`, `kestrel.target_request` sharing one trace id, the global
      tracer provider untouched (`trace.get_tracer_provider()` is not Kestrel's), `service.name == "kestrel"` by
      default and `OTEL_SERVICE_NAME` when set, `configure_tracing` callable twice in one process; an exporter
      stub whose `export()` raises and one returning `SpanExportResult.FAILURE` each → spans dropped, exactly one
      `tracing.export_failed` warning (`error` = the class name / `failure_result`), no exception; the **real**
      OTLP/HTTP exporter with `OTEL_EXPORTER_OTLP_ENDPOINT` at a closed local port and a short
      `OTEL_EXPORTER_OTLP_TIMEOUT` → a traced stub run's outcome unchanged, exactly one warning, and
      `shutdown(5.0)` returns within 5 s (measured) while the batch processor's `shutdown` runs in a daemon thread
      (this real-exporter case carries the marker the `KESTREL_TEST_BLOCK_OTLP=1` switch skips); the
      `opentelemetry` loggers do not propagate to the stream (010/FR-013, 010/FR-014, 010/FR-015, 010/SC-004,
      010/SC-007).
- [ ] T036 [P] [US4] Integration test `tests/integration/test_tracing_run.py`: with tracing on and
      `span_collector` and the real clients over `model_transport`, an adaptive run against the stub target started
      through `POST /api/runs` and a two-run experiment started through `POST /api/experiments` yield **only**
      `kestrel.*` spans and, per run, exactly one parentless `kestrel.run` carrying that run's id whose child spans
      cover every turn, model request and target request with the data-model attributes (three distinct trace ids
      for the three runs); a single-turn run against the stub target, the same way, yields the one-turn tree with
      the judge span under the turn span; no span attribute contains `SECRET`, `TARGET_URL`,
      `TARGET_NAME`, `ATTACK_TEXT` or `REPLY_TEXT`; the stub target's recorded requests carry no `traceparent`,
      `tracestate` or `baggage` header; with the flag off the collector stays empty (010/FR-013, 010/SC-002,
      010/SC-004).
- [ ] T037 [US4] Implement `src/kestrel/tracing.py` per `contracts/tracing.md`: no module-level `opentelemetry`
      import; `Tracing` protocol, the no-op, the OpenTelemetry adapter with lazy imports inside
      `configure_tracing(settings, *, exporter=None)` — the OTLP/HTTP exporter module imported only when no
      `exporter` was injected; a **private** `TracerProvider(Resource.create({"service.name":
      os.environ.get("OTEL_SERVICE_NAME", "kestrel")}))` never passed to `trace.set_tracer_provider`;
      `BatchSpanProcessor(_GuardedExporter(exporter or OTLPSpanExporter()))` — the exporter constructed without
      arguments so the standard `OTEL_EXPORTER_OTLP_*` variables (timeout included) apply unchanged, the guard
      turning an exception or a `FAILURE` result from `export()` into exactly one `tracing.export_failed` warning
      per process and returning `FAILURE`; `ImportError` → one `tracing.unavailable` warning; the `opentelemetry.*`
      logger bridge (`propagate False`); `run_span(ctx)` starting the root from an empty `Context()` and storing it
      on `ctx.run_span`; `span(name, *, parent, **attrs)` with an explicit parent; `set_attributes` (scalars only);
      `shutdown(timeout_s=5.0)` running `provider.shutdown()` in a daemon thread joined for at most `timeout_s`,
      never raising; no propagator, no header injection (010/FR-013, 010/FR-014, 010/FR-015).
- [ ] T038 [US4] Wire the spans: `src/kestrel/api/main.py` creates the app with
      `FastAPI(..., telemetry={"tracing": False, "metrics": False, "logs": False})`, calls
      `configure_tracing(settings, exporter=span_exporter)` (`create_app` gains the `span_exporter=None` test seam)
      and adds a `lifespan` whose exit calls `tracing.current().shutdown(5.0)`;
      `src/kestrel/events.py`: `run_started` opens the `kestrel.run` root span (`ctx.run_span`, from an empty
      context) and the run scope's exit ends it after setting the run-end attributes — `kestrel.memory_written`
      included, which is known only after the caller's write-back; `src/kestrel/attack/graph.py` opens a
      `kestrel.turn` span per turn with `parent=ctx.run_span` (`ctx.turn_span`); `src/kestrel/runs.py` the same for
      the single turn; `src/kestrel/attack/attacker.py` and
      `src/kestrel/judge/client.py` wrap each logical call in `kestrel.model_request` with `parent=ctx.turn_span`
      (the recommender excluded); `src/kestrel/connection/tester.py` wraps a run-bound send in
      `kestrel.target_request` with `parent=ctx.turn_span`; attributes come from the same field dicts as the lines
      (010/FR-013).

**Checkpoint**: `KESTREL_TRACING=on` against a local collector shows one `kestrel.run` trace per run and nothing
else.

---

## Phase 7: User Story 5 — Logging can never harm a run (P1)

**Goal**: a failing sink, a failing exporter or the cap never changes a run's verdict, evidence, turns or tokens;
one warning per cause; no extra calls.
**Independent Test**: the same stub run three ways compares equal; the cap keeps 1,000 + marker.

- [ ] T039 [P] [US5] Integration test `tests/integration/test_log_resilience.py` (stubs suffice: outcomes only):
      the same stub adaptive run with (a) a working sink, (b) a store whose `add_log_line` raises on every call,
      (c) tracing on with an exporter that raises; assert identical `verdict`, `hard_evidence`,
      `stopping_condition`, `turns_used`, `tokens_used`; exactly one `log.sink_failed` / `tracing.export_failed`
      warning; the stub sender, attacker and judge call counts are identical in all three (logging adds no call);
      the run's `tokens_used` equals the stubs' reported tokens (no logging token counted) (010/FR-015,
      010/FR-017, 010/SC-005).
- [ ] T040 [P] [US5] Integration test `tests/integration/test_run_log_cap.py`: with `RUN_LOG_CAP` monkeypatched
      low (and a unit assertion that the shipped constant is 1000), a stub adaptive run with a turn cap large
      enough to overflow keeps exactly the first `RUN_LOG_CAP` records plus one `log.truncated` row whose `dropped`
      equals the overflow, while the `json_log` stream carries every record and the run finishes normally; the
      endpoint reports `truncated True` (010/FR-010, 010/SC-009).
- [ ] T041 [US5] Harden every emission and span path (`src/kestrel/events.py`, `src/kestrel/logging_setup.py`,
      `src/kestrel/tracing.py`): wrap formatting, keeping and span operations in try/except that records one
      warning per cause (a per-process set keyed by event + error class) and swallows; `RunLogHandler` ignores
      records that lack `kestrel_keep`; `logging.raiseExceptions` cannot surface a sink failure; confirm the whole
      offline suite passes with no existing test deleted or weakened (010/FR-015, 010/FR-017, 010/SC-005).

**Checkpoint**: the suite proves logging and tracing are inert for outcomes.

---

## Phase 8: Polish & Cross-Cutting

- [ ] T042 [P] e2e `tests/e2e/test_us010_run_log.py` (marker `e2e`, `FEATURE = "010"`): one real adaptive run
      against the HS-code target through the API; `GET /api/runs/{id}/log` returns lines that parse as JSON, the
      `run.start` carries `attacker:<family>@N` and `judge@N` references and the model slugs, and the target's
      real key appears zero times in the API's log output and in the served lines (010/SC-001, 010/SC-002).
- [ ] T043 [P] Docs: `docs/technical-design.md` (structured logging, the event catalogue pointer, the run scope,
      schema v8, the provenance correction, tracing with the private provider), `README.md` (reading the log, the
      Log expander, `KESTREL_LOG_FORMAT`, `KESTREL_TRACING`, the `otel` extra and the `OTEL_*` variables), and a
      dated learned note in `CLAUDE.md` (the ChromaDB/FastAPI transitive OpenTelemetry fact and FastAPI's native
      telemetry being switched off; the SDK's unbounded flush; the fields-not-interpolation rule; the deny-list)
      (010/FR-006, 010/FR-013).
- [ ] T044 Quality gate: `uvx ruff check src ui tests scripts`; `uv run mypy src` (advisory); `uv run pytest
      tests/unit tests/integration` with coverage ≥ 85% on `src`; run the offline suite once more with
      `KESTREL_TEST_BLOCK_OTLP=1` (the exporter import blocked, the real-exporter tests skipped) and record the
      result in the PR description (the SC-007 evidence); walk `quickstart.md` including the rest of the SC-007
      step (a run with the flag off, and with the flag on → the single warning) and the no-behaviour-drift
      check; confirm no existing test was deleted or weakened and that existing assertions changed only in the
      shape of the log lines they read (010/SC-005, 010/SC-007).
- [ ] T045 Traceability: confirm every new or changed test carries a `010/FR-###`/`010/SC-###` token or
      `FEATURE = "010"`; create `specs/010-structured-logging/traceability.md` mapping ids to tests and justifying
      any id without a dedicated token (expected: none — FR-017 is covered by `test_log_resilience.py`); run
      `uv run python scripts/check_traceability.py` (010/FR-017).

---

## Phase 9: Review round 1 (spec review, 2026-11-13)

Tasks added by the review; each names where it executes.

- [X] T046 (executes in Phase 2, after T010, before any story) Provenance records the version actually used, from
      the single source the lines use (research D15): `src/kestrel/attack/graph.py::run_adaptive` takes the
      attacker and judge references from the clients (`attacker.prompt_ref(seed_prompt.family)`,
      `judge.judge_prompt_ref` — T016/T017 add the accessors; until then from `load_prompt(...)[1]`) instead of
      resolving the active version itself, so a pinned arm's `run_turns.attacker_prompt_*`/`judge_prompt_*` and
      `runs.judge_prompt_*` record the pinned version; `src/kestrel/runs.py::execute_run` passes the judge
      reference (`judge_prompt_id`, `judge_prompt_version` split from `id@N`) to `finish_run` only when a judge
      request was made, so a single-turn verdict records its judge provenance; judge provenance is recorded only
      when a judge request was made — an adaptive run with no judge configured records null judge provenance on
      `runs` and `run_turns` (`runs.judge_prompt_*` follows `ctx.judge_requests > 0`, not the stored `judge_used`
      flag) and a canary-decided turn records null judge provenance; when a client has no `prompt_ref()` /
      `judge_prompt_ref` accessor (the `tests/support.py` doubles) the run functions fall back to the registry's
      active reference (`load_prompt(...)[1]`), so the existing tests keep passing; a unit test in
      `tests/unit/test_store_run_turns.py` (extend) covers the split; pre-v8 rows are untouched; this is a
      recording correction of a feature-009 gap, not a behaviour change (010/FR-007, 010/FR-017, 010/SC-005).
- [X] T047 [US1] (executes with the US1 tests, T011–T014) Integration test
      `tests/integration/test_prompt_provenance_pinned.py` (the `two_judge_versions` fixture pattern of
      `tests/integration/test_prompt_arm.py`; real clients over `model_transport`): a two-arm experiment whose arm B
      pins `judge@1` while `judge@2` is active yields, for arm B's run, `runs.judge_prompt_version == "1"`,
      `run_turns.judge_prompt_version == "1"` on its judged turns and `judge@1` on its `run.start.judge_prompt`,
      `turn.judge_prompt` and judge `model.request.prompt` lines; arm A's run records and logs `judge@2`; an
      attacker pin is checked the same way on `run_turns.attacker_prompt_*` and the attacker lines; a single-turn
      run records `runs.judge_prompt_id/version` equal to its judge line's reference; an adaptive run with no
      judge configured records null judge provenance on `runs` and `run_turns` and its `run.start` has no
      `judge_prompt`; a canary-decided turn records null judge provenance and its turn line's `judge_prompt` is
      null (010/FR-007, 010/SC-001).
- [ ] T048 [US3] (executes with the US3 tests, after T033) Integration test
      `tests/integration/test_run_log_after_report.py` (real clients over `model_transport`): after a stub-target
      run, and after a run truncated at the cap (`RUN_LOG_CAP` monkeypatched low), generating the target's report
      (`GET /api/targets/{id}/report`, `model_transport` answering the recommender request with a canned
      recommendation for a succeeded run) emits a recommender `model.request` on the stream
      carrying the finding's `run_id`, `target_id`, `mode` and `family`, while `GET /api/runs/{id}/log` answers
      byte-identically before and after the report — same lines, same `kept`/`dropped`, the `log.truncated` marker
      still last — and `run_log` gained no row; a second report (cached recommendation) emits no model line and
      changes nothing (010/FR-003, 010/FR-010, 010/SC-009).

---

## Dependencies & Execution Order

- **Setup (T001–T003)** → **Foundational (T004–T010, then T046)** blocks all stories. T009 (events) before T010
  (formatter wiring); the tests T004–T008 are written first and fail until T009/T010; T046 after T010 and before
  any story (T016/T017 later replace its interim `load_prompt(...)[1]` source with the client accessors).
- **US1 (T011–T022, with T047)** depends only on Foundational. Same-file ordering: `attacker.py` T016 before the
  engine reference change in T017; `main.py` T015 → T018 → T020; `engine.py` T017 → T020 → T021; `graph.py` T046 →
  T019. T047 is written with T011–T014 and passes once T016/T017/T019/T021 are done.
- **US2 (T023–T026)** depends on US1's instrumentation (the lines must exist to be checked); T023 is extended in
  US3 (endpoint, viewer) and US4 (spans) with the same tokens.
- **US3 (T027–T034, with T048)** depends on Foundational and US1 (in-scope records); `store.py` T031 before
  `logging_setup` T032 before `main.py` T033 before the UI T034; T048 is written with T027–T030 and passes after
  T033 (and T022, the reference binder).
- **US4 (T035–T038)** depends on Foundational and US1 (the field dicts the spans reuse); T037 before T038.
- **US5 (T039–T041)** depends on US3 (the sink) and US4 (the exporter) — it is P1 but runs last because it tests
  what they build.
- **Polish (T042–T045)** after the stories it checks; T045 last.
- Within a story: the tests (T011–T014 and T047, T023–T024, T027–T030 and T048, T035–T036, T039–T040) are written
  FIRST and must fail before their implementation.

## Parallel Opportunities

- Setup: T002 and T003 together. Foundational: T004–T008 together (five test files), then T009 → T010 → T046.
- US1: T011–T014 and T047 together; then T015, T016, T017 in parallel (different files), T018 and T019 in
  parallel, T020 after T015 and T018, T021–T022 after T017.
- US3: T027–T030 and T048 together. US4: T035–T036 together. US5: T039–T040 together. Polish: T042–T043 together.
- After Foundational, US1 and the US4 adapter (T035, T037) can proceed in parallel; US3's store and handler (T028,
  T031, T032) can start alongside US1.

## Implementation Strategy

1. Setup + Foundational (T001–T010, T046) → the emission API, the JSON stream, the settings and the corrected
   provenance source exist.
2. US1 + US2 (T011–T026, T047) → **MVP**: every run step is a clean JSON line. Stop & validate (`quickstart.md`
   US1/US2).
3. US3 (kept lines, endpoint, viewer, T048) and US4 (tracing) as independent P2 increments.
4. US5 (resilience and cap) once the sink and the exporter exist, then Polish: e2e, docs, quality gate,
   traceability.

## Notes

- Tests cite the feature per the project rule (`010/FR-###` scoped token or `FEATURE = "010"`); any untraced id is
  justified in `specs/010-structured-logging/traceability.md`.
- No new runtime dependency (Principle X): `logging`, `json`, `contextvars`, `time`, `traceback`, `threading` are
  stdlib; the tracing packages are the optional `otel` extra (and the dev group for the suite) — justified in
  `plan.md`.
- Secrets never leave the vault: the catalogue is the allow-list; the connection-test line loses the URL and the
  display name; exceptions log as class + frames; the redaction test counts the known strings on every surface.
- Tracing is inert by default: the no-op adapter imports nothing; the provider is private and the framework's own
  telemetry is off; one warning per cause; shutdown bounded to 5 s by Kestrel's own join.

## Analysis remediation (`/speckit-analyze`, 2026-11-13, before implementation)

No CRITICAL or HIGH finding; coverage 100% (17 FR + 9 SC). The MEDIUM findings were fixed in the design documents
(no requirement in `spec.md` changed):

- C1 — the catalogue (the allow-list) gained the events the tasks name but it lacked (`memory.retrieval_failed`,
  `memory.flag_failed`, `recommendation.unavailable`), the value fields of `message` events (`path`, `count`,
  `stored_version`, `expected_version`), and `exc_type`/`stack`/`message` on any record (contracts/log-records.md).
- C2 — `emit(..., message=<constant text>)` keeps a converted line's constant text as the record's message, so
  the plain-message `caplog` assertions D10 relies on keep working; values stay fields (research D1/D10, T010).
- C3 — a direct `write_back` call outside a scope binds the run as a reference so `memory.writeback` names it
  (T020).
- C4 — `create_app(..., span_exporter=None)` hands the in-process collector to an app; conftest resets the
  module-level state between tests (research D8, T003, T038).
- C5 — kept lines go through the store on the record's own run context, not a store fixed at install time
  (research D3, data-model, plan, T009, T032).
- C6 — experiment tests with real clients use the engine's own factories over `model_transport`; the injected-
  double factories accept the pin keywords (research D10, T003, T017).
- C7 — the clients accept `(text, ref)` and still the feature-009 plain text (research D5, T017).

LOW findings fixed in the same pass: C8 (`turn.judge_prompt` equals the provenance wherever it is recorded), C9
(a turn or run with no model request costs 0, null tokens), C10 (single-turn `run.start` caps), C11 (the
`log.truncated` marker carries the common fields), C12 ("once" = per configured logger/tracer, one per process
start), C13 (a failed model request carries the usage the provider reported, null when none — FR-003).

Found while writing T025's test: C14 — the catalogue named two category fields `reason` (`experiment.end`,
`tracing.unavailable`) while T025 asserts no field is called `reason` (the judge's free text must have no field);
renamed to `stopped_reason` (the stored column's name) and `cause`. `tracing.span_failed` and `log.format_failed`
were added for the span and formatting failures FR-015 names.
