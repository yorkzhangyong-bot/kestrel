# Contract: optional OpenTelemetry tracing (one trace per run)

Module `src/kestrel/tracing.py`. Off by default; nothing changes for a user who never sets the flag.

## Turning it on

| Setting | Meaning |
|---------|---------|
| `KESTREL_TRACING=on` | enable tracing (`off` is the default; any other value is a settings error) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` (and the other standard `OTEL_EXPORTER_OTLP_*` variables: `_TRACES_ENDPOINT`, `_HEADERS`, `_CERTIFICATE`, `_TIMEOUT`, …) | read by the exporter itself; Kestrel overrides none of them; unset means the protocol's standard local address |
| `OTEL_SERVICE_NAME` | the service name on every span; `kestrel` when unset |

Installation: the tracing packages are the optional extra `kestrel[otel]` = `opentelemetry-sdk` +
`opentelemetry-exporter-otlp-proto-http` (`pyproject.toml`, `[project.optional-dependencies]`). They are not a
runtime requirement: without the extra every other feature works. The development group also lists them so the
test suite drives the real adapter.

## Behaviour matrix (FR-013, FR-014, FR-015)

| Flag | Packages | Collector | Result |
|------|----------|-----------|--------|
| off | any | any | `configure_tracing` returns the no-op tracer **without importing** anything from the tracing packages (and `kestrel/tracing.py` has no module-level import of one); no span anywhere |
| on | present | reachable | one trace per run, delivered in batches by the SDK's background processor; spans never block the run |
| on | absent | — | exactly one `tracing.unavailable` warning at start-up (`cause: package_missing`, `extra: kestrel[otel]`); runs proceed exactly as with the flag off |
| on | present | unreachable, or refusing the spans | runs proceed unchanged; exactly one `tracing.export_failed` warning per process (`error`: the exception's class name, or `failure_result`); spans are dropped; shutdown waits at most 5 s |

The "exactly one warning" rule covers both failure shapes and the exporter's own logging: Kestrel wraps the
exporter so an exception **and** a failure result from `export()` each become the single Kestrel warning (the SDK
itself never logs a failure result), and the `opentelemetry.*` loggers do not propagate to the stream (a bridge
handler drops the rest), so no plain-text line and no repeated warning ever reaches the JSON stream.

## Private tracer — nothing but Kestrel's spans

- The tracer provider is **private** to Kestrel: it is never installed as the global provider
  (`trace.set_tracer_provider` is never called). The web framework's built-in telemetry is created **off**
  (`FastAPI(..., telemetry={"tracing": False, "metrics": False, "logs": False})`), so no request span exists.
- The run's root span is started from an **empty context**, so it has no parent whatever the ambient context
  holds: a run started by `POST /api/runs` and a run started by an experiment's background task both yield a trace
  of their own; an experiment of two runs yields two traces.
- Child spans are opened with an **explicit parent** held on the run context (`run_span`, `turn_span`), never
  through ambient context — a turn spans several graph nodes and a value set in one node is not visible to the
  next.
- No propagator is installed and nothing injects headers into target requests: a request sent to the target MUST
  NOT carry `traceparent`, `tracestate` or `baggage` (tested).

## Span tree (one trace per run; one tree for both modes)

```text
kestrel.run                       (root, no parent; opened by run_started, ended at the run scope's exit after the write-back;
                                   kestrel.run_id, …run.start fields; run.end fields incl. kestrel.memory_written set before it ends)
