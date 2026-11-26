"""A resumed run uses its own stored caps and its own recorded attacker/judge models and prompt references -
never whatever Kestrel is currently configured with (014/FR-041, FR-047, SC-020, research D16)."""
import asyncio
import dataclasses

import pytest

from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from tests.integration.test_stop_endpoint import _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge
from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _claim_and_cut(store, target_id, *, attacker_model, judge_model, attacker_prompt_version="1",
                   judge_prompt_version="1", turn_budget=2, token_budget=40000, time_limit_s=300):
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", mode="adaptive", attacker_model=attacker_model,
                             turn_budget=turn_budget, token_budget=token_budget, time_limit_s=time_limit_s,
                             is_checkpointed=True, attacker_prompt_id="attacker:system_prompt_leak",
                             attacker_prompt_version=attacker_prompt_version, judge_model=judge_model,
                             judge_prompt_id="judge", judge_prompt_version=judge_prompt_version)
    saver = _FailingPutSaver(store, 4)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=turn_budget),
        run_id=run_id)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    return run_id


def test_resume_uses_its_own_pinned_caps_and_models_not_current_settings(settings, make_client, model_transport):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    # Claimed with a different attacker/judge model than whatever "current settings" would pick - and the
    # currently-configured client (registered at make_client time) would not honour these at all if resume ever
    # built its deps from it instead of the run's own stored row.
    run_id = _claim_and_cut(store, target_id, attacker_model="deepseek/pinned-model",
                            judge_model="google/pinned-judge-model")

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "finished"
    assert body["judge_model"] == "google/pinned-judge-model"
    # the real transport only recognises requests by shape (never by model string), so a mismatched model name
    # would still reach it as "attacker"/"judge" - the model string itself travelled through untouched.
    judge_requests = model_transport.model_requests("judge")
    assert judge_requests and b"pinned-judge-model" in judge_requests[0].content


def test_resume_refuses_with_a_named_message_when_the_pinned_prompt_version_file_is_gone(
        settings, make_client, model_transport, monkeypatch):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_and_cut(store, target_id, attacker_model="deepseek/x", judge_model="google/gemini-3.8-flash",
                            judge_prompt_version="999")   # a version that was never bumped to exist

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "pinned_model_unavailable"
    assert body["error"]["message"]

    stop_response = api.post(f"/api/runs/{run_id}/stop")
    assert stop_response.status_code == 200   # Stop never needs the pinned prompt text at all


def test_resume_refuses_with_a_named_message_when_the_pinned_api_key_is_not_configured(settings, make_client,
                                                                                       model_transport):
    no_key_settings = dataclasses.replace(model_settings(settings), judge_api_key="")
    api = make_client(no_key_settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_and_cut(store, target_id, attacker_model="deepseek/x", judge_model="google/gemini-3.8-flash")

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "pinned_model_unavailable"
    assert api.post(f"/api/runs/{run_id}/stop").status_code == 200


def test_resume_refuses_when_the_pinned_prompt_id_no_longer_exists_in_the_library(settings, make_client,
                                                                                  model_transport):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="no-such-prompt-id", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", mode="adaptive", attacker_model="deepseek/x",
                             turn_budget=2, token_budget=40000, time_limit_s=300, is_checkpointed=True,
                             attacker_prompt_id="attacker:system_prompt_leak", attacker_prompt_version="1",
                             judge_model="google/gemini-3.8-flash", judge_prompt_id="judge", judge_prompt_version="1")
    saver = _FailingPutSaver(store, 4)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_id)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409   # never an unhandled error from rebuild_live_checker's own seed lookup
    assert response.json()["error"]["code"] == "pinned_model_unavailable"
    assert api.post(f"/api/runs/{run_id}/stop").status_code == 200


def test_an_invalid_but_present_model_slug_is_not_detected_by_this_check(settings, make_client, model_transport):
    # A merely-invalid slug would only ever fail on an actual call - resume is not refused for that reason alone.
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_and_cut(store, target_id, attacker_model="not-a-real-model-slug",
                            judge_model="also-not-a-real-model-slug")

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200   # the offline transport answers by request shape, not model name
    assert response.json()["status"] == "finished"
