"""The custom LangGraph checkpoint saver, classification, and the execution lease (feature 014, data-model.md).

No new dependency (Principle X, Clarifications): `KestrelCheckpointSaver` subclasses `langgraph-checkpoint`'s own
`BaseCheckpointSaver`, reusing its own serializer class, over `TargetStore`'s existing sqlite3 connection and
schema-migration story - never a second file, a second schema, or a third-party saver package. Every async method
wraps a synchronous body (plain `sqlite3`, through `TargetStore.connect()`) in `asyncio.to_thread`.

`classify()` is the one read-only status check reused by the start-up sweep, the run-detail/run-list endpoints,
the decision-validation step, and Stop (research D13): it never mutates anything and never calls `ainvoke`.

The execution lease (research D12) is a plain `set[int]` of currently-leased run ids held on `app.state` - never a
bare module-level object, so two unrelated apps (two test apps over different databases) never collide on the
same run id - plus `app.state.accepted_exits`, the flag `mark_active()` sets so the lease's own release knows
whether this exit actually did something (research D26): a refused request's exit never touches the run's own
idle clock.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Iterator

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP, get_checkpoint_id)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from kestrel.store import TargetStore, utc_now

# The exact range this saver is tested against (owner's third condition, Clarifications, FR-037); pyproject.toml
# declares the identical range for both packages - test_checkpoint_version_guard.py reads it with tomllib and
# asserts the two agree exactly.
SUPPORTED_LANGGRAPH_CHECKPOINT = ">=4.3.0,<4.4.0"
SUPPORTED_LANGGRAPH = ">=1.2.17,<1.3"

# A small constant (a few minutes), short against the default 24-hour idle window (research D27); the periodic
# idle-stop loop's own default interval.
IDLE_CHECK_INTERVAL_S = 300.0


class CheckpointVersionError(Exception):
    """An installed package's version falls outside the range this saver is tested against (FR-037); Kestrel
    refuses to start rather than silently resume against an upgrade it has never been tested with."""


def _parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _parse_spec(spec: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """`">=X,<Y"` -> (lower bound, upper bound), each a plain version tuple - two or three components, since the
    declared upper bound (`<1.3`) has only two."""
    lower_part, _, upper_part = spec.partition(",")
    if not lower_part.startswith(">=") or not upper_part.startswith("<"):
        raise ValueError(f"unsupported version spec shape: {spec!r}")
    return _parse_version(lower_part.removeprefix(">=")), _parse_version(upper_part.removeprefix("<"))


def _in_range(installed: str, spec: str) -> bool:
    lower, upper = _parse_spec(spec)
    version = _parse_version(installed)
    width = max(len(version), len(lower), len(upper))

    def pad(bound: tuple[int, ...]) -> tuple[int, ...]:
        return bound + (0,) * (width - len(bound))

    return pad(lower) <= pad(version) < pad(upper)


def check_supported_versions(*, langgraph_version: str | None = None,
                             langgraph_checkpoint_version: str | None = None) -> None:
    """Fail loudly, naming the installed version and the declared range, for whichever package falls outside it
    (FR-037); called once, in `lifespan`, before the saver is attached to any app copy. The two keywords are a test
    seam (monkeypatching the installed-version lookup); production always reads the real installed versions."""
    import importlib.metadata

    checked = {
        "langgraph": (langgraph_version or importlib.metadata.version("langgraph"), SUPPORTED_LANGGRAPH),
        "langgraph-checkpoint": (langgraph_checkpoint_version or importlib.metadata.version("langgraph-checkpoint"),
                                 SUPPORTED_LANGGRAPH_CHECKPOINT),
    }
    for name, (installed, declared) in checked.items():
        if not _in_range(installed, declared):
            raise CheckpointVersionError(
                f"{name} {installed} is installed, outside the range this checkpoint saver is tested against "
                f"({declared}); upgrade langgraph-checkpoint/langgraph's declared ranges (and this saver's own "
                f"tests) together, or pin a compatible version, before starting Kestrel.")


class KestrelCheckpointSaver(BaseCheckpointSaver[str]):
    """A `BaseCheckpointSaver` over `TargetStore`'s own sqlite3 connection (research D9): five async methods, each
    `asyncio.to_thread`-wrapped around a synchronous body. Constructed with its own explicit serializer - never
    `self.with_allowlist(...)` after the fact, which is a no-op in the serializer's permissive mode - so the three
    Kestrel dataclasses a checkpoint may carry round-trip as themselves, with no warning, under the serializer's
    default mode and its strict mode alike."""

    def __init__(self, store: TargetStore) -> None:
        super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=[
            ("kestrel.attack.graph", "Outcome"),
            ("kestrel.evidence.checker", "TurnEvidence"),
            ("kestrel.evidence.model", "EvidenceItem"),
        ]))
        self._store = store

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self._put, config, checkpoint, metadata)

    async def aput_writes(self, config, writes, task_id: str, task_path: str = "") -> None:
        await asyncio.to_thread(self._put_writes, config, writes, task_id, task_path)

    async def aget_tuple(self, config) -> CheckpointTuple | None:
        return await asyncio.to_thread(self._get_tuple, config)

    async def alist(self, config, *, filter=None, before=None, limit=None) -> AsyncIterator[CheckpointTuple]:
        rows = await asyncio.to_thread(self._list, config, filter, before, limit)
        for item in rows:
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self._store.delete_checkpoint, int(thread_id))

    # ---- synchronous bodies, each run in a worker thread ----

    def _put(self, config, checkpoint, metadata):
        from kestrel.attack.graph import CURRENT_GRAPH_VERSION   # lazy: avoids a module-level import cycle

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        # The version stamp (research D18): added to the metadata dict before it is persisted - LangGraph never
        # needs to see this key; it is purely Kestrel's own addition to data Kestrel already owns writing.
        stamped = {**metadata, "kestrel_graph_version": CURRENT_GRAPH_VERSION}
        type_, blob = self.serde.dumps_typed(checkpoint)
        _, meta_blob = self.serde.dumps_typed(stamped)   # a plain dict always serialises as "msgpack" (never
        #                                                   None/bytes/bytearray) - no separate type column needed
        with self._store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id,"
                " parent_checkpoint_id, type, checkpoint, metadata, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (thread_id, checkpoint_ns, checkpoint["id"], parent_checkpoint_id, type_, blob, meta_blob,
                 utc_now()))
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns,
                                 "checkpoint_id": checkpoint["id"]}}

    def _put_writes(self, config, writes, task_id: str, task_path: str) -> None:
        """Replicates LangGraph's own replace/ignore rule (research D10): a control write (a negative index, from
        LangGraph's own index map) is upserted, so a second one of the same kind overwrites the first, never
        duplicating it; a regular write (its own position in the node's return value, always >= 0) is inserted
        only if absent - idempotent under a retried node."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self._store.connect() as db:
            for position, (channel, value) in enumerate(writes):
                index = WRITES_IDX_MAP.get(channel, position)
                type_, blob = self.serde.dumps_typed(value)
                verb = "INSERT OR REPLACE" if index < 0 else "INSERT OR IGNORE"
                db.execute(
                    f"{verb} INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,"
                    f" channel, type, value, task_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, index, channel, type_, blob, task_path))

    def _get_tuple(self, config) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with self._store.connect() as db:
            if checkpoint_id is not None:
                row = db.execute(
                    "SELECT * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
                    (thread_id, checkpoint_ns, checkpoint_id)).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ?"
                    " ORDER BY checkpoint_id DESC LIMIT 1", (thread_id, checkpoint_ns)).fetchone()
            if row is None:
                return None
            write_rows = db.execute(
                "SELECT * FROM checkpoint_writes WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?"
                " ORDER BY task_path, task_id, idx",
                (thread_id, checkpoint_ns, row["checkpoint_id"])).fetchall()
        return self._tuple_from_row(row, write_rows)

    def _list(self, config, filter, before, limit) -> list[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"] if config else None
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "") if config else None
        before_id = get_checkpoint_id(before) if before else None
        query, params = "SELECT * FROM checkpoints WHERE 1 = 1", []
        if thread_id is not None:
            query += " AND thread_id = ?"
            params.append(thread_id)
        if checkpoint_ns is not None:
            query += " AND checkpoint_ns = ?"
            params.append(checkpoint_ns)
        if before_id is not None:
            query += " AND checkpoint_id < ?"
            params.append(before_id)
        query += " ORDER BY checkpoint_id DESC"
        out: list[CheckpointTuple] = []
        with self._store.connect() as db:
            for row in db.execute(query, params).fetchall():
                metadata = self.serde.loads_typed(("msgpack", row["metadata"]))
                if filter and not all(metadata.get(key) == value for key, value in filter.items()):
                    continue
                write_rows = db.execute(
                    "SELECT * FROM checkpoint_writes WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?"
                    " ORDER BY task_path, task_id, idx",
                    (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"])).fetchall()
                out.append(self._tuple_from_row(row, write_rows, metadata=metadata))
                if limit is not None and len(out) >= limit:
                    break
        return out

    def _tuple_from_row(self, row, write_rows, *, metadata=None) -> CheckpointTuple:
        checkpoint = self.serde.loads_typed((row["type"], row["checkpoint"]))
        if metadata is None:
            metadata = self.serde.loads_typed(("msgpack", row["metadata"]))
        pending_writes = [(write["task_id"], write["channel"], self.serde.loads_typed((write["type"], write["value"])))
                          for write in write_rows]
        parent_config: RunnableConfig | None = None
        if row["parent_checkpoint_id"] is not None:
            parent_config = {"configurable": {"thread_id": row["thread_id"], "checkpoint_ns": row["checkpoint_ns"],
                                              "checkpoint_id": row["parent_checkpoint_id"]}}
        return CheckpointTuple(
            config={"configurable": {"thread_id": row["thread_id"], "checkpoint_ns": row["checkpoint_ns"],
                                     "checkpoint_id": row["checkpoint_id"]}},
            checkpoint=checkpoint, metadata=metadata, parent_config=parent_config, pending_writes=pending_writes)


def thread_config(run_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(run_id)}}


# ---- classification (research D13): one read-only status check, distinct results ----


@dataclass(frozen=True)
class Running:
    """This run's execution lease is currently held (FR-038): reads as plainly in progress, no control offered."""


@dataclass(frozen=True)
class NoCheckpoint:
    """No loadable checkpoint for this thread: close exactly as today."""


@dataclass(frozen=True)
class Unreadable:
    """A checkpoint exists but could not be read at all (aget_tuple or aget_state raised): close exactly as a
    missing one would be."""


@dataclass(frozen=True)
class Incompatible:
    """The checkpoint's own version stamp does not match the running build (FR-048): close with its own distinct
    reason, never resumed against mismatched code."""


@dataclass(frozen=True)
class ReachedEnd:
    """The graph genuinely reached its own end (no pending tasks at all): reconciled using this outcome, never
    offered as Resume (research D11). `values` is the final state dict (`snap.values`), so a caller reconciling
    this row can read its own persisted turns_used/tokens_used - a never-finished row's own `Run` columns are
    still null, so these must come from the checkpoint, not the database row."""
    outcome: Any
    values: dict[str, Any]


@dataclass(frozen=True)
class Resumable:
    """A pending task, no interrupt: a step's writes landed but its own checkpoint commit did not (or the next
    node has not started at all yet). `from_step` is the real next node to run, read from the compiled graph's
    own routing write, never a hand-written table (FR-052); `completed` tells a caller whether *send* has already
    happened for this turn (FR-044): "past send" is `from_step in ("evidence", "judge", "decide", "record")`."""
    from_step: str
    completed: bool
    snapshot: Any


@dataclass(frozen=True)
class Paused:
    """A pending task whose own interrupt is set: awaiting a decision."""
    interrupt_id: str
    turn: int
    message: str


ClassificationResult = Running | NoCheckpoint | Unreadable | Incompatible | ReachedEnd | Resumable | Paused

# The plain, statically single-target edges with no routing write of their own (FR-052) - every other node's own
# outgoing edge is conditional and so always carries its own `branch:to:` write.
_STATIC_NEXT_STEP = {"judge": "record", "record": "decide"}


async def classify(graph: Any, run_id: int, *, leased: bool) -> ClassificationResult:
    """Read-only; never mutates anything and never calls `ainvoke` (research D13). Reused by the start-up sweep,
    the run-detail/run-list endpoints, the decision-validation step, and Stop."""
    from kestrel.attack.graph import CURRENT_GRAPH_VERSION   # lazy: avoids a module-level import cycle

    if leased:
        return Running()
    try:
        tup = await graph.checkpointer.aget_tuple(thread_config(run_id))
        if tup is None:
            return NoCheckpoint()
        if tup.metadata.get("kestrel_graph_version") != CURRENT_GRAPH_VERSION:
            return Incompatible()
        snap = await graph.aget_state(thread_config(run_id))
    except Exception:
        return Unreadable()
    if not snap.tasks:
        return ReachedEnd(outcome=snap.values.get("outcome"), values=snap.values)
    interrupts = [interrupt for task in snap.tasks for interrupt in task.interrupts]
    if interrupts:
        first = interrupts[0]
        return Paused(interrupt_id=first.id, turn=first.value["turn"], message=first.value["message"])
    task = snap.tasks[0]
    completed = task.result is not None
    if not completed:
        from_step = "attacker" if task.name == "__start__" else task.name
    else:
        routed = next((channel.removeprefix("branch:to:") for task_id, channel, _ in (tup.pending_writes or ())
                       if task_id == task.id and channel.startswith("branch:to:")), None)
        if routed is None and task.name not in _STATIC_NEXT_STEP:
            # FR-052: this task's own conditional edge routed to the graph's end - a route to END carries no
            # `branch:to:` write at all (there is no further channel to name), so the checkpoint confirming "zero
            # tasks remain" is exactly what never committed. The state this task already produced (channel
            # values, never a task-level write) shows the run is functionally over regardless; a naturally
            # completed thread would classify as ReachedEnd the same way once its own final checkpoint lands.
            return ReachedEnd(outcome=snap.values.get("outcome"), values=snap.values)
        from_step = routed or _STATIC_NEXT_STEP[task.name]
    return Resumable(from_step=from_step, completed=completed, snapshot=snap)


def run_state_for(status: ClassificationResult) -> str:
    """FR-054's one classification-derived field, over the five is_checkpointed-row shapes only; a finished row,
    or one outside this feature's reach, is for the caller's own `status` column to describe instead."""
    if isinstance(status, Running):
        return "running"
    if isinstance(status, Paused):
        return "paused"
    if isinstance(status, Resumable):
        return "resumable"
    return "stoppable"   # ReachedEnd, NoCheckpoint, Unreadable, or Incompatible (unreachable without a restart)


# ---- the execution lease (research D12) ----


class RunLeased(Exception):
    """This run's execution lease is currently held by another request (FR-038); -> 409 run_executing."""

    def __init__(self, run_id: int) -> None:
        super().__init__(run_id)
        self.run_id = run_id


@contextmanager
def lease(app_state: Any, store: TargetStore, run_id: int) -> Iterator[None]:
    """A non-blocking, per-app execution lease: acquiring it for a run id already leased raises immediately;
    releasing it (even via an exception escaping the `with` block) makes it acquirable again. Its own release
    touches `last_activity_at` only when `mark_active(app_state, run_id)` was called inside the block (research
    D26) - never unconditionally, so a request refused by a precondition never resets the run's idle clock."""
    if run_id in app_state.leases:
        raise RunLeased(run_id)
    app_state.leases.add(run_id)
    try:
        yield
    finally:
        app_state.leases.discard(run_id)
        if run_id in app_state.accepted_exits:   # set.discard() itself always returns None - check membership
            app_state.accepted_exits.discard(run_id)   # first, never branch on its own return value
            store.touch_last_activity(run_id, now=app_state.clock())


def mark_active(app_state: Any, run_id: int) -> None:
    """Marks this run's current lease-holding exit as accepted (research D26): called once a handler's own
    preconditions have already passed and it is about to actually invoke the graph or perform the stop - never
    before, and never by the automatic idle check (research D26, D27), for which an automatic stop (successful or
    not) is never one of the accepted-exit kinds."""
    app_state.accepted_exits.add(run_id)


def idle_hours(run: Any, app_state: Any) -> float:
    """How long `run`'s own idle clock has been running (research D27): `last_activity_at` (stored `TEXT`) parsed
    into a `datetime` before subtracting - never a `str` from a `datetime` - against `app_state.clock()`'s own
    current reading. Plain wall-clock, no `max()` with anything; a run with no `last_activity_at` at all (should
    not happen for a checkpointed row, which always gets one at claim time) is never this function's problem to
    paper over."""
    parsed = datetime.fromisoformat(run.last_activity_at)
    return (app_state.clock() - parsed).total_seconds() / 3600.0
