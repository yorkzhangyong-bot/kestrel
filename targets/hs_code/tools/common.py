"""Shared plumbing for the tools: the runtime context (store, knowledge base, client), the
per-line input model, and the bounded-concurrency runner with per-line isolation (FR-048)."""
from __future__ import annotations

import logging

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from agent.config import PER_LINE_TIMEOUT_S, Settings, get_settings
from agent.llm import StructuredCaller, get_client
from agent.schemas import Extracted

log = logging.getLogger(__name__)
T = TypeVar("T")


class LineText(BaseModel):
    line_no: int
    text_zh: str = ""
    text_en: str = ""
    extracted: Extracted | None = None
    pure_stop_word: bool = False
    flag_kind: str | None = None
    flag_reason: str = ""

    @property
    def display_text(self) -> str:
        return " / ".join(t for t in (self.text_zh, self.text_en) if t)


@dataclass
class ToolContext:
    """What the agent-facing tool wrappers need at run time. Set once per turn by the app."""

    store: Any                       # agent.store.LineStore
    kb: Any                          # rag.loader.KnowledgeBase (index, retriever, bti, rules)
    settings: Settings = field(default_factory=get_settings)
    client: StructuredCaller | None = None
    workers: int | None = None
    selected_line_no: int | None = None
    reply_ref: str | None = None          # a reply turn: the stored reply and the line the app resolved for it in code
    reply_line_no: int | None = None
    applied_replies: dict[str, Any] = field(default_factory=dict)   # reply_ref → ApplyReplyOutput; each reply is applied once per turn

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = get_client(usage_sink=self.store.add_usage, settings=self.settings)
        if self.workers is None:
            self.workers = self.settings.workers


_ctx: dict[str, ToolContext | None] = {"value": None}  # module global: LangGraph may run tools off the calling thread


def set_context(ctx: ToolContext | None) -> None:
    _ctx["value"] = ctx


def get_context() -> ToolContext:
    ctx = _ctx["value"]
    if ctx is None:
        raise RuntimeError("tool context not set — the app must call tools.common.set_context() before running the agent")
    return ctx


def select_lines(store: Any, line_nos: list[int] | None = None, all_pending: bool = False) -> list[LineText]:
    """LineText inputs for the given line numbers, or every pending line, or every line."""
    out: list[LineText] = []
    for line in store.lines:
        v = line.current
        if line_nos and line.line_no not in line_nos:
            continue
        if not line_nos and all_pending and v.status.value != "pending":
            continue
        out.append(LineText(line_no=line.line_no, text_zh=v.text_zh, text_en=v.text_en, extracted=v.extracted,
                            pure_stop_word=bool(v.flag and v.flag.pure_stop_word),
                            flag_kind=v.flag.kind.value if v.flag else None, flag_reason=v.flag.reason if v.flag else ""))
    return out


def run_per_line(items: Iterable[T], fn: Callable[[T], Any], on_error: Callable[[T, BaseException], Any],
                 workers: int = 4, timeout: float = PER_LINE_TIMEOUT_S) -> list[Any]:
    """Apply fn to every item with bounded concurrency; a failure on one item becomes on_error(item, exc)
    and never stops the others. Output order equals input order."""
    items = list(items)
    if not items:
        return []
    results: list[Any] = [None] * len(items)
    workers = max(1, min(workers, len(items)))

    def _one(i: int, item: T) -> None:
        try:
            results[i] = fn(item)
        except BaseException as exc:  # noqa: BLE001 - isolation is the point
            log.warning("line task failed: %s", type(exc).__name__)
            results[i] = on_error(item, exc)

    if workers == 1:
        for i, item in enumerate(items):
            _one(i, item)
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, i, item) for i, item in enumerate(items)]
        for i, fut in enumerate(futures):
            try:
                fut.result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - timeouts
                results[i] = on_error(items[i], exc)
    return results
