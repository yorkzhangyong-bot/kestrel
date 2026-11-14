# Phase 0 Research: Structured Logging and Tracing (010)

All decisions respect Principle X (no new required dependency) and the clarifications recorded in `spec.md`
(kept lines in SQLite; the whole stream is JSON by default with a text setting; OTLP/HTTP export configured by the
standard variables; operational lines in scope; the tracing packages in the development group only), amended by
the spec review of 2026-11-13 (round 1: private tracer, run scope in the callers, kept = in-scope records,
provenance correction, SDK shutdown semantics, turn-line fields, explicit span parents, test realism).

Code facts this builds on (verified in the worktree):

- One logger, `kestrel` (children `kestrel.connection`), configured once in `create_app` by `_configure_logging`
  (`src/kestrel/api/main.py`) with a text `LOG_FORMAT` on a stderr `StreamHandler`. Existing lines: the attack-run
  line in `runs.py::_finish`, the adaptive-run line at the end of `attack/graph.py::run_adaptive`, the
  connection-test line in `connection/tester.py::_log` (today it prints the display name and the scheme/host/path
  of the URL — both must go, FR-009), the attacker's empty-content warning (`attack/attacker.py`), the write-back
  and hint-retrieval `log.exception` calls, the experiment-failed exception, and the start-up messages (key file,
  interrupted runs, experience-store seeding). Three start-up lines interpolate exception text today: the library
  load failure (`main.py` "could not be loaded … %s"), the experience-store unavailable line and the seeding
  failure (`describe_store_error(...)`); two more lines are named by the review: the key-mismatch error (a
  constant message) and the delete-target memory failure (`logger.exception` in the delete endpoint).
- Model calls are plain `httpx` POSTs through `retry.post_with_retry` (`RetryResult(response, tokens)`, tokens
  summed over attempts from `usage.total_tokens`); the attacker adds a second attempt on empty content, the judge
  adds one schema-correction attempt (`judge/client.py::_structured_call`).
- Target requests go through `connection/tester.py::run_test` for connection tests, single-turn runs and every
  adaptive turn; it already measures `duration_ms` and names the `step`/`status_code`.
- Prompt provenance: `prompt_registry.load_prompt(id)` returns `(text, "id@N")`; `attack/graph.py::run_adaptive`
  resolves the **active** attacker/judge versions once per run and records them on `run_turns`/`runs` **even when an
  experiment arm pins another version** (the pin reaches only the client text through `engine._prompt_overrides`,
  which returns texts, not references); `runs.py::execute_run` records **no judge provenance** for a single-turn
  run (`_finish` never passes `judge_prompt_id/version`). These are the feature-009 recording gaps FR-007 closes.
- Cost: `experiments/pricing.py::arm_cost(total_tokens, price_model, model_prices)` = tokens / 1000 × price, `None`
  when unpriced; `settings.model_prices` comes from `KESTREL_MODEL_PRICES`.
- Experiments: `engine._run_rep` calls `execute_run`/`execute_adaptive_run`, then links the run
  (`store.add_experiment_run`), then calls `write_back(...)` — the write-back follows the run; the API's `start_run`
  likewise calls the run function and then `write_back`. The engine knows `experiment.id` and `arm.label` before
  each run. The recommender runs at report time (`report/recommend.py::recommendations_for`, from
  `GET /api/targets/{id}/report`), often in a later process.
- Schema: `SCHEMA_VERSION = "7"`, additive `TargetStore._migrate` accepting prior versions `"1"`–`"6"`.
- **ChromaDB (1.5.9) and FastAPI (0.161.1) already depend on `opentelemetry-api`; ChromaDB also depends on
  `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-grpc` (all 1.45.1, in `uv.lock`). `import chromadb`
  loads 129 `opentelemetry.*` modules, including `opentelemetry.sdk.trace`. The OTLP/HTTP exporter
  (`opentelemetry-exporter-otlp-proto-http`, with `opentelemetry-exporter-http-transport`) is the only package the
  feature's extra actually adds to the environment.** `opentelemetry.sdk.trace.export.in_memory_span_exporter`
  is importable today.
