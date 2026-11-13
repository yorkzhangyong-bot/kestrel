# Phase 1 Data Model: Structured Logging and Tracing (010)

Entities, the one schema change, settings, and the shapes the API and the tracer carry. The per-event field
catalogue of the log records is the stream contract, [contracts/log-records.md](contracts/log-records.md); this
file does not repeat it. All DB changes are **additive**: `SCHEMA_VERSION "7" → "8"`, one new table.

## Entity: Log record (one JSON line)

"The stream" is the output of the `kestrel` logger (and its children); the web server's own lines are not part of
it.

| Field group | Fields | Rule |
|-------------|--------|------|
| Common, every record | `ts` (ISO-8601 UTC, milliseconds, `Z`), `level` (`INFO`/`WARNING`/`ERROR`), `logger`, `event` | always present |
| Run scope | `run_id` (int), `target_id` (int), `mode` (`single_turn`/`adaptive`), `family` | present on every record emitted while a run context is bound — the live scope (D4) or a run reference |
| Turn scope | `turn` (int, 1-based) | present when the record is about a turn |
| Experiment scope | `experiment_id` (int), `arm` (`A`/`B`) | present on every record of a run executed by an experiment, and on the experiment's own records |
| Event fields | per event, see the contract | absent when not applicable; `null` only where the contract says a value exists but is unknown (unreported tokens, unpriced cost) |

Invariants: one JSON object per line (no embedded newlines; strings escaped), stable key order (common fields,
then run/turn/experiment scope, then event fields in catalogue order); every value is a named field (D1); no field
ever carries a value from the FR-009 deny-list — auth header values, API keys or tokens, the target URL, the target
display name, attack message text, reply text, judge reason or progress text, provider or exception message text.
Exceptions appear as `exc_type` (class name) and `stack` (frames `file:line in function`), never their message.

## Entity: RunContext (in-process, `src/kestrel/events.py`)

| Field | Type | Set by |
|-------|------|--------|
| `run_id`, `target_id`, `mode`, `family` | int, int, str, str | `run_started(...)` inside the run function right after `claim_run`; or `bind_run_reference(run)` for a post-scope emitter |
| `experiment_id`, `arm` | int \| None, str \| None | `bind_experiment(...)` by the experiment engine before the run starts; inherited by the scope |
| `keep` | bool | `True` inside `run_scope()`; `False` under `bind_run_reference` — copied onto every record as `kestrel_keep`, the handler's keep rule (D3) |
| `turn`, `turn_started_at` | int \| None, monotonic float | the run loop, by mutating the shared object (D4) |
| `started_at` | monotonic float | `run_started` — `run.end.duration_ms` is measured from it |
| `attacker_model`, `judge_model`, `attacker_prompt`, `judge_prompt` | str \| None | `run_started`, from the clients' references (D5/D15); copied onto `turn` lines where applicable |
| `turn_tokens` / `turn_cost`, `cost_usd`, `cost_missing` | per-turn and per-run accumulators | `events.model_request(...)`: sums of reported tokens and priced costs, or the first reason a request could not be priced |
| `judge_requests` | int | incremented by every judge `model.request`; `run.end.judge_used = judge_requests > 0` |
| `outcome` | the finished run's verdict, hard_evidence, stopping_condition, failure_step, turns_used, tokens_used, succeeded_turn | `run_finished(ctx, run)` after `finish_run` |
| `memory_written` | bool \| None | the write-back, inside the scope |
| `store` | the run's `TargetStore` | `run_started(store, …)` — the run's own database, where the `RunLogHandler` keeps the scope's records (FR-010) |
| `log_seq`, `log_kept`, `log_dropped` | int | the `RunLogHandler`, per kept record (D3): the per-run order and the cap counters live on the run's own context |
| `run_span`, `turn_span` | tracer span handles or None | D8: the root span (opened by `run_started`, ended at the scope's exit) and the current turn span; children are opened with an explicit parent |

Lifecycle (D4): the **caller** of a run function opens `run_scope()` (`api/main.py::start_run`,
`experiments/engine.py::_run_rep`) and the scope encloses the run function and the write-back; `run.start` is
emitted by `run_started` once the row is claimed; `run.end` is emitted by the scope's exit — after the write-back,
as the run's last line — carrying the outcome, `memory_written`, duration and cost totals (and `error` = the class
name when an exception escaped); a failed claim emits nothing. `bind_run_reference(run)` binds a run's identifiers
for a post-scope emitter (the recommender at report time) without emitting `run.start`/`run.end` and with `keep`
false. The context lives in a `contextvars.ContextVar` holding the mutable object, so nodes run in child tasks see
the same turn counter and span handles.

