"""Regression replay (feature 012, contracts/api.md, data-model.md): re-send a past, succeeded run's recorded
attacker message(s) verbatim, with no attacker-model call, score each reply exactly as a live run does, and report
one outcome against the source - fixed, still vulnerable, or inconclusive. A replay never queries or writes the
shared pattern pool or a target's memory (FR-025, FR-026); it never imports kestrel.experience (defence in depth,
research "Experience isolation" code-fact).
"""
from __future__ import annotations

from dataclasses import dataclass

from kestrel.store import Run, Target

REPLAY_BLOCKED_REASONS = {
    "in_progress": "A run still in progress can't be replayed.",
    "not_succeeded": "Only a succeeded run can be replayed.",
    "no_message": "This run has no recorded message to resend.",
    "permission_missing": "Tick the permission box and save the target before attacking it.",
    "terms_outdated": "The terms of service have changed; read them and tick the box again.",
    "run_in_progress": "A run against this target is already in progress.",
}

REPLAY_ADVISORY_OVER_TURN_LIMIT = (
    "This source recorded more turns than the current adaptive limit; the replay can end at best "
    "still vulnerable or inconclusive.")


class NotReplayable(Exception):
    """`run` cannot be replayed; `.reason` is one of "in_progress" | "not_succeeded" | "no_message" (FR-004)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReplayOfReplay(Exception):
    """`run` is itself a replay; `.source_run_id` names the original to replay instead (FR-005)."""

    def __init__(self, source_run_id: int | None) -> None:
        super().__init__(source_run_id)
        self.source_run_id = source_run_id


def check_replayable(run: Run) -> None:
    """Raise ReplayOfReplay or NotReplayable; return normally when `run` is eligible (FR-004, FR-005)."""
    if run.mode == "replay":
        raise ReplayOfReplay(run.source_run_id)
    if run.status == "in_progress":
        raise NotReplayable("in_progress")
    if run.verdict != "succeeded":
        raise NotReplayable("not_succeeded")
    if run.mode == "adaptive" and not run.turns_used:
        raise NotReplayable("no_message")


@dataclass(frozen=True)
class ReplayStatus:
    replayable: bool
    blocked_reason: str | None   # one of REPLAY_BLOCKED_REASONS' values, or the ReplayOfReplay message; None iff
                                  #   replayable
    advisory: str | None         # REPLAY_ADVISORY_OVER_TURN_LIMIT or None; independent of blocked_reason


def compute_replay_status(run: Run, target: Target, terms_version: str, adaptive_max_turns: int,
                          target_has_other_run_in_progress: bool) -> ReplayStatus:
    """FR-004 to FR-006, FR-040, FR-042. `terms_version` is the currently loaded terms (load_terms().version);
    `adaptive_max_turns` is settings.adaptive_max_turns; `target_has_other_run_in_progress` is whether a run
    *other than this one* is currently in progress on `run`'s own target. Checked in a fixed order - replay-of-a-
    replay, then check_replayable's own three reasons, then permission, then terms, then another run in progress -
    the same order the single-replay endpoint's own 409 table checks them in, so the two can never disagree. Never
    raises."""
    try:
        check_replayable(run)
    except ReplayOfReplay as error:
        return ReplayStatus(False, f"This run is itself a replay of run #{error.source_run_id}.", None)
    except NotReplayable as error:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS[error.reason], None)
    if not target.permission_confirmed_at:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["permission_missing"], None)
    if target.terms_version != terms_version:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["terms_outdated"], None)
    if target_has_other_run_in_progress:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["run_in_progress"], None)
    advisory = None
    if run.mode == "adaptive" and (run.turns_used or 0) > adaptive_max_turns:
        advisory = REPLAY_ADVISORY_OVER_TURN_LIMIT
    return ReplayStatus(True, None, advisory)


def is_finding(run: Run) -> bool:
    """True for a succeeded, non-replay run (FR-027). No mode check lives in the UI: ui/app.py::render_metrics
    drives its three headline cards from this flag together with the run's own hard_evidence, never a mode check
    of its own, since one boolean alone cannot produce two cards: Confirmed = runs where `finding` and
    `hard_evidence` are both true; Suspected = runs where `finding` is true and `hard_evidence` is false; Runs =
    every run, finding or not. api/main.py::target_report's own report-level exclusion (research D9) already
    computes the same condition inline."""
    return run.verdict == "succeeded" and run.mode != "replay"


def compute_outcome(turn_results: list[str | None], recorded_total: int, winning_turn: int | None) -> str:
    """"fixed" | "still_vulnerable" | "inconclusive" (research D5; FR-012 to FR-016). `turn_results` has exactly
    one entry per turn actually attempted, in order - never an aggregate run-level verdict: each entry is
    "succeeded", "failed", or None (an unclear judge verdict, a judge error, no judge configured and no canary, or
    a send failure that ended the attempt before any judge call). A turn never reached because the replay stopped
    earlier has no entry at all, so `len(turn_results) < recorded_total` alone is enough to say not every message
    was sent. `winning_turn` is the source's own winning turn - the turn its original run succeeded at
    (`runs.succeeded_turn`, 1-based) - inspected only when `recorded_total` is more than one message, where
    "fixed" additionally requires `turn_results[winning_turn - 1] == "failed"`: the source's later recorded
    messages were written to continue a conversation the *original* target produced, so once today's target's
    replies diverge, those later messages may no longer fit the conversation they were written for, and an
    all-"failed" judge run should still confirm the one turn whose failure actually matters. `winning_turn is None`
    for a multi-message source is the defensive case of a succeeded source with no recorded winning turn (not
    reachable through normal operation) - fails closed to "inconclusive", never "fixed". For `recorded_total == 1`
    the check does not apply at all and `winning_turn` is ignored outright - a single-turn source's own
    `succeeded_turn` is always `None` (`store.py`'s schema: "single-turn runs leave these at their defaults/null");
    gating on `recorded_total > 1`, not on `winning_turn is None`, is what keeps a single-message source's outcome
    exactly as it was before this addition."""
    if any(result == "succeeded" for result in turn_results):
        return "still_vulnerable"
    if not (len(turn_results) == recorded_total and all(result == "failed" for result in turn_results)):
        return "inconclusive"
    if recorded_total > 1 and (winning_turn is None or not (1 <= winning_turn <= len(turn_results))
                                or turn_results[winning_turn - 1] != "failed"):
        return "inconclusive"
    return "fixed"
