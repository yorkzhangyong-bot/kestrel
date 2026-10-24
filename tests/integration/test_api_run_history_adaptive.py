"""Adaptive run history through the API: the conversation, the Mode in the list, deletion (FR-020, FR-022)."""
import uuid

import httpx
import pytest

from kestrel.api.main import load_terms
from tests.support import StubAttacker, StubJudge, fixture_library

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


@pytest.fixture
def api(make_client):
    return make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"})),
                       library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())


def save_target(api):
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS Agent", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS}).json()["id"]


def test_the_single_run_endpoint_returns_the_ordered_conversation(api):
    tid = save_target(api)
    run_id = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak",
                                         "mode": "adaptive"}).json()["id"]
    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["mode"] == "adaptive" and len(detail["turns"]) >= 1
    assert [t["position"] for t in detail["turns"]] == list(range(1, len(detail["turns"]) + 1))


def test_the_list_shows_mode_for_each_run(api):
    tid = save_target(api)
    api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak"})          # single-turn
    api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive"})
    modes = [r["mode"] for r in api.get(f"/api/targets/{tid}/runs").json()]
    assert "adaptive" in modes and "single_turn" in modes
    # newest first
    assert api.get(f"/api/targets/{tid}/runs").json()[0]["mode"] == "adaptive"


def test_deleting_the_target_removes_adaptive_runs_and_their_turns(api):
    tid = save_target(api)
    run_id = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak",
                                         "mode": "adaptive"}).json()["id"]
    assert api.delete(f"/api/targets/{tid}").status_code == 204
    assert api.get(f"/api/runs/{run_id}").status_code == 404
    assert api.app.state.store.list_turns(run_id) == []
