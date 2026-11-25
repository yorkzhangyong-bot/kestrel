"""Structured events (feature 010): the one way Kestrel emits a log line, and the run scope that stamps it.

Every value is a named field, never interpolated into text (FR-006): `emit(event, **fields)` logs through the `kestrel`
logger with the event name — or a constant `message` — as the record's message and the fields in `extra`. The field
catalogue below is the allow-list (FR-009): a field outside it is dropped and reported once as `log.unknown_field`, and
no catalogued field carries an auth value, a URL, a target name, attack or reply text, a judge's reason or progress
note, or a provider or exception message — identifiers, counts, lengths, categories, model slugs, prompt versions,
timings, tokens and cost only (contracts/log-records.md).

The run scope (research D4) is a mutable `RunContext` held in a ContextVar. The code that starts a run opens it
(`run_scope()`) around the run function *and* its write-back; `run_started` fills it once the run row is claimed and
emits `run.start`; the scope's exit emits `run.end` as the run's last record. LangGraph nodes see the same object, so a
turn number or a span handle set in one node is visible in the next. Every helper is wrapped: a failure here is
reported once as a warning and never reaches a run (FR-015).
"""
from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from kestrel import tracing
from kestrel.experiments.pricing import arm_cost

log = logging.getLogger("kestrel")
connection_log = logging.getLogger("kestrel.connection")

NO_USAGE = "no usage reported by the provider"

# The scope fields, in their rendering order, and the fields any record may carry.
SCOPE_FIELDS = ("run_id", "target_id", "mode", "family", "turn", "experiment_id", "arm")
ANY_EVENT_FIELDS = ("message", "exc_type", "stack")

# The event catalogue: the allow-list of each event's own fields, in their rendering order (contracts/log-records.md).
CATALOGUE: dict[str, tuple[str, ...]] = {
    "run.start": ("prompt_id", "attacker_source", "attacker_model", "judge_model", "attacker_prompt", "judge_prompt",
                  "turn_budget", "token_budget", "time_limit_s", "use_prior_experience", "source_run_id",
                  "side_channel", "callback_listener", "override_planted", "callback_planted"),
    "turn": ("source", "duration_ms", "prompt_tokens", "completion_tokens", "total_tokens", "cost_usd", "cost_note",
             "attacker_model", "attacker_prompt", "judge_model", "judge_prompt", "message_chars", "reply_chars",
             "reply_truncated", "canary_hit", "hard_evidence", "judged", "verdict", "evidence_kinds",
             "evidence_count"),
    "model.request": ("kind", "model", "prompt", "latency_ms", "ok", "status", "error", "attempts", "prompt_tokens",
                      "completion_tokens", "total_tokens", "cost_usd", "cost_note", "verdict", "hard_evidence",
                      "message_chars"),
    "model.empty_content": ("attempt", "finish_reason", "completion_tokens", "reasoning_tokens", "total_tokens",
                            "reasoning_chars"),
    "target.request": ("latency_ms", "ok", "status", "step", "reply_chars", "reply_truncated"),
    "connection.test": ("latency_ms", "ok", "status", "step"),
    "memory.retrieval": ("warm", "pattern_count", "memory_count", "pattern_ids", "k", "distance_floor",
                         "dedupe_threshold", "candidate_count", "dropped_floor", "dropped_duplicate", "distances",
                         "query_messages"),
    "memory.retrieval_failed": (),
    "memory.writeback": ("written", "pattern_written", "error", "pattern_outcome", "pattern_id", "hit_count",
                         "pattern_distance"),
    "memory.flag_failed": (),
    "run.end": ("verdict", "hard_evidence", "stopping_condition", "failure_step", "judge_used", "turns_used",
                "tokens_used", "succeeded_turn", "memory_written", "duration_ms", "cost_usd", "cost_note", "error",
                "replay_outcome", "evidence_kinds", "evidence_count", "side_channel_status"),
    # Feature 014: a checkpointed row found still in_progress at start-up (the sweep's own classification), or a
    # checkpointed scope exiting on an exception within the same process (research D20, D21) - never confused for
    # each other by a reader; `error` only on the second source, the exception's own class, never its text.
    "run.interrupted": ("resumable", "error"),
    "run.resumed": ("from_turn", "from_step", "was_paused"),
    "run.paused": ("turn",),
    "run.decided": ("decision",),
    "run.stopped": ("was_paused", "reconciled", "trigger", "idle_hours"),
    "idle_stop.check_failed": ("run_id", "exc_type"),
    # Feature 013 (contracts/log-records-delta.md): counts, kinds, statuses and steps only - never a token, a
    # URL, a correlation id, an auth value, a tool-argument value, a state key or value, or an evidence detail.
    "evidence.check": ("checks", "evidence_kinds", "evidence_count", "side_channel_status", "callback_wait_ms",
                       "state_changed_keys"),
    "evidence.override_disarmed": (),        # `turn` is a scope field
    # Part 2 adds `evidence.side_channel_unavailable`, `callback.hit` and `callback.ignored` with the lines that
    # emit them; `callback.ignored`'s own field is named `reason_kind`, not `reason`, because the field name
    # `reason` is on the deny-list `tests/unit/test_events.py` enforces over this catalogue (a `reason` is free
    # text everywhere else in Kestrel). Recorded in contracts/log-records-delta.md.
    "experiment.start": ("families", "reps", "max_runs", "token_budget_total", "wall_clock_s", "arms"),
    "experiment.cap": ("cap", "completed_runs", "tokens_used", "elapsed_s"),
    "experiment.end": ("status", "stopped_reason", "completed_runs", "tokens_used", "duration_ms", "error"),
    "replay.batch.start": ("target_id", "replayable_count", "cap"),
    "replay.batch.end": ("target_id", "fixed_count", "still_vulnerable_count", "inconclusive_count", "duration_ms",
                         "complete", "stop_reason", "error"),
    "library.unavailable": (),
    "experience.unavailable": ("reason_kind", "stored_model", "expected_model", "stored_space", "expected_space"),
    "experience.seed_failed": ("reason_kind",),
    "key.mismatch": (),
    "experience.delete_failed": (),
    "recommendation.unavailable": ("error",),
    "log.truncated": ("kept", "dropped"),
    "log.sink_failed": ("error", "for_run"),
    "log.unknown_field": ("field", "for_event"),
    "log.format_failed": ("error", "for_event"),
    "tracing.unavailable": ("cause", "extra", "error"),
    "tracing.export_failed": ("error",),
    "tracing.span_failed": ("error",),
    "message": ("path", "count", "stored_version", "expected_version"),
}

