"""The adaptive attacker/judge loop as a LangGraph graph (contracts/adaptive-loop.md, Principle X).

LangGraph orchestrates; the attacker and judge model calls are plain httpx (their own clients). The loop claims a
run row, drives the conversation turn by turn under three caps, and finishes the row. The deterministic checks
first, the judge only if none found evidence (Principle II; feature 013: the evidence checker runs the canary and
the two reply detectors in the fixed order of 013/FR-001, and `evidence_node` delegates to it); hard_evidence comes
from a deterministic check alone. Every message and reply is masked before it is stored, judged or handed to the
attacker (Principle IV, FR-021). No attack text lives here. Feature 010: the loop emits `run.start` once the row is
claimed and one `turn` line per recorded turn (lengths, categories, totals); the turn number and the turn span
ride on the shared run context, which every graph node sees.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Protocol, Sequence
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from kestrel import events, prompt_registry
from kestrel.attack.attacker import AttackerError
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings, TestOutcome, run_test, secret_values
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


class _State(TypedDict, total=False):
    conversation: list[tuple[str, str]]   # (role, masked text) so far
    turns_used: int
    tokens_used: int
    judge_used: bool
    last_verdict: str | None
    last_progress: str | None
    last_reason: str | None
    last_judged_turn: int                 # the turn the judge last produced a verdict on (feature 009)
    pending_message: str                  # this turn's attacker message, masked
    pending_reply: str | None
    pending_truncated: bool
    pending_canary: bool                  # a canary matched this turn's reply (feature 010: the turn line)
    pending_evidence: TurnEvidence | None  # this turn's deterministic findings (feature 013); None before the check
    outcome: dict[str, Any] | None        # set exactly once, when the run ends


def _format(conversation: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{'attacker' if role == 'attacker' else 'agent'}: {text}" for role, text in conversation)


# ---- per-turn nodes shared by a live run (run_adaptive) and a replay (run_replay_adaptive, feature 012) ----
#
# judge_node, send_node, evidence_node and decide_node are identical in substance whether this turn's message
# came from the attacker model or from a recorded transcript (FR-008: the per-turn judge-call shape is explicitly
# unchanged for a replay), so their bodies live here, as module-level functions parameterised by what they used
# to close over; both run_adaptive and run_replay_adaptive wire a thin node closure to each (research D14). This
# is a mechanical, behaviour-preserving extraction - run_adaptive's own existing tests pass unmodified afterward.
# attacker_node and record_node are NOT shared (a model call versus a list lookup; run-wide-constant provenance
# versus per-turn copied provenance) and stay defined separately, beside each other, inside their own function.


async def _judge_turn(state: _State, *, judge: _Judge, judge_prompt: str | None,
                      remaining: Callable[[], float], requests: list[int]) -> _State:
    """judge_node's existing body, unchanged in substance: identical conversation shape, identical token/event
    accounting. `requests` is a one-item mutable counter (a closure can mutate a list in place but cannot rebind
    an int by reference): the caller's own `judge_requests` becomes `requests[0] += 1` here."""
    if not judge.configured:
        return {"judge_used": True, "last_verdict": "unclear", "last_reason": "No judge is configured.",
                "last_progress": state["last_progress"]}
    conversation = list(state["conversation"]) + [("attacker", state["pending_message"]),
                                                  ("agent", state["pending_reply"] or "")]
    requests[0] += 1
    events.judge_requested(judge_prompt)
    try:
        verdict = await judge.judge(attack=state["pending_message"], reply=state["pending_reply"] or "",
                                    conversation=_format(conversation),
                                    timeout=max(0.1, min(JUDGE_LIMIT_S, remaining())))
    except JudgeError as error:
        return {"judge_used": True, "last_verdict": "unclear", "last_reason": f"The judge could not decide: {error}",
                "last_progress": state["last_progress"]}
    update: _State = {"judge_used": True, "tokens_used": state["tokens_used"] + verdict.tokens,
                      "last_verdict": verdict.verdict, "last_reason": verdict.reason,
                      "last_progress": verdict.progress, "last_judged_turn": state["turns_used"] + 1}
    if verdict.verdict == "succeeded":
        update["outcome"] = {"verdict": "succeeded", "hard_evidence": False, "reason": verdict.reason,
                             "judge_used": True, "stopping_condition": "succeeded",
                             "succeeded_turn": state["turns_used"] + 1}
    return update


