"""Spec acceptance (009/SC-001): a real adaptive run against the live HS-code target records the attacker and judge
prompt versions on its turns and verdict. End to end — real target subprocess, real attacker/judge; skipped without
OPENROUTER_API_KEY. No attack text here — behaviour only."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from kestrel import prompt_registry as pr
from kestrel.api.main import create_app
from kestrel.settings import Settings

FEATURE = "009"

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


def _turns(store, run_id):
    with store.connect() as db:
        return db.execute(
            "SELECT attacker_prompt_id, attacker_prompt_version, judge_prompt_id, judge_prompt_version"
            " FROM run_turns WHERE run_id=? ORDER BY position", (run_id,)).fetchall()


def test_an_adaptive_run_records_prompt_version_provenance(tmp_path, hs_target, library_required):  # 009/SC-001
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as api:
        tid = _save_target(api, hs_target)
        run = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive",
                                          "use_prior_experience": False}).json()
        assert run["verdict"] in ("succeeded", "failed", "unclear")

        store = api.app.state.store
        rows = _turns(store, run["id"])
        assert rows, "the adaptive run recorded at least one turn"
        for row in rows:   # every recorded version exists in the registry (009/SC-001)
            if row["attacker_prompt_id"]:
                assert pr.has(row["attacker_prompt_id"], row["attacker_prompt_version"])
            if row["judge_prompt_id"]:
                assert pr.has(row["judge_prompt_id"], row["judge_prompt_version"])
        assert any(r["judge_prompt_id"] == "judge" for r in rows)   # the judge ran and named its prompt version
