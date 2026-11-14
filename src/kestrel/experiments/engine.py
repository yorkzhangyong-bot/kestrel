"""The experiment engine (feature 007): run arm A's campaign then arm B's (contracts/experiment-engine.md).

Pure orchestration over the existing run path (kestrel.runs); unit-testable with fakes. No attack text here - seeds
come from the existing library and the existing run functions do the work. All progress is written to the store, so
the status/result endpoints read the DB and survive a restart. Feature 010: the experiment's start, cap stop and end
are log lines, and every record of each run — its write-back included — carries the experiment id and the arm.
"""
from __future__ import annotations

import time
from typing import Callable

from kestrel import events, prompt_registry
from kestrel.attack.attacker import AttackerClient
from kestrel.attacks.library import family_label
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings
from kestrel.experience.hints import format_hints
from kestrel.experience.writeback import write_back
from kestrel.judge.client import JudgeClient
from kestrel.runs import execute_adaptive_run, execute_run
from kestrel.store import RunInProgress, TargetStore


async def run_experiment(store: TargetStore, *, experiment_id: int, settings, library, experience=None,
                         transport=None, resolver=default_resolver,
                         make_judge: Callable | None = None, make_attacker: Callable | None = None,
                         clock: Callable[[], float] = time.monotonic) -> None:
    """Execute an experiment to completion, writing every outcome to the store. Returns nothing (read the DB)."""
    make_judge = make_judge or (lambda model, system_prompt=None: JudgeClient(
        model=model, api_key=settings.judge_api_key, base_url=settings.judge_base_url, transport=transport,
        system_prompt=system_prompt))
    make_attacker = make_attacker or (lambda model, system_overrides=None: AttackerClient(
        model=model, api_key=settings.attacker_api_key, base_url=settings.attacker_base_url, transport=transport,
        system_overrides=system_overrides))
    experiment = store.get_experiment(experiment_id)
    target = store.get_target(experiment.target_id)
    canaries = store.list_canaries(target.id)
    resolved = _resolve(store, target)
    start = clock()
    completed = 0
    tokens = 0
    with events.bind_experiment(experiment_id):
        events.experiment_started(
            experiment_id=experiment_id, target_id=experiment.target_id, mode=experiment.mode,
            families=list(experiment.families), reps=experiment.reps, max_runs=experiment.max_runs,
            token_budget_total=experiment.token_budget_total, wall_clock_s=experiment.wall_clock_s,
            arms=[_arm_fields(arm) for arm in sorted(experiment.arms, key=lambda a: a.label)])

        def ended(status: str, reason: str, **failure) -> None:
            events.experiment_ended(experiment_id=experiment_id, status=status, stopped_reason=reason,
                                    completed_runs=completed, tokens_used=tokens,
                                    duration_ms=int((clock() - start) * 1000), **failure)

        try:
            for order, arm in enumerate(sorted(experiment.arms, key=lambda a: a.label), start=1):
                store.set_arm_order(arm.id, order)
                judge_override, attacker_overrides = _prompt_overrides(arm)   # feature 009 US4: a pinned version
                judge = (make_judge(arm.judge_model) if judge_override is None
                         else make_judge(arm.judge_model, system_prompt=judge_override))
                if experiment.mode == "adaptive":
                    attacker = (make_attacker(arm.attacker_model) if attacker_overrides is None
                                else make_attacker(arm.attacker_model, system_overrides=attacker_overrides))
                else:
                    attacker = None
                for family in experiment.families:
                    seed = library.pick(family, experiment.seed_prompt_ids.get(family))
                    for rep in range(experiment.reps):
                        cap = _cap_hit(experiment, completed, tokens, clock() - start)
                        if cap is not None:   # stop cleanly at a run boundary, with what has been gathered (FR-008)
                            store.set_experiment_status(experiment_id, status="stopped", stopped_reason=cap,
                                                        finished=True)
                            events.experiment_cap(experiment_id=experiment_id, cap=cap, completed_runs=completed,
                                                  tokens_used=tokens, elapsed_s=clock() - start)
                            ended("stopped", cap)
                            return
                        with events.bind_experiment(experiment_id, arm.label):   # bound before the run starts
                            run = await _run_rep(store, experiment, target, arm, family, rep, seed, resolved,
                                                 canaries, settings, library, judge, attacker, experience, transport,
                                                 resolver)
                        completed += 1
                        if run is not None:
                            tokens += run.tokens_used or 0
            store.set_experiment_status(experiment_id, status="finished", stopped_reason="completed", finished=True)
            ended("finished", "completed")
        except Exception as error:  # a run that failed to start is recorded below; anything else fails the experiment
            reason = f"failed:{type(error).__name__}"
            store.set_experiment_status(experiment_id, status="failed", stopped_reason=reason, finished=True)
            ended("failed", reason, error=type(error).__name__, exc_info=True)   # the class and frames, no text


