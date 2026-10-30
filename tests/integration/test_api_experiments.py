"""Create / status / result for experiments through the API (feature 007).

Traces 007/FR-001, 007/FR-002, 007/FR-003, 007/FR-012, 007/FR-015, 007/SC-001. Offline: MockTransport + stubs.
"""
import time

import httpx

from tests.support import StubAttacker, StubJudge, fixture_library

FEATURE = "007"

ARM_A = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
         "turn_cap": 6, "token_budget": 40000, "write_back": False}
ARM_B = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
         "turn_cap": 6, "token_budget": 40000, "write_back": True}


def _client(make_client, reply="the agent held"):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": reply}))
    return make_client(transport=transport, library=fixture_library(), judge=StubJudge(verdict="failed"),
                       attacker=StubAttacker())


def _target(client):
    config = client.get("/api/config").json()
    target = client.app.state.store.create_target(
        name="HS", url="http://t/chat", method="POST", headers=[],
        body_template='{"message":"{{prompt}}"}', response_path="$.reply",
        terms_version=config["terms"]["version"])
    return target.id


def _await_finished(client, experiment_id, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = client.get(f"/api/experiments/{experiment_id}/status").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"experiment {experiment_id} did not finish within {timeout_s}s")


def test_identical_arms_are_rejected(make_client):
    client = _client(make_client)
    target_id = _target(client)
    body = {"target_id": target_id, "mode": "single_turn", "families": ["direct_injection"], "reps": 1,
            "arm_a": ARM_A, "arm_b": ARM_A}
    response = client.post("/api/experiments", json=body)
    assert response.status_code == 422
    assert any("differ" in e["message"] for e in response.json()["errors"])


def test_create_status_result_happy_path(make_client):
    client = _client(make_client)
    target_id = _target(client)
    body = {"target_id": target_id, "mode": "single_turn", "families": ["direct_injection"], "reps": 2,
            "arm_a": ARM_A, "arm_b": ARM_B}
    created = client.post("/api/experiments", json=body)
    assert created.status_code == 201
    experiment_id = created.json()["id"]

    status = _await_finished(client, experiment_id)
    assert status["status"] == "finished"
    assert status["planned_runs"] == 4 and status["completed_runs"] == 4   # 1 family x 2 reps x 2 arms

    result = client.get(f"/api/experiments/{experiment_id}/result").json()
    labels = {arm["label"] for arm in result["arms"]}
    assert labels == {"A", "B"}
    for arm in result["arms"]:
        assert "confirmed" in arm and "suspected" in arm          # split, never conflated (SC-002)
    assert result["comparison"]["confirmed"]["small_sample"] is True
    assert any("retrieval" in d for d in result["diff"])          # the recorded arm diff (FR-003)


def test_unknown_target_is_404(make_client):
    client = _client(make_client)
    body = {"target_id": 999, "mode": "single_turn", "arm_a": ARM_A, "arm_b": ARM_B}
    assert client.post("/api/experiments", json=body).status_code == 404


def test_experiments_are_listed(make_client):
    client = _client(make_client)
    target_id = _target(client)
    body = {"target_id": target_id, "mode": "single_turn", "families": ["direct_injection"], "reps": 1,
            "arm_a": ARM_A, "arm_b": ARM_B}
    experiment_id = client.post("/api/experiments", json=body).json()["id"]
    _await_finished(client, experiment_id)
    listing = client.get("/api/experiments").json()
    assert any(item["id"] == experiment_id for item in listing)
