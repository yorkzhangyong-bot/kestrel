"""GET /api/targets/{id}/runs and GET /api/runs/{id} (contracts/kestrel-api.md, FR-028, FR-030, SC-010)."""
import uuid

import httpx
import pytest

from kestrel.api.main import load_terms
from tests.support import StubJudge, fixture_library

FEATURE = "002"

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


@pytest.fixture
def api(make_client):
    return make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"})),
                       library=fixture_library(), judge=StubJudge())


def save_target(api):
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS Agent", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS}).json()["id"]


def run_once(api, target_id, family="system_prompt_leak"):
    return api.post("/api/runs", json={"target_id": target_id, "family": family}).json()


def test_runs_are_listed_newest_first(api):
    target_id = save_target(api)
    first = run_once(api, target_id)
    second = run_once(api, target_id)
    listed = api.get(f"/api/targets/{target_id}/runs").json()
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    assert set(listed[0]) >= {"id", "family", "verdict", "started_at"}  # the summary shape


def test_run_history_404s_for_an_unknown_target(api):
    assert api.get("/api/targets/999/runs").status_code == 404


def test_a_single_run_is_fetchable_in_full(api):
    target_id = save_target(api)
    run_id = run_once(api, target_id)["id"]
    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["id"] == run_id and detail["status"] == "finished"
    assert "prompt_text" in detail and "attacker_source" in detail


def test_an_unknown_run_is_404(api):
    assert api.get("/api/runs/999").status_code == 404


def test_deleting_a_target_removes_its_runs(api):
    target_id = save_target(api)
    run_id = run_once(api, target_id)["id"]
    assert api.delete(f"/api/targets/{target_id}").status_code == 204
    assert api.get(f"/api/runs/{run_id}").status_code == 404
    assert api.get(f"/api/targets/{target_id}/runs").status_code == 404


def test_runs_survive_a_restart(make_client, settings):
    """SC-010: the runs are in the database, so a fresh app over the same file still lists them."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))
    api = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge())
    target_id = save_target(api)
    run_once(api, target_id)
    again = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge())
    assert len(again.get(f"/api/targets/{target_id}/runs").json()) == 1
