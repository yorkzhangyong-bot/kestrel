"""No secret in an arm, the status/result, or the logs (feature 007). Traces 007/FR-011, 007/SC-007."""
import logging
import time

import httpx

from tests.support import StubJudge, fixture_library

FEATURE = "007"

SECRET = "FAKE-NOT-A-REAL-KEY-000000"   # a deliberately fake header value, allowlisted in .gitleaks.toml
ARM_A = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
         "turn_cap": 6, "token_budget": 40000, "write_back": False}
ARM_B = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
         "turn_cap": 6, "token_budget": 40000, "write_back": True}


def _await_finished(client, experiment_id, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = client.get(f"/api/experiments/{experiment_id}/status").json()
        if status["status"] != "running":
            return
        time.sleep(0.05)
    raise AssertionError("experiment did not finish")


def test_no_secret_in_arm_result_or_logs(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "the agent held"}))
    client = make_client(transport=transport, library=fixture_library(), judge=StubJudge(verdict="failed"))
    config = client.get("/api/config").json()
    target = client.app.state.store.create_target(
        name="HS", url="http://t/chat", method="POST", headers=[("X-API-Key", SECRET)],
        body_template='{"message":"{{prompt}}"}', response_path="$.reply",
        terms_version=config["terms"]["version"])
    body = {"target_id": target.id, "mode": "single_turn", "families": ["direct_injection"], "reps": 1,
            "arm_a": ARM_A, "arm_b": ARM_B}
    experiment_id = client.post("/api/experiments", json=body).json()["id"]
    _await_finished(client, experiment_id)

    status_text = client.get(f"/api/experiments/{experiment_id}/status").text
    result_text = client.get(f"/api/experiments/{experiment_id}/result").text
    assert SECRET not in status_text
    assert SECRET not in result_text
    assert SECRET not in caplog.text
    for arm in client.app.state.store.get_experiment(experiment_id).arms:
        assert SECRET not in arm.attacker_model and SECRET not in arm.judge_model   # arms carry names only
