"""Fix recommendations for the report's findings (contracts/report-module.md, FR-012/FR-013).

The only I/O-touching report function: it reads/writes the per-run recommendation cache and may call the judge
model once per uncached success. It never calls the target and never writes the experience store. Inputs to the
model are non-secret only (family, OWASP class, the winning attacker message, the evidence) — see FR-018.
"""
from __future__ import annotations

import logging
from typing import Any

from kestrel.judge.client import JudgeError
from kestrel.report.model import Recommendation, proof, winning_message

logger = logging.getLogger("kestrel")


async def recommendations_for(store: Any, judge: Any, runs: list, turns_by_run: dict) -> dict[int, Recommendation]:
    """Return {run_id: Recommendation} for the succeeded runs that have one.

    For each success: serve the cached recommendation if present; otherwise, when a judge is configured, call it
    once with non-secret inputs, cache the result, and include it. A missing judge key, or a failed call, simply
    omits that recommendation (the report then shows a clear "no recommendation" note)."""
    out: dict[int, Recommendation] = {}
    for run in runs:
        if (run.verdict or "") != "succeeded":
            continue
        cached = store.get_recommendation(run.id)
        if cached is not None:
            out[run.id] = Recommendation(text=cached.recommendation, model=cached.model)
            continue
        if not judge.configured:
            continue
        turns = turns_by_run.get(run.id, ())
        evidence, judge_note = proof(run, turns)
        try:
            text, _tokens = await judge.recommend(
                family=run.family, owasp_category=run.owasp_category,
                attack=winning_message(run, turns), evidence=evidence if evidence is not None else (judge_note or ""))
        except JudgeError as error:
            logger.warning("No recommendation for run %s: %s", run.id, error)
            continue
        store.save_recommendation(run.id, recommendation=text, model=judge.model)
        out[run.id] = Recommendation(text=text, model=judge.model)
    return out
