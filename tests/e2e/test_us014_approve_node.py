"""Spec acceptance (014/FR-030, 014/SC-010, part 2): the pending-message and the three decision controls, end to
end, across a real application boundary. Instance A starts an adaptive run with "Ask before each turn" ticked and
pauses before turn 2's drafted message; instance B — a fresh app over the same database, whose own start-up sweep
must classify the paused row rather than close it — shows the identical pending message and exercises Approve
(pause again) then Run to end (finish), and Stop (on a fresh pause). Offline throughout (a stubbed model transport
and the real offline clients); the marker still requires OPENROUTER_API_KEY because it lives in the e2e tree.

The live HS-code attempt is a separate, known-failing concern (the OpenRouter guardrail gotcha, CLAUDE.md
2026-11-21/2026-11-24): an untouched pre-existing e2e fails at the connection-test step before this feature's code
is ever reached, so that failure is never a regression of this feature."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app, load_terms
from kestrel.settings import Settings
from tests.support import ModelTransport, fixture_library, model_settings, real_attacker, real_judge

FEATURE = "014"

pytestmark = pytest.mark.e2e


def _settings(tmp_path) -> Settings:
    return model_settings(Settings(mode="local", db_path=tmp_path / "kestrel.db",
                                   key_file=tmp_path / "secret.key", secret_key=None,
                                   chroma_path=tmp_path / "chroma"))


def _seed_target(api) -> int:
    store = api.app.state.store
    target = store.create_target(name="approve-target", url="http://127.0.0.1:8001/chat", method="POST", headers=[],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply",
                                 terms_version=load_terms().version)
    return target.id


def _client(settings, transport):
    return TestClient(create_app(settings, transport=transport.transport, library=fixture_library(),
                                 judge=real_judge(transport), attacker=real_attacker(transport)))


def test_the_approve_node_controls_end_to_end_across_a_restart(tmp_path):
    settings = dataclasses.replace(_settings(tmp_path), adaptive_max_turns=4)
    transport = ModelTransport()
    transport.verdict = "failed"
    transport.attacker_message = "<drafted message>"

    with _client(settings, transport) as api_a:
        target_id = _seed_target(api_a)
        response = api_a.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                                 "mode": "adaptive", "ask_before_each_turn": True})
        assert response.status_code == 201, response.text
        paused = response.json()
        assert paused["paused"] is True and paused["run_state"] == "paused"
        assert paused["pending_turn"]["turn"] == 2
        assert paused["pending_turn"]["message"] == "<drafted message>"
        run_id = paused["id"]

    # Instance B over the same database: the pause survives the restart, the pending message is identical, and
    # Approve then Run to end drive the run to its natural stop.
    with _client(settings, transport) as api_b:
        detail = api_b.get(f"/api/runs/{run_id}").json()
        assert detail["run_state"] == "paused"
        assert detail["pending_turn"] == paused["pending_turn"]

        approved = api_b.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "approve"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["pending_turn"]["turn"] == 3   # sent turn 2, paused again before turn 3

        finished = api_b.post(f"/api/runs/{run_id}/decision", json={"turn": 3, "decision": "run_to_end"})
        assert finished.status_code == 200, finished.text
        assert finished.json()["status"] == "finished" and finished.json()["paused"] is False

        # Stop, on a fresh pause of a second run against the same target.
        paused_2 = api_b.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                                 "mode": "adaptive", "ask_before_each_turn": True}).json()
        stopped = api_b.post(f"/api/runs/{paused_2['id']}/decision", json={"turn": 2, "decision": "stop"})
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "finished"
        assert stopped.json()["stopping_condition"] == "stopped_by_user"
