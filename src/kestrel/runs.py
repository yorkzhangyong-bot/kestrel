"""Run one attack end to end: send, the deterministic checks, then judge, all within one deadline
(contracts/kestrel-api.md).

Order (fixed): claim the run row → send through the connection tester → the evidence checker's deterministic
checks over the reply (feature 013: canary, then the two reply detectors, in the fixed order of 013/FR-001) → judge
only if none found evidence → finish the row. hard_evidence is set by a deterministic check alone, never from the
judge (Principle II). Feature 010: `run.start` once the row is claimed, one `turn` line for the run's single turn,
and the outcome stashed for the `run.end` line the caller's run scope emits after the write-back — identifiers,
lengths and categories only.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Literal, Protocol, Sequence

from kestrel import checkpointing, events, prompt_registry
from kestrel.attack.attacker import AttackerClient, Pinned
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings, TestOutcome, run_test
from kestrel.evidence.checker import EvidenceChecker, rebuild_live_checker
from kestrel.experience.writeback import write_back
from kestrel.judge.client import JudgeClient, JudgeError
from kestrel.judge.verdict import ParsedVerdict
from kestrel.store import Run, TargetStore, Turn

TOTAL_DEADLINE_S = 90.0   # FR-013: the whole run, start to verdict
SEND_LIMIT_S = 60.0       # feature 001's send limit, inside the deadline
JUDGE_LIMIT_S = 30.0      # the judge's slice, inside the deadline

CANARY_REASON = "The reply contains a canary string the agent was told to keep, so the attack is confirmed."
NO_JUDGE_REASON = "No judge is configured, so this run could not be scored. Canary evidence still applies."
DEADLINE_REASON = "The run reached its 90-second time limit before it could be judged."


class Judge(Protocol):
    configured: bool
    model: str

    async def judge(self, *, attack: str, reply: str, timeout: float | None = None) -> ParsedVerdict:
        ...


Sender = Callable[..., Awaitable[TestOutcome]]


def judge_ref(judge) -> str | None:
    """The judge prompt reference (`judge@N`) the client sends — its `judge_prompt_ref`, the pinned version for a
    pinned A/B arm — or the registry's active one for a client double without the accessor (research D15). The one
    source for both the recorded provenance and the log lines (FR-007)."""
    if hasattr(judge, "judge_prompt_ref"):
        return judge.judge_prompt_ref
    return prompt_registry.active_ref(prompt_registry.JUDGE_ID)


def attacker_ref(attacker, family: str) -> str | None:
    """The attacker prompt reference (`attacker:<family>@N`) the client sends for this family, or the registry's
    active one for a client double without `prompt_ref` (research D15)."""
    prompt_ref = getattr(attacker, "prompt_ref", None)
    if prompt_ref is not None:
        return prompt_ref(family)
    return prompt_registry.active_ref(prompt_registry.attacker_id(family))


def match_canary(reply: str, canaries: Sequence[str]) -> str | None:
    """The first declared canary that appears exactly (case-sensitively) in the reply, or None (FR-026, R6).
    Feature 013 moved the run paths onto `EvidenceChecker` (which records one item per distinct canary matched);
    this stays the single-match helper other callers and tests use."""
    for canary in canaries:
        if canary in reply:
            return canary
    return None


async def execute_run(store: TargetStore, *, target_id: int, prompt: AttackPrompt, attacker_source: str,
                      canaries: list[str], resolved: ResolvedSettings, mode: str, judge: Judge,
                      sender: Sender = run_test, transport=None, resolver=default_resolver,
                      use_prior_experience: bool = True,
                      clock: Callable[[], float] = time.monotonic, total_s: float = TOTAL_DEADLINE_S,
                      send_s: float = SEND_LIMIT_S, judge_s: float = JUDGE_LIMIT_S,
                      evidence: EvidenceChecker | None = None) -> Run:
    """Claim a run row, carry it to a verdict (or a failure step), and return the finished Run.

    May raise RunInProgress from the claim (the API turns that into 409); any other failure still closes the row.
    `use_prior_experience` is recorded on the run; a single-turn run has no attacker to hint, so it has no effect (C1).
    `evidence` (feature 013) is the run's deterministic checker; None is the canary-only checker — today's
    behaviour exactly — so every existing caller is unchanged (013/FR-002, research D2).
    """
    checker = evidence if evidence is not None else EvidenceChecker.canary_only(canaries, family=prompt.family,
                                                                                 store=store)
    # The message sent is the seed with any planted task placed at its insertion point (013/FR-011); the stored
    # prompt_text, the judge's attack text and the turn line's length all see this same text (013/FR-061).
    message = checker.opening_message(prompt)
    run_id = store.claim_run(target_id, prompt_id=prompt.id, prompt_title=prompt.title, prompt_text=message,
                             family=prompt.family, owasp_category=prompt.owasp_category,
                             attacker_source=attacker_source, use_prior_experience=use_prior_experience)
    deadline = clock() + total_s
    try:
        # Everything after the claim is one protected region: a failure anywhere below - recording the planted
        # token included - must still close the row, never leave it in_progress until the start-up sweep.
        checker.bind_run(run_id)   # records what the run planted, right after the claim (013/FR-008)
        # The judge reference this run would send — the one source of its lines and its provenance (FR-007, D15).
        judge_prompt = judge_ref(judge) if judge.configured else None
        events.run_started(store, run_id=run_id, target_id=target_id, mode="single_turn", family=prompt.family,
                           prompt_id=prompt.id, attacker_source=attacker_source,
                           judge_model=judge.model if judge.configured else None, judge_prompt=judge_prompt,
                           turn_budget=1, time_limit_s=int(total_s), use_prior_experience=use_prior_experience,
                           **checker.run_start_fields())
        events.turn_started(1)
        send_budget = max(0.1, min(send_s, deadline - clock()))
        checker.note_sent(message, 1)   # every sent message is inspected before it goes out (013/FR-012)
        outcome = await sender(resolved, mode=mode, display_name="", transport=transport, resolver=resolver,
                               deadline_s=send_budget, prompt=message)
        if not outcome.ok:
            return _finish(store, run_id, prompt, message, failure_step=outcome.step, tokens_used=0)

        reply = outcome.reply_text or ""
        truncated = outcome.reply_truncated

        found = await checker.check_turn(1, reply, lambda: deadline - clock())
        events.evidence_check(checks=found.checks, evidence_kinds=found.kinds, evidence_count=len(found.items),
                              side_channel_status=found.side_channel_status,
                              callback_wait_ms=found.callback_wait_ms,
                              state_changed_keys=found.state_changed_keys)
        if found.items:
            store.add_evidence(run_id, found.items)
            return _finish(store, run_id, prompt, message, canary_hit=found.canary_hit, evidence_kinds=found.kinds,
                           evidence_count=len(found.items), verdict="succeeded", hard_evidence=True,
                           reason=found.reason, reply_text=reply, reply_truncated=truncated, tokens_used=0)

        if not judge.configured:
            return _finish(store, run_id, prompt, message, verdict="unclear", reason=NO_JUDGE_REASON,
                           reply_text=reply, reply_truncated=truncated, tokens_used=0)

        judge_budget = min(judge_s, deadline - clock())
        if judge_budget <= 0:
            return _finish(store, run_id, prompt, message, verdict="unclear", reason=DEADLINE_REASON,
                           reply_text=reply, reply_truncated=truncated, tokens_used=0)

        # A judge request is made: its prompt version is recorded on the verdict (feature 010, FR-007; D15).
        judge_prompt_id, judge_prompt_version = prompt_registry.split_ref(judge_prompt)
        events.judge_requested(judge_prompt)
        try:
            verdict = await judge.judge(attack=message, reply=reply, timeout=judge_budget)
        except JudgeError as error:
            return _finish(store, run_id, prompt, message, verdict="unclear", judge_used=True, judge_model=judge.model,
                           reason=f"The judge could not decide: {error}", reply_text=reply, reply_truncated=truncated,
                           tokens_used=0, judge_prompt_id=judge_prompt_id, judge_prompt_version=judge_prompt_version)
        return _finish(store, run_id, prompt, message, judged=True, verdict=verdict.verdict, hard_evidence=False,
                       judge_used=True, judge_model=judge.model, reason=verdict.reason, reply_text=reply,
                       reply_truncated=truncated, tokens_used=verdict.tokens, judge_prompt_id=judge_prompt_id,
                       judge_prompt_version=judge_prompt_version)
    except Exception:
        # Close the row so the target is not left locked by FR-010; the start-up sweep is only a backstop.
        events.run_finished(store.finish_run(run_id, verdict="unclear", reason="The run failed unexpectedly."))
        raise


def _finish(store: TargetStore, run_id: int, prompt: AttackPrompt, message: str, *, canary_hit: bool = False,
            judged: bool = False, evidence_kinds: Sequence[str] = (), evidence_count: int = 0, **fields) -> Run:
    """Emit the run's one `turn` line, finish the row, and stash the outcome for `run.end` (feature 010). Lengths and
    categories only: no prompt text, reply, reason or header value (research R13, FR-009). `message` is the text
    actually sent (the opened seed), whose length the line reports."""
    reply = fields.get("reply_text")
    events.turn_ended(turn=1, source=f"library:{prompt.id}", message_chars=len(message),
                      reply_chars=None if reply is None else len(reply),
                      reply_truncated=bool(fields.get("reply_truncated", False)), canary_hit=canary_hit,
                      hard_evidence=bool(evidence_kinds), judged=judged,
                      verdict=fields.get("verdict"), attacker_generated=False,
                      evidence_kinds=evidence_kinds, evidence_count=evidence_count)
    run = store.finish_run(run_id, **fields)
    events.run_finished(run)
    return run


def finish_with_outcome(store: TargetStore, run: Run, outcome, *, turns_used: int | None = None,
                        tokens_used: int | None = None) -> Run:
    """Finish `run`'s row with an outcome the deterministic checks or the judge already decided, but that was not
    yet durably recorded (feature 014, research D7, D11): shared by the start-up sweep's own reconciliation of a
    thread whose graph reached its own end, and by Stop's identical reconciliation branch. Preserves the run's
    own pinned judge provenance whenever the outcome was judge-decided - never left null by `finish_run`'s own
    column-writing UPDATE, which would otherwise misattribute an already-judge-scored turn to no judge at all
    (Principle III, FR-047). `turns_used`/`tokens_used` come from the checkpoint's own persisted state, never the
    stale, never-finished `run` row (which has not had either written yet)."""
    return store.finish_run(
        run.id, verdict=outcome.verdict, hard_evidence=outcome.hard_evidence, reason=outcome.reason,
        judge_used=outcome.judge_used, judge_model=run.judge_model if outcome.judge_used else None,
        failure_step=outcome.failure_step, stopping_condition=outcome.stopping_condition,
        succeeded_turn=outcome.succeeded_turn, turns_used=turns_used, tokens_used=tokens_used,
        judge_prompt_id=run.judge_prompt_id if outcome.judge_used else None,
        judge_prompt_version=run.judge_prompt_version if outcome.judge_used else None)


INTERRUPTED_REASON = "Kestrel stopped while this run was in progress, so it was interrupted."


class NotStoppable(Exception):
    """`run_id`'s checkpoint is incompatible with the running build (FR-048): unreachable without a restart in
    between, since the start-up sweep always resolves this before any request could reach Stop for it."""

    def __init__(self, run_id: int) -> None:
        super().__init__(run_id)
        self.run_id = run_id


class NotResumable(Exception):
    """`run_id` cannot be resumed or decided right now; `.code`/`.message` are the documented 409 (contracts/api.md,
    FR-041, FR-054)."""

    def __init__(self, run_id: int, code: str, message: str) -> None:
        super().__init__(run_id, code, message)
        self.run_id = run_id
        self.code = code
        self.message = message


class PinnedModelUnavailable(Exception):
    """A resumed or decided run's own pinned attacker/judge model, prompt version, or library seed can no longer
    be constructed (FR-041, FR-047); `.message` names the problem."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _last_durably_judged_turn(turns: Sequence[Turn]) -> Turn | None:
    """The last `run_turns` row this run's own judge actually reached a verdict on (FR-040) - never a nonexistent
    `Run.last_judged_verdict` attribute."""
    for turn in reversed(turns):
        if turn.judge_verdict is not None:
            return turn
    return None