_PRICES: Mapping[str, float] = {}
_WARNED: set[tuple[str, str]] = set()


# ---- cost (FR-008) ----


def request_cost(total_tokens: int | None, model: str, prices: Mapping[str, float]) -> tuple[float | None, str | None]:
    """The estimated cost of one model request: the feature-007 arithmetic (tokens / 1000 x price), or None with the
    reason it could not be estimated — never 0 for tokens nobody priced (FR-008)."""
    if total_tokens is None:
        return None, NO_USAGE
    cost = arm_cost(total_tokens, model, prices)
    if cost is None:
        return None, f"unavailable (no configured price for {model})"
    return cost, None


@dataclass
class Tokens:
    """Prompt, completion and total tokens summed over requests; None while no request reported that kind."""
    prompt: int | None = None
    completion: int | None = None
    total: int | None = None

    def add(self, prompt: int | None, completion: int | None, total: int | None) -> None:
        self.prompt, self.completion, self.total = (_plus(self.prompt, prompt), _plus(self.completion, completion),
                                                    _plus(self.total, total))

    def fields(self) -> dict[str, int | None]:
        return {"prompt_tokens": self.prompt, "completion_tokens": self.completion, "total_tokens": self.total}


@dataclass
class Cost:
    """A sum of request costs; once any request could not be priced, the sum is None with the first reason."""
    total: float = 0.0
    note: str | None = None

    def add(self, cost: float | None, note: str | None) -> None:
        if cost is None:
            self.note = self.note or note or NO_USAGE
        else:
            self.total += cost

    def value(self) -> tuple[float | None, str | None]:
        return (None, self.note) if self.note is not None else (self.total, None)


def _plus(a: int | None, b: int | None) -> int | None:
    if b is None:
        return a
    return b if a is None else a + b


# ---- the run context (research D4) ----


@dataclass(eq=False)
class RunContext:
    """One run's scope: its identifiers, what is in play, and the accumulators its lines report (data-model.md)."""
    keep: bool = False                     # True in a live run scope; False under a run reference
    started: bool = False                  # run.start was emitted
    run_id: int | None = None
    target_id: int | None = None
    mode: str | None = None
    family: str | None = None
    experiment_id: int | None = None
    arm: str | None = None
    turn: int | None = None
    store: Any = None                      # the run's own database: where its records are kept (FR-010)
    started_at: float = 0.0
    turn_started_at: float = 0.0
    attacker_model: str | None = None
    judge_model: str | None = None         # set only when a judge is configured
    attacker_prompt: str | None = None
    judge_prompt: str | None = None
    turn_tokens: Tokens = field(default_factory=Tokens)
    turn_cost: Cost = field(default_factory=Cost)
    run_cost: Cost = field(default_factory=Cost)
    turn_judge_prompt: str | None = None   # the reference of the judge request made on this turn
    judge_requests: int = 0
    turn_lines: int = 0
    memory_written: bool | None = None
    outcome: dict[str, Any] | None = None
    run_span: Any = None
    turn_span: Any = None
    log_kept: int = 0                      # the RunLogHandler's per-run counters (FR-010)
    log_dropped: int = 0
    # Feature 013: what this run's deterministic checks have found so far, and how its side channel fared - the
    # three fields `run.end` reports, accumulated by the per-turn `evidence.check` line.
    evidence_kinds: list[str] = field(default_factory=list)
    evidence_count: int = 0
    side_channel_status: str = "not_configured"
    # Feature 014 (research D21): whether this run is a live, checkpointed adaptive run at all (set once, when
    # the scope opens, never re-read from the store at exit) and whether the row was actually finished before
    # this scope closes - together, these decide whether the exit emits `run.end`, a kept `run.interrupted`, or
    # nothing (a clean pause).
    checkpointed: bool = False
    finished: bool = False


