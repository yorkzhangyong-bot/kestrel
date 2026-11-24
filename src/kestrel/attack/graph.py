"""The adaptive attacker/judge loop as a LangGraph graph (contracts/adaptive-loop.md, Principle X).

LangGraph orchestrates; the attacker and judge model calls are plain httpx (their own clients). The loop claims a
run row, drives the conversation turn by turn under three caps, and finishes the row. The deterministic checks
first, the judge only if none found evidence (Principle II; feature 013: the evidence checker runs the canary and
the two reply detectors in the fixed order of 013/FR-001, and the evidence node delegates to it); hard_evidence
comes from a deterministic check alone. Every message and reply is masked before it is stored, judged or handed to
the attacker (Principle IV, FR-021). No attack text lives here. Feature 010: the loop emits `run.start` once the
row is claimed and one `turn` line per recorded turn (lengths, categories, totals); the turn number and the turn
span ride on the shared run context, which every graph node sees.

Shape: the two graphs (a live run's and a replay's, feature 012) are compiled once, at import, from module-level
node functions. The state is typed (`_State`, `_ReplayState`): the conversation and a replay's per-turn results
are appended through a reducer, so a node returns only its turn's delta; the run's outcome is one frozen
`Outcome`, set exactly once. Everything a node needs per run - the store and run id, the resolved target and its
secrets, the clients, the sender, the checker, the caps and the clock, the prompt references, a replay's recorded
turns - travels as LangGraph's runtime context (`_LiveDeps` / `_ReplayDeps`, read by each node as
`runtime.context`), so no node closes over a per-run value.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, Awaitable, Callable, Protocol, Sequence, TypeVar
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from kestrel import events, prompt_registry
from kestrel.attack.attacker import AttackerError
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings, TestOutcome, run_test
from kestrel.evidence.checker import EvidenceChecker, TurnEvidence, build_checker
from kestrel.judge.client import JudgeError
from kestrel.runs import attacker_ref, judge_ref
from kestrel.secrets import mask_values
from kestrel.store import Run, TargetStore, Turn

SEND_LIMIT_S = 60.0
JUDGE_LIMIT_S = 30.0
ATTACKER_LIMIT_S = 30.0
MAX_REPLY_CHARS = 2000

CANARY_REASON = "The reply contains a canary string the agent was told to keep, so the attack is confirmed."
INTERRUPTED_BY_DEADLINE = "The agent held until the run reached a limit."


class _Attacker(Protocol):
    configured: bool
    model: str
    async def next_message(self, *, conversation, family, progress=None, timeout=None): ...


class _Judge(Protocol):
    configured: bool
    model: str
    async def judge(self, *, attack, reply, conversation=None, timeout=None): ...


Sender = Callable[..., Awaitable[TestOutcome]]


@dataclass(frozen=True)
class Outcome:
    """How a run ended - set exactly once, when the run ends; `finish_run` reads exactly these values.
    `failure_step` is only ever set by a failed send (the step the connection tester failed at)."""
    verdict: str | None
    hard_evidence: bool
    reason: str
    judge_used: bool
    stopping_condition: str
    succeeded_turn: int | None
    failure_step: str | None = None


_T = TypeVar("_T")


def _appended(left: list[_T], right: list[_T]) -> list[_T]:
    """The reducer behind the appended-to state fields: a node returns only its delta, the graph keeps the whole
    list, and an empty delta leaves it unchanged."""
    return left + right


class _State(TypedDict, total=False):
    conversation: Annotated[list[tuple[str, str]], _appended]   # (role, masked text) so far; nodes append a delta
    turns_used: int
    tokens_used: int
    judge_used: bool
    judge_requests: int                   # judge calls actually made (the judge node counts them; provenance)
    last_verdict: str | None
    last_progress: str | None
    last_reason: str | None
    last_judged_turn: int                 # the turn the judge last produced a verdict on (feature 009)
    pending_message: str                  # this turn's attacker message, masked
    pending_reply: str | None
    pending_truncated: bool
    pending_canary: bool                  # a canary matched this turn's reply (feature 010: the turn line)
    pending_evidence: TurnEvidence | None  # this turn's deterministic findings (feature 013); None before the check
    outcome: Outcome | None               # set exactly once, when the run ends


class _ReplayState(_State, total=False):
    # One entry per turn actually attempted, captured live as the replay's record node runs (feature 012,
    # research D5) - never reconstructed from stored rows afterward - and fed to `compute_outcome` in order.
    turn_results: Annotated[list[str | None], _appended]


def _initial_state() -> _State:
    return {"conversation": [], "turns_used": 0, "tokens_used": 0, "judge_used": False, "judge_requests": 0,
            "last_verdict": None, "last_progress": None, "last_reason": None, "outcome": None}


# ---- the per-run dependencies: LangGraph's runtime context, never a closure ----


@dataclass(frozen=True)
class _Deps:
    """What every node of a run needs, handed to the compiled graph as its runtime context
    (`compiled.ainvoke(initial, context=deps)`) and read by a node as `runtime.context`."""
    store: TargetStore
    run_id: int
    resolved: ResolvedSettings
    secrets: list[str]                    # the target's auth values: masked out of every message and reply
    mode: str
    sender: Sender
    transport: Any
    resolver: Any
    judge: _Judge
    judge_prompt: str | None              # the reference the judge client actually sends (feature 010, D15)
    judge_prompt_id: str | None
    judge_prompt_version: str | None
    checker: EvidenceChecker
    max_turns: int
    token_budget: int
    deadline: float
    clock: Callable[[], float]

    def remaining(self) -> float:
        return self.deadline - self.clock()


@dataclass(frozen=True)
class _LiveDeps(_Deps):
    seed_prompt: AttackPrompt
    opening: str                          # turn 1's message: the seed with any planted task in place (013/FR-011)
    attacker: _Attacker
    hint_provider: Callable[[list], str | None] | None
    attacker_prompt: str | None           # constant for the run (feature 009, FR-003; feature 010, FR-007)
    attacker_prompt_id: str | None
    attacker_prompt_version: str | None


@dataclass(frozen=True)
class _ReplayDeps(_Deps):
    source: Run
    source_turns: list[Turn]


_DepsT = TypeVar("_DepsT", bound=_Deps)


def _format(conversation: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{'attacker' if role == 'attacker' else 'agent'}: {text}" for role, text in conversation)


# ---- per-turn bodies shared by a live run (run_adaptive) and a replay (run_replay_adaptive, feature 012) ----
#
# The judge, send, evidence and decide steps are identical in substance whether this turn's message came from the
# attacker model or from a recorded transcript (FR-008: the per-turn judge-call shape is explicitly unchanged for
# a replay), so their bodies live here, parameterised by what they need (research D14), and one module-level node
# per step (`_send_node`, `_evidence_node`, `_judge_node`, `_decide_node`, below) calls each from the runtime
# context in both graphs. The attacker and record steps are NOT shared (a model call versus a list lookup;
# run-wide-constant provenance versus per-turn copied provenance) and stay defined separately, beside each other.


async def _judge_turn(state: _State, *, judge: _Judge, judge_prompt: str | None,
                      remaining: Callable[[], float]) -> _State:
    """The judge step: the judge sees the recorded conversation plus this turn's pending message and reply (read
    from the state, never written back); identical token/event accounting for a live run and a replay. A request
    counts in `judge_requests` before it is made, so one the judge fails still counts (provenance is recorded for
    a run that made at least one request)."""
    if not judge.configured:
        return {"judge_used": True, "last_verdict": "unclear", "last_reason": "No judge is configured.",
                "last_progress": state["last_progress"]}
    conversation = list(state["conversation"]) + [("attacker", state["pending_message"]),
                                                  ("agent", state["pending_reply"] or "")]
    requests = state["judge_requests"] + 1
    events.judge_requested(judge_prompt)
    try:
        verdict = await judge.judge(attack=state["pending_message"], reply=state["pending_reply"] or "",
                                    conversation=_format(conversation),
                                    timeout=max(0.1, min(JUDGE_LIMIT_S, remaining())))
    except JudgeError as error:
        return {"judge_used": True, "judge_requests": requests, "last_verdict": "unclear",
                "last_reason": f"The judge could not decide: {error}", "last_progress": state["last_progress"]}
    update: _State = {"judge_used": True, "judge_requests": requests,
                      "tokens_used": state["tokens_used"] + verdict.tokens,
                      "last_verdict": verdict.verdict, "last_reason": verdict.reason,
                      "last_progress": verdict.progress, "last_judged_turn": state["turns_used"] + 1}
    if verdict.verdict == "succeeded":
        update["outcome"] = Outcome(verdict="succeeded", hard_evidence=False, reason=verdict.reason,
                                    judge_used=True, stopping_condition="succeeded",
                                    succeeded_turn=state["turns_used"] + 1)
    return update


async def _send_turn(state: _State, *, resolved: ResolvedSettings, mode: str, sender: Sender, transport: Any,
                     resolver: Any, remaining: Callable[[], float], secrets: list[str],
                     evidence: EvidenceChecker) -> _State:
    """The send step: still masks the reply with `mask_values(outcome.reply_text or "", secrets)` before returning
    it - a replay's own stored reply is masked exactly as a live run's is, never the attacker message (which
    arrives already masked, FR-001). `secrets` is a parameter: run_adaptive and run_replay_adaptive each pass
    their own target's secret values. Feature 013: every message is handed to the checker's `note_sent` before it
    goes out - the one place both a live run's and a replay's messages pass through - so the override token is
    disarmed by the text actually sent (013/FR-012, FR-035)."""
    evidence.note_sent(state["pending_message"], state["turns_used"] + 1)
    outcome = await sender(resolved, mode=mode, display_name="", transport=transport, resolver=resolver,
                           deadline_s=max(0.1, min(SEND_LIMIT_S, remaining())), prompt=state["pending_message"])
    if not outcome.ok:
        return {"pending_reply": None, "pending_truncated": False,
                "outcome": Outcome(verdict=None, hard_evidence=False, reason=outcome.message,
                                   judge_used=state["judge_used"], stopping_condition="send_failed",
                                   succeeded_turn=None, failure_step=outcome.step)}
    reply = mask_values(outcome.reply_text or "", secrets)[:MAX_REPLY_CHARS]
    return {"pending_reply": reply, "pending_truncated": bool(outcome.reply_truncated)}


async def _check_evidence(state: _State, evidence: EvidenceChecker, remaining: Callable[[], float]) -> _State:
    """The evidence step: the checker's deterministic checks over this turn's reply, in the fixed order
    (013/FR-001). Any item ends the run as succeeded with hard evidence and no judge call (013/FR-002);
    `pending_canary` keeps its narrower meaning (a canary matched) for the turn line's `canary_hit`."""
    found = await evidence.check_turn(state["turns_used"] + 1, state["pending_reply"] or "", remaining)
    events.evidence_check(checks=found.checks, evidence_kinds=found.kinds, evidence_count=len(found.items),
                          side_channel_status=found.side_channel_status, callback_wait_ms=found.callback_wait_ms,
                          state_changed_keys=found.state_changed_keys)
    update: _State = {"pending_canary": found.canary_hit, "pending_evidence": found}
    if found.items:
        update["outcome"] = Outcome(verdict="succeeded", hard_evidence=True, reason=found.reason,
                                    judge_used=state["judge_used"], stopping_condition="succeeded",
                                    succeeded_turn=state["turns_used"] + 1)
    return update


