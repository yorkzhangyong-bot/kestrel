"""The experiment comparison report (feature 007, FR-009, FR-010, FR-014).

Builds a comparison-shaped model and a Markdown rendering; HTML reuses kestrel.report.render.render_html (same
escaping and self-contained style as the feature-005 report) and the per-OWASP table reuses kestrel.report.owasp.
The report names both arms' attacker model slugs (model+version) and judges, with each arm's budget (Principle III),
and maps every category row to the OWASP LLM Top 10 (Principle VI).
"""
from __future__ import annotations

from dataclasses import dataclass

from kestrel.experiments.results import ArmResult, Comparison
from kestrel.report import owasp
from kestrel.store import Experiment


@dataclass(frozen=True)
class ExperimentReportModel:
    experiment: Experiment
    target_name: str
    result_a: ArmResult
    result_b: ArmResult
    comparison: Comparison
    diff: tuple[str, ...]
    order: str
    warming: str
    generated_at: str


def build_experiment_report(experiment: Experiment, result_a: ArmResult, result_b: ArmResult,
                            comparison: Comparison, *, diff, order: str, warming: str, now: str,
                            target_name: str = "") -> ExperimentReportModel:
    return ExperimentReportModel(experiment=experiment, target_name=target_name, result_a=result_a,
                                 result_b=result_b, comparison=comparison, diff=tuple(diff), order=order,
                                 warming=warming, generated_at=now)


def _rate(rate) -> str:
    """Never a bare percentage: always shows the n it is over, or "no data" (SC-003)."""
    return "no data" if rate.rate is None else f"{rate.rate * 100:.0f}% ({rate.successes}/{rate.n})"


def _tokens(result: ArmResult) -> str:
    return "—" if result.mean_tokens is None else f"{result.mean_tokens:.0f}"


def _cost(result: ArmResult) -> str:
    if result.cost is None:
        return result.cost_note or "unavailable"
    return f"${result.cost:.2f}"


def _turns(result: ArmResult) -> str:
    return "—" if result.mean_turns_to_success is None else f"{result.mean_turns_to_success:.1f}"


def render_experiment_markdown(model: ExperimentReportModel) -> str:
    experiment = model.experiment
    a, b = model.result_a, model.result_b
    arms = {arm.label: arm for arm in experiment.arms}
    lines: list[str] = [f"# A/B experiment report — {model.target_name or f'experiment #{experiment.id}'}", ""]
    lines.append(f"- **Experiment**: #{experiment.id}")
    lines.append(f"- **Mode**: {experiment.mode} · **Families**: {', '.join(experiment.families)} "
                 f"· **Reps**: {experiment.reps}")
    lines.append(f"- **Status**: {experiment.status}"
                 + (f" ({experiment.stopped_reason})" if experiment.stopped_reason else ""))
    lines.append(f"- **Diff**: {'; '.join(model.diff) or '—'}")
    lines.append(f"- **Order**: {model.order} · **Warming**: {model.warming}")
    lines += [f"- **Generated**: {model.generated_at}", ""]

    # Both attacker models + versions and judges, with each arm's budget (Principle III).
    lines += ["## Arms", ""]
    for result in (a, b):
        arm = arms.get(result.label)
        budget = f"turn cap {arm.turn_cap} · token budget {arm.token_budget}" if arm else ""
        lines.append(f"- **Arm {result.label}** — attacker `{result.attacker_model}` · "
                     f"judge `{result.judge_model}` · {budget}")
    lines.append("")

    lines += ["## Comparison", "", "| Metric | Arm A | Arm B |", "| --- | --- | --- |",
              f"| Confirmed success (hard evidence) | {_rate(a.confirmed)} | {_rate(b.confirmed)} |",
              f"| Suspected success (judge opinion) | {_rate(a.suspected)} | {_rate(b.suspected)} |",
              f"| Mean turns to success | {_turns(a)} | {_turns(b)} |",
              f"| Mean tokens | {_tokens(a)} | {_tokens(b)} |",
              f"| Estimated cost | {_cost(a)} | {_cost(b)} |", ""]

    confirmed = model.comparison.confirmed
    if confirmed.get("no_data"):
        lines += ["Confirmed-rate comparison: no data in at least one arm.", ""]
    else:
        diff = confirmed["diff"]
        p_value = confirmed.get("p_value")
        lines.append("Confirmed-rate difference (B − A): "
                     f"{diff * 100:+.0f} percentage points"
                     + (f" (p = {p_value:.3f})" if p_value is not None else "") + ".")
        if confirmed.get("caveat"):
            lines.append(f"_{confirmed['caveat']}_")
        lines.append("")

    lines += ["## OWASP coverage", "", "| OWASP class | Arm A (confirmed/suspected) | Arm B (confirmed/suspected) |",
              "| --- | --- | --- |"]
    by_owasp_a = {count.key: count for count in a.by_owasp}
    by_owasp_b = {count.key: count for count in b.by_owasp}
    for tested in owasp.TESTED:
        ca = by_owasp_a.get(tested.owasp_class)
        cb = by_owasp_b.get(tested.owasp_class)
        lines.append(f"| {tested.owasp_class} | {_cell(ca)} | {_cell(cb)} |")
    lines.append("")
    return "\n".join(lines)


def _cell(count) -> str:
    return "—" if count is None else f"{count.confirmed}/{count.suspected}"