_RUN: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar("kestrel_run", default=None)
_EXPERIMENT: contextvars.ContextVar[tuple[int, str | None] | None] = contextvars.ContextVar("kestrel_experiment",
                                                                                           default=None)


def current() -> RunContext | None:
    return _RUN.get()


def _live() -> RunContext | None:
    """The run context of a live scope whose run.start was emitted, else None."""
    ctx = _RUN.get()
    return ctx if ctx is not None and ctx.keep and ctx.started else None


def in_run() -> bool:
    """True inside a live run scope (a target request is then a `target.request`, not a `connection.test`)."""
    return _live() is not None


@contextmanager
def run_scope(*, checkpointed: bool = False) -> Iterator[RunContext]:
    """Open a run's scope around the run function and its write-back (research D4). Its exit emits `run.end` — with
    the error's class when an exception escaped — but only if `run.start` was emitted: a failed claim emits nothing.

    `checkpointed` (feature 014, research D21, FR-053) marks this scope, from the moment it opens, as belonging to
    a live, checkpointed adaptive run — the original run-start path passes `checkpointed=True` the instant it
    claims such a row, before its first invocation, never only a later, reopened scope. This is what the exit
    branches on (`_scope_exit`), never a fresh store read."""
    experiment_id, arm = _EXPERIMENT.get() or (None, None)
    ctx = RunContext(keep=True, experiment_id=experiment_id, arm=arm, checkpointed=checkpointed)
    token = _RUN.set(ctx)
    error: BaseException | None = None
    try:
        yield ctx
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            if ctx.started:
                _scope_exit(ctx, error)
        finally:
            _RUN.reset(token)


@contextmanager
def reopened_run_scope(store: Any, run: Any) -> Iterator[RunContext]:
    """Open a logging scope for a run that already has its own `run.start` from an earlier segment (feature 014,
    research D20, D21): a resume, a decision, Stop, the automatic idle-stop check, or the start-up sweep's own
    classification of a checkpointed row. Never emits a fresh `run.start`; binds the run exactly as `run_scope()`
    does, copying `checkpointed` straight from the `Run` it is given (never a second, independent store read);
    seeds the per-run kept-line counter from the highest one already stored, so a new line continues this run's
    own sequence rather than restarting it (FR-017). The scope's own exit follows the identical rule `run_scope()`
    already does (`_scope_exit`)."""
    ctx = RunContext(keep=True, run_id=run.id, target_id=run.target_id, mode=run.mode, family=run.family,
                     store=store, started=True, checkpointed=bool(getattr(run, "is_checkpointed", False)),
                     log_kept=store.highest_log_seq(run.id))
    token = _RUN.set(ctx)
    error: BaseException | None = None
    try:
        yield ctx
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            _scope_exit(ctx, error)
        finally:
            _RUN.reset(token)


def mark_finished(ctx: RunContext | None = None) -> None:
    """Tell this scope's own exit that the row was actually finished before it closes (feature 014, research
    D21): called by the one shared finishing function the moment it actually finishes a run's row. Defaults to
    the current scope; a caller that already holds the context it just opened may pass it directly."""
    target = ctx if ctx is not None else _RUN.get()
    if target is not None:
        target.finished = True


def _scope_exit(ctx: RunContext, error: BaseException | None) -> None:
    """Feature 014 (research D21): `run.end` keeps its existing, unconditional rule for every run and every exit,
    except one narrow case - a checkpointed adaptive run whose scope is ending while its row is still
    `in_progress`. That case emits a kept `run.interrupted` line instead, only when an exception escaped (a clean
    exit at a pause - `run.paused` already told that story - emits nothing in its place); every other combination
    (not checkpointed at all, or checkpointed and finished) emits `run.end` exactly as today."""
    if not ctx.checkpointed or ctx.finished:
        _run_end(ctx, error)
        return
    if error is not None:
        emit("run.interrupted", logging.ERROR, resumable=True, error=type(_root_cause(error)).__name__)


