"""Aggregate an experiment's stored runs into per-arm results and a comparison (feature 007, FR-006, FR-007).

Pure functions over data already fetched from SQLite (like kestrel.report.model). Success is split into confirmed
(hard evidence) and suspected (judge opinion) and never conflated (Principle II); the comparison's significance is
computed at the overall-arm level on the confirmed rate (clarified 2026-10-29).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from kestrel.experiments import stats
from kestrel.experiments.pricing import arm_cost
from kestrel.store import ExperimentArm, Run


@dataclass(frozen=True)
class Rate:
    successes: int
    n: int
    rate: float | None                      # None when n == 0 (no data), never a spurious 0%
    ci: tuple[float, float] | None


@dataclass(frozen=True)
class CategoryCount:
    key: str
    confirmed: int
    suspected: int
    n: int


@dataclass(frozen=True)
class ArmResult:
    label: str
    attacker_model: str
    judge_model: str
    run_order: int | None
    completed: int
    send_failures: int
    confirmed: Rate
    suspected: Rate
    mean_turns_to_success: float | None
    mean_tokens: float | None
    cost: float | None
    cost_note: str | None
    by_family: tuple[CategoryCount, ...]
    by_owasp: tuple[CategoryCount, ...]


@dataclass(frozen=True)
class Comparison:
    confirmed: dict                         # two_proportion(...) on the confirmed rate (the primary verdict)
    suspected_diff: float | None            # descriptive only (judge opinion, Principle II)


def _confirmed(run: Run) -> bool:
    return (run.verdict or "") == "succeeded" and run.hard_evidence


def _suspected(run: Run) -> bool:
    return (run.verdict or "") == "succeeded" and not run.hard_evidence


def _rate(successes: int, n: int) -> Rate:
    if n == 0:
        return Rate(successes=0, n=0, rate=None, ci=None)
    return Rate(successes=successes, n=n, rate=successes / n, ci=stats.wilson_interval(successes, n))


def _counts(runs: Sequence[Run], key: Callable[[Run], str]) -> tuple[CategoryCount, ...]:
    groups: dict[str, list[int]] = {}
    for run in runs:
        confirmed, suspected, n = groups.setdefault(key(run), [0, 0, 0])
        if run.verdict is not None:
            groups[key(run)][2] = n + 1
        if _confirmed(run):
            groups[key(run)][0] = confirmed + 1
        elif _suspected(run):
            groups[key(run)][1] = suspected + 1
    return tuple(CategoryCount(key=k, confirmed=c, suspected=s, n=n) for k, (c, s, n) in sorted(groups.items()))


def arm_result(arm: ExperimentArm, runs: Sequence[Run], *, mode: str, model_prices: Mapping[str, float],
               send_failures: int = 0) -> ArmResult:
    """Aggregate one arm's stored runs. ``runs`` are the runs linked to this arm; ``send_failures`` is the count of
    attempts that could not send (recorded, not dropped - FR-015)."""
    scored = [r for r in runs if r.verdict is not None]
    n = len(scored)
    confirmed = sum(1 for r in scored if _confirmed(r))
    suspected = sum(1 for r in scored if _suspected(r))

    turns = [r.succeeded_turn if r.succeeded_turn is not None else 1
             for r in runs if (r.verdict or "") == "succeeded"
             and (r.succeeded_turn is not None or r.mode == "single_turn")]
    mean_turns = sum(turns) / len(turns) if turns else None

    token_values = [r.tokens_used for r in runs if r.tokens_used is not None]
    mean_tokens = sum(token_values) / len(token_values) if token_values else None
    price_model = arm.attacker_model if mode == "adaptive" else arm.judge_model
    cost = arm_cost(sum(token_values), price_model, model_prices)
    cost_note = None if cost is not None else f"unavailable (no configured price for {price_model})"

    return ArmResult(label=arm.label, attacker_model=arm.attacker_model, judge_model=arm.judge_model,
                     run_order=arm.run_order, completed=len(runs), send_failures=send_failures,
                     confirmed=_rate(confirmed, n), suspected=_rate(suspected, n),
                     mean_turns_to_success=mean_turns, mean_tokens=mean_tokens, cost=cost, cost_note=cost_note,
                     by_family=_counts(runs, lambda r: r.family),
                     by_owasp=_counts(runs, lambda r: r.owasp_category))


def build_comparison(arm_a: ArmResult, arm_b: ArmResult) -> Comparison:
    """Compare the two arms: a two-proportion test on the confirmed rate; the suspected diff is descriptive."""
    confirmed = stats.two_proportion(arm_a.confirmed.successes, arm_a.confirmed.n,
                                     arm_b.confirmed.successes, arm_b.confirmed.n)
    suspected_diff = None
    if arm_a.suspected.rate is not None and arm_b.suspected.rate is not None:
        suspected_diff = arm_b.suspected.rate - arm_a.suspected.rate
    return Comparison(confirmed=confirmed, suspected_diff=suspected_diff)