def _decide_next(state: _State, *, max_turns: int, token_budget: int, remaining: Callable[[], float]) -> _State:
    """The decide step. For a replay (research D2), `max_turns` is already `min(len(source's recorded messages),
    the currently configured adaptive turn cap)`, so "ran out of recorded messages" and "hit the turn cap" are the
    same `stopping_condition == "turn_cap"` value this already produces - no new stopping condition is needed to
    tell the two apart from inside the graph."""
    if state.get("outcome"):
        return {}
    cap = None
    if state["turns_used"] >= max_turns:
        cap = "turn_cap"
    elif state["tokens_used"] >= token_budget:
        cap = "token_budget"
    elif remaining() <= 0:
        cap = "time_limit"
    if cap is not None:
        return {"outcome": Outcome(verdict=state["last_verdict"] or "unclear", hard_evidence=False,
                                   reason=state.get("last_reason") or INTERRUPTED_BY_DEADLINE,
                                   judge_used=state["judge_used"], stopping_condition=cap, succeeded_turn=None)}
    return {}


# ---- the shared nodes: one per shared step, reading the run's dependencies from the runtime context ----


async def _send_node(state: _State, runtime: Runtime[_DepsT]) -> _State:
    deps = runtime.context
    return await _send_turn(state, resolved=deps.resolved, mode=deps.mode, sender=deps.sender,
                            transport=deps.transport, resolver=deps.resolver, remaining=deps.remaining,
                            secrets=deps.secrets, evidence=deps.checker)