@contextmanager
def bind_experiment(experiment_id: int, arm: str | None = None) -> Iterator[None]:
    """Stamp the experiment id (and arm) on the experiment's own records and on every record of a run scope opened
    inside — bound before the run starts, though the run-experiment link row is written after it (FR-005)."""
    token = _EXPERIMENT.set((experiment_id, arm))
    try:
        yield
    finally:
        _EXPERIMENT.reset(token)


@contextmanager
def bind_run_reference(run: Any) -> Iterator[RunContext]:
    """Name a run on the lines emitted about it outside its scope (the recommender at report time; a direct
    write-back call): its identifiers, no run.start/run.end, never kept (FR-010). Inside that run's own live scope it
    changes nothing, so the run's lines stay its own."""
    ctx = _RUN.get()
    if ctx is not None and ctx.keep and ctx.started and ctx.run_id == run.id:
        yield ctx
        return
    reference = RunContext(keep=False, run_id=run.id, target_id=run.target_id, mode=run.mode, family=run.family)
    token = _RUN.set(reference)
    try:
        yield reference
    finally:
        _RUN.reset(token)


# ---- emission ----


def emit(event: str, level: int = logging.INFO, *, message: str | None = None, exc_info: Any = None,
         logger: logging.Logger | None = None, scoped: bool = True, **fields: Any) -> None:
    """Log one event. The scope's fields are merged in; a field outside the catalogue is dropped (and reported once);
    `message` is constant text, never a value. An attached exception renders as its class and frames only."""
    try:
        ctx = _RUN.get() if scoped else None
        record = _scope_fields(ctx) if scoped else {}
        if message is not None:
            record["message"] = message
        allowed = CATALOGUE.get(event, ())
        for name, value in fields.items():
            if name in allowed or name in SCOPE_FIELDS or name in ANY_EVENT_FIELDS:
                record[name] = value
            else:
                warn_once("log.unknown_field", name, field=name, for_event=event)
        keep = ctx is not None and ctx.keep and ctx.started
        (logger or log).log(level, message if message is not None else event, exc_info=exc_info,
                            extra={"kestrel_event": event, "kestrel_fields": record, "kestrel_keep": keep,
                                   "kestrel_ctx": ctx if keep else None})
    except Exception as error:  # the logger itself failed: logging never reaches a run (FR-015)
        _backstop(event, error)


def warn_once(event: str, key: str, **fields: Any) -> None:
    """One warning per cause (FR-015): the first `(event, key)` is logged, later ones are not. Unscoped, so a warning
    about the logging machinery is never kept in a run's log."""
    marker = (event, key)
    if marker in _WARNED:
        return
    _WARNED.add(marker)
    emit(event, logging.WARNING, scoped=False, **fields)


def clear_warnings() -> None:
    """Forget which warnings were given (a fresh logger or tracer: one warning per cause again)."""
    _WARNED.clear()


def configure(*, prices: Mapping[str, float]) -> None:
    """Set the per-model price table every model-request line is costed with (`settings.model_prices`)."""
    global _PRICES
    _PRICES = dict(prices)
    clear_warnings()


def reset() -> None:
    """No prices and no remembered warnings (between tests)."""
    configure(prices={})