async def _send_turn(state: _State, *, resolved: ResolvedSettings, mode: str, sender: Sender, transport: Any,
                     resolver: Any, remaining: Callable[[], float], secrets: list[str],
                     evidence: EvidenceChecker) -> _State:
    """send_node's existing body, unchanged in substance (stated explicitly so the lift cannot silently drop it):
    still masks the reply with `mask_values(outcome.reply_text or "", secrets)` before returning it - a replay's
    own stored reply is masked exactly as a live run's is, never the attacker message (which arrives already
    masked, FR-001). `secrets` is a parameter, not something this function closes over - run_adaptive and
    run_replay_adaptive each pass their own target's secret values. Feature 013: every message is handed to the
    checker's `note_sent` before it goes out - the one place both a live run's and a replay's messages pass
    through - so the override token is disarmed by the text actually sent (013/FR-012, FR-035)."""
    evidence.note_sent(state["pending_message"], state["turns_used"] + 1)
    outcome = await sender(resolved, mode=mode, display_name="", transport=transport, resolver=resolver,
                           deadline_s=max(0.1, min(SEND_LIMIT_S, remaining())), prompt=state["pending_message"],
                           extra_headers=evidence.extra_headers)   # the correlation header, if any (013/FR-022)
    if not outcome.ok:
        return {"pending_reply": None, "pending_truncated": False,
                "outcome": {"verdict": None, "hard_evidence": False, "reason": outcome.message,
                            "judge_used": state["judge_used"], "stopping_condition": "send_failed",
                            "succeeded_turn": None, "failure_step": outcome.step}}
    reply = mask_values(outcome.reply_text or "", secrets)[:MAX_REPLY_CHARS]
    return {"pending_reply": reply, "pending_truncated": bool(outcome.reply_truncated)}


async def _check_evidence(state: _State, evidence: EvidenceChecker, remaining: Callable[[], float]) -> _State:
    """evidence_node's body: the checker's deterministic checks over this turn's reply, in the fixed order
    (013/FR-001). Any item ends the run as succeeded with hard evidence and no judge call (013/FR-002);
    `pending_canary` keeps its narrower meaning (a canary matched) for the turn line's `canary_hit`."""
    found = await evidence.check_turn(state["turns_used"] + 1, state["pending_reply"] or "", remaining)
    events.evidence_check(checks=found.checks, evidence_kinds=found.kinds, evidence_count=len(found.items),
                          side_channel_status=found.side_channel_status, callback_wait_ms=found.callback_wait_ms,
                          state_changed_keys=found.state_changed_keys)
    update: _State = {"pending_canary": found.canary_hit, "pending_evidence": found}
    if found.items:
        update["outcome"] = {"verdict": "succeeded", "hard_evidence": True, "reason": found.reason,
                             "judge_used": state["judge_used"], "stopping_condition": "succeeded",
                             "succeeded_turn": state["turns_used"] + 1}
    return update