def _pending_turn_fields(run: Run, state: dict) -> dict:
    """Exactly the fields `record` itself would read to write this pending turn (research D7): Stop constructs no
    call `record` would not already make for the identical turn, reading the run's own pinned provenance rather
    than whatever is currently configured (FR-047)."""
    turn = state["turns_used"] + 1
    judged = state.get("last_judged_turn") == turn
    found = state.get("pending_evidence")
    items = found.items if found is not None else []
    return {"attacker_message": state["pending_message"], "reply_text": state.get("pending_reply"),
           "reply_truncated": state.get("pending_truncated", False), "judge_verdict": state.get("last_verdict"),
           "judge_reason": state.get("last_reason"), "judge_progress": state.get("last_progress"),
           "attacker_prompt_id": run.attacker_prompt_id if turn >= 2 else None,
           "attacker_prompt_version": run.attacker_prompt_version if turn >= 2 else None,
           "judge_prompt_id": run.judge_prompt_id if judged else None,
           "judge_prompt_version": run.judge_prompt_version if judged else None, "evidence_items": items}


async def stop_run(store: TargetStore, graph: Any, settings: Any, run_id: int, *,
                   triggered_by: Literal["user", "idle_timeout"] = "user") -> Run:
    """End any resumable run - paused or not - without ever resuming its graph (FR-040, research D7). The caller
    already holds `run_id`'s execution lease and already has its own logging scope open before calling in
    (research D29): this function neither acquires nor releases the lease, neither opens nor closes a scope, and
    performs no precondition validation of its own - all three are the caller's own job, already done."""
    status = await checkpointing.classify(graph, run_id, leased=False)
    idle_hours = settings.resume_idle_hours if triggered_by == "idle_timeout" else None
    if isinstance(status, (checkpointing.NoCheckpoint, checkpointing.Unreadable)):
        # FR-056: the exact close the sweep itself performs for this shape, same reason text, no write-back -
        # never a 409 that would otherwise trap the target until a restart; triggered_by changes nothing here.
        run = store.finish_run(run_id, verdict="unclear", judge_used=False, stopping_condition="interrupted",
                               reason=INTERRUPTED_REASON)
        store.set_memory_written(run_id, False)   # never attempted (nothing of this run's progress survived)
        run = store.get_run(run_id)
        events.run_stopped(was_paused=False, reconciled=False, trigger=triggered_by, idle_hours=idle_hours)
        events.run_finished(run)
        return run
    if isinstance(status, checkpointing.Incompatible):
        raise NotStoppable(run_id)
    run = store.get_run(run_id)
    if isinstance(status, checkpointing.ReachedEnd):
        state: dict | None = status.values
    elif isinstance(status, checkpointing.Resumable):
        state = status.snapshot.values
    else:   # Paused
        snap = await graph.aget_state(checkpointing.thread_config(run_id))
        state = snap.values
    decided = status.outcome if isinstance(status, checkpointing.ReachedEnd) else (state or {}).get("outcome")
    if decided is not None:
        # FR-051: write the pending turn only when `record` itself has not yet run for it - status.from_step ==
        # "record" is the shared signal both the evidence and judge commit windows share (record is their own
        # next step); record's own commit window (from_step == "decide") and everything later already has it.
        if state is not None and getattr(status, "from_step", None) == "record":
            turn = state["turns_used"] + 1
            store.add_turn_with_evidence(run_id, position=turn, **_pending_turn_fields(run, state))
        run = finish_with_outcome(store, run, decided, turns_used=(state or {}).get("turns_used"),
                                  tokens_used=(state or {}).get("tokens_used"))
        events.run_stopped(was_paused=isinstance(status, checkpointing.Paused), reconciled=True,
                           trigger=triggered_by, idle_hours=idle_hours)
    else:
        last_judged = _last_durably_judged_turn(store.list_turns(run_id))
        reason = ("stopped_by_user" if triggered_by == "user" else
                 f"Kestrel stopped this run automatically after {settings.resume_idle_hours:g} hours with "
                 f"nobody acting on it.")
        run = store.finish_run(
            run_id, verdict=(last_judged.judge_verdict if last_judged else "unclear"),
            judge_used=last_judged is not None,
            judge_model=(run.judge_model if last_judged else None),
            judge_prompt_id=(run.judge_prompt_id if last_judged else None),
            judge_prompt_version=(run.judge_prompt_version if last_judged else None),
            turns_used=(state or {}).get("turns_used"), tokens_used=(state or {}).get("tokens_used"),
            stopping_condition="stopped_by_user", reason=reason)
        events.run_stopped(was_paused=isinstance(status, checkpointing.Paused), reconciled=False,
                           trigger=triggered_by, idle_hours=idle_hours)
    events.run_finished(run)
    return run


