"""Spec acceptance (013/SC-010, part 1): the two reply detectors against the live HS-code sacrificial target,
through the API running in-process (as tests/e2e/test_us012_replay.py does) on a temporary store.

Structure only. Which evidence a live model produces on the day is the model's behaviour, not Kestrel's, so this
asserts what must hold whatever it answers: the run plants its own override token, the joined form is absent
from the message Kestrel sent (checked on the normalised text, the same form the detector's own echo-proofness
rests on), every evidence item carries a known kind, a confirmed run needed no judge, and the judge prompt
version is recorded exactly when the judge was consulted.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.evidence import override
from kestrel.evidence.model import KINDS
from kestrel.settings import Settings
from tests.support import SpyExperienceStore

FEATURE = "013"

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


def test_a_direct_injection_run_plants_an_echo_proof_token_and_reports_its_evidence(tmp_path, hs_target,
                                                                                     library_required, json_log):
    settings = _settings(tmp_path)
    experience = SpyExperienceStore(settings.chroma_path)
    with TestClient(create_app(settings, experience=experience)) as api:
        target_id = _save_target(api, hs_target)

        config = api.get("/api/config").json()["evidence"]
        assert config["callback_listener"] is False          # no base URL configured: no listener route (FR-073)
        assert config["detectors"] == ["instruction_override", "unsafe_executable_output"]

        response = api.post("/api/runs", json={"target_id": target_id, "family": "direct_injection",
                                               "mode": "single_turn"})
        assert response.status_code == 201, response.text
        run = response.json()

        # The run planted its own override token, and the API reports it without its value (FR-038).
        assert run["planted_tokens"] == [{"kind": "override", "armed": True, "disarmed_turn": None,
                                          "prompt": "override_task@1"}]
        store = api.app.state.store
        token = store.list_planted_tokens(run["id"])[0]
        assert len(token.token) == 2 * override.PART_LENGTH

        # Echo-proof: the joined form is in nothing Kestrel composed, even after normalisation (FR-009, SC-010).
        assert override.text_contains_joined(run["prompt_text"], token.token) is False
        parts = override.OverrideToken.from_joined(token.token)
        assert parts.first in run["prompt_text"] and parts.second in run["prompt_text"]

        # Every item is of a known kind, with the fields the contract fixes - whatever the model answered.
        for item in run["evidence"]:
            assert item["kind"] in KINDS and item["label"] == KINDS[item["kind"]].label
            assert item["location"] == KINDS[item["kind"]].location and item["turn"] == 1
            assert item["line"].startswith(f"{item['label']} · turn 1 · ")
            assert token.token not in item["detail"] and parts.first not in item["detail"]
        assert run["evidence_count"] == len(run["evidence"])
        assert run["evidence_kinds"] == sorted({i["kind"] for i in run["evidence"]},
                                               key=lambda kind: list(KINDS).index(kind))
        assert run["side_channel_status"] == "not_configured"

        # Deterministic evidence decides without the judge; the judge prompt version is recorded exactly when
        # the judge was consulted - never for a run the detectors confirmed (FR-002, 009/FR-003).
        stored = store.get_run(run["id"])
        if run["evidence"]:
            assert run["hard_evidence"] is True and run["verdict"] == "succeeded" and run["judge_used"] is False
            assert stored.judge_prompt_version is None
        else:
            assert run["hard_evidence"] is False and run["judge_used"] is True
            assert stored.judge_prompt_id == "judge" and stored.judge_prompt_version is not None
        detail = api.get(f"/api/runs/{run['id']}").json()
        assert detail["evidence"] == run["evidence"] and detail["override_disarmed_notice"] is None

        # The run's own stored message keeps the planted task; the pattern pool never sees it (FR-063).
        for document in experience.pattern_documents:
            assert parts.first not in document and parts.second not in document
        for query in experience.queries:
            assert parts.first not in query["query_text"] and parts.second not in query["query_text"]

    # No token, no part and no reply text on any line of the run's own stream (FR-048, SC-007).
    stream = json_log.text()
    for marker in (token.token, parts.first, parts.second, hs_target.key):
        assert stream.count(marker) == 0
