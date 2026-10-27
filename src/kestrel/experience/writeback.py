"""Write-back after every run (contracts/writeback.md, FR-006, FR-009, FR-010).

Called once from POST /api/runs after a run finishes. Writes one memory record (always) and, on success, one
pattern record; records whether it succeeded on the run. A failure is loud: the attack result is kept, the run is
flagged memory_written=false, and an error is logged — a run that does not write back is a bug (Principle V).
"""
from __future__ import annotations

import logging

from kestrel.experience.summary import build_summary

log = logging.getLogger("kestrel")


def write_back(experience, store, run, turns) -> bool:
    """Record the run in the experience store. Returns True if memory was written, False if write-back failed."""
    try:
        summary = build_summary([t.judge_progress for t in turns], family=run.family, verdict=run.verdict,
                                hard_evidence=run.hard_evidence, turns_used=run.turns_used,
                                stopping_condition=run.stopping_condition)
        experience.write_memory(run_id=run.id, target_id=run.target_id, summary=summary, family=run.family,
                                owasp_category=run.owasp_category, verdict=run.verdict or "unclear",
                                hard_evidence=run.hard_evidence, turns_used=run.turns_used,
                                stopping_condition=run.stopping_condition, attacker_model=run.attacker_model)
        if run.verdict == "succeeded":
            experience.write_pattern(run_id=run.id, document=_winning_messages(run, turns), family=run.family,
                                     owasp_category=run.owasp_category)
        store.set_memory_written(run.id, True)
        return True
    except Exception:
        log.exception("write-back failed for run %s; the attack result is kept but was not recorded to the store",
                      run.id)
        try:
            store.set_memory_written(run.id, False)
        except Exception:
            log.exception("could not flag run %s as not written back", run.id)
        return False


def _winning_messages(run, turns) -> str:
    """The attacker message(s) that led to the success — adaptive turns up to succeeded_turn, or the single prompt."""
    if run.mode == "adaptive" and turns:
        cutoff = run.succeeded_turn or max(t.position for t in turns)
        ordered = sorted((t for t in turns if t.position <= cutoff), key=lambda t: t.position)
        return "\n".join(t.attacker_message for t in ordered)
    return run.prompt_text