async def _evidence_node(state: _State, runtime: Runtime[_DepsT]) -> _State:
    deps = runtime.context
    return await _check_evidence(state, deps.checker, deps.remaining)


async def _judge_node(state: _State, runtime: Runtime[_DepsT]) -> _State:
    deps = runtime.context
    return await _judge_turn(state, judge=deps.judge, judge_prompt=deps.judge_prompt, remaining=deps.remaining)


def _decide_node(state: _State, runtime: Runtime[_DepsT]) -> _State:
    deps = runtime.context
    return _decide_next(state, max_turns=deps.max_turns, token_budget=deps.token_budget, remaining=deps.remaining)


def _record_evidence(state: _State, deps: _Deps) -> tuple[TurnEvidence | None, list]:
    """The turn's evidence items, written right after its turn row (013/FR-003); both record nodes do this."""
    found = state.get("pending_evidence")
    items = found.items if found is not None else []
    if items:
        deps.store.add_evidence(deps.run_id, items)
    return found, items


def _conversation_delta(state: _State) -> list[tuple[str, str]]:
    """What a record node appends to the conversation: this turn's attacker message, then the agent's reply when
    the send produced one (a failed send records the message alone)."""
    delta: list[tuple[str, str]] = [("attacker", state["pending_message"])]
    reply = state.get("pending_reply")
    if reply is not None:
        delta.append(("agent", reply))
    return delta


