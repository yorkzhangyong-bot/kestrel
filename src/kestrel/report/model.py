"""The report's in-memory model and the pure function that builds it (contracts/report-module.md).

`build_report` is a pure function over data already fetched from SQLite (and read-only counts from the experience
store); it does no I/O of its own. The renderers in `render.py` consume only the ReportModel.
"""
from __future__ import annotations

from dataclasses import dataclass

from kestrel.report import owasp


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
    recommendations = recommendations or {}
    header = _header(target, runs, now)
    coverage = tuple(_coverage_row(tested, runs) for tested in owasp.TESTED)
    untested = tuple(UntestedClass(owasp_class=name, reason=reason) for name, reason in owasp.UNTESTED)
    findings = tuple(_finding(run, turns_by_run.get(run.id, ()), recommendations)
                     for run in runs if (run.verdict or "") == "succeeded")
    other_runs = tuple(_other_run(run) for run in runs if (run.verdict or "") != "succeeded")
    return ReportModel(header=header, coverage=coverage, untested=untested, findings=findings,
                       other_runs=other_runs, limitations=_limitations(experience_summary), is_empty=False)


def _coverage_row(tested, runs) -> CoverageRow:
    matching = [r for r in runs if r.owasp_category == tested.owasp_class]
    confirmed = sum(1 for r in matching if (r.verdict or "") == "succeeded" and r.hard_evidence)
    suspected = sum(1 for r in matching if (r.verdict or "") == "succeeded" and not r.hard_evidence)
    return CoverageRow(owasp_class=tested.owasp_class, families=tested.family_label, run_count=len(matching),
                       result=_coverage_result(len(matching), confirmed, suspected))


def _coverage_result(count: int, confirmed: int, suspected: int) -> str:
    """An honest one-liner: confirmed = hard evidence (Principle II), suspected = judge-only, else held."""
    if count == 0:
        return "not run yet"
    parts = []
    if confirmed:
        parts.append(f"{confirmed} confirmed")
    if suspected:
        parts.append(f"{suspected} suspected")
    if not parts:
        return f"{count} run(s), held"
    return f"{count} run(s), " + " + ".join(parts) + " finding(s)"


def winning_message(run, turns) -> str:
    """The attacker message(s) that won: an adaptive run's turns up to `succeeded_turn` (turn 1 is the seed),
    or the seed prompt for a single-turn or turn-less run. Shared by the finding and the recommendation input."""
    if run.mode == "adaptive" and turns:
        cutoff = run.succeeded_turn
        chosen = [t.attacker_message for t in turns if cutoff is None or t.position <= cutoff]
        if chosen:
            return "\n\n".join(chosen)
    return run.prompt_text


def proof(run, turns) -> tuple[str | None, str | None]:
    """The success evidence as (verbatim hard evidence, judge note). A canary success carries the reply that
    contained the canary; a judge-only success carries the judge's note (shown as suspected). Never both."""
    if run.hard_evidence:
        return _success_reply(run, turns), None
    return None, _judge_note(run, turns)


def _finding(run, turns, recommendations) -> Finding:
    evidence, judge_note = proof(run, turns)
    return Finding(family=run.family, owasp_class=run.owasp_category, winning_message=winning_message(run, turns),
                   evidence=evidence, judge_note=judge_note, recommendation=recommendations.get(run.id))


def _turn_at(turns, position):
    if position is None:
        return turns[-1] if turns else None
    return next((t for t in turns if t.position == position), None)


def _success_reply(run, turns) -> str | None:
    if run.mode == "adaptive" and turns:
        turn = _turn_at(turns, run.succeeded_turn)
        if turn is not None and turn.reply_text is not None:
            return turn.reply_text
    return run.reply_text


def _judge_note(run, turns) -> str | None:
    if run.mode == "adaptive" and turns:
        turn = _turn_at(turns, run.succeeded_turn)
        if turn is not None:
            return turn.judge_progress or turn.judge_reason or run.reason
    return run.reason


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