def _decide_next(state: _State, *, max_turns: int, token_budget: int, remaining: Callable[[], float]) -> _State:
    """decide_node's existing body, unchanged in substance. For a replay (research D2), `max_turns` is already
    `min(len(source's recorded messages), the currently configured adaptive turn cap)`, so "ran out of recorded
    messages" and "hit the turn cap" are the same `stopping_condition == "turn_cap"` value this already produces -
    no new stopping condition is needed to tell the two apart from inside the graph."""
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
                             use_prior_experience=use_prior_experience,
                             correlation_id=checker.correlation_id,            # 013/FR-022, FR-034: a side-channel
                             side_channel_status=checker.side_channel_status)   # target's id and status at claim time
    checker.bind_run(run_id)   # records what the run planted, right after the claim (013/FR-008)
    deadline = clock() + time_limit_s
    secrets = secret_values(resolved)   # the target's auth values and the side channel's (013/FR-071)
    # Prompt-version provenance (feature 009, FR-003): the attacker (per family) and judge prompt versions are
    # constant for the run. Feature 010 (FR-007, D15): they are the references the clients actually send — a pinned
    # A/B arm's version, not the active one — the same source the log lines use; judge provenance is recorded only
    # when a judge request was made.
    attacker_prompt = attacker_ref(attacker, seed_prompt.family)
    judge_prompt = judge_ref(judge) if judge.configured else None
    attacker_prompt_id, attacker_prompt_version = prompt_registry.split_ref(attacker_prompt)
    judge_prompt_id, judge_prompt_version = prompt_registry.split_ref(judge_prompt)
    judge_requests_box = [0]   # a one-item mutable counter: a closure can mutate a list, not rebind an int
    events.run_started(store, run_id=run_id, target_id=target_id, mode="adaptive", family=seed_prompt.family,
                       prompt_id=seed_prompt.id, attacker_source=attacker_source, attacker_model=attacker.model,
                       judge_model=judge.model if judge.configured else None, attacker_prompt=attacker_prompt,
                       judge_prompt=judge_prompt, turn_budget=max_turns, token_budget=token_budget,
                       time_limit_s=int(time_limit_s), use_prior_experience=use_prior_experience,
                       **checker.run_start_fields())

    def remaining() -> float:
        return deadline - clock()

    async def attacker_node(state: _State) -> _State:
        turn = state["turns_used"] + 1
        events.turn_started(turn)   # every line of this turn carries its number, through all the nodes
        if turn == 1:
            return {"pending_message": mask_values(opening, secrets), "pending_canary": False,
                    "pending_evidence": None}
        hints = None
        if hint_provider is not None:
            try:
                hints = hint_provider(state["conversation"])   # best-effort; a retrieval failure never fails the run
            except Exception:
                events.emit("memory.retrieval_failed", logging.WARNING, exc_info=True)
        try:
            reply = await attacker.next_message(conversation=state["conversation"], family=seed_prompt.family,
                                                progress=state["last_progress"], hints=hints,
                                                timeout=max(0.1, min(ATTACKER_LIMIT_S, remaining())))
        except AttackerError as error:
            return {"outcome": {"verdict": "unclear", "hard_evidence": False, "reason": str(error),
                                "judge_used": state["judge_used"], "stopping_condition": "attacker_failed",
                                "succeeded_turn": None}}
        return {"pending_message": mask_values(reply.message, secrets), "pending_canary": False,
                "pending_evidence": None, "tokens_used": state["tokens_used"] + reply.tokens}

    async def send_node(state: _State) -> _State:
        return await _send_turn(state, resolved=resolved, mode=mode, sender=sender, transport=transport,
                                resolver=resolver, remaining=remaining, secrets=secrets, evidence=checker)

    async def evidence_node(state: _State) -> _State:
        return await _check_evidence(state, checker, remaining)

    async def judge_node(state: _State) -> _State:
        return await _judge_turn(state, judge=judge, judge_prompt=judge_prompt, remaining=remaining,
                                 requests=judge_requests_box)

    def record_node(state: _State) -> _State:
        turn = state["turns_used"] + 1
        judged = state.get("last_judged_turn") == turn   # the judge produced a verdict on this turn (feature 009)
        store.add_turn(run_id, position=turn, attacker_message=state["pending_message"],
                       reply_text=state.get("pending_reply"), reply_truncated=state.get("pending_truncated", False),
                       judge_verdict=state.get("last_verdict"), judge_reason=state.get("last_reason"),
                       judge_progress=state.get("last_progress"),
                       attacker_prompt_id=attacker_prompt_id if turn >= 2 else None,
                       attacker_prompt_version=attacker_prompt_version if turn >= 2 else None,
                       judge_prompt_id=judge_prompt_id if judged else None,
                       judge_prompt_version=judge_prompt_version if judged else None)
        found = state.get("pending_evidence")
        items = found.items if found is not None else []
        if items:   # the turn's evidence items, right after its turn row (013/FR-003)
            store.add_evidence(run_id, items)
        reply = state.get("pending_reply")
        canary = bool(state.get("pending_canary", False))
        events.turn_ended(turn=turn, source=f"library:{seed_prompt.id}" if turn == 1 else
                          (attacker_prompt or prompt_registry.attacker_id(seed_prompt.family)),
                          message_chars=len(state["pending_message"]),
                          reply_chars=None if reply is None else len(reply),
                          reply_truncated=bool(state.get("pending_truncated", False)), canary_hit=canary,
                          hard_evidence=bool(items), judged=judged,
                          verdict=state.get("last_verdict") if judged else None, attacker_generated=turn >= 2,
                          evidence_kinds=found.kinds if found is not None else [],
                          evidence_count=len(items))
        conversation = list(state["conversation"]) + [("attacker", state["pending_message"])]
        if state.get("pending_reply") is not None:
            conversation.append(("agent", state["pending_reply"]))
        return {"conversation": conversation, "turns_used": turn}

    def decide_node(state: _State) -> _State:
        return _decide_next(state, max_turns=max_turns, token_budget=token_budget, remaining=remaining)

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
                           tokens_used=final["tokens_used"],
                           judge_prompt_id=judge_prompt_id if judge_requests_box[0] else None,
                           judge_prompt_version=judge_prompt_version if judge_requests_box[0] else None)
    events.run_finished(run)   # run.end is emitted by the caller's run scope, after the write-back (FR-001)
    return run