def _arm_fields(arm) -> dict:
    """An arm as the experiment.start line names it: model slugs, settings and the pinned prompt — never a secret."""
    pinned = f"{arm.prompt_arm_target}@{arm.prompt_arm_version}" if arm.prompt_arm_target else None
    return {"label": arm.label, "attacker_model": arm.attacker_model, "judge_model": arm.judge_model,
            "use_prior_experience": arm.use_prior_experience, "turn_cap": arm.turn_cap,
            "token_budget": arm.token_budget, "write_back": arm.write_back, "prompt": pinned}


def _prompt_overrides(arm):
    """Resolve an arm's pinned prompt version to what its client should send (feature 009 US4): the text with its
    reference `id@N`, so the lines and the recorded provenance name the pinned version (feature 010, FR-007).
    Returns (judge (text, ref) | None, attacker {family: (text, ref)} | None); both None when the arm pins nothing."""
    target, version = arm.prompt_arm_target, arm.prompt_arm_version
    if not target:
        return None, None
    pinned = (prompt_registry.text_for(target, version), f"{target}@{version}")
    if target == prompt_registry.JUDGE_ID:
        return pinned, None
    if target.startswith("attacker:"):
        return None, {target.split(":", 1)[1]: pinned}
    return None, None


def _cap_hit(experiment, completed: int, tokens: int, elapsed_s: float) -> str | None:
    """The first hard cap that has been reached, or None (FR-008). Checked before each run, so none truncates one."""
    if completed >= experiment.max_runs:
        return "max_runs"
    if tokens >= experiment.token_budget_total:
        return "token_budget"
    if elapsed_s >= experiment.wall_clock_s:
        return "wall_clock"
    return None


async def _run_rep(store, experiment, target, arm, family, rep, seed, resolved, canaries, settings, library, judge,
                   attacker, experience, transport, resolver):
    """Run one repetition for one arm, record the link, and (by default) write back. Returns the Run, or None.

    The run's scope encloses the run and its write-back (feature 010): the write-back line belongs to the run, and
    run.end is the run's last line."""
    with events.run_scope():
        try:
            if experiment.mode == "adaptive":
                run = await execute_adaptive_run(
                    store, target_id=experiment.target_id, seed_prompt=seed, attacker_source=library.attacker_source,
                    canaries=canaries, resolved=resolved, mode=settings.mode, attacker=attacker, judge=judge,
                    max_turns=arm.turn_cap, token_budget=arm.token_budget,
                    time_limit_s=settings.adaptive_time_limit_s, transport=transport, resolver=resolver,
                    use_prior_experience=arm.use_prior_experience,
                    hint_provider=_hint_provider(arm, target, seed, experience, settings))
            else:
                run = await execute_run(store, target_id=experiment.target_id, prompt=seed,
                                        attacker_source=library.attacker_source, canaries=canaries,
                                        resolved=resolved, mode=settings.mode, judge=judge, transport=transport,
                                        resolver=resolver, use_prior_experience=arm.use_prior_experience)
        except RunInProgress:
            # Could not claim a run row (another run is active on the target); record it, never drop it (FR-015).
            store.add_experiment_run(experiment_id=experiment.id, arm_id=arm.id, rep_index=rep, family=family,
                                     run_id=None, send_ok=False)
            return None
        store.add_experiment_run(experiment_id=experiment.id, arm_id=arm.id, rep_index=rep, family=family,
                                 run_id=run.id, send_ok=run.failure_step is None)
        if arm.write_back:   # a cold arm skips write-back so the other arm is not warmed by it (FR-005);
            write_back(experience, store, run, store.list_turns(run.id))   # otherwise learn from the run (Principle V)
        return run


def _resolve(store: TargetStore, target) -> ResolvedSettings:
    """Build the target's connection settings with header values resolved, exactly as POST /api/runs does."""
    stored = {h.name.lower(): h.value for h in store.resolve_headers(target.id)}
    headers = tuple((h.name, stored.get(h.name.lower()) or "") for h in target.headers)
    return ResolvedSettings(url=target.url, method=target.method, headers=headers,
                            body_template=target.body_template, response_path=target.response_path)


def _hint_provider(arm, target, seed, experience, settings):
    """The attacker's background each turn: purpose always; patterns + memory only on a warm arm (feature 004)."""
    def provider(conversation):
        purpose = target.description
        if not arm.use_prior_experience or experience is None:
            return format_hints(purpose=purpose, patterns=[], memory=[])
        memory = experience.retrieve_memory(target_id=target.id, family=seed.family,
                                            cap=settings.experience_memory_cap)
        recent = " ".join(text for _, text in conversation[-4:])
        query = f"{family_label(seed.family)} {recent}".strip()
        found = experience.retrieve_patterns_with_ids(family=seed.family, query_text=query,
                                                      k=settings.experience_pattern_k)
        # Feature 010 (FR-016): counts and pattern ids whenever the store was asked — zero when nothing came back.
        events.memory_retrieval(pattern_ids=[pattern_id for pattern_id, _ in found], memory_count=len(memory))
        return format_hints(purpose=purpose, patterns=[document for _, document in found], memory=memory)
    return provider