def _pinned_attacker(run: Run, *, settings: Any, transport: Any) -> AttackerClient:
    overrides: dict[str, Pinned] | None = None
    if run.attacker_prompt_id and run.attacker_prompt_version:
        text = prompt_registry.text_for(run.attacker_prompt_id, run.attacker_prompt_version)   # may raise
        family = run.attacker_prompt_id.removeprefix(prompt_registry.ATTACKER_PREFIX)
        overrides = {family: (text, f"{run.attacker_prompt_id}@{run.attacker_prompt_version}")}
    return AttackerClient(model=run.attacker_model or "", api_key=settings.attacker_api_key,
                         base_url=settings.attacker_base_url, transport=transport, system_overrides=overrides)


def _pinned_judge(run: Run, *, settings: Any, transport: Any) -> JudgeClient:
    pinned = None
    if run.judge_prompt_id and run.judge_prompt_version:
        text = prompt_registry.text_for(run.judge_prompt_id, run.judge_prompt_version)   # may raise
        pinned = (text, f"{run.judge_prompt_id}@{run.judge_prompt_version}")
    api_key = settings.judge_api_key if run.judge_model else None
    return JudgeClient(model=run.judge_model or "", api_key=api_key, base_url=settings.judge_base_url,
                      transport=transport, system_prompt=pinned)


