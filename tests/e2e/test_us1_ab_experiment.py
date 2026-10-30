"""Spec acceptance (SC-009, FR-003/005/006): a 2-arm experiment against the live HS-code target, N=1,
retrieval off (arm A, cold) vs on (arm B, warm), producing a comparison.

End to end with real pieces - the real HS-code target subprocess, the real attacker and judge, the real ChromaDB
store. The API runs in-process (TestClient) so the experiment's background task runs and the store can be inspected.
Skipped without OPENROUTER_API_KEY (the target makes real model calls). No attack text here - behaviour only.
"""
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.settings import Settings

FEATURE = "007"

pytestmark = pytest.mark.e2e


def _settings(tmp_path) -> Settings:
    key = os.environ["OPENROUTER_API_KEY"]
    return Settings(mode="local", db_path=tmp_path / "data" / "kestrel.db", key_file=tmp_path / "secret.key",
                    secret_key=None, chroma_path=tmp_path / "data" / "chroma",
                    judge_api_key=key, attacker_api_key=key, adaptive_max_turns=2, adaptive_time_limit_s=120)


def _save_target(api, hs_target) -> int:
    form_id = str(uuid.uuid4())
    settings = {"url": hs_target.url, "method": "POST", "headers": [{"name": "X-API-Key", "value": hs_target.key}],
                "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "HS",
                                                   "settings": settings}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS-code target", "settings": settings,
                                          "permission_confirmed": True,
                                          "terms_version": api.get("/api/config").json()["terms"]["version"],
                                          "canaries": [hs_target.canary]}).json()["id"]


def _await_finished(api, experiment_id, timeout_s=300.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = api.get(f"/api/experiments/{experiment_id}/status").json()
        if status["status"] != "running":
            return status
        time.sleep(1.0)
    raise AssertionError("experiment did not finish in time")


def test_two_arm_retrieval_off_vs_on_produces_a_comparison(tmp_path, hs_target, library_required):
    settings = _settings(tmp_path)
    cold = {"attacker_model": settings.attacker_model, "judge_model": settings.judge_model,
            "use_prior_experience": False, "turn_cap": 2, "token_budget": 40000, "write_back": False}
    warm = {"attacker_model": settings.attacker_model, "judge_model": settings.judge_model,
            "use_prior_experience": True, "turn_cap": 2, "token_budget": 40000, "write_back": True}
    with TestClient(create_app(settings)) as api:
        target_id = _save_target(api, hs_target)
        created = api.post("/api/experiments", json={
            "target_id": target_id, "mode": "adaptive", "families": ["system_prompt_leak"], "reps": 1,
            "arm_a": cold, "arm_b": warm})
        assert created.status_code == 201
        experiment_id = created.json()["id"]

        status = _await_finished(api, experiment_id)
        assert status["status"] in ("finished", "stopped")

        result = api.get(f"/api/experiments/{experiment_id}/result").json()
        assert {arm["label"] for arm in result["arms"]} == {"A", "B"}
        for arm in result["arms"]:   # success split into confirmed and suspected, never conflated (SC-002)
            assert "confirmed" in arm and "suspected" in arm
        assert result["comparison"]["confirmed"]["small_sample"] is True   # N=1: a caveat, never a bare % (SC-003)
        assert any("retrieval" in d for d in result["diff"])                # the recorded arm diff (FR-003)
        assert "cold" in result["warming"]                                  # arm A ran cold (FR-005)

        # The cold arm did not write back, so it was not warmed by the other arm (SC-005).
        experiment = api.app.state.store.get_experiment(experiment_id)
        cold_arm = next(arm for arm in experiment.arms if arm.label == "A")
        assert all(run.memory_written is None for run in api.app.state.store.arm_runs(experiment_id, cold_arm.id))

        # The report downloads in both feature-005 formats (FR-014).
        assert api.get(f"/api/experiments/{experiment_id}/report", params={"format": "md"}).status_code == 200
        assert api.get(f"/api/experiments/{experiment_id}/report", params={"format": "html"}).status_code == 200