def _replay_turn_source(source_turn: Turn, family: str) -> str:
    """The replay turn-line's `source` field, turn 2 onward (review item 10): a source turn from before feature
    009 (prompt provenance) stores neither `attacker_prompt_id` nor `attacker_prompt_version`, so copying them
    verbatim would render `"None@None"`. Falls back the same way the live path's own `record_node` does for an
    unknown reference - the bare family-based id (`prompt_registry.attacker_id`) - when no id is stored at all;
    `@N` is appended only when a version is actually known, never `"<id>@None"`."""
    if source_turn.attacker_prompt_id is None:
        return prompt_registry.attacker_id(family)
    if source_turn.attacker_prompt_version is None:
        return source_turn.attacker_prompt_id
    return f"{source_turn.attacker_prompt_id}@{source_turn.attacker_prompt_version}"


async def run_replay_adaptive(store: TargetStore, *, target_id: int, source: Run, source_turns: list[Turn],
                              canaries: list[str], resolved: ResolvedSettings, judge: _Judge, sender: Sender = run_test,
                              mode: str = "local", transport: Any = None, resolver: Any = default_resolver,
                              max_turns: int, token_budget: int, time_limit_s: float,
                              clock: Callable[[], float] = time.monotonic,
                              evidence: EvidenceChecker | None = None, target: Any = None,
                              settings: Any = None) -> Run:
    """Replay an adaptive source, turn by turn, with no attacker-model call (feature 012, FR-001, FR-002,
    FR-007 to FR-011). `run_adaptive`'s six-node shape, minus `hint_provider` (a replay never calls the
    experience store, FR-025), sharing `_judge_turn`/`_send_turn`/`_check_evidence`/`_decide_next` (above) and
    replacing `attacker_node`/`record_node` with ones that look up the next recorded message instead of calling a
    model. `max_turns` is already `min(len(source_turns), the currently configured adaptive turn cap)` by the time
    it reaches here (the caller's job, research D2): "ran out of recorded messages" and "hit the turn cap" are
    therefore the same `decide_node` path, needing no new stopping condition.

    On an unexpected failure, closes the row inconclusive and raises `kestrel.replay.ReplayFailed(run_id)`,
    chained from the original error - a deliberate *addition* over `run_adaptive`, which has no such handler and
    is not given one (FR-049; research D15).

    Feature 013: the replay copies the source's planted tokens to its own row, armed state included, and builds
    its checker from those copies (`evidence=None`), so the override check verifies against the source's token
    and a message that disarmed the source disarms the replay at the same turn (013/FR-035); a source that
    planted nothing gives it no tokens (013/FR-036). Each turn's `turn_results` entry is derived from whether
    that turn produced any evidence item, never from the canary flag alone (013/FR-035, research D23)."""
    from kestrel.replay import ReplayFailed, compute_outcome   # lazy: avoids a module-level cycle (research D14)

    # The checker is built before the claim (feature 013 part 2): a side-channel target's correlation id and
    # `checked` status are written with the row (013/FR-022, FR-034). It verifies against the source's planted
    # tokens (copied to the replay's own row right after the claim); a failure here precedes the claim and
    # propagates bare, like any other pre-claim failure (`kestrel.replay.execute_replay`).
    checker = evidence if evidence is not None else build_checker(
        store=store, family=source.family, canaries=canaries, mode=mode, target=target, settings=settings,
        transport=transport, resolver=resolver, planted=store.list_planted_tokens(source.id),
        mask=secret_values(resolved) + [resolved.url])
    run_id = store.claim_run(target_id, prompt_id=source.prompt_id, prompt_title=source.prompt_title,
                             prompt_text=source.prompt_text, family=source.family,
                             owasp_category=source.owasp_category, attacker_source=source.attacker_source,
                             mode="replay", attacker_model=None, turn_budget=max_turns, token_budget=token_budget,
                             time_limit_s=int(time_limit_s), use_prior_experience=False, source_run_id=source.id,
                             correlation_id=checker.correlation_id, side_channel_status=checker.side_channel_status)
    # The claim and everything after it is one protected region (review round 2, item 1): a failure anywhere
    # below - judge_ref, building or compiling the graph included - must still close the row, never leave it
    # in_progress (locking the target) until the start-up sweep. The try wraps the whole rest of the function,
    # including the final finish_run on the success path.
    try:
        deadline = clock() + time_limit_s
        secrets = secret_values(resolved)   # the target's auth values and the side channel's (013/FR-071)
        store.copy_planted_tokens(source.id, run_id)
        checker.bind_run(run_id)
        judge_prompt = judge_ref(judge) if judge.configured else None
        judge_prompt_id, judge_prompt_version = prompt_registry.split_ref(judge_prompt)
        judge_requests_box = [0]
        events.run_started(store, run_id=run_id, target_id=target_id, mode="replay", family=source.family,
                           prompt_id=source.prompt_id, attacker_source=source.attacker_source, attacker_model=None,
                           judge_model=judge.model if judge.configured else None, judge_prompt=judge_prompt,
                           turn_budget=max_turns, token_budget=token_budget, time_limit_s=int(time_limit_s),
                           use_prior_experience=False, source_run_id=source.id, **checker.run_start_fields())

        def remaining() -> float:
            return deadline - clock()

        turn_results: list[str | None] = []   # captured live, one entry per turn actually attempted (research D5)

        def attacker_node(state: _State) -> _State:
            turn = state["turns_used"] + 1
            events.turn_started(turn)
            if turn <= len(source_turns):
                return {"pending_message": source_turns[turn - 1].attacker_message, "pending_canary": False,
                        "pending_evidence": None}
            # Defensive: unreachable while max_turns <= len(source_turns), the same decide_node turn-cap shape
            # (research D2) in case this is ever called with a looser max_turns.
            return {"outcome": {"verdict": state["last_verdict"] or "unclear", "hard_evidence": False,
                                "reason": state.get("last_reason") or INTERRUPTED_BY_DEADLINE,
                                "judge_used": state["judge_used"], "stopping_condition": "turn_cap",
                                "succeeded_turn": None}}

        async def send_node(state: _State) -> _State:
            return await _send_turn(state, resolved=resolved, mode=mode, sender=sender, transport=transport,
                                    resolver=resolver, remaining=remaining, secrets=secrets, evidence=checker)

        async def evidence_node(state: _State) -> _State:
            return await _check_evidence(state, checker, remaining)

        async def judge_node(state: _State) -> _State:
            return await _judge_turn(state, judge=judge, judge_prompt=judge_prompt, remaining=remaining,
                                     requests=judge_requests_box)

        def record_node(state: _State) -> _State:
            turn = state["turns_used"] + 1
            judged = state.get("last_judged_turn") == turn
            source_turn = source_turns[turn - 1]   # the same index attacker_node used for this same turn (T018)
            store.add_turn(run_id, position=turn, attacker_message=state["pending_message"],
                           reply_text=state.get("pending_reply"),
                           reply_truncated=state.get("pending_truncated", False),
                           judge_verdict=state.get("last_verdict"), judge_reason=state.get("last_reason"),
                           judge_progress=state.get("last_progress"),
                           attacker_prompt_id=source_turn.attacker_prompt_id,
                           attacker_prompt_version=source_turn.attacker_prompt_version,
                           judge_prompt_id=judge_prompt_id if judged else None,
                           judge_prompt_version=judge_prompt_version if judged else None)
            found = state.get("pending_evidence")
            items = found.items if found is not None else []
            if items:   # the turn's evidence items, right after its turn row (013/FR-003)
                store.add_evidence(run_id, items)
            reply = state.get("pending_reply")
            canary = bool(state.get("pending_canary", False))
            source_label = (f"library:{source.prompt_id}" if turn == 1
                            else _replay_turn_source(source_turn, source.family))
            events.turn_ended(turn=turn, source=source_label, message_chars=len(state["pending_message"]),
                              reply_chars=None if reply is None else len(reply),
                              reply_truncated=bool(state.get("pending_truncated", False)), canary_hit=canary,
                              hard_evidence=bool(items), judged=judged,
                              verdict=state.get("last_verdict") if judged else None, attacker_generated=False,
                              evidence_kinds=found.kinds if found is not None else [],
                              evidence_count=len(items))
            # Any evidence item of any kind decides this turn (013/FR-035, research D23) - never the canary alone.
            turn_results.append("succeeded" if items else (state.get("last_verdict") if judged else None))
            conversation = list(state["conversation"]) + [("attacker", state["pending_message"])]
            if reply is not None:   # the already-bound local narrows to str for mypy, not a fresh state.get() (item 16)
                conversation.append(("agent", reply))
            return {"conversation": conversation, "turns_used": turn}

        def decide_node(state: _State) -> _State:
            return _decide_next(state, max_turns=max_turns, token_budget=token_budget, remaining=remaining)

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
        final = await compiled.ainvoke(initial, {"recursion_limit": max(25, max_turns * 8)})
        outcome = final["outcome"]
        replay_outcome = compute_outcome(turn_results, len(source_turns), source.succeeded_turn)
        run = store.finish_run(run_id, verdict=outcome["verdict"], hard_evidence=outcome["hard_evidence"],
                               reason=outcome["reason"], judge_used=outcome["judge_used"],
                               judge_model=judge.model if outcome["judge_used"] else None,
                               failure_step=outcome.get("failure_step"),
                               stopping_condition=outcome["stopping_condition"],
                               succeeded_turn=outcome["succeeded_turn"], turns_used=final["turns_used"],
                               tokens_used=final["tokens_used"],
                               judge_prompt_id=judge_prompt_id if judge_requests_box[0] else None,
                               judge_prompt_version=judge_prompt_version if judge_requests_box[0] else None,
                               replay_outcome=replay_outcome)
        events.run_finished(run)
        return run
    except Exception as error:
        closed = store.finish_run(run_id, verdict="unclear", reason="The run failed unexpectedly.",
                                  replay_outcome="inconclusive")
        events.run_finished(closed)
        raise ReplayFailed(run_id) from error