async def execute_resume(store: TargetStore, graph: Any, app_state: Any, settings: Any, library: Any,
                         terms_version: str, run_id: int) -> Run:
    """Continue a resumable (not paused) run (014/FR-014, FR-041, FR-047, contracts/api.md). The caller already
    holds `run_id`'s own execution lease and has already validated its plain columns before opening any scope
    (research D29); this builds a fresh `_LiveDeps`, pinned to the run's own claim-time caps/model/prompt
    references, and resumes the real compiled graph from its last durably committed step. Raises `NotResumable`
    (the documented 409s) or `PinnedModelUnavailable`."""
    from kestrel.attack.graph import LIVE_GRAPH, Outcome, _LiveDeps   # lazy: avoids a module-level import cycle

    status = await checkpointing.classify(graph, run_id, leased=False)
    if isinstance(status, checkpointing.ReachedEnd):
        return await stop_run(store, graph, settings, run_id, triggered_by="user")
    if isinstance(status, (checkpointing.NoCheckpoint, checkpointing.Unreadable, checkpointing.Incompatible)):
        raise NotResumable(run_id, "not_resumable", "This run cannot be resumed.")
    if isinstance(status, checkpointing.Paused):
        raise NotResumable(run_id, "paused", "This run is paused awaiting a decision; decide it instead.")
    # `leased=False` above means Running is unreachable; the remaining shape is the resumable one.
    assert isinstance(status, checkpointing.Resumable)
    run = store.get_run(run_id)
    target = store.get_target(run.target_id)
    if not target.permission_confirmed_at:
        raise NotResumable(run_id, "permission_missing",
                           "Tick the permission box and save the target before attacking it.")
    if target.terms_version != terms_version:
        raise NotResumable(run_id, "terms_outdated",
                           "The terms of service have changed; read them and tick the box again.")
    if not settings.attacker_api_key:
        raise NotResumable(run_id, "attacker_unavailable",
                           "No attacker model is configured, so an adaptive attack can't run.")
    if library is None:
        raise NotResumable(run_id, "library_unavailable", "The attack library is not available.")
    try:
        seed = library.pick(run.family, run.prompt_id)
        attacker = _pinned_attacker(run, settings=settings, transport=app_state.transport)
        judge = _pinned_judge(run, settings=settings, transport=app_state.transport)
        if run.judge_model and not settings.judge_api_key:
            raise PinnedModelUnavailable(
                "This run's own attacker or judge model (or its prompt version, or its own library seed) is no "
                "longer available; stop it instead.")
    except LookupError as error:
        raise PinnedModelUnavailable(
            "This run's own attacker or judge model (or its prompt version, or its own library seed) is no "
            "longer available; stop it instead.") from error

    state = status.snapshot.values
    stored_turns = store.list_turns(run_id)
    # The target's *current* connection settings and secrets (feature 012's own "current, not as it was" meaning,
    # FR-047's Assumptions) - never api/main.py's own stored_values helper, to avoid a module-level import cycle.
    stored = {h.name.lower(): h.value for h in store.resolve_headers(target.id)}
    resolved_headers = tuple((h.name, stored.get(h.name.lower()) or "") for h in target.headers)
    resolved = ResolvedSettings(url=target.url, method=target.method, headers=resolved_headers,
                                body_template=target.body_template, response_path=target.response_path)
    checker = rebuild_live_checker(store, library, run, stored_turns,
                                   mask=[value for _, value in resolved_headers] + [resolved.url])
    if status.completed and status.from_step in ("evidence", "judge", "decide", "record"):
        checker.note_sent(state["pending_message"], state["turns_used"] + 1, emit_disarm_event=True)

    clock = time.monotonic
    deadline = clock() + max(0.0, (run.time_limit_s or 0) - state.get("time_spent_s", 0.0))
    deps = _LiveDeps(store=store, run_id=run_id, resolved=resolved,
                     secrets=[value for _, value in resolved_headers], mode=app_state.settings.mode,
                     sender=run_test, transport=app_state.transport, resolver=app_state.resolver, judge=judge,
                     judge_prompt=(f"{run.judge_prompt_id}@{run.judge_prompt_version}"
                                  if run.judge_prompt_id else None),
                     judge_prompt_id=run.judge_prompt_id, judge_prompt_version=run.judge_prompt_version,
                     checker=checker, max_turns=run.turn_budget or 0, token_budget=run.token_budget or 0,
                     deadline=deadline, clock=clock, time_spent_at_invocation_start=state.get("time_spent_s", 0.0),
                     invocation_start=clock(), seed_prompt=seed, opening=run.prompt_text, attacker=attacker,
                     hint_provider=None,
                     attacker_prompt=(f"{run.attacker_prompt_id}@{run.attacker_prompt_version}"
                                     if run.attacker_prompt_id else None),
                     attacker_prompt_id=run.attacker_prompt_id, attacker_prompt_version=run.attacker_prompt_version)
    events.run_resumed(from_turn=state["turns_used"] + 1, from_step=status.from_step, was_paused=False)
    events.reopen_turn(turn=state["turns_used"] + 1,
                       elapsed_s=state.get("time_spent_s", 0.0) - state.get("turn_time_spent_at_start", 0.0),
                       attacker_usage=state.get("turn_attacker_usage"))
    final = await graph.ainvoke(None, checkpointing.thread_config(run_id), context=deps, durability="sync")
    outcome: Outcome = final["outcome"]
    requested = final["judge_requests"]
    run = store.finish_run(run_id, verdict=outcome.verdict, hard_evidence=outcome.hard_evidence,
                           reason=outcome.reason, judge_used=outcome.judge_used,
                           judge_model=run.judge_model if outcome.judge_used else None,
                           failure_step=outcome.failure_step, stopping_condition=outcome.stopping_condition,
                           succeeded_turn=outcome.succeeded_turn, turns_used=final["turns_used"],
                           tokens_used=final["tokens_used"],
                           judge_prompt_id=run.judge_prompt_id if requested else None,
                           judge_prompt_version=run.judge_prompt_version if requested else None)
    events.run_finished(run)
    return run