├── kestrel.turn [turn=1]         (turn fields: duration, token totals, cost, model slugs, prompt refs, lengths, verdict)
│   ├── kestrel.target_request    (latency_ms, status, step, reply_chars, reply_truncated)
│   └── kestrel.model_request     (kind=judge, model, prompt, latency_ms, status, attempts, tokens, cost, verdict, hard_evidence)
├── kestrel.turn [turn=2]
│   ├── kestrel.model_request     (kind=attacker, …, message_chars)
│   ├── kestrel.target_request
│   └── kestrel.model_request     (kind=judge)
└── …
```

A single-turn run has exactly one `kestrel.turn` (turn 1) whose children are the target request and, when the
judge is configured and no canary matched, the judge request — the judge span's parent is the turn span in both
modes. Attribute names and the full list are in [data-model.md](../data-model.md#trace-fr-013--span-tree-and-attributes).
Model-request spans also carry `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
(GenAI semantic conventions) when the value is known. Attributes are scalars only and come from the same field
sets as the log lines, so the FR-009 deny-list is enforced once for both.

Not traced: the recommender (report time, outside a run), connection tests, experiment-level events, API request
handling.

## Shutdown

`shutdown(timeout_s=5.0)` runs `provider.shutdown()` **in a daemon thread joined for at most `timeout_s`**: the
SDK's own `force_flush` ignores its timeout and exports the whole queue, and its `shutdown` can wait up to 30 s
for the worker, so the bound is Kestrel's; whatever is still undelivered after the join is abandoned with the
process. The FastAPI app's `lifespan` calls it on exit. It never raises.

## Programmatic surface (internal)

```python
def configure_tracing(settings: Settings, *, exporter: object | None = None) -> Tracing: ...  # called by create_app
def current() -> Tracing: ...                       # the configured tracer, or the no-op
class Tracing(Protocol):
    enabled: bool
    def run_span(self, ctx: RunContext) -> ContextManager[Span]: ...              # root, from an empty context; entered by run_started, exited at the run scope's exit
    def span(self, name: str, *, parent: Span, **attributes) -> ContextManager[Span]: ...  # explicit parent
    def set_attributes(self, span: Span, **attributes) -> None: ...
    def shutdown(self, timeout_s: float = 5.0) -> None: ...   # provider.shutdown() in a daemon thread, joined ≤ timeout_s
```

`exporter` lets tests inject the SDK's `InMemorySpanExporter` or a stub — the OTLP/HTTP exporter module is
imported only when no exporter is injected; production uses the OTLP/HTTP exporter constructed without arguments
(so the standard variables, including the timeout, apply), wrapped by Kestrel's guard. The test suite's
`KESTREL_TEST_BLOCK_OTLP=1` switch blocks that module's import for a whole session and skips the tests that need
the real exporter, which is how SC-007 ("works without the extra") is measured.

## Verification (D9)

- Span tree and attributes: `configure_tracing(settings_with_tracing_on, exporter=InMemorySpanExporter())`, run a
  stub-target run through the API and two runs through an experiment, read `exporter.get_finished_spans()`: only
  `kestrel.*` spans; per run exactly one parentless `kestrel.run` with `kestrel.run_id`, one `kestrel.turn` per
  turn, one `kestrel.model_request` per model request, one `kestrel.target_request` per send, all sharing that
  run's trace id; the two experiment runs have two trace ids.
- No propagation: the stub target's recorded requests carry no `traceparent`, `tracestate` or `baggage` header.
- Packages missing: `sys.modules["opentelemetry.exporter.otlp.proto.http.trace_exporter"] = None` (import raises)
  → one `tracing.unavailable` warning, `current().enabled is False`, the run's outcome unchanged.
- Flag off: the same blocked import → no warning, no error (Kestrel's tracing code never imported it); a static
  check of `kestrel/tracing.py` finds no module-level `opentelemetry` import.
- Unreachable collector: the **real** OTLP/HTTP exporter with `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at a closed
  local port (and a short `OTEL_EXPORTER_OTLP_TIMEOUT`) → the run's outcome unchanged, exactly one
  `tracing.export_failed` warning, `shutdown(5.0)` returns within the bound; a stub exporter returning
  `SpanExportResult.FAILURE` and one raising cover the guard's two branches.
- Deny-list: the redaction test (US2) also collects spans in-process and asserts no attribute carries the known
  auth value, URL, display name, attack message or reply.