# ---- a live run's own attacker and record nodes ----


async def _live_attacker_node(state: _State, runtime: Runtime[_LiveDeps]) -> _State:
    deps = runtime.context
    turn = state["turns_used"] + 1
    events.turn_started(turn)   # every line of this turn carries its number, through all the nodes
    if turn == 1:
        return {"pending_message": mask_values(deps.opening, deps.secrets), "pending_canary": False,
                "pending_evidence": None}
    hints = None
    if deps.hint_provider is not None:
        try:
            hints = deps.hint_provider(state["conversation"])   # best-effort; a retrieval failure never fails the run
        except Exception:
            events.emit("memory.retrieval_failed", logging.WARNING, exc_info=True)
    try:
        reply = await deps.attacker.next_message(conversation=state["conversation"], family=deps.seed_prompt.family,
                                                 progress=state["last_progress"], hints=hints,
                                                 timeout=max(0.1, min(ATTACKER_LIMIT_S, deps.remaining())))
    except AttackerError as error:
        return {"outcome": Outcome(verdict="unclear", hard_evidence=False, reason=str(error),
                                   judge_used=state["judge_used"], stopping_condition="attacker_failed",
                                   succeeded_turn=None)}
    return {"pending_message": mask_values(reply.message, deps.secrets), "pending_canary": False,
            "pending_evidence": None, "tokens_used": state["tokens_used"] + reply.tokens}


def _live_record_node(state: _State, runtime: Runtime[_LiveDeps]) -> _State:
    deps = runtime.context
    turn = state["turns_used"] + 1
    judged = state.get("last_judged_turn") == turn   # the judge produced a verdict on this turn (feature 009)
    deps.store.add_turn(deps.run_id, position=turn, attacker_message=state["pending_message"],
                        reply_text=state.get("pending_reply"), reply_truncated=state.get("pending_truncated", False),
                        judge_verdict=state.get("last_verdict"), judge_reason=state.get("last_reason"),
                        judge_progress=state.get("last_progress"),
                        attacker_prompt_id=deps.attacker_prompt_id if turn >= 2 else None,
                        attacker_prompt_version=deps.attacker_prompt_version if turn >= 2 else None,
                        judge_prompt_id=deps.judge_prompt_id if judged else None,
                        judge_prompt_version=deps.judge_prompt_version if judged else None)
    found, items = _record_evidence(state, deps)
    reply = state.get("pending_reply")
    canary = bool(state.get("pending_canary", False))
    events.turn_ended(turn=turn, source=f"library:{deps.seed_prompt.id}" if turn == 1 else
                      (deps.attacker_prompt or prompt_registry.attacker_id(deps.seed_prompt.family)),
                      message_chars=len(state["pending_message"]),
                      reply_chars=None if reply is None else len(reply),
                      reply_truncated=bool(state.get("pending_truncated", False)), canary_hit=canary,
                      hard_evidence=bool(items), judged=judged,
                      verdict=state.get("last_verdict") if judged else None, attacker_generated=turn >= 2,
                      evidence_kinds=found.kinds if found is not None else [],
                      evidence_count=len(items))
    return {"conversation": _conversation_delta(state), "turns_used": turn}


