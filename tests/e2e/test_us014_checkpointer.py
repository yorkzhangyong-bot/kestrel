"""Spec acceptance (014/FR-030, 014/SC-010, part 1): a checkpointed adaptive run survives a real process
restart. Two separate
`create_app` instances share one temporary database (never a browser test, which cannot restart Kestrel): instance A
starts an adaptive run and crashes mid-send, leaving the row in_progress and resumable; instance B — a fresh app over
the same database, whose own start-up sweep must classify rather than close that row — resumes it over the real API
surface. Offline throughout (a stubbed model transport and the real offline clients), so the scenario is
deterministic and needs no model key of its own; the marker still requires OPENROUTER_API_KEY because it lives in the
e2e tree.

The live HS-code attempt is a separate, known-failing concern (the OpenRouter guardrail gotcha, CLAUDE.md
2026-11-21/2026-11-24): an untouched pre-existing e2e fails at the connection-test step before this feature's code is
ever reached, so that failure is never a regression of this feature."""
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.settings import Settings
from tests.support import ModelTransport, fixture_library, model_settings, real_attacker, real_judge

FEATURE = "014"

pytestmark = pytest.mark.e2e

TERMS_VERSION = "2"


def _settings(tmp_path) -> Settings:
    return model_settings(Settings(mode="local", db_path=tmp_path / "kestrel.db",
                                   key_file=tmp_path / "secret.key", secret_key=None,
                                   chroma_path=tmp_path / "chroma"))


def _seed_target(api) -> int:
    store = api.app.state.store
    target = store.create_target(name="restart-target", url="http://127.0.0.1:8001/chat", method="POST", headers=[],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply",
                                 terms_version=TERMS_VERSION)
    return target.id


def test_a_checkpointed_run_survives_a_process_restart_and_is_resumed(tmp_path):
    settings = dataclasses.replace(_settings(tmp_path), adaptive_max_turns=2)
    transport = ModelTransport()
    transport.verdict = "failed"

    crashing = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(RuntimeError("simulated crash: attacker drafted, send never completed")))

    with TestClient(create_app(settings, transport=transport.transport, library=fixture_library(),
                               judge=real_judge(transport), attacker=real_attacker(transport))) as api_a:
        target_id = _seed_target(api_a)
        api_a.app.state.transport = crashing   # the send crashes; the attacker/judge still reach `transport`
        with pytest.raises(RuntimeError):
            api_a.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "adaptive"})
        runs = api_a.get(f"/api/targets/{target_id}/runs").json()
        assert len(runs) == 1 and runs[0]["status"] == "in_progress"
        run_id = runs[0]["id"]

    # Instance B over the same database: its own start-up sweep classifies (never closes) the resumable row, then
    # the API resumes it to completion.
    with TestClient(create_app(settings, transport=transport.transport, library=fixture_library(),
                               judge=real_judge(transport), attacker=real_attacker(transport))) as api_b:
        detail = api_b.get(f"/api/runs/{run_id}").json()
        assert detail["run_state"] in ("resumable", "paused")
        resumed = api_b.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "finished"
