"""The experiment engine (feature 007): run arm A's campaign then arm B's (contracts/experiment-engine.md).

Pure orchestration over the existing run path (kestrel.runs); unit-testable with fakes. No attack text here - seeds
come from the existing library and the existing run functions do the work. All progress is written to the store, so
the status/result endpoints read the DB and survive a restart.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from kestrel.attack.attacker import GOALS, AttackerClient
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.tester import ResolvedSettings
from kestrel.experience.hints import format_hints
from kestrel.experience.writeback import write_back
from kestrel.judge.client import JudgeClient
from kestrel.runs import execute_adaptive_run, execute_run
from kestrel.store import RunInProgress, TargetStore

log = logging.getLogger("kestrel")


async def run_experiment(store: TargetStore, *, experiment_id: int, settings, library, experience=None,
                         transport=None, resolver=default_resolver,
                         make_judge: Callable | None = None, make_attacker: Callable | None = None,
                         clock: Callable[[], float] = time.monotonic) -> None:
    """Execute an experiment to completion, writing every outcome to the store. Returns nothing (read the DB)."""
    make_judge = make_judge or (lambda model: JudgeClient(model=model, api_key=settings.judge_api_key,
                                                          base_url=settings.judge_base_url, transport=transport))
    make_attacker = make_attacker or (lambda model: AttackerClient(model=model, api_key=settings.attacker_api_key,
                                                                   base_url=settings.attacker_base_url,
                                                                   transport=transport))
    experiment = store.get_experiment(experiment_id)
    target = store.get_target(experiment.target_id)
    canaries = store.list_canaries(target.id)
    resolved = _resolve(store, target)
    try:
        for order, arm in enumerate(sorted(experiment.arms, key=lambda a: a.label), start=1):
            store.set_arm_order(arm.id, order)
            judge = make_judge(arm.judge_model)
            attacker = make_attacker(arm.attacker_model) if experiment.mode == "adaptive" else None
            for family in experiment.families:
                seed = library.pick(family, experiment.seed_prompt_ids.get(family))
                for rep in range(experiment.reps):
                    await _run_rep(store, experiment, target, arm, family, rep, seed, resolved, canaries, settings,
                                   library, judge, attacker, experience, transport, resolver)
        store.set_experiment_status(experiment_id, status="finished", stopped_reason="completed", finished=True)
    except Exception as error:  # a run that failed to start is recorded below; anything else fails the experiment
        log.exception("experiment %s failed", experiment_id)
        store.set_experiment_status(experiment_id, status="failed",
                                    stopped_reason=f"failed:{type(error).__name__}", finished=True)


async def _run_rep(store, experiment, target, arm, family, rep, seed, resolved, canaries, settings, library, judge,
                   attacker, experience, transport, resolver):
    """Run one repetition for one arm, record the link, and (by default) write back. Returns the Run, or None."""
    try:
        if experiment.mode == "adaptive":
            run = await execute_adaptive_run(
                store, target_id=experiment.target_id, seed_prompt=seed, attacker_source=library.attacker_source,
                canaries=canaries, resolved=resolved, mode=settings.mode, attacker=attacker, judge=judge,
                max_turns=arm.turn_cap, token_budget=arm.token_budget, time_limit_s=settings.adaptive_time_limit_s,
                transport=transport, resolver=resolver, use_prior_experience=arm.use_prior_experience,
                hint_provider=_hint_provider(arm, target, seed, experience, settings))
        else:
            run = await execute_run(store, target_id=experiment.target_id, prompt=seed,
                                    attacker_source=library.attacker_source, canaries=canaries, resolved=resolved,
                                    mode=settings.mode, judge=judge, transport=transport, resolver=resolver,
                                    use_prior_experience=arm.use_prior_experience)
    except RunInProgress:
        # Could not claim a run row (another run is active on the target); record it, never drop it (FR-015).
        store.add_experiment_run(experiment_id=experiment.id, arm_id=arm.id, rep_index=rep, family=family,
                                 run_id=None, send_ok=False)
        return None
    store.add_experiment_run(experiment_id=experiment.id, arm_id=arm.id, rep_index=rep, family=family,
                             run_id=run.id, send_ok=run.failure_step is None)
    write_back(experience, store, run, store.list_turns(run.id))   # by default every run writes back (Principle V)
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
        query = f"{GOALS.get(seed.family, '')} {recent}".strip()
        patterns = experience.retrieve_patterns(family=seed.family, query_text=query, k=settings.experience_pattern_k)
        return format_hints(purpose=purpose, patterns=patterns, memory=memory)
    return provider
