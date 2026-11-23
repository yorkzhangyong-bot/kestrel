"""`build_comparison`: the source run and its replay shown side by side (data-model.md "research D7, D8";
012/FR-017, FR-018, FR-019, FR-041)."""
from __future__ import annotations

from dataclasses import replace

from kestrel.replay import MULTI_TURN_CAPTION, TurnComparison, build_comparison
from kestrel.store import Run, Turn

FEATURE = "012"

SOURCE_BASE = Run(id=1, target_id=1, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                  family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                  attacker_source="library:1.0.0", status="finished", started_at="2026-11-19T10:00:00Z",
                  verdict="succeeded")
REPLAY_BASE = replace(SOURCE_BASE, id=2, mode="replay", source_run_id=1)


def turn(position, judge_verdict="failed", judge_prompt_id="judge", judge_prompt_version="1"):
    return Turn(position=position, attacker_message="<turn>", reply_text="<reply>", judge_verdict=judge_verdict,
               judge_prompt_id=judge_prompt_id, judge_prompt_version=judge_prompt_version)


# ---- the single-turn pair: one synthetic TurnComparison, no run_turns involved ----


def test_a_single_turn_pair_has_exactly_one_synthetic_turn_comparison():  # FR-017, FR-018, FR-019
    source = replace(SOURCE_BASE, verdict="succeeded", hard_evidence=True, judge_model=None)
    replay = replace(REPLAY_BASE, verdict="failed", hard_evidence=False, judge_model="j/m",
                     judge_prompt_id="judge", judge_prompt_version="1", replay_outcome="fixed")
    comparison = build_comparison(source, [], replay, [])
    assert comparison.turns == (TurnComparison(position=1, sent=True, source_verdict="succeeded",
                                               replay_verdict="failed"),)
    assert comparison.multi_turn_caption is None
    assert comparison.outcome == "fixed"
    assert comparison.source_hard_evidence is True and comparison.replay_hard_evidence is False
    assert comparison.source_judge_prompt is None   # the source's own judge_model is None: no prompt to show
    assert comparison.replay_judge_prompt == "judge@1"


# ---- the adaptive pair: the replay stopped before every recorded message was sent ----


def test_unsent_positions_are_marked_sent_false_with_no_replay_verdict():  # FR-010, FR-017
    source = replace(SOURCE_BASE, mode="adaptive", turns_used=3, hard_evidence=False, verdict="succeeded",
                     succeeded_turn=3)
    source_turns = [turn(1), turn(2), turn(3, judge_verdict="succeeded")]
    replay = replace(REPLAY_BASE, mode="adaptive", turns_used=1, verdict="unclear", replay_outcome="inconclusive")
    replay_turns = [turn(1, judge_verdict="failed")]

    comparison = build_comparison(source, source_turns, replay, replay_turns)

    by_position = {t.position: t for t in comparison.turns}
    assert by_position[1].sent is True and by_position[1].replay_verdict == "failed"
    assert by_position[2].sent is False and by_position[2].replay_verdict is None
    assert by_position[3].sent is False and by_position[3].replay_verdict is None
    assert comparison.multi_turn_caption == MULTI_TURN_CAPTION


# ---- the terminal-turn derivation (research D7): a canary hit never trusts a stale stored judge_verdict ----


def test_the_last_sent_turn_ending_by_canary_is_succeeded_even_with_a_stale_stored_verdict():  # FR-017, SC-002
    """Constructed by hand: turn 2's own run_turns.judge_verdict is 'failed', copied forward from an earlier
    judged turn by the graph's own record_node (the judge never actually ran again on turn 2 - evidence_node's
    canary hit routed straight to record, skipping judge_node) - build_comparison must not trust it blindly."""
    source = replace(SOURCE_BASE, mode="adaptive", turns_used=2, hard_evidence=True, verdict="succeeded",
                     succeeded_turn=2)
    source_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict="failed", judge_prompt_id=None,
                                                          judge_prompt_version=None)]
    replay = replace(REPLAY_BASE, mode="adaptive", turns_used=2, hard_evidence=True, verdict="succeeded",
                     succeeded_turn=2, replay_outcome="still_vulnerable")
    replay_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict="failed", judge_prompt_id=None,
                                                          judge_prompt_version=None)]

    comparison = build_comparison(source, source_turns, replay, replay_turns)

    assert comparison.turns[0].source_verdict == "failed" and comparison.turns[0].replay_verdict == "failed"
    assert comparison.turns[1].source_verdict == "succeeded"   # not the stale stored "failed"
    assert comparison.turns[1].replay_verdict == "succeeded"


def test_the_last_sent_turn_ending_by_a_send_failure_is_not_judged():  # FR-017
    source = replace(SOURCE_BASE, mode="adaptive", turns_used=2, verdict="succeeded", succeeded_turn=2,
                     hard_evidence=False)
    source_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict="succeeded")]
    replay = replace(REPLAY_BASE, mode="adaptive", turns_used=2, verdict=None, failure_step="unreachable",
                     replay_outcome="inconclusive")
    replay_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict=None)]

    comparison = build_comparison(source, source_turns, replay, replay_turns)

    assert comparison.turns[1].replay_verdict is None   # "not judged": the send failed before any judge call
    assert comparison.turns[0].replay_verdict == "failed"   # every earlier turn still trusts the stored verdict


def test_every_turn_before_the_last_sent_one_trusts_the_stored_verdict():  # FR-017
    source = replace(SOURCE_BASE, mode="adaptive", turns_used=3, verdict="succeeded", succeeded_turn=3,
                     hard_evidence=False)
    source_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict="unclear"),
                    turn(3, judge_verdict="succeeded")]
    replay = replace(REPLAY_BASE, mode="adaptive", turns_used=3, verdict="succeeded", succeeded_turn=3,
                     hard_evidence=False, replay_outcome="still_vulnerable")
    replay_turns = [turn(1, judge_verdict="failed"), turn(2, judge_verdict="unclear"),
                   turn(3, judge_verdict="succeeded")]

    comparison = build_comparison(source, source_turns, replay, replay_turns)

    assert [t.source_verdict for t in comparison.turns] == ["failed", "unclear", "succeeded"]
    assert [t.replay_verdict for t in comparison.turns] == ["failed", "unclear", "succeeded"]