def finish_api_run(store: TargetStore, run: Run, *, experience: Any, dedupe_threshold: float | None,
                   planted_values: Sequence[str] = (), task_texts: Sequence[str] = ()) -> Run:
    """The one shared step every API-driven finishing path (other than the original start, whose own equivalent
    is `api/main.py::start_run` itself) funnels an already-finished run through (feature 014, research D19):
    write-back, skipped if already attempted (`run.memory_written is not None` - Stop's own no-checkpoint branch
    pre-sets it False, FR-056), then checkpoint deletion. Lease release is never a step here - it is the caller's
    own `with checkpointing.lease(...):` block exiting, exactly like `run_adaptive`'s own self-contained use of
    it (FR-055)."""
    if run.memory_written is None:
        turns = store.list_turns(run.id) if run.mode == "adaptive" else []
        write_back(experience, store, run, turns, dedupe_threshold=dedupe_threshold,
                  planted_values=list(planted_values), task_texts=list(task_texts))
        run = store.get_run(run.id)
    store.delete_checkpoint(run.id)
    return run


async def execute_adaptive_run(store, *, target_id, seed_prompt, attacker_source, canaries, resolved, mode,
                               attacker, judge, max_turns, token_budget, time_limit_s, sender=run_test,
                               transport=None, resolver=default_resolver, use_prior_experience=True,
                               hint_provider=None, evidence=None, graph=None, app_state=None):
    """Run an adaptive (multi-turn) attack via the LangGraph loop (feature 003). Single-turn keeps execute_run.

    `hint_provider` (feature 004) supplies the attacker's background each turn; `evidence` (feature 013) is the
    run's deterministic checker, None for the canary-only default. `graph`/`app_state` (feature 014) pass through
    to `run_adaptive` unchanged: the experiment harness leaves both None (the bare, checkpointer-free LIVE_GRAPH,
    no execution lease), exactly as before this feature. Imported lazily so runs.py and attack.graph have no
    import cycle."""
    from kestrel.attack.graph import run_adaptive

    return await run_adaptive(store, target_id=target_id, seed_prompt=seed_prompt, attacker_source=attacker_source,
                              canaries=canaries, resolved=resolved, attacker=attacker, judge=judge, sender=sender,
                              mode=mode, transport=transport, resolver=resolver, max_turns=max_turns,
                              token_budget=token_budget, time_limit_s=time_limit_s,
                              use_prior_experience=use_prior_experience, hint_provider=hint_provider,
                              evidence=evidence, graph=graph, app_state=app_state)