## Schema v8 — the `run_log` table (kept lines, FR-010)

```sql
-- Added in schema version 8 (feature 010): the structured log lines kept for a run, in emission order.
CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,                 -- 1-based emission order within the run's scope
    ts TEXT NOT NULL,                     -- copied from the record, for ordering and display
    event TEXT NOT NULL,                  -- copied from the record, for filtering
    record TEXT NOT NULL                  -- the exact JSON line that went to the stream
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_log_seq ON run_log (run_id, seq);
```

- **Migration**: `SCHEMA_VERSION = "8"`; `_migrate` accepts `"7"` among the prior versions; the table is created by
  the schema script, so a v7 database needs no ALTER. Rows created before v8 do not exist — a pre-feature run
  simply has no kept lines (the viewer's "no log lines were recorded" state).
- **What is kept**: exactly the records emitted inside the run's live scope (`kestrel_keep` true), from `run.start`
  to `run.end` inclusive — `memory.writeback` is inside it. A record with a run id emitted outside the scope (the
  recommender line at report time, bound by `bind_run_reference`) is ignored by the handler: never kept, never a
  `seq`, never a counter change, so a report generation leaves a run's kept log and its marker unchanged.
- **Cap**: `RUN_LOG_CAP = 1000` (a module constant, not a setting). The `RunLogHandler` keeps the first 1,000
  in-scope records of a run; on the scope's `run.end` it writes one `log.truncated` row (`seq = kept + 1`,
  `event = "log.truncated"`, record = the `run.end` record's common and run-scope fields with `event`
  `log.truncated`, `level` `WARNING`, `kept` and `dropped`, e.g. `{"ts": …, "level": "WARNING", "logger":
  "kestrel", "event": "log.truncated", "run_id": …, "target_id": …, "mode": …, "family": …, "kept": 1000,
  "dropped": n}`) when `n > 0`. Records the experiment engine emits outside a run (no `run_id`) are never kept.
- **Which database**: the handler is installed once per process (`configure_logging(settings)`, idempotent) and
  keeps each record through the store on **that record's own run context** (`RunContext.store`, set by
  `run_started(store, …)`), so a process holding several stores (the test suite builds one app per test; the
  engine can be driven directly) can never keep a line in another run's database. The per-run `seq`/`kept`/
  `dropped` counters live on the same context and die with it.
- **Store API** (`src/kestrel/store.py`): `add_log_line(run_id, *, seq, ts, event, record) -> None`,
  `list_log_lines(run_id) -> list[LogLine]` ordered by `seq`, `LogLine(seq, ts, event, record)` frozen dataclass.
  Deleting a target cascades to its runs and their lines (existing `ON DELETE CASCADE` chain).
- **Failure**: a write that raises is reported once per error kind as a `log.sink_failed` warning and dropped; the
  run is never affected (FR-015).

## Provenance columns (schema v7, feature 009) — recording corrected (D15, FR-007)