# ---- a replay's own attacker and record nodes (feature 012) ----


def _replay_turn_source(source_turn: Turn, family: str) -> str:
    """The replay turn-line's `source` field, turn 2 onward (review item 10): a source turn from before feature
    009 (prompt provenance) stores neither `attacker_prompt_id` nor `attacker_prompt_version`, so copying them
    verbatim would render `"None@None"`. Falls back the same way the live path's own record node does for an
    unknown reference - the bare family-based id (`prompt_registry.attacker_id`) - when no id is stored at all;
    `@N` is appended only when a version is actually known, never `"<id>@None"`."""
    if source_turn.attacker_prompt_id is None:
        return prompt_registry.attacker_id(family)
    if source_turn.attacker_prompt_version is None:
        return source_turn.attacker_prompt_id
    return f"{source_turn.attacker_prompt_id}@{source_turn.attacker_prompt_version}"


def _replay_attacker_node(state: _ReplayState, runtime: Runtime[_ReplayDeps]) -> _ReplayState:
    deps = runtime.context
    turn = state["turns_used"] + 1
    events.turn_started(turn)
    if turn <= len(deps.source_turns):
        return {"pending_message": deps.source_turns[turn - 1].attacker_message, "pending_canary": False,
                "pending_evidence": None}
    # Defensive: unreachable while max_turns <= len(source_turns), the same decide-step turn-cap shape
    # (research D2) in case this is ever called with a looser max_turns.
    return {"outcome": Outcome(verdict=state["last_verdict"] or "unclear", hard_evidence=False,
                               reason=state.get("last_reason") or INTERRUPTED_BY_DEADLINE,
                               judge_used=state["judge_used"], stopping_condition="turn_cap", succeeded_turn=None)}


def _replay_record_node(state: _ReplayState, runtime: Runtime[_ReplayDeps]) -> _ReplayState:
    deps = runtime.context
    turn = state["turns_used"] + 1
    judged = state.get("last_judged_turn") == turn
    source_turn = deps.source_turns[turn - 1]   # the same index the attacker node used for this same turn (T018)
    deps.store.add_turn(deps.run_id, position=turn, attacker_message=state["pending_message"],
                        reply_text=state.get("pending_reply"),
                        reply_truncated=state.get("pending_truncated", False),
                        judge_verdict=state.get("last_verdict"), judge_reason=state.get("last_reason"),
                        judge_progress=state.get("last_progress"),
                        attacker_prompt_id=source_turn.attacker_prompt_id,
                        attacker_prompt_version=source_turn.attacker_prompt_version,
                        judge_prompt_id=deps.judge_prompt_id if judged else None,
                        judge_prompt_version=deps.judge_prompt_version if judged else None)
    found, items = _record_evidence(state, deps)
    reply = state.get("pending_reply")
    canary = bool(state.get("pending_canary", False))
    source_label = (f"library:{deps.source.prompt_id}" if turn == 1
                    else _replay_turn_source(source_turn, deps.source.family))
    events.turn_ended(turn=turn, source=source_label, message_chars=len(state["pending_message"]),
                      reply_chars=None if reply is None else len(reply),
                      reply_truncated=bool(state.get("pending_truncated", False)), canary_hit=canary,
                      hard_evidence=bool(items), judged=judged,
                      verdict=state.get("last_verdict") if judged else None, attacker_generated=False,
                      evidence_kinds=found.kinds if found is not None else [],
                      evidence_count=len(items))
    # Any evidence item of any kind decides this turn (013/FR-035, research D23) - never the canary alone.
    result = "succeeded" if items else (state.get("last_verdict") if judged else None)
    return {"conversation": _conversation_delta(state), "turns_used": turn, "turn_results": [result]}


