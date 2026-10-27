"""The adaptive attacker/judge loop as a LangGraph graph (contracts/adaptive-loop.md, Principle X).

LangGraph orchestrates; the attacker and judge model calls are plain httpx (their own clients). The loop claims a
run row, drives the conversation turn by turn under three caps, and finishes the row. Canary first, judge only if
nothing matched (Principle II); hard_evidence comes from a canary alone. Every message and reply is masked before
it is stored, judged or handed to the attacker (Principle IV, FR-021). No attack text lives here.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Protocol, Sequence
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from kestrel.attack.attacker import AttackerError
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings, TestOutcome, run_test
from kestrel.judge.client import JudgeError
from kestrel.runs import match_canary
from kestrel.secrets import mask_values
from kestrel.store import Run, TargetStore

log = logging.getLogger("kestrel")

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


class _State(TypedDict, total=False):
    conversation: list[tuple[str, str]]   # (role, masked text) so far
    turns_used: int
    tokens_used: int
    judge_used: bool
    last_verdict: str | None
    last_progress: str | None
    last_reason: str | None
    pending_message: str                  # this turn's attacker message, masked
    pending_reply: str | None
    pending_truncated: bool
    outcome: dict[str, Any] | None        # set exactly once, when the run ends


def _format(conversation: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{'attacker' if role == 'attacker' else 'agent'}: {text}" for role, text in conversation)


async def run_adaptive(store: TargetStore, *, target_id: int, seed_prompt: AttackPrompt, attacker_source: str,
                       canaries: list[str], resolved: ResolvedSettings, attacker: _Attacker, judge: _Judge,
                       sender: Sender = run_test, mode: str = "local", transport=None, resolver=default_resolver,
                       max_turns: int, token_budget: int, time_limit_s: float,
                       use_prior_experience: bool = True, hint_provider: Callable[[list], str | None] | None = None,
                       clock: Callable[[], float] = time.monotonic) -> Run:
    """Claim an adaptive run, drive the loop to an outcome, finish and return it. May raise RunInProgress (409).

    `hint_provider(conversation)` (feature 004) returns the attacker's background block each turn, or None."""
    run_id = store.claim_run(target_id, prompt_id=seed_prompt.id, prompt_title=seed_prompt.title,
                             prompt_text=seed_prompt.text, family=seed_prompt.family,
                             owasp_category=seed_prompt.owasp_category, attacker_source=attacker_source,
                             mode="adaptive", attacker_model=attacker.model, turn_budget=max_turns,
                             token_budget=token_budget, time_limit_s=int(time_limit_s),
                             use_prior_experience=use_prior_experience)
    deadline = clock() + time_limit_s
    secrets = [value for _, value in resolved.headers]

    def remaining() -> float:
        return deadline - clock()

    async def attacker_node(state: _State) -> _State:
        turn = state["turns_used"] + 1
        if turn == 1:
            return {"pending_message": mask_values(seed_prompt.text, secrets)}
        hints = None
        if hint_provider is not None:
            try:
                hints = hint_provider(state["conversation"])   # best-effort; a retrieval failure never fails the run
            except Exception:
                log.exception("retrieving experience hints failed; continuing without them for run %s", run_id)
        try:
            reply = await attacker.next_message(conversation=state["conversation"], family=seed_prompt.family,
                                                progress=state["last_progress"], hints=hints,
                                                timeout=max(0.1, min(ATTACKER_LIMIT_S, remaining())))
        except AttackerError as error:
            return {"outcome": {"verdict": "unclear", "hard_evidence": False, "reason": str(error),
                                "judge_used": state["judge_used"], "stopping_condition": "attacker_failed",
                                "succeeded_turn": None}}
        return {"pending_message": mask_values(reply.message, secrets),
                "tokens_used": state["tokens_used"] + reply.tokens}

    async def send_node(state: _State) -> _State:
        outcome = await sender(resolved, mode=mode, display_name="", transport=transport, resolver=resolver,
                               deadline_s=max(0.1, min(SEND_LIMIT_S, remaining())), prompt=state["pending_message"])
        if not outcome.ok:
            return {"pending_reply": None, "pending_truncated": False,
                    "outcome": {"verdict": None, "hard_evidence": False, "reason": outcome.message,
                                "judge_used": state["judge_used"], "stopping_condition": "send_failed",
                                "succeeded_turn": None, "failure_step": outcome.step}}
        reply = mask_values(outcome.reply_text or "", secrets)[:MAX_REPLY_CHARS]
        return {"pending_reply": reply, "pending_truncated": bool(outcome.reply_truncated)}

    def evidence_node(state: _State) -> _State:
        if match_canary(state["pending_reply"] or "", canaries) is not None:
            return {"outcome": {"verdict": "succeeded", "hard_evidence": True, "reason": CANARY_REASON,
                                "judge_used": state["judge_used"], "stopping_condition": "succeeded",
                                "succeeded_turn": state["turns_used"] + 1}}
        return {}

    async def judge_node(state: _State) -> _State:
        if not judge.configured:
            return {"judge_used": True, "last_verdict": "unclear", "last_reason": "No judge is configured.",
                    "last_progress": state["last_progress"]}
        conversation = list(state["conversation"]) + [("attacker", state["pending_message"]),
                                                      ("agent", state["pending_reply"] or "")]
        try:
            verdict = await judge.judge(attack=state["pending_message"], reply=state["pending_reply"] or "",
                                        conversation=_format(conversation),
                                        timeout=max(0.1, min(JUDGE_LIMIT_S, remaining())))
        except JudgeError as error:
            return {"judge_used": True, "last_verdict": "unclear", "last_reason": f"The judge could not decide: {error}",
                    "last_progress": state["last_progress"]}
        update: _State = {"judge_used": True, "tokens_used": state["tokens_used"] + verdict.tokens,
                          "last_verdict": verdict.verdict, "last_reason": verdict.reason,
                          "last_progress": verdict.progress}
        if verdict.verdict == "succeeded":
            update["outcome"] = {"verdict": "succeeded", "hard_evidence": False, "reason": verdict.reason,
                                 "judge_used": True, "stopping_condition": "succeeded",
                                 "succeeded_turn": state["turns_used"] + 1}
        return update

    def record_node(state: _State) -> _State:
        turn = state["turns_used"] + 1
        store.add_turn(run_id, position=turn, attacker_message=state["pending_message"],
                       reply_text=state.get("pending_reply"), reply_truncated=state.get("pending_truncated", False),
                       judge_verdict=state.get("last_verdict"), judge_reason=state.get("last_reason"),
                       judge_progress=state.get("last_progress"))
        conversation = list(state["conversation"]) + [("attacker", state["pending_message"])]
        if state.get("pending_reply") is not None:
            conversation.append(("agent", state["pending_reply"]))
        return {"conversation": conversation, "turns_used": turn}

    def decide_node(state: _State) -> _State:
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
            return {"outcome": {"verdict": state["last_verdict"] or "unclear", "hard_evidence": False,
                                "reason": state.get("last_reason") or INTERRUPTED_BY_DEADLINE,
                                "judge_used": state["judge_used"], "stopping_condition": cap,
                                "succeeded_turn": None}}
        return {}

    graph = StateGraph(_State)
    graph.add_node("attacker", attacker_node)
    graph.add_node("send", send_node)
    graph.add_node("evidence", evidence_node)
    graph.add_node("judge", judge_node)
    graph.add_node("record", record_node)
    graph.add_node("decide", decide_node)
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
    compiled = graph.compile()

    initial: _State = {"conversation": [], "turns_used": 0, "tokens_used": 0, "judge_used": False,
                       "last_verdict": None, "last_progress": None, "last_reason": None, "outcome": None}
    # Allow enough node steps for the deepest run: ~6 nodes per turn.
    final = await compiled.ainvoke(initial, {"recursion_limit": max(25, max_turns * 8)})
    outcome = final["outcome"]
    run = store.finish_run(run_id, verdict=outcome["verdict"], hard_evidence=outcome["hard_evidence"],
                           reason=outcome["reason"], judge_used=outcome["judge_used"],
                           judge_model=judge.model if outcome["judge_used"] else None,
                           failure_step=outcome.get("failure_step"), stopping_condition=outcome["stopping_condition"],
                           succeeded_turn=outcome["succeeded_turn"], turns_used=final["turns_used"],
                           tokens_used=final["tokens_used"])
    log.info("adaptive run target_id=%d family=%s verdict=%s hard_evidence=%s stop=%s attacker=%s judge=%s "
             "turns=%s tokens=%s", run.target_id, run.family, run.verdict or "-", run.hard_evidence,
             run.stopping_condition, attacker.model, judge.model if outcome["judge_used"] else "-",
             run.turns_used, run.tokens_used)
    return run