- **FastAPI 0.161.1 has native OpenTelemetry**: `FastAPI(telemetry=...)` defaults to `{"tracing": True, "metrics":
  True, "logs": True, ...}` (`fastapi/applications.py`), and `fastapi/telemetry/_asgi.py` creates server and
  endpoint spans for every request as soon as a global tracer provider is configured. A global provider is also
  set-once per process.
- **opentelemetry-sdk 1.45.1 batch processor** (`opentelemetry/sdk/_shared_internal/__init__.py`):
  `export_timeout_millis` is stored but unused ("No way currently to pass timeout to export"); `force_flush()`
  ignores its timeout and exports the whole queue; `shutdown(timeout_millis=30000)` joins the worker for up to
  30 s; an export that raises is logged by the SDK, but an export that returns `SpanExportResult.FAILURE` is not.
- **LangGraph 1.2.17** runs a turn across several nodes; a value set in the ambient context inside one node is not
  visible to the next node, so span parents cannot ride on ambient context — only a shared object can carry them.

---

## D1 — Event emission: named fields through `logging`, never %-interpolation

- **Decision**: a small module `src/kestrel/events.py` is the only way feature code emits structured events:
  `emit(event: str, level=logging.INFO, **fields)` calls `logging.getLogger("kestrel").log(level, event,
  extra={"kestrel_event": event, "kestrel_fields": fields, "kestrel_keep": <in a live run scope>})`. Every value
  is a field; the record's message is the event name, or — when the emitter passes `message=` — that **constant**
  text (never a value, never interpolated), which is also carried as the `message` field; this keeps a converted
  pre-existing line readable by any other handler on the logger (a test's `caplog` keeps seeing "doesn't match",
  "interrupted", "back this file up"). The run context (D4) is merged into every record
  automatically. Convenience wrappers build the per-event field sets (`run_started`, `turn`, `model_request`,
  `target_request`, `connection_test`, `memory_retrieval`, `memory_writeback`, `run_ended`, …) so field names are
  defined once (contracts/log-records.md); the field catalogue is the allow-list — a field name outside it is
  dropped and counted once as a `log.unknown_field` warning.
- **Rationale**: the owner's roadmap entry ("log with `extra={...}` fields, never %-interpolation") and FR-006;
  stdlib only (Principle X); one choke point makes the FR-009 allow-list reviewable.
- **Alternatives**: `structlog` (a new dependency, rejected); f-string messages parsed later (lossy, rejected).

## D2 — One formatter for the whole `kestrel` stream: JSON by default, text by setting

- **Decision**: `src/kestrel/logging_setup.py` replaces `_configure_logging`: a `JsonFormatter` (stdlib `json`,
  `ensure_ascii=False`, `separators=(",", ":")`, one object per line, keys in a stable order: common fields first)
  and a `TextFormatter` that renders the same fields as `ts level event key=value …`. `KESTREL_LOG_FORMAT`
  (`json` default, `text`) selects one. "The stream" is the `kestrel` logger's output; uvicorn's own loggers are
  not touched and are not part of it. Records emitted without `kestrel_event` (the pre-existing free-text lines)
  become `{"event": "message", "message": "<formatted text>", …common fields}`. Exceptions attached to a record
  are rendered as `exc_type` (the class name) and `stack` (a list of `file:line in function` frames) — never the
  exception message and never local values, because an exception message may quote a URL or a provider error.
  The pre-existing lines are converted to events where they carry structured facts: the connection-test line
  becomes `connection.test` (target id/step/status/duration only); the attack-run and adaptive-run summary lines
  are replaced by `run.end`; the attacker's empty-content warning becomes `model.empty_content` with its counters
  as fields; and the three start-up lines that interpolate exception text become named events with `exc_type`
  and no message text — `library.unavailable` (`exc_type`), `experience.unavailable` (`exc_type`, `reason_kind` ∈
  `embedding_function_mismatch | model_download | other`, the categories `describe_store_error` already
  distinguishes) and `experience.seed_failed` (`exc_type`, `reason_kind`); the key-mismatch error line (a
  constant message with no exception) becomes `key.mismatch`, and the delete-target memory failure
  (`logger.exception(...)` in the delete endpoint) becomes `experience.delete_failed` (`exc_type`, `target_id`).
  The start-up lines that carry only paths and counts (key file, interrupted runs, seeded patterns) stay
  `message` events with their values as fields: a record's message is constant text and every value (a count, a
  path, an exception type, an id) travels as a field; no exception text is embedded (FR-006).
