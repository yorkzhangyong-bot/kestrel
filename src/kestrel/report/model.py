"""The report's in-memory model and the pure function that builds it (contracts/report-module.md).

`build_report` is a pure function over data already fetched from SQLite (and read-only counts from the experience
store); it does no I/O of its own. The renderers in `render.py` consume only the ReportModel.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recommendation:
    """A model-generated fix suggestion for one finding (always shown labelled as a suggestion)."""
    text: str
    model: str | None = None


@dataclass(frozen=True)
class Header:
    target_name: str
    purpose: str | None
    generated_at: str
    run_count: int
    attacker_models: tuple[str, ...] = ()   # distinct attacker models across the runs (empty for single-turn-only)
    judge_models: tuple[str, ...] = ()
    token_budget: int | None = None
    tokens_used: int = 0


@dataclass(frozen=True)
class CoverageRow:
    owasp_class: str           # e.g. "LLM07: System Prompt Leakage"
    families: str              # the family label(s) Kestrel uses for it
    run_count: int
    result: str                # e.g. "2 run(s), 1 confirmed finding" / "3 run(s), held" / "not run yet"


@dataclass(frozen=True)
class UntestedClass:
    owasp_class: str
    reason: str


@dataclass(frozen=True)
class Finding:
    family: str
    owasp_class: str
    winning_message: str                    # attacker turn(s) up to the succeeded turn, or the seed prompt
    evidence: str | None = None             # verbatim canary evidence (hard evidence), as stored
    judge_note: str | None = None           # the judge's note when the success was judged (suspected)
    recommendation: Recommendation | None = None


@dataclass(frozen=True)
class OtherRun:
    family: str
    when: str
    verdict: str                            # "failed" / "unclear"
    stopping_condition: str | None = None


@dataclass(frozen=True)
class ReportModel:
    header: Header
    coverage: tuple[CoverageRow, ...] = ()
    untested: tuple[UntestedClass, ...] = ()
    findings: tuple[Finding, ...] = ()
    other_runs: tuple[OtherRun, ...] = ()
    limitations: str = ""
    is_empty: bool = False


LIMITATIONS_BASE = (
    "This report covers only the attacks that were run against this target. Judge verdicts are suspected, "
    "not proof. Results depend on the attacker model and the token budget, and warm runs reuse learned memory "
    "and patterns, so outcomes vary between runs.")


def build_report(*, target, runs, turns_by_run, recommendations=None, experience_summary=None, now) -> ReportModel:
    """Assemble the report model from already-fetched data. Pure: no database, model, store or clock of its own.

    `runs` is newest-first; `turns_by_run` maps an adaptive run id to its Turns; `recommendations` maps a
    succeeded run id to a Recommendation; `experience_summary` is {memory_count, pattern_count} or None."""
    if not runs:
        return ReportModel(header=Header(target_name=target.name, purpose=target.description, generated_at=now,
                                         run_count=0), is_empty=True)
    header = _header(target, runs, now)
    other_runs = tuple(_other_run(run) for run in runs if (run.verdict or "") != "succeeded")
    return ReportModel(header=header, other_runs=other_runs, limitations=_limitations(experience_summary),
                       is_empty=False)


def _header(target, runs, now) -> Header:
    attacker_models = tuple(sorted({r.attacker_model for r in runs if r.attacker_model}))
    judge_models = tuple(sorted({r.judge_model for r in runs if r.judge_model}))
    token_budget = next((r.token_budget for r in runs if r.token_budget is not None), None)
    tokens_used = sum((r.tokens_used or 0) for r in runs)
    return Header(target_name=target.name, purpose=target.description, generated_at=now, run_count=len(runs),
                  attacker_models=attacker_models, judge_models=judge_models, token_budget=token_budget,
                  tokens_used=tokens_used)


def _other_run(run) -> OtherRun:
    verdict = run.verdict or ("failed to send" if run.failure_step else "unclear")
    when = (run.finished_at or run.started_at or "")[:19].replace("T", " ")
    return OtherRun(family=run.family, when=when, verdict=verdict, stopping_condition=run.stopping_condition)


def _limitations(experience_summary) -> str:
    text = LIMITATIONS_BASE
    if experience_summary:
        text += (f" This target has {experience_summary.get('memory_count', 0)} memory record(s), and the shared "
                 f"pattern library holds {experience_summary.get('pattern_count', 0)} pattern(s).")
    return text