No new column. `run_turns.attacker_prompt_id/attacker_prompt_version`, `run_turns.judge_prompt_id/
judge_prompt_version` and `runs.judge_prompt_id/judge_prompt_version` are written from the prompt reference the
client actually used (`"<id>@<version>"` split on `@`): the pinned version for a pinned experiment arm, and the
judge reference on a single-turn run's verdict (today recorded as the active version, and not at all,
respectively). Judge provenance is recorded only when a judge request was made: an adaptive run with no judge
records null judge provenance (and its `run.start` has no `judge_prompt`); a canary-decided turn records null
judge provenance on `run_turns` (and its turn line's `judge_prompt` is null); `runs.judge_prompt_*` follows
`ctx.judge_requests > 0`. The log lines use the same reference, so wherever provenance is recorded (non-null)
`run.start.attacker_prompt`/`judge_prompt`, `turn.attacker_prompt`/`judge_prompt` and `model.request.prompt`
equal it.

## Settings (`src/kestrel/settings.py`)

| Field | Env | Values | Default |
|-------|-----|--------|---------|
| `log_format` | `KESTREL_LOG_FORMAT` | `json`, `text` | `json` |
| `tracing` | `KESTREL_TRACING` | `on`, `off` | `off` |

Any other value raises `SettingsError` (the `KESTREL_MODE` convention). The collector is configured by the standard
`OTEL_EXPORTER_OTLP_*` variables, read by the exporter itself and overridden by nothing in Kestrel (endpoint,
headers, certificates, timeout); `OTEL_SERVICE_NAME` overrides the default service name `kestrel`. No API field
exposes either setting.

## Cost estimate (FR-008)

```
request_cost(total_tokens, model, prices):
  total_tokens is None            -> (None, "no usage reported by the provider")
  model not in prices             -> (None, "unavailable (no configured price for <model>)")
  else                            -> (total_tokens / 1000 * prices[model], None)        # pricing.arm_cost
turn total:  sum of the turn's priced requests, or (None, first reason) if any was unpriced   # turn lines
run total:   sum of priced requests, or (None, first reason) if any request was unpriced       # run.end
no request:  a turn or run that made no model request costs 0 (nothing was spent); its token totals are null
```

`prices` is `settings.model_prices` (the feature-007 table, one blended price per 1,000 tokens per model slug),
handed to `events.configure(prices=...)` by `create_app`.

## Trace (FR-013) — span tree and attributes

A **private** tracer provider (never the global one; the web framework's telemetry is created off), one trace per
run, the root started from an empty context so it has no parent — opened by `run_started` when the run scope
starts and ended at the scope's exit, after the caller's write-back, so `kestrel.memory_written` can be set on it —
every child opened with an explicit parent held on `RunContext` (D8). One tree for both modes:

```text
kestrel.run (root, no parent)
└── kestrel.turn [turn = n]                 one per turn; a single-turn run has exactly one (turn 1)
    ├── kestrel.model_request (attacker)    adaptive turns ≥ 2 only
    ├── kestrel.target_request
    └── kestrel.model_request (judge)       when a judge is configured and no canary matched
```

| Span | Parent | Attributes (all scalar; `kestrel.` prefix) |
|------|--------|---------------------------------------------|
| `kestrel.run` | none | opened by `run_started`, ended at the run scope's exit (after the caller's write-back): `kestrel.run_id`, `kestrel.target_id`, `kestrel.mode`, `kestrel.family`, `kestrel.experiment_id`, `kestrel.arm`, `kestrel.attacker_model`, `kestrel.judge_model`, `kestrel.attacker_prompt`, `kestrel.judge_prompt`, `kestrel.turn_budget`, `kestrel.token_budget`, `kestrel.time_limit_s`; set at the scope's exit, before the span ends: `kestrel.verdict`, `kestrel.hard_evidence`, `kestrel.stopping_condition`, `kestrel.judge_used`, `kestrel.turns_used`, `kestrel.tokens_used`, `kestrel.memory_written`, `kestrel.cost_usd` |
| `kestrel.turn` | `kestrel.run` (explicit) | `kestrel.turn`, `kestrel.source`, `kestrel.duration_ms`, `kestrel.prompt_tokens`, `kestrel.completion_tokens`, `kestrel.total_tokens`, `kestrel.cost_usd`, `kestrel.cost_note`, `kestrel.attacker_model`, `kestrel.judge_model`, `kestrel.attacker_prompt`, `kestrel.judge_prompt` (omitted on the span when the turn line's value is null — a canary-decided turn), `kestrel.message_chars`, `kestrel.reply_chars`, `kestrel.canary_hit`, `kestrel.hard_evidence`, `kestrel.verdict` |
| `kestrel.model_request` | `kestrel.turn` (explicit) | `kestrel.kind`, `kestrel.model`, `kestrel.prompt`, `kestrel.latency_ms`, `kestrel.status`, `kestrel.error`, `kestrel.attempts`, `kestrel.total_tokens`, `kestrel.cost_usd`, `kestrel.verdict`, `kestrel.hard_evidence`; plus `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` when known |
| `kestrel.target_request` | `kestrel.turn` (explicit) | `kestrel.latency_ms`, `kestrel.status`, `kestrel.step`, `kestrel.reply_chars`, `kestrel.reply_truncated` |

No other span exists (no request spans, no experiment span); the recommender (report time), connection tests and
the experiment-level events are not traced. Resource: `service.name` = `OTEL_SERVICE_NAME` or `kestrel`. No span
attribute may carry a deny-list value (the same `events` field sets feed both lines and spans, so the allow-list is
enforced once). No `traceparent`, `tracestate` or `baggage` header is ever added to a request sent to the target.

## API shapes (`src/kestrel/api/schemas.py`)

```python
class RunLogOut(BaseModel):
    run_id: int
    lines: list[dict[str, Any]]   # the kept in-scope records, parsed, in seq order (the log.truncated marker last)
    kept: int                     # records kept (≤ RUN_LOG_CAP)
    dropped: int                  # records not kept because of the cap
    truncated: bool               # dropped > 0
```

`GET /api/runs/{run_id}/log` — see [contracts/api-run-log.md](contracts/api-run-log.md).

## UI client (`ui/api_client.py`)

`get_run_log(run_id) -> dict` (`GET /api/runs/{run_id}/log`); the screen renders it in the "Log" expander of every
opened run, a send-failed one included — see [contracts/ui-run-log.md](contracts/ui-run-log.md).