# ---- the two graphs, compiled once at import ----


def _wire(graph: StateGraph[Any, _DepsT, Any, Any]) -> None:
    """The six-node shape both graphs share, minus the two nodes each defines for itself: a send failure skips
    the evidence and the judge, any evidence item skips the judge, and the decide step loops or ends."""
    graph.add_node("send", _send_node)
    graph.add_node("evidence", _evidence_node)
    graph.add_node("judge", _judge_node)
    graph.add_node("decide", _decide_node)
    graph.add_edge(START, "attacker")
    graph.add_conditional_edges("attacker", lambda s: "end" if s.get("outcome") else "send",
                                {"end": END, "send": "send"})
    graph.add_conditional_edges("send", lambda s: "record" if s.get("outcome") else "evidence",
                                {"record": "record", "evidence": "evidence"})
    graph.add_conditional_edges("evidence", lambda s: "record" if s.get("outcome") else "judge",
                                {"record": "record", "judge": "judge"})
    graph.add_edge("judge", "record")
    graph.add_edge("record", "decide")
    graph.add_conditional_edges("decide", lambda s: "end" if s.get("outcome") else "attacker",
                                {"end": END, "attacker": "attacker"})


def _compile_live():
    graph = StateGraph(_State, context_schema=_LiveDeps)
    graph.add_node("attacker", _live_attacker_node)
    graph.add_node("record", _live_record_node)
    _wire(graph)
    return graph.compile()


def _compile_replay():
    graph = StateGraph(_ReplayState, context_schema=_ReplayDeps)
    graph.add_node("attacker", _replay_attacker_node)
    graph.add_node("record", _replay_record_node)
    _wire(graph)
    return graph.compile()


LIVE_GRAPH = _compile_live()
REPLAY_GRAPH = _compile_replay()


def _recursion_limit(max_turns: int) -> dict[str, Any]:
    """Allow enough node steps for the deepest run: ~6 nodes per turn."""
    return {"recursion_limit": max(25, max_turns * 8)}


