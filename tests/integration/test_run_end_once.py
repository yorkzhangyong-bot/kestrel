"""Exactly one `run.end` per run, with whole-run totals, across any number of resumed segments; a segment ending
at a pause emits neither `run.end` nor `run.interrupted`; a segment ending on an exception emits a kept
`run.interrupted` line in place of `run.end` - never both, never neither (014/FR-046, FR-053, SC-018, research D21).
"""
import httpx
import pytest

from kestrel.evidence.checker import EvidenceChecker
from tests.integration.test_stop_endpoint import _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge

FEATURE = "014"


def _target_transport():
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "<agent reply>"}))


def test_a_first_segment_pause_emits_no_run_end(settings, make_client, monkeypatch):
    # FR-053: interrupt() (this feature's own generic suppression mechanism) fired from the run's very first
    # segment, proved independently of part 2's own approve node, which has not shipped yet in this phase.
    from langgraph.types import interrupt

    async def pausing_check_turn(self, turn, reply, remaining):
        interrupt({"turn": turn, "message": "paused for testing"})
        raise AssertionError("unreachable: interrupt() does not return within this invocation")

    monkeypatch.setattr(EvidenceChecker, "check_turn", pausing_check_turn)
    api = make_client(settings, transport=_target_transport(), library=fixture_library(), judge=StubJudge(),
                      attacker=StubAttacker())
    store = api.app.state.store
    target = _target(store)
    response = api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "adaptive"})
    assert response.status_code == 201
    run_id = response.json()["id"]

    lines = store.list_log_lines(run_id)
    assert [line for line in lines if line.event in ("run.end", "run.interrupted")] == []
    assert len([line for line in lines if line.event == "run.paused"]) == 1
    assert store.get_run(run_id).status == "in_progress"


def test_a_first_segment_exception_emits_run_interrupted_not_run_end(settings, make_client, monkeypatch):
    async def boom(self, turn, reply, remaining):
        raise RuntimeError("simulated node crash")

    monkeypatch.setattr(EvidenceChecker, "check_turn", boom)
    api = make_client(settings, transport=_target_transport(), library=fixture_library(), judge=StubJudge(),
                      attacker=StubAttacker())
    store = api.app.state.store
    target = _target(store)
    with pytest.raises(RuntimeError, match="simulated node crash"):
        api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "adaptive"})
    run_id = store.list_runs(target)[0].id

    lines = store.list_log_lines(run_id)
    assert [line.event for line in lines if line.event in ("run.end", "run.interrupted")] == ["run.interrupted"]
    interrupted = [line for line in lines if line.event == "run.interrupted"][0]
    assert '"resumable":true' in interrupted.record.replace(" ", "")
    assert '"error":"RuntimeError"' in interrupted.record.replace(" ", "")
    assert "simulated node crash" not in interrupted.record   # the exception's own class name only, never its text


def test_across_two_resumed_segments_exactly_one_run_end_with_whole_run_totals(settings, make_client,
                                                                                model_transport, monkeypatch):
    calls = {"n": 0}
    original = EvidenceChecker.check_turn

    async def fail_once(self, turn, reply, remaining):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash in segment 1")
        return await original(self, turn, reply, remaining)

    monkeypatch.setattr(EvidenceChecker, "check_turn", fail_once)
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target = _target(store)
    with pytest.raises(RuntimeError, match="simulated crash in segment 1"):
        api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "adaptive",
                                    "adaptive_max_turns": 3})
    run_id = store.list_runs(target)[0].id

    monkeypatch.setattr(EvidenceChecker, "check_turn", original)   # segment 2 completes normally
    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"

    lines = store.list_log_lines(run_id)
    ends = [line for line in lines if line.event == "run.end"]
    assert len(ends) == 1
    interrupted = [line for line in lines if line.event == "run.interrupted"]
    assert len(interrupted) == 1   # segment 1's own crash, kept once, never duplicated by the later run.end
    turns = [line for line in lines if line.event == "turn"]
    assert len(turns) == response.json()["turns_used"]   # one turn line per turn of the *whole* run, not per segment


def test_a_single_turn_run_still_emits_run_end_unconditionally_even_on_exception(settings, make_client, monkeypatch):
    # FR-053: the suppression applies only to a checkpointed, still-in_progress adaptive run - a single-turn run
    # (never checkpointed) keeps today's behaviour exactly.
    async def boom(self, turn, reply, remaining):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(EvidenceChecker, "check_turn", boom)
    api = make_client(settings, transport=_target_transport(), library=fixture_library(), judge=StubJudge())
    store = api.app.state.store
    target = _target(store)
    with pytest.raises(RuntimeError, match="simulated crash"):
        api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "single_turn"})
    run_id = store.list_runs(target)[0].id
    lines = store.list_log_lines(run_id)
    assert [line.event for line in lines if line.event in ("run.end", "run.interrupted")] == ["run.end"]


def test_no_pre_existing_event_test_needed_editing_for_this_feature():
    # 014/FR-046, FR-053: every existing event-level test opens a scope with no run bound, or one bound to a run
    # that is never checkpointed - "checkpointed and still in_progress" can never be satisfied there, so both
    # suites are unaffected by construction. Run unmodified, alongside this feature's own suite.
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/unit/test_events.py",
                             "tests/unit/test_run_log_handler.py", "-q"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