- **Rationale**: Clarification Q2; a mixed stream breaks log tools; the text format loses nothing (same fields);
  FR-006/FR-009 forbid exception message text anywhere.
- **Alternatives**: JSON only for new events (rejected in clarification); third-party JSON formatters (rejected,
  Principle X).

## D3 — Kept lines: a `run_log` table in the run's SQLite file (schema v8), in-scope records only, cap 1,000 + marker

- **Decision**: `SCHEMA_VERSION "7" → "8"` adds `run_log(id, run_id REFERENCES runs ON DELETE CASCADE, seq, ts,
  event, record TEXT)` with `UNIQUE(run_id, seq)`; `_migrate` accepts `"7"` as a prior version; the table comes
  from the schema script (`CREATE TABLE IF NOT EXISTS`), so a v7 database migrates without an ALTER. A
  `RunLogHandler(logging.Handler)` installed once on the `kestrel` logger keeps **exactly the records emitted inside
  a live run scope** (`kestrel_keep` true — set by the scope binder of D4, never by the reference binder): it
  serialises the record with the `JsonFormatter`, counts per run (`kept`, `dropped`, on the record's own run
  context, under the handler's lock), writes rows through **that run's** `store.add_log_line(...)` (the store
  `run_started` put on the context — never a store fixed at install time, so a process holding several stores
  cannot keep a line in another run's database) up to the cap of 1,000, drops the rest from the table (never from
  the stream),
  and on the scope's `run.end` record writes one final `log.truncated` row (`seq = kept + 1`, `kept`, `dropped`)
  when anything was dropped, then forgets the run's counters. A record that carries a run id but was emitted
  outside the scope (the recommender line at report time, D4) is ignored by the handler: it never touches `seq`,
  the marker or the counters, so `UNIQUE(run_id, seq)` can never collide across processes and a report generation
  leaves a run's kept log byte-identical. Its `handleError` override emits one `log.sink_failed` warning per error
  kind (deduplicated per process) and swallows the failure; that warning has no run id, so the handler never
  recurses on it.
- **Rationale**: Clarification Q1 and review finding 3; same file, same backup, cascade delete for free, no file
  lifecycle; the cap bounds storage for any turn cap an operator sets; the marker keeps the truncation honest
  (feature-002 honesty rule).
- **Alternatives**: a JSONL file per run (file lifecycle, a second store; rejected in clarification); keeping all
  lines unbounded (rejected: an operator-raised turn cap could grow a run's log without limit); keeping post-run
  records by re-reading the stored count (rejected: a second writer per run across processes, and the marker
  would no longer be last).

## D4 — Run scope: opened by the callers, a mutable object in a `ContextVar`, closed after the write-back

- **Decision**: `events.RunContext` (mutable dataclass: `run_id`, `target_id`, `mode`, `family`, `experiment_id`,
  `arm`, `turn`, `keep`, `started_at`, `turn_started_at`, per-turn and per-run token/cost accumulators,
  `judge_requests`, `memory_written`, `outcome` fields, plus the `run_span`/`turn_span` handles of D8) lives in a
  `contextvars.ContextVar`. Three binders:
  - `events.run_scope()` — opened by the **callers** of the run functions (`api/main.py::start_run` and
    `experiments/engine.py::_run_rep`) so that it encloses the run function **and** the write-back; on exit it
    emits `run.end` (with the outcome stashed by `run_finished`, `memory_written` from the write-back, duration and
    cost totals; `error` = the exception class name when one escaped) — but only if `run.start` was emitted, so a
    failed claim (`RunInProgress`) emits nothing. `kestrel_keep` is true inside it.
  - `events.run_started(ctx, run_id, target_id, mode, family, …)` — called by `execute_run` and `run_adaptive`
    right after `claim_run`; fills the identifiers and emits `run.start`. `events.run_finished(ctx, run)` stashes
    the finished `Run`'s outcome fields after `finish_run`. Both are **null-safe outside a scope**: the existing
    unit tests call `execute_run`/`run_adaptive` directly with no `run_scope()` open, and must keep passing
    (SC-005) — with no scope bound, `run_started` raises nothing, emits the `run.start` line with `run_id` null
    (no scope identifiers) and `kestrel_keep` false, so it reaches the stream only and is not kept; `run_finished`
    is a no-op; no `run.end` is emitted because no scope exits.
  - `events.bind_run_reference(run)` — a **non-emitting** binder for anything that logs about a run after its
    scope has closed (the recommender at report time; any future post-run emitter): it binds the run's
    identifiers so the line carries `run_id`/`target_id`/`mode`/`family`, emits neither `run.start` nor `run.end`,
    and sets `kestrel_keep` false so the line reaches the stream only (D3).
  The experiment engine binds `experiment_id`/`arm` around each `_run_rep` call (`events.bind_experiment(...)`),
  so every record of that run carries them even though the link row is written afterwards. Lines the engine
  emits outside a run (`experiment.start`, `experiment.cap`, `experiment.end`) carry `experiment_id` and no run
  id, so they reach the stream but are not kept. The graph's nodes set `ctx.turn` by mutating the shared object,
  not by re-setting the variable: LangGraph runs nodes whose copied contexts would not see a re-set, but they
  share the object (the same mechanism carries the span handles of D8).
- **Rationale**: review finding 2 (the write-back must be inside the scope and `run.end` must be last) and finding
  3 (post-scope lines must not touch the kept log); the owner's roadmap entry (run id on every record; experiment
  id and arm on every record of an experiment's run) and FR-005; `contextvars` is stdlib and propagates into
  `asyncio` tasks.
- **Alternatives**: binding inside the run functions (the write-back would fall outside the scope; rejected);
  threading an explicit `log` argument through every call (invasive); a module-level global (wrong under
  concurrent experiment runs in the background task).

## D5 — Timing and attempt counting at the client boundary; tokens as reported; one source for the prompt reference

- **Decision**: `retry.post_with_retry` returns `RetryResult(response, tokens, attempts, prompt_tokens,
  completion_tokens)` — attempts counted, prompt/completion/total tokens summed over attempts, `None` when no
  attempt reported usage (`tokens` keeps its current int semantics for the budget). `AttackerClient.next_message`
  and `JudgeClient.judge`/`recommend` time the whole logical call (`time.perf_counter`, retries and the
  empty-content/schema second attempts included), sum attempts across their own loops, and emit one
  `model.request` through `events.model_request(kind, model, prompt_ref, …)` in a `finally`, with `status` = the
  last HTTP status (or `None`) and `error` = the exception class name on failure — never the message. The clients
  also expose the prompt reference they used (`AttackerClient.prompt_ref(family)`, `JudgeClient.judge_prompt_ref`,
  `JudgeClient.recommender_prompt_ref`): `load_prompt(...)[1]` for the active version, or the pinned
  `"<id>@<version>"` an arm supplied (`system_overrides` also accepts `{family: (text, ref)}`, `system_prompt` also
  accepts `(text, ref)`, and `engine._prompt_overrides` returns the references alongside the texts; a plain text —
  the feature-009 form, still used by `tests/integration/test_prompt_arm.py` — keeps working with an unknown
  reference, `None`, rather than being mislabelled as the active version). That reference is the
  **single source** both for the lines and for the provenance written to `runs`/`run_turns` (D15). When a client
  lacks the accessor — the `StubJudge`/`StubAttacker` doubles of `tests/support.py` — the run functions fall back
  to the registry's active reference (`load_prompt(...)[1]`), so the existing tests keep passing (SC-005).
- **Rationale**: FR-003 and the owner's note that a retry must not hide spend; the clients are the single place
  that knows model, prompt reference, attempts and usage; one source is what makes FR-007's equality hold.
- **Alternatives**: one line per HTTP attempt (needs the retry helper to know prompt/model; noisier; rejected);
  timing in the graph nodes (would miss single-turn judge calls and recommender calls).

## D6 — Cost: reuse the price table and arithmetic; null with a reason, never zero

- **Decision**: `events.request_cost(total_tokens, model, prices) -> (cost | None, note | None)`: `None, "no
  usage reported by the provider"` when `total_tokens is None`; `None, "unavailable (no configured price for
  <model>)"` (the feature-007 wording) when the slug has no price; else `pricing.arm_cost(...)`. The price table is
  handed to `events.configure(prices=settings.model_prices)` in `create_app` (tests call it directly). The run
  context accumulates the run total and a `cost_missing` reason, and a per-turn total that `turn` lines carry
  (D16); `run.end` carries `cost_usd` or `null` + `cost_note`.
- **Rationale**: FR-008; one arithmetic for experiments and logs; "null with a reason, never 0" is the project's
  honesty rule for unavailable numbers.
- **Alternatives**: a live billing lookup (rejected in feature 007); separate input/output prices (the table is
  blended per 1,000 tokens; unchanged).

## D7 — Target requests and connection tests: one instrumentation point in the tester

- **Decision**: `connection/tester.py::run_test` (and `refused`) emits `target.request` when a run context is
  bound (with the turn from the context) and `connection.test` otherwise; fields are `latency_ms`, `status`,
  `step`, `ok`, `reply_chars`, `reply_truncated`, plus `target_id` for a saved target (a new optional `target_id`
  argument the API passes from the form's `target_id`). The `display_name` argument stays accepted but is no
  longer logged; the URL is no longer logged in any form (the `_loggable_url` helper is retired from logging).
- **Rationale**: FR-004 and FR-009 (latency and status only); one call site covers all three callers.
- **Alternatives**: logging from the callers (three places, easy to drift).

## D8 — Tracing adapter: private provider, lazy, optional, no-op by default; OTLP/HTTP; bounded shutdown; one warning per cause

- **Decision**: `src/kestrel/tracing.py` exposes `configure_tracing(settings, *, exporter=None) -> Tracing`,
  `current()`, `run_span(ctx)`, `span(name, parent, **attrs)`, `set_attributes(span, **attrs)` and
  `shutdown(timeout_s=5.0)`. `create_app(..., span_exporter=None)` passes its `span_exporter` through as
  `exporter` — a test seam like the app's existing `transport`/`judge`/`experience` injections, so an
  integration test hands the in-process span collector to an app built through the API. The module has **no module-level import** of any `opentelemetry` package. With
  `settings.tracing` off it returns the no-op implementation without importing anything from the tracing
  packages. With it on, it imports `opentelemetry.sdk.trace`, `opentelemetry.sdk.trace.export` and
  `opentelemetry.context` inside the function, and `opentelemetry.exporter.otlp.proto.http.trace_exporter` **only
  when no `exporter` was injected** (tests inject the in-memory exporter and never touch the OTLP module); an
  `ImportError` emits exactly one `tracing.unavailable` warning (`extra="kestrel[otel]"`) and returns the no-op.
  Otherwise it builds a **private** `TracerProvider(resource=Resource.create({"service.name":
  os.environ.get("OTEL_SERVICE_NAME", "kestrel")}))` that is **never** installed with `trace.set_tracer_provider`
  (so FastAPI's native telemetry and ChromaDB's own tracing never see it, and `configure_tracing` can be called
  again in tests), with a `BatchSpanProcessor(_GuardedExporter(exporter or OTLPSpanExporter()))`. The exporter is
  constructed without arguments so it reads every standard `OTEL_EXPORTER_OTLP_*` variable itself (endpoint,
  headers, certificates, **timeout** — Kestrel overrides none of them), defaulting to the protocol's standard local
  address. `_GuardedExporter` wraps `export()`: an exception or a `SpanExportResult.FAILURE` result is turned into
  exactly one Kestrel `tracing.export_failed` warning per process (deduplicated) and reported upward as `FAILURE`,
  so the SDK never raises or logs on its own; the `opentelemetry.*` loggers get `propagate = False` and a bridge
  handler so no plain-text line and no repeated warning ever reaches the JSON stream. **The app is created with the
  framework's telemetry off**: `FastAPI(..., telemetry={"tracing": False, "metrics": False, "logs": False})`, so
  no request span exists and a run started by `POST /api/runs` or by an experiment's background task cannot be
  nested under anything. The root span is started from an **empty** context (`tracer.start_span("kestrel.run",
  context=Context())`), so it has no parent whatever the ambient context holds; `run_started` opens it when the run
  scope starts and the scope's exit ends it after the caller's write-back (so `kestrel.memory_written` is set on
  it before it ends); `RunContext.run_span` and
  `RunContext.turn_span` hold the handles, and every child span is opened with an **explicit** `parent=` argument
  (`span(name, parent=ctx.turn_span or ctx.run_span, ...)`) — ambient context cannot carry a parent across LangGraph
  nodes (code facts). One span tree for both modes: `kestrel.run` → `kestrel.turn` → `kestrel.model_request` /
  `kestrel.target_request`; a single-turn run has one `kestrel.turn` (turn 1) whose children are the target request
  and, when a judge is configured, the judge request. Shutdown: the FastAPI `lifespan` exit calls
  `shutdown(5.0)`, which runs `provider.shutdown()` **in a daemon thread joined for at most 5 seconds** — the SDK's
  own `force_flush` ignores its timeout and its `shutdown` can wait 30 s (code facts), so the bound must be
  Kestrel's; whatever is still undelivered after the join is abandoned with the process. Attributes are scalars
  only and come from the same field sets as the lines; model-request spans also set `gen_ai.request.model`,
  `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` from the GenAI semantic conventions where the value
  exists. No propagator is installed and nothing injects headers into target requests — a test asserts that no
  `traceparent`, `tracestate` or `baggage` header reaches the stub target. The recommender is not traced.
- **Rationale**: Clarification Q3 and the owner's additions (standard variables, service name `kestrel`, bounded
  flush, exactly one warning, never fail/block/change a run); review findings 1 (FastAPI native OTel, global
  provider), 5 (SDK flush/shutdown semantics, unlogged FAILURE, timeout override), 7 (explicit parents, one
  single-turn tree) and 13 (MUST NOT propagate, tested); the HTTP exporter is the only genuinely new package.
- **Alternatives**: the global provider (would trace every API request and nest runs under request or experiment
  spans; rejected); the gRPC exporter already present through ChromaDB (relies on a transitive dependency and was
  not the clarified choice); a console exporter (no collector; rejected in clarification); `httpx`/FastAPI
  instrumentors (more packages, and they would add trace headers to target requests — rejected); relying on the
  SDK's `force_flush(timeout)` (ignored by the SDK — rejected).

## D9 — Verification: real adapter in CI through the development group; missing-package path by blocking the import; real exporter against a closed port

- **Decision**: `pyproject.toml` gains `[project.optional-dependencies] otel = ["opentelemetry-sdk>=1.45",
  "opentelemetry-exporter-otlp-proto-http>=1.45"]` and the `dev` group lists the same two packages, so `uv sync`
  (CI's `uv sync`) installs them and the suite drives the real adapter with the SDK's `InMemorySpanExporter`
  (`configure_tracing(settings, exporter=InMemorySpanExporter())`). The "flag on, package missing" path is tested
  by placing `None` in `sys.modules` for `opentelemetry.exporter.otlp.proto.http.trace_exporter` (which makes the
  lazy import raise `ImportError`) and asserting one `tracing.unavailable` warning and an unchanged run; the same
  blocked import with the flag off must produce neither error nor warning, and a static check asserts
  `kestrel/tracing.py` has no module-level `opentelemetry` import (FR-014). The unreachable-collector path uses the
  **real OTLP/HTTP exporter** pointed at a closed local port (`OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:<free
  port>`, a short `OTEL_EXPORTER_OTLP_TIMEOUT`): the run's outcome is unchanged, exactly one `tracing.export_failed`
  warning is logged, and `shutdown(5.0)` returns within the bound; a stub exporter that returns `FAILURE` and one
  that raises cover the wrapper's two branches. SC-007 ("works without the extra") is measured as "the offline
  suite passes once with the exporter import blocked", since the development environment always has the packages:
  a `tests/conftest.py` switch — the environment variable `KESTREL_TEST_BLOCK_OTLP=1` — places `None` in
  `sys.modules` for `opentelemetry.exporter.otlp.proto.http.trace_exporter` at session start (so any import of
  the OTLP/HTTP exporter raises `ImportError`) and skips the tests that need the real exporter (the closed-port
  case); every other test runs unchanged because `configure_tracing` imports the exporter module only when no
  exporter is injected. The quality gate (T044) runs the offline suite once in that mode and records the result.
- **Rationale**: Clarification Q5 and review findings 5 and 14; a runtime requirement is unchanged (Principle X),
  the development group is where test-only packages already live (`pytest-cov`, `mypy`, `mutmut`, `pip-audit`).
- **Alternatives**: `importorskip` only when installed (CI would never exercise the adapter; rejected in
  clarification); an exporter stub only (would not exercise the SDK's real shutdown path; rejected in review).

## D10 — Test realism and the pre-existing tests that read the log text

- **Decision**: the tests that assert on `model.request` lines (US1's sequence tests, the experiment test, the
  redaction test) drive the **real** `AttackerClient` and `JudgeClient` over `httpx.MockTransport` (canned
  OpenAI-style JSON bodies with a `usage` object, no attack text), because the `StubJudge`/`StubAttacker` doubles in
  `tests/support.py` bypass the clients that emit those lines; the stubs remain for tests where only outcomes
  matter (resilience, cap). Because values are fields now, `caplog.text` shows only event names: every existing
  "secret never reaches the logs" assertion (`tests/integration/test_api_connection_tests.py`, `test_api_save.py`,
  `test_api_manage.py`, `test_experiment_secrets.py`) moves to the rendered JSON lines through the `json_log`
  fixture (the real `JsonFormatter` on a `StringIO` handler attached to the `kestrel` logger), so the counts stay
  meaningful; plain-message assertions (`"doesn't match"`, the interrupted-run and key-file messages) keep working
  on `caplog` because those records keep a constant `message` (D1). Tests change with the lines they read:
  `tests/unit/test_tester.py` (the `kestrel.connection` message no longer carries target/URL; assert on the
  record's fields), `tests/unit/test_attacker_client.py` (the empty-content warning's counters are fields),
  `tests/unit/test_secrets.py` (the key path is a field: `str(path) in caplog.text` becomes the `path` field of the
  JSON line) and `tests/integration/test_writeback.py` (the run id is the `run_id` field of the `memory.writeback`
  line, which a direct call outside a scope still carries by binding the run as a reference). No existing test is
  deleted or weakened (SC-005).
- **Experiments with real clients**: `api/main.py::_schedule_experiment` reuses an *injected* test double for every
  arm (`make_judge = lambda model: injected`), so a pinned arm never reaches a real client that way. The tests that
  need real clients inside an experiment (T013, T047) inject no judge/attacker double: settings carry the model
  keys, the app's `transport` is the `model_transport` that answers both the stub target and the model endpoints
  (routing by host), and the engine's own factories build real `JudgeClient`/`AttackerClient`s over it with the
  pinned `(text, ref)`. The injected-double factories accept and ignore the pin keywords, so a pinned arm with a
  double no longer fails on a `TypeError`.
- **Rationale**: review finding 9; tests must observe the real stream format and the real emitters (SC-001/SC-002).

## D11 — Settings

- **Decision**: `Settings.log_format: Literal["json", "text"] = "json"` from `KESTREL_LOG_FORMAT`, and
  `Settings.tracing: bool = False` from `KESTREL_TRACING` (`on`/`off`; any other value raises `SettingsError`, like
  `KESTREL_MODE`). Both are documented in `.env.example`. No new API field: the viewer needs none, and the stream
  format is an operator setting.
- **Alternatives**: `OTEL_SDK_DISABLED` as the flag (it would also affect ChromaDB's own tracing; rejected).

## D12 — The log endpoint and the viewer

- **Decision**: `GET /api/runs/{run_id}/log` → `RunLogOut {run_id, lines: list[object], kept, dropped,
  truncated}` where each line is the kept record parsed back to an object; 404 `not_found` as `GET /api/runs/{id}`;
  the app-wide token dependency applies. `ui/api_client.get_run_log(run_id)`; `ui/app.py::_render_finding` renders
  the "Log" expander **before** its early return for a send-failed run, so every opened run (including one whose
  send failed) has it, both right after a run and when a run is opened from the Runs tab: a `st.dataframe` of the
  columns time, event, turn, model, prompt, latency ms, tokens, cost (missing fields blank), a `st.code(...,
  language="json")` block with the raw lines, a caption with the dropped count when truncated, and the caption "No
  log lines were recorded for this run." when the list is empty.
- **Rationale**: FR-011/FR-012, review finding 8, and the project rule that the UI only calls the API.
- **Alternatives**: embedding the lines in `RunDetail` (would bloat every run read; rejected); a download button
  (out of scope).

## D13 — The retrieval line: emitted whenever retrieval runs; `warm` = at least one pattern retrieved

- **Decision**: `ExperienceStore.retrieve_patterns` keeps its signature; a sibling `retrieve_patterns_with_ids`
  returns `list[tuple[str, str]]` (ChromaDB returns `ids` with every query; ids are `pattern:lib:<prompt_id>` or
  `pattern:run:<run_id>`). The two hint providers (`api/main.py::start_run.hint_provider`,
  `experiments/engine.py::_hint_provider`) use it and emit `memory.retrieval` (`turn`, `warm`, `pattern_count`,
  `memory_count`, `pattern_ids`) **whenever they ask the store** — a warm run (`use_prior_experience` on) with the
  store available — with zero counts and an empty id list when nothing came back; `warm` is `pattern_count > 0`
  (at least one pattern retrieved), not the run's switch. A run with prior experience off, or one whose store is
  unavailable, asks for nothing and emits no retrieval line.
- **Rationale**: FR-016 asks for pattern ids; ids are identifiers, never text (FR-009); review finding 10 settled
  "always emitted when retrieval runs, zero counts on a cold store, warm = ≥ 1 pattern".

## D14 — What a kept record looks like on the wire

- **Decision**: the kept `record` column holds the exact JSON line (so the endpoint serves what the stream
  carried); `seq` is the per-run order; `ts` and `event` are copied into columns for ordering and filtering.
  Common fields are omitted when not applicable (no `turn` on `run.start`, no `experiment_id` outside an
  experiment); absent, not null, so consumers can test presence.
- **Rationale**: one representation for stream, table, endpoint and viewer (FR-006, FR-010, FR-011).

## D15 — Provenance records the version actually used (a feature-009 recording gap, in scope for FR-007)

- **Decision**: the provenance columns (`run_turns.attacker_prompt_id/version`, `run_turns.judge_prompt_id/
  version`, `runs.judge_prompt_id/version`) are written from the **same prompt reference the clients used** (D5):
  `run_adaptive` takes the references from the attacker and judge clients (`attacker.prompt_ref(family)`,
  `judge.judge_prompt_ref`, falling back to the registry's active reference when the client has no accessor —
  D5) instead of resolving the active version itself, so a pinned arm records the pinned version; `execute_run`
  passes the judge reference to `finish_run` so a single-turn verdict records its judge provenance. **Judge
  provenance is recorded only when a judge request was made**: an adaptive run with no judge configured records
  null judge provenance on `runs` and `run_turns` and its `run.start` carries no judge prompt reference; a
  canary-decided turn records null judge provenance and its turn line carries a null judge prompt reference;
  `runs.judge_prompt_*` is written from `ctx.judge_requests > 0`, not from the stored `judge_used` flag. The lines
  (`run.start`, `turn`, `model.request`) carry the same references, so FR-007's equality holds by construction
  wherever provenance is recorded (non-null). Nothing else about recording changes; pre-v8 rows are untouched.
- **Rationale**: review finding 4 — without this, lines and provenance disagree whenever a pin is not the active
  version (the `two_judge_versions` fixture of `tests/integration/test_prompt_arm.py` makes that case easy to
  test), and FR-007 could not hold. A recording correction, not a behaviour change (FR-017).
- **Alternatives**: weakening FR-007 to "the lines name the version sent" (rejected in review: the recorded
  provenance would stay wrong).

## D16 — Turn-line totals and `judge_used`

- **Decision**: the run context accumulates per turn the duration (from `turn_started_at`), the token totals
  (prompt/completion/total summed over the turn's model requests, `None` when none reported) and the cost (sum of
  priced requests, or the first reason), and the `turn` line carries them together with the attacker and judge
  model slugs and prompt references in play (absent where no such request can occur: no attacker fields on a
  library-seed turn, no judge fields when no judge is configured). `judge_used` on `run.end` is
  `ctx.judge_requests > 0` — at least one judge request was made — computed from the requests actually made, not
  from the stored `runs.judge_used` column (which feature 003 sets true on an adaptive run even when no judge is
  configured; that column is unchanged by this feature).
- **Rationale**: review findings 6 and 12; the requirement wants latency, tokens, cost, model slug and prompt
  versions on every turn line, and a flag that says "a judge was asked" must mean that.
