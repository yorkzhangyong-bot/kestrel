# Quickstart / Validation: Structured Logging and Tracing (010)

Proves US1–US5 end to end. Shapes and names: [data-model.md](data-model.md) and [contracts/](contracts/).
PowerShell first (Windows dev), bash where useful.

## Prerequisites

- Python 3.12 + uv. `uv sync` installs the development group, which includes the tracing packages the test suite
  needs (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`); a production install without tracing is
  `uv sync --no-dev`, and with it `uv sync --no-dev --extra otel`.
- The offline suite needs no keys. Only the end-to-end run needs `OPENROUTER_API_KEY` and the HS-code target
  running (project `CLAUDE.md` → "HS-code target").

## US1 — every step is a JSON line (offline)

```
uv run pytest tests/unit tests/integration -k "log_records or run_events or experiment_events"
```

Expected: a stub single-turn run (the real judge client answering through a mocked transport) yields
`run.start`, `target.request`, `model.request`(judge), `turn`, `memory.writeback`, `run.end` in that order, each
`turn` carrying its duration, token totals, cost, model slugs and prompt references; an adaptive run adds one
`turn` per turn, one attacker `model.request` per attacker call and one `memory.retrieval` per turn on which the
run asked the store (zero counts and `warm` false when nothing came back; no line on a run with prior experience
off); every line parses as JSON; experiment runs carry `experiment_id` and `arm` on every line, the write-back
line included; a report generation emits a recommender `model.request` with the finding's `run_id` on the stream
while the run's kept log stays unchanged. (SC-001, SC-008.)

Watch it live (local mode; the stream is the `kestrel` logger's output on stderr — uvicorn's own start-up and
access lines share stderr but are not part of it, hence the filter on `"event":`):

```powershell
$env:KESTREL_MODE = "local"
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000 2>&1 |
    Select-String '"event":"(run\.|turn|model\.request|target\.request)'
```

```bash
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000 2>&1 | grep '"event":"'
```

Then start a run from the screen or with `POST /api/runs`. Set `KESTREL_LOG_FORMAT=text` and restart to see the
same fields as `ts level event key=value …` (FR-006).

## US2 — nothing sensitive in the log (offline + e2e)

```
uv run pytest tests/unit tests/integration -k "log_redaction or connection_test_line"
```

Expected: with a target whose auth header value, URL and display name are known strings and a run whose attack
message and reply are known strings, the known strings appear zero times across the JSON stream, the in-process
spans, `GET /api/runs/{id}/log` and the rendered viewer; the connection-test line carries target id, step, status
and duration only. (SC-002.) The e2e (`uv run pytest -m e2e tests/e2e/test_us010_run_log.py`) repeats the count on
the real HS-code target: its key appears zero times in the API's log output and in the run's served lines.

## US3 — the log on the run page (API + UI)

```powershell
curl.exe http://127.0.0.1:8000/api/runs/1/log        # hosted mode: add -H "X-Kestrel-Token: $env:KESTREL_API_TOKEN"
```

Expected: `{"run_id": 1, "lines": [...], "kept": n, "dropped": 0, "truncated": false}` with `run.start` first,
`memory.writeback` before `run.end` and `run.end` last; an unknown id → 404 `not_found`. On the screen: open the
run (Runs tab → "Open a run") → expand **Log** → the table (time, event, turn, model, prompt, latency, tokens,
cost) and the raw JSON — a run whose send failed shows the expander under its failure message; a run from before
this feature shows "No log lines were recorded for this run." Generate the target's report (Report tab) and
request the log again: byte-identical — the recommender's line went to the stream only. (SC-003.) Offline:
`uv run pytest tests/integration -k "run_log_api or ui_run_log or run_log_after_report"`.

## US4 — trace a run, optionally

```
uv run pytest tests/unit tests/integration -k tracing
```

Expected: flag off → `configure_tracing` imports nothing from the tracing packages (and `kestrel/tracing.py` has no
module-level import of one) and no span exists; flag on with the SDK's in-memory exporter → one trace of its own
per run, whether started from the API or by a two-run experiment: a parentless root `kestrel.run` (with
`kestrel.run_id`) → `kestrel.turn` → `kestrel.model_request` / `kestrel.target_request`, and no other span; the stub
target received no `traceparent`, `tracestate` or `baggage` header; flag on with the exporter import blocked →
exactly one `tracing.unavailable` warning and an unchanged run; flag on with the real OTLP/HTTP exporter pointed
at a closed local port (or a stub that raises or returns a failure result) → an unchanged run, exactly one
`tracing.export_failed` warning, `shutdown(5.0)` returns within 5 s. (SC-004.)

Manually, against a local collector that accepts OTLP/HTTP (for example Jaeger with OTLP enabled, listening on
4318):

```powershell
$env:KESTREL_TRACING = "on"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"   # optional: this is the protocol's default
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000
```

Run an attack; the collector shows one trace whose root is `kestrel.run` under the service `kestrel`
(`OTEL_SERVICE_NAME` renames it) and no request span. Stop the collector and run again: the run completes, one
`tracing.export_failed` warning appears, and stopping the API returns within 5 seconds (Kestrel joins the SDK's
shutdown for at most 5 s; `OTEL_EXPORTER_OTLP_TIMEOUT` is honoured, not overridden).

## US5 — logging can never harm a run (offline)

```
uv run pytest tests/unit tests/integration -k "log_resilience or run_log_cap"
```

Expected: the same stub run with a working sink, a sink that raises on every write, and an exporter that fails
produces identical verdict, hard evidence, stopping condition, turns and tokens, with one `log.sink_failed` /
`tracing.export_failed` warning; a run that emits more than 1,000 run-scoped records keeps the first 1,000 plus one
`log.truncated` marker whose `dropped` equals the overflow, while the stream carries everything. (SC-005, SC-009.)

## Cost (offline)

```
uv run pytest tests/unit -k request_cost
```

Expected: with `KESTREL_MODEL_PRICES` naming the model, `cost_usd == total_tokens / 1000 * price` (within 1e-9);
without a price, or with no reported usage, `cost_usd` is null and `cost_note` names the reason; `run.end` sums
the priced requests or carries the first reason. (SC-006.)

## No new required dependency (SC-007)

`pyproject.toml` `[project] dependencies` is unchanged; the tracing packages appear only under
`[project.optional-dependencies] otel` and in the `dev` group. Because the development environment always has
them, SC-007 is measured as "the offline suite passes once with the exporter package import blocked": the
`tests/conftest.py` switch `KESTREL_TEST_BLOCK_OTLP=1` blocks the OTLP/HTTP exporter module import for the whole
session and skips the tests that need the real exporter (the closed-port case); everything else runs unchanged
because `configure_tracing` imports the exporter only when none is injected.

```powershell
$env:KESTREL_TEST_BLOCK_OTLP = "1"; uv run pytest tests/unit tests/integration; Remove-Item Env:KESTREL_TEST_BLOCK_OTLP
```

```bash
KESTREL_TEST_BLOCK_OTLP=1 uv run pytest tests/unit tests/integration
```

Expected: the suite passes with the real-exporter tests reported as skipped (the quality gate, T044, runs this
once and records the result). Manually, `uv sync --no-dev` followed by a run with the flag off works without the
packages, and with the flag on it logs the single `tracing.unavailable` warning.

## Quality gate (must stay green)

```
uvx ruff check src ui tests scripts
uv run mypy src                                   # advisory
uv run pytest tests/unit tests/integration        # coverage >= 85% on src
uv run python scripts/check_traceability.py       # every 010 id traced or justified
```

No existing test is deleted or weakened by this feature; the assertions that change do so only in the shape of
the log lines they read (secret counts over the rendered JSON lines, the connection-test and empty-content fields).
(SC-005.)
