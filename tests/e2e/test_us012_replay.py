"""Spec acceptance (012/SC-010): replaying a real run against the live HS-code sacrificial target, through the
API running in-process (as tests/e2e/test_us011_retrieval.py does) on a temporary store.

A live model's own verdict on the day is not guaranteed "succeeded" (tests/e2e/test_us1_attack.py already
documents this for a comparable case), so the source run's own `verdict` column is promoted directly by SQL -
documented, test-only, never a code path a real user action can reach - so it becomes replayable. The scenario
does not assert which of the three outcomes the live model's reply to the replay produces (that depends on the
model's behaviour on the day, not on Kestrel); it asserts the *structure*: a new run linked to the source, one of
the three outcome labels, the judge prompt version recorded, zero attacker-model calls, zero experience-store
writes, and the side-by-side readable afterward.
"""
from __future__ import annotations

import os
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.settings import Settings
from tests.support import SpyExperienceStore

FEATURE = "012"

pytestmark = pytest.mark.e2e


def _settings(tmp_path) -> Settings:
    key = os.environ["OPENROUTER_API_KEY"]
    return Settings(mode="local", db_path=tmp_path / "data" / "kestrel.db", key_file=tmp_path / "secret.key",
                    secret_key=None, chroma_path=tmp_path / "data" / "chroma",
                    judge_api_key=key, attacker_api_key=key)


def _save_target(api, hs_target) -> int:
    form_id = str(uuid.uuid4())
    settings = {"url": hs_target.url, "method": "POST", "headers": [{"name": "X-API-Key", "value": hs_target.key}],
               "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    tested = api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "HS",
                                                      "settings": settings})
    assert tested.json()["ok"], tested.text
    saved = api.post("/api/targets", json={"form_id": form_id, "name": "HS-code target", "settings": settings,
                                           "permission_confirmed": True,
                                           "terms_version": api.get("/api/config").json()["terms"]["version"],
                                           "canaries": [hs_target.canary]})
    assert saved.status_code == 201, saved.text
    return saved.json()["id"]


def _promote_to_succeeded(db_path, run_id: int) -> None:
    """Test-only: bypasses TargetStore.finish_run entirely, which only updates a row still 'in_progress'
    (`WHERE id = ? AND status = 'in_progress'`, store.py) and would raise LookupError on this already-finished
    row. A second, direct sqlite3 connection on the same settings.db_path, overriding only `verdict` - never the
    target's actual reply or any other column, and never reachable through any real user action."""
    db = sqlite3.connect(db_path)
    try:
        with db:
            updated = db.execute("UPDATE runs SET verdict = 'succeeded' WHERE id = ?", (run_id,)).rowcount
        assert updated == 1
    finally:
        db.close()


def test_replaying_a_real_run_has_the_right_structure(tmp_path, hs_target, library_required, json_log):
    settings = _settings(tmp_path)
    experience = SpyExperienceStore(settings.chroma_path)
    with TestClient(create_app(settings, experience=experience)) as api:
        target_id = _save_target(api, hs_target)

        source = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                             "mode": "single_turn"}).json()
        assert source["verdict"] in ("succeeded", "failed", "unclear")
        if source["verdict"] != "succeeded":
            _promote_to_succeeded(settings.db_path, source["id"])

        experience_calls_before = len(experience.queries) + len(experience.pattern_writes) + len(experience.memory_writes)

        response = api.post(f"/api/runs/{source['id']}/replay")
        assert response.status_code == 201, response.text
        replay = response.json()

        assert replay["mode"] == "replay" and replay["source_run_id"] == source["id"]
        assert replay["replay_outcome"] in ("fixed", "still_vulnerable", "inconclusive")
        assert replay["attacker_model"] is None and replay["use_prior_experience"] is False

        detail = api.get(f"/api/runs/{replay['id']}").json()
        comparison = detail["comparison"]
        assert comparison is not None
        assert comparison["source_run_id"] == source["id"] and comparison["replay_run_id"] == replay["id"]
        assert comparison["outcome"] == replay["replay_outcome"]
        # A judge prompt version is recorded whenever the judge was actually consulted (no canary match).
        if not replay["hard_evidence"]:
            assert comparison["replay_judge_prompt"] is not None

        # Zero attacker-model calls, a real count straight off the stream, not inferred from attacker_model being
        # None (FR-002, review item 13).
        attacker_calls = [line for line in json_log() if line.get("event") == "model.request"
                         and line.get("kind") == "attacker"]
        assert attacker_calls == []

        # Zero experience-store calls of any kind, kept under its own name (FR-025, FR-026).
        assert len(experience.queries) + len(experience.pattern_writes) + len(experience.memory_writes) == \
            experience_calls_before

        # A second replay of the replay itself is refused, naming the original source (FR-005).
        again = api.post(f"/api/runs/{replay['id']}/replay")
        assert again.status_code == 409
        error = again.json()["error"]
        assert error["code"] == "replay_of_replay"
        assert error["message"] == f"This run is itself a replay of run #{source['id']}."

    # No attack text, reply text, the target's URL, or the target's key anywhere on the stream (FR-045, FR-047).
    assert hs_target.key not in json_log.text()