def _scope_fields(ctx: RunContext | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ctx is not None:
        for name in ("run_id", "target_id", "mode", "family", "turn"):
            value = getattr(ctx, name)
            if value is not None:
                out[name] = value
        experiment_id, arm = ctx.experiment_id, ctx.arm
    else:
        experiment_id, arm = _EXPERIMENT.get() or (None, None)
    if experiment_id is not None:
        out["experiment_id"] = experiment_id
        if arm is not None:
            out["arm"] = arm
    return out


def _backstop(event: str, error: Exception) -> None:
    """The last line of defence: report a failure of the event machinery once, by hand, and swallow it."""
    marker = ("log.format_failed", f"{event}:{type(error).__name__}")
    if marker in _WARNED:
        return
    _WARNED.add(marker)
    try:
        log.warning("log.format_failed", extra={"kestrel_event": "log.format_failed", "kestrel_keep": False,
                                                "kestrel_ctx": None,
                                                "kestrel_fields": {"error": type(error).__name__,
                                                                   "for_event": event}})
    except Exception:
        pass


def _present(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop the fields that do not apply (None): absent, not null (contracts/log-records.md)."""
    return {name: value for name, value in fields.items() if value is not None}


def span_attributes(fields: Mapping[str, Any]) -> dict[str, Any]:
    """A line's fields as span attributes: `kestrel.`-prefixed scalars only, None omitted (contracts/tracing.md)."""
    return {f"kestrel.{name}": value for name, value in fields.items()
            if value is not None and isinstance(value, (str, bool, int, float))}


# ---- the run's lifecycle (FR-001, FR-002) ----


def run_started(store: Any, *, run_id: int, target_id: int, mode: str, family: str, prompt_id: str | None = None,
                attacker_source: str | None = None, attacker_model: str | None = None, judge_model: str | None = None,
                attacker_prompt: str | None = None, judge_prompt: str | None = None, turn_budget: int | None = None,
                token_budget: int | None = None, time_limit_s: int | None = None,
                use_prior_experience: bool | None = None, source_run_id: int | None = None,
                side_channel: str | None = None, callback_listener: str | None = None,
                override_planted: bool | None = None, callback_planted: bool | None = None) -> None:
    """Emit `run.start` right after the run row is claimed and bind the run on its scope. With no scope open (a
    direct call) the line still goes to the stream, with no run identifiers, and is not kept (SC-005).
    `source_run_id` (feature 012) names the run a replay re-tests; omitted entirely for a non-replay run.
    Feature 013 adds four more, each omitted unless the caller passes it (the real run starters always do):
    whether the target has a side channel, whether the listener is enabled at all (which `callback_planted`
    alone cannot distinguish from "this family carries no callback task"), and what this run planted."""
    try:
        fields = _present({"prompt_id": prompt_id, "attacker_source": attacker_source,
                           "attacker_model": attacker_model, "judge_model": judge_model,
                           "attacker_prompt": attacker_prompt, "judge_prompt": judge_prompt,
                           "turn_budget": turn_budget, "token_budget": token_budget, "time_limit_s": time_limit_s,
                           "use_prior_experience": use_prior_experience, "source_run_id": source_run_id,
                           "side_channel": side_channel, "callback_listener": callback_listener,
                           "override_planted": override_planted, "callback_planted": callback_planted})
        ctx = _RUN.get()
        if ctx is None or not ctx.keep or ctx.started:
            emit("run.start", **fields)
            return
        ctx.run_id, ctx.target_id, ctx.mode, ctx.family = run_id, target_id, mode, family
        ctx.store, ctx.started_at, ctx.started = store, time.monotonic(), True
        ctx.attacker_model, ctx.judge_model = attacker_model, judge_model
        ctx.attacker_prompt, ctx.judge_prompt = attacker_prompt, judge_prompt
        identifiers = {"run_id": run_id, "target_id": target_id, "mode": mode, "family": family,
                       "experiment_id": ctx.experiment_id, "arm": ctx.arm}
        try:   # a tracing failure never costs the line (FR-015)
            ctx.run_span = tracing.current().start_root("kestrel.run", **span_attributes({**identifiers, **fields}))
        except Exception as error:
            _backstop("run.start", error)
        emit("run.start", **fields)
    except Exception as error:
        _backstop("run.start", error)


def run_finished(run: Any) -> None:
    """Stash the finished run's outcome for `run.end` (emitted at the scope's exit, after the write-back).
    `replay_outcome` (feature 012) is None for every non-replay run, so `_run_end` omits it there entirely.
    Feature 014 (research D21): marks the scope's own `finished` flag too - this is the one place every existing
    finishing path already calls, exactly when a row has just been durably finished, so a checkpointed scope's
    own exit (`_scope_exit`) correctly emits `run.end` for a normal finish and never mistakes it for an exit still
    leaving the row `in_progress`."""
    try:
        ctx = _live()
        if ctx is None:
            return
        ctx.finished = True
        ctx.outcome = {"verdict": run.verdict, "hard_evidence": bool(run.hard_evidence),
                       "stopping_condition": run.stopping_condition, "failure_step": run.failure_step,
                       "turns_used": run.turns_used if run.turns_used is not None else ctx.turn_lines,
                       "tokens_used": run.tokens_used, "succeeded_turn": run.succeeded_turn,
                       "replay_outcome": getattr(run, "replay_outcome", None)}
        ctx.turn = None
        _end_turn_span(ctx)
    except Exception as error:
        _backstop("run.end", error)


def run_interrupted(*, resumable: bool, error: str | None = None) -> None:
    """The start-up sweep's own classification of a checkpointed row left `in_progress` by a previous process
    (feature 014, research D20): kept into that run's own log, not only the stream. `error` is never set from
    this source (nothing escaped; the row was simply found this way) - the scope-exit source sets it itself,
    directly in `_scope_exit`."""
    emit("run.interrupted", logging.ERROR if error is not None else logging.INFO, resumable=resumable,
         **_present({"error": error}))


def _root_cause(error: BaseException) -> BaseException:
    """`error`'s own class, unless it is a `kestrel.replay.ReplayFailed` wrapper (feature 012, review item 8):
    `execute_replay`/`run_replay_adaptive` always raise `ReplayFailed(run_id) from error`, so logging the
    wrapper's own class would always say "ReplayFailed" and never the real fault. Lazy import: avoids a
    module-load cycle (replay.py imports this module), the same convention replay.py and graph.py already use
    for each other (research D14)."""
    from kestrel.replay import ReplayFailed
    if isinstance(error, ReplayFailed) and error.__cause__ is not None:
        return error.__cause__
    return error


def _run_end(ctx: RunContext, error: BaseException | None) -> None:
    try:
        outcome = ctx.outcome or {}
        cost, note = ctx.run_cost.value()
        fields: dict[str, Any] = {
            "verdict": outcome.get("verdict"), "hard_evidence": bool(outcome.get("hard_evidence", False)),
            "stopping_condition": outcome.get("stopping_condition"), "failure_step": outcome.get("failure_step"),
            "judge_used": ctx.judge_requests > 0, "turns_used": outcome.get("turns_used", ctx.turn_lines),
            "tokens_used": outcome.get("tokens_used"), "succeeded_turn": outcome.get("succeeded_turn"),
            "memory_written": ctx.memory_written, "duration_ms": _ms_since(ctx.started_at), "cost_usd": cost,
            "evidence_kinds": list(ctx.evidence_kinds), "evidence_count": ctx.evidence_count,
            "side_channel_status": ctx.side_channel_status}
        if cost is None:
            fields["cost_note"] = note
        if error is not None:
            fields["error"] = type(_root_cause(error)).__name__
        # Feature 012: present only for a replay (never "replay_outcome": null for a normal run), unlike
        # verdict/succeeded_turn above, which are always present.
        fields.update(_present({"replay_outcome": outcome.get("replay_outcome")}))
        ctx.turn = None
        _end_turn_span(ctx)
        emit("run.end", logging.ERROR if error is not None else logging.INFO, **fields)
        tracing.current().end_span(ctx.run_span, **span_attributes(fields))
        ctx.run_span = None
    except Exception as exc:
        _backstop("run.end", exc)


def turn_started(turn: int) -> None:
    """A new turn: set its number on the shared context (every record of the turn carries it), start its clock and
    its totals, and open its span under the run's (FR-002, FR-013)."""
    try:
        ctx = _live()
        if ctx is None:
            return
        _end_turn_span(ctx)
        ctx.turn, ctx.turn_started_at = turn, time.monotonic()
        ctx.turn_tokens, ctx.turn_cost, ctx.turn_judge_prompt = Tokens(), Cost(), None
        ctx.turn_span = tracing.current().start_span("kestrel.turn", parent=ctx.run_span, **{"kestrel.turn": turn})
    except Exception as error:
        _backstop("turn", error)


def judge_requested(prompt_ref: str | None) -> None:
    """The run asked the judge on this turn: `run.end.judge_used` counts it, and the turn line names the reference."""
    ctx = _live()
    if ctx is not None:
        ctx.judge_requests += 1
        ctx.turn_judge_prompt = prompt_ref


def evidence_check(*, checks: Sequence[str], evidence_kinds: Sequence[str], evidence_count: int,
                   side_channel_status: str, callback_wait_ms: int | None = None,
                   state_changed_keys: int | None = None) -> None:
    """The per-turn line the deterministic checks emit, after they run and before `turn` (feature 013, FR-047):
    which checks ran, in order, what they found, how the side channel fared, the bounded callback wait actually
    spent and how many protected-state keys differed - a count only, never a key name or value (FR-033). The two
    part-2 fields are omitted when their check did not run. The run's own totals are accumulated here, so
    `run.end` reports the whole run without any caller threading them through."""
    try:
        ctx = _live()
        if ctx is not None:
            for kind in evidence_kinds:
                if kind not in ctx.evidence_kinds:
                    ctx.evidence_kinds.append(kind)
            ctx.evidence_count += evidence_count
            ctx.side_channel_status = side_channel_status
        emit("evidence.check", checks=list(checks), evidence_kinds=list(evidence_kinds),
             evidence_count=evidence_count, side_channel_status=side_channel_status,
             **_present({"callback_wait_ms": callback_wait_ms, "state_changed_keys": state_changed_keys}))
    except Exception as error:
        _backstop("evidence.check", error)


def turn_ended(*, turn: int, source: str, message_chars: int | None, reply_chars: int | None,
               reply_truncated: bool, canary_hit: bool, hard_evidence: bool, judged: bool, verdict: str | None,
               attacker_generated: bool, evidence_kinds: Sequence[str] = (), evidence_count: int = 0) -> None:
    """Emit the turn's one `turn` line with its duration, totals, cost and what was in play, and close its span
    (FR-002). Lengths and categories only: there is no parameter for any text. Feature 013: `evidence_kinds` and
    `evidence_count` are always present, and `hard_evidence` on this row now means "this turn produced at least
    one evidence item of any kind" - `canary_hit` keeps the narrower meaning."""
    try:
        ctx = _live()
        fields: dict[str, Any] = {"turn": turn, "source": source}
        if ctx is not None:
            cost, note = ctx.turn_cost.value()
            fields["duration_ms"] = _ms_since(ctx.turn_started_at)
            fields.update(ctx.turn_tokens.fields())
            fields["cost_usd"] = cost
            if cost is None:
                fields["cost_note"] = note
            if attacker_generated:
                fields["attacker_model"], fields["attacker_prompt"] = ctx.attacker_model, ctx.attacker_prompt
            if ctx.judge_model is not None:   # a judge is configured: its slug, and this turn's request (or null)
                fields["judge_model"], fields["judge_prompt"] = ctx.judge_model, ctx.turn_judge_prompt
        fields.update({"message_chars": message_chars, "reply_chars": reply_chars, "reply_truncated": reply_truncated,
                       "canary_hit": canary_hit, "hard_evidence": hard_evidence, "judged": judged,
                       "verdict": verdict if judged else None, "evidence_kinds": list(evidence_kinds),
                       "evidence_count": evidence_count})
        emit("turn", **fields)
        if ctx is not None:
            ctx.turn_lines += 1
            tracing.current().end_span(ctx.turn_span, **span_attributes(fields))
            ctx.turn_span, ctx.turn = None, None
    except Exception as error:
        _backstop("turn", error)


def _end_turn_span(ctx: RunContext) -> None:
    """Close a turn span the run left open (a turn that ended without its line, e.g. an attacker failure)."""
    if ctx.turn_span is not None:
        span, ctx.turn_span = ctx.turn_span, None
        tracing.current().end_span(span)


def _ms_since(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


@contextmanager
def child_span(name: str) -> Iterator[Any]:
    """A request span under the current turn (or the run) with an explicit parent, when the run is traced; None
    otherwise — outside a run, under a run reference, or with tracing off (FR-013)."""
    ctx = _live()
    parent = None if ctx is None else (ctx.turn_span or ctx.run_span)
    if parent is None:
        yield None
        return
    with tracing.current().span(name, parent=parent) as span:
        yield span


# ---- per-event helpers: each builds exactly its catalogue fields ----


def model_request(*, kind: str, model: str, prompt: str | None, latency_ms: int, ok: bool, status: int | None,
                  attempts: int, prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None,
                  error: str | None = None, verdict: str | None = None, message_chars: int | None = None,
                  span: Any = None) -> None:
    """One logical model request (FR-003): latency over the whole request, retries included; attempts; the tokens the
    provider reported; the estimated cost. A judge line adds its verdict category and `hard_evidence` false (the judge
    is consulted only when no canary matched, so a judge line can never read as a confirmed finding)."""
    try:
        cost, note = request_cost(total_tokens, model, _PRICES)
        fields: dict[str, Any] = {"kind": kind, "model": model, "prompt": prompt, "latency_ms": latency_ms, "ok": ok,
                                  "status": status}
        if error is not None:
            fields["error"] = error
        fields.update({"attempts": attempts, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                       "total_tokens": total_tokens, "cost_usd": cost})
        if cost is None:
            fields["cost_note"] = note
        if kind == "judge":
            if ok and verdict is not None:
                fields["verdict"] = verdict
            fields["hard_evidence"] = False
        if kind == "attacker" and message_chars is not None:
            fields["message_chars"] = message_chars
        ctx = _live()
        if ctx is not None and kind != "recommender":
            ctx.turn_tokens.add(prompt_tokens, completion_tokens, total_tokens)
            ctx.turn_cost.add(cost, note)
            ctx.run_cost.add(cost, note)
        emit("model.request", logging.INFO if ok else logging.ERROR, **fields)
        if span is not None:
            attributes = span_attributes(fields)
            attributes.update(_present({"gen_ai.request.model": model, "gen_ai.usage.input_tokens": prompt_tokens,
                                        "gen_ai.usage.output_tokens": completion_tokens}))
            tracing.current().set_attributes(span, **attributes)
    except Exception as exc:
        _backstop("model.request", exc)


def target_request(*, latency_ms: int, ok: bool, status: int | None, step: str, reply_chars: int | None,
                   reply_truncated: bool, span: Any = None) -> None:
    """One request sent to the target inside a run (FR-004): elapsed time, status or step, the reply's length —
    nothing about the URL, headers, body or reply text."""
    fields: dict[str, Any] = {"latency_ms": latency_ms, "ok": ok, "status": status, "step": step,
                              "reply_chars": reply_chars, "reply_truncated": reply_truncated}
    emit("target.request", logger=connection_log, **fields)
    if span is not None:
        tracing.current().set_attributes(span, **span_attributes(fields))


def connection_test(*, target_id: int | None, latency_ms: int, ok: bool, status: int | None, step: str) -> None:
    """A connection test outside any run (FR-009): the saved target's id, the step, the status and the duration."""
    emit("connection.test", logger=connection_log, scoped=False,
         **_present({"target_id": target_id}), latency_ms=latency_ms, ok=ok, status=status, step=step)


def memory_retrieval(*, pattern_ids: list[str], memory_count: int, k: int, distance_floor: float | None,
                     dedupe_threshold: float | None, candidate_count: int, dropped_floor: int,
                     dropped_duplicate: int, distances: list[float], query_messages: int) -> None:
    """The attacker's background was asked for (FR-016): counts, the pattern ids, and `warm` = a pattern came back.
    Feature 011 adds the settings in effect (a control switched off is `null`) and the selection's outcome — the
    candidates examined, dropped by the floor, skipped as near-identical, the selected hits' distances (4 decimals,
    nearest first) and the attacker messages in the query. Numbers and identifiers only: never the query text."""
    emit("memory.retrieval", warm=len(pattern_ids) > 0, pattern_count=len(pattern_ids), memory_count=memory_count,
         pattern_ids=list(pattern_ids), k=k, distance_floor=distance_floor, dedupe_threshold=dedupe_threshold,
         candidate_count=candidate_count, dropped_floor=dropped_floor, dropped_duplicate=dropped_duplicate,
         distances=[round(float(distance), 4) for distance in distances], query_messages=query_messages)


def memory_writeback(*, written: bool, pattern_written: bool, error: str | None = None, exc_info: Any = None,
                     message: str | None = None, pattern_outcome: str | None = None, pattern_id: str | None = None,
                     hit_count: int | None = None, pattern_distance: float | None = None) -> None:
    """The run's write-back result (FR-016), inside its scope; `run.end` reports it as `memory_written`. Feature
    011: on a success the outcome — `added` or `merged`, the pattern added or merged into, its hit count and its
    distance to the nearest existing same-family pattern (`null` when the family had none or de-duplication is
    off); all four absent otherwise."""
    ctx = _live()
    if ctx is not None:
        ctx.memory_written = written
    outcome: dict[str, Any] = {}
    if pattern_outcome is not None:
        outcome = {"pattern_outcome": pattern_outcome, "pattern_id": pattern_id, "hit_count": hit_count,
                   "pattern_distance": None if pattern_distance is None else round(float(pattern_distance), 4)}
    emit("memory.writeback", logging.INFO if written else logging.ERROR, exc_info=exc_info, message=message,
         written=written, pattern_written=pattern_written, **_present({"error": error}), **outcome)


def experiment_started(*, experiment_id: int, target_id: int, mode: str, families: list[str], reps: int,
                       max_runs: int, token_budget_total: int, wall_clock_s: int, arms: list[dict[str, Any]]) -> None:
    emit("experiment.start", experiment_id=experiment_id, target_id=target_id, mode=mode, families=list(families),
         reps=reps, max_runs=max_runs, token_budget_total=token_budget_total, wall_clock_s=wall_clock_s, arms=arms)


def experiment_cap(*, experiment_id: int, cap: str, completed_runs: int, tokens_used: int, elapsed_s: float) -> None:
    emit("experiment.cap", logging.WARNING, experiment_id=experiment_id, cap=cap, completed_runs=completed_runs,
         tokens_used=tokens_used, elapsed_s=round(elapsed_s, 3))


def experiment_ended(*, experiment_id: int, status: str, stopped_reason: str, completed_runs: int, tokens_used: int,
                     duration_ms: int, error: str | None = None, exc_info: Any = None) -> None:
    emit("experiment.end", logging.ERROR if error is not None else logging.INFO, exc_info=exc_info,
         experiment_id=experiment_id, status=status, stopped_reason=stopped_reason, completed_runs=completed_runs,
         tokens_used=tokens_used, duration_ms=duration_ms, **_present({"error": error}))


def replay_batch_started(*, target_id: int, replayable_count: int, cap: int) -> None:
    """A batch replay (feature 012) is about to claim its first entry: unscoped, like `connection_test` - there is
    no one `run_id` for a whole batch (FR-043, FR-044)."""
    emit("replay.batch.start", scoped=False, target_id=target_id, replayable_count=replayable_count, cap=cap)


def replay_batch_ended(*, target_id: int, fixed: int, still_vulnerable: int, inconclusive: int, duration_ms: int,
                       complete: bool, stop_reason: str | None = None, error: str | None = None) -> None:
    """A batch replay (feature 012) has finished, or stopped early: unscoped, outside every entry's own run scope
    (FR-044). `stop_reason` ("run_in_progress" | "replay_failed") is present only when `complete` is False;
    `error` only on an unexpected failure, which also raises the line to ERROR."""
    emit("replay.batch.end", logging.ERROR if error is not None else logging.INFO, scoped=False,
         target_id=target_id, fixed_count=fixed, still_vulnerable_count=still_vulnerable,
         inconclusive_count=inconclusive, duration_ms=duration_ms, complete=complete,
         **_present({"stop_reason": stop_reason, "error": error}))