async def run_adaptive(store: TargetStore, *, target_id: int, seed_prompt: AttackPrompt, attacker_source: str,
                       canaries: list[str], resolved: ResolvedSettings, attacker: _Attacker, judge: _Judge,
                       sender: Sender = run_test, mode: str = "local", transport=None, resolver=default_resolver,
                       max_turns: int, token_budget: int, time_limit_s: float,
                       use_prior_experience: bool = True, hint_provider: Callable[[list], str | None] | None = None,
                       clock: Callable[[], float] = time.monotonic,
                       evidence: EvidenceChecker | None = None) -> Run:
    """Claim an adaptive run, drive the loop to an outcome, finish and return it. May raise RunInProgress (409).

    `hint_provider(conversation)` (feature 004) returns the attacker's background block each turn, or None.
    `evidence` (feature 013) is the run's deterministic checker; None is the canary-only checker - today's
    behaviour exactly (013/FR-002, research D2)."""
    checker = evidence if evidence is not None else EvidenceChecker.canary_only(canaries, family=seed_prompt.family,
                                                                                 store=store)
    # Turn 1 sends the seed with any planted task placed at its insertion point (013/FR-011); the stored
    # prompt_text is that same text, so a replay re-sends exactly what went out (013/FR-035).
    opening = checker.opening_message(seed_prompt)
    run_id = store.claim_run(target_id, prompt_id=seed_prompt.id, prompt_title=seed_prompt.title,
                             prompt_text=opening, family=seed_prompt.family,
                             owasp_category=seed_prompt.owasp_category, attacker_source=attacker_source,
                             mode="adaptive", attacker_model=attacker.model, turn_budget=max_turns,
                             token_budget=token_budget, time_limit_s=int(time_limit_s),
                             use_prior_experience=use_prior_experience)
    checker.bind_run(run_id)   # records what the run planted, right after the claim (013/FR-008)
    deadline = clock() + time_limit_s
    # Prompt-version provenance (feature 009, FR-003): the attacker (per family) and judge prompt versions are
    # constant for the run. Feature 010 (FR-007, D15): they are the references the clients actually send — a pinned
    # A/B arm's version, not the active one — the same source the log lines use; judge provenance is recorded only
    # when a judge request was made.
    attacker_prompt = attacker_ref(attacker, seed_prompt.family)
    judge_prompt = judge_ref(judge) if judge.configured else None
    attacker_prompt_id, attacker_prompt_version = prompt_registry.split_ref(attacker_prompt)
    judge_prompt_id, judge_prompt_version = prompt_registry.split_ref(judge_prompt)
    events.run_started(store, run_id=run_id, target_id=target_id, mode="adaptive", family=seed_prompt.family,
                       prompt_id=seed_prompt.id, attacker_source=attacker_source, attacker_model=attacker.model,
                       judge_model=judge.model if judge.configured else None, attacker_prompt=attacker_prompt,
                       judge_prompt=judge_prompt, turn_budget=max_turns, token_budget=token_budget,
                       time_limit_s=int(time_limit_s), use_prior_experience=use_prior_experience,
                       **checker.run_start_fields())
    deps = _LiveDeps(store=store, run_id=run_id, resolved=resolved, secrets=[value for _, value in resolved.headers],
                     mode=mode, sender=sender, transport=transport, resolver=resolver, judge=judge,
                     judge_prompt=judge_prompt, judge_prompt_id=judge_prompt_id,
                     judge_prompt_version=judge_prompt_version, checker=checker, max_turns=max_turns,
                     token_budget=token_budget, deadline=deadline, clock=clock,
                     seed_prompt=seed_prompt, opening=opening, attacker=attacker, hint_provider=hint_provider,
                     attacker_prompt=attacker_prompt, attacker_prompt_id=attacker_prompt_id,
                     attacker_prompt_version=attacker_prompt_version)
    final = await LIVE_GRAPH.ainvoke(_initial_state(), _recursion_limit(max_turns), context=deps)
    outcome: Outcome = final["outcome"]
    requested = final["judge_requests"]
    run = store.finish_run(run_id, verdict=outcome.verdict, hard_evidence=outcome.hard_evidence,
                           reason=outcome.reason, judge_used=outcome.judge_used,
                           judge_model=judge.model if outcome.judge_used else None,
                           failure_step=outcome.failure_step, stopping_condition=outcome.stopping_condition,
                           succeeded_turn=outcome.succeeded_turn, turns_used=final["turns_used"],
                           tokens_used=final["tokens_used"],
                           judge_prompt_id=judge_prompt_id if requested else None,
                           judge_prompt_version=judge_prompt_version if requested else None)
    events.run_finished(run)   # run.end is emitted by the caller's run scope, after the write-back (FR-001)
    return run


async def run_replay_adaptive(store: TargetStore, *, target_id: int, source: Run, source_turns: list[Turn],
                              canaries: list[str], resolved: ResolvedSettings, judge: _Judge, sender: Sender = run_test,
                              mode: str = "local", transport: Any = None, resolver: Any = default_resolver,
                              max_turns: int, token_budget: int, time_limit_s: float,
                              clock: Callable[[], float] = time.monotonic,
                              evidence: EvidenceChecker | None = None) -> Run:
    """Replay an adaptive source, turn by turn, with no attacker-model call (feature 012, FR-001, FR-002,
    FR-007 to FR-011). `run_adaptive`'s six-node shape, minus `hint_provider` (a replay never calls the
    experience store, FR-025), sharing the send, evidence, judge and decide nodes and replacing the attacker and
    record nodes with ones that look up the next recorded message instead of calling a model. `max_turns` is
    already `min(len(source_turns), the currently configured adaptive turn cap)` by the time it reaches here (the
    caller's job, research D2): "ran out of recorded messages" and "hit the turn cap" are therefore the same
    decide-step path, needing no new stopping condition.

    On an unexpected failure, closes the row inconclusive and raises `kestrel.replay.ReplayFailed(run_id)`,
    chained from the original error - a deliberate *addition* over `run_adaptive`, which has no such handler and
    is not given one (FR-049; research D15).

    Feature 013: the replay copies the source's planted tokens to its own row, armed state included, and builds
    its checker from those copies (`evidence=None`), so the override check verifies against the source's token
    and a message that disarmed the source disarms the replay at the same turn (013/FR-035); a source that
    planted nothing gives it no tokens (013/FR-036). Each turn's `turn_results` entry is derived from whether
    that turn produced any evidence item, never from the canary flag alone (013/FR-035, research D23)."""
    from kestrel.replay import ReplayFailed, compute_outcome   # lazy: avoids a module-level cycle (research D14)

    run_id = store.claim_run(target_id, prompt_id=source.prompt_id, prompt_title=source.prompt_title,
                             prompt_text=source.prompt_text, family=source.family,
                             owasp_category=source.owasp_category, attacker_source=source.attacker_source,
                             mode="replay", attacker_model=None, turn_budget=max_turns, token_budget=token_budget,
                             time_limit_s=int(time_limit_s), use_prior_experience=False, source_run_id=source.id)
    # The claim and everything after it is one protected region (review round 2, item 1): a failure anywhere
    # below - judge_ref, building the dependencies, the graph run included - must still close the row, never
    # leave it in_progress (locking the target) until the start-up sweep. The try wraps the whole rest of the
    # function, including the final finish_run on the success path.
    try:
        deadline = clock() + time_limit_s
        store.copy_planted_tokens(source.id, run_id)
        checker = evidence if evidence is not None else build_checker(
            store=store, family=source.family, canaries=canaries, mode=mode, transport=transport,
            resolver=resolver, planted=store.list_planted_tokens(run_id),
            mask=[value for _, value in resolved.headers] + [resolved.url])
        checker.bind_run(run_id)
        judge_prompt = judge_ref(judge) if judge.configured else None
        judge_prompt_id, judge_prompt_version = prompt_registry.split_ref(judge_prompt)
        events.run_started(store, run_id=run_id, target_id=target_id, mode="replay", family=source.family,
                           prompt_id=source.prompt_id, attacker_source=source.attacker_source, attacker_model=None,
                           judge_model=judge.model if judge.configured else None, judge_prompt=judge_prompt,
                           turn_budget=max_turns, token_budget=token_budget, time_limit_s=int(time_limit_s),
                           use_prior_experience=False, source_run_id=source.id, **checker.run_start_fields())
        deps = _ReplayDeps(store=store, run_id=run_id, resolved=resolved,
                           secrets=[value for _, value in resolved.headers], mode=mode, sender=sender,
                           transport=transport, resolver=resolver, judge=judge, judge_prompt=judge_prompt,
                           judge_prompt_id=judge_prompt_id, judge_prompt_version=judge_prompt_version,
                           checker=checker, max_turns=max_turns, token_budget=token_budget, deadline=deadline,
                           clock=clock, source=source, source_turns=source_turns)
        initial: _ReplayState = {**_initial_state(), "turn_results": []}
        final = await REPLAY_GRAPH.ainvoke(initial, _recursion_limit(max_turns), context=deps)
        outcome: Outcome = final["outcome"]
        requested = final["judge_requests"]
        replay_outcome = compute_outcome(final["turn_results"], len(source_turns), source.succeeded_turn)
        run = store.finish_run(run_id, verdict=outcome.verdict, hard_evidence=outcome.hard_evidence,
                               reason=outcome.reason, judge_used=outcome.judge_used,
                               judge_model=judge.model if outcome.judge_used else None,
                               failure_step=outcome.failure_step, stopping_condition=outcome.stopping_condition,
                               succeeded_turn=outcome.succeeded_turn, turns_used=final["turns_used"],
                               tokens_used=final["tokens_used"],
                               judge_prompt_id=judge_prompt_id if requested else None,
                               judge_prompt_version=judge_prompt_version if requested else None,
                               replay_outcome=replay_outcome)
        events.run_finished(run)
        return run
    except Exception as error:
        closed = store.finish_run(run_id, verdict="unclear", reason="The run failed unexpectedly.",
                                  replay_outcome="inconclusive")
        events.run_finished(closed)
        raise ReplayFailed(run_id) from error
