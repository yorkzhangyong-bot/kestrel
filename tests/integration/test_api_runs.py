"""POST /api/runs end to end through the API, with a fixture library and a stub judge (contracts/kestrel-api.md).

Covers FR-006, FR-009 to FR-011, FR-023, SC-009, SC-011. The target send goes through a MockTransport; the judge
is stubbed, so no network and no real attack content.
"""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubJudge, fixture_library

FEATURE = "002"

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
CANARY = "KESTREL-CANARY-7Q4M2X"


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def target_replying(reply: str):
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": reply}))


def make_api(make_client, *, reply="an ordinary answer", judge=None, terms=CURRENT_TERMS):
    client = make_client(transport=target_replying(reply), library=fixture_library(),
                         judge=judge or StubJudge())
    return client


def save_target(client, *, canaries=None, permission=True, terms=CURRENT_TERMS):
    form_id = str(uuid.uuid4())
    assert client.post("/api/connection-tests",
                       json={"form_id": form_id, "target_id": None, "display_name": "Agent",
                             "settings": connection()}).json()["ok"]
    body = {"form_id": form_id, "name": "HS Agent", "settings": connection(), "permission_confirmed": permission,
            "terms_version": terms}
    if canaries is not None:
        body["canaries"] = canaries
    response = client.post("/api/targets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_run_returns_a_finished_run_detail(make_client):
    api = make_api(make_client)
    target_id = save_target(api)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "finished" and body["verdict"] == "failed"
    assert body["family"] == "system_prompt_leak" and body["attacker_source"] == "library:1.0.0"
    assert body["judge_used"] is True and body["judge_model"] == "google/gemini-3.8-flash"


def test_a_specific_prompt_can_be_chosen(make_client):
    api = make_api(make_client)
    target_id = save_target(api)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "prompt_id": "spl-002"})
    assert response.json()["prompt_id"] == "spl-002"


def test_a_canary_match_succeeds_without_the_judge(make_client):
    judge = StubJudge(verdict="failed")  # would disagree, but must not be consulted
    api = make_api(make_client, reply=f"the key is {CANARY}", judge=judge)
    target_id = save_target(api, canaries=[CANARY])
    body = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"}).json()
    assert body["verdict"] == "succeeded" and body["hard_evidence"] is True
    assert body["judge_used"] is False and judge.calls == []


def test_an_unknown_target_is_404(make_client):
    api = make_api(make_client)
    assert api.post("/api/runs", json={"target_id": 999, "family": "system_prompt_leak"}).status_code == 404


def test_an_unknown_family_is_422_on_family(make_client):
    api = make_api(make_client)
    target_id = save_target(api)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "nonsense"})
    assert response.status_code == 422 and response.json()["errors"][0]["field"] == "family"


def test_an_unknown_prompt_id_is_422_on_prompt_id(make_client):
    api = make_api(make_client)
    target_id = save_target(api)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "prompt_id": "spl-999"})
    assert response.status_code == 422 and response.json()["errors"][0]["field"] == "prompt_id"


def test_a_tester_failure_still_stores_a_run(make_client):
    """address_not_allowed, unreachable and the like are failures of the send, so they do leave a run (FR-014)."""
    def handler(request):
        # The greeting (connection test) succeeds so the target can be saved; the attack send fails.
        return httpx.Response(200, json={"reply": "Hi"}) if b"Hello" in request.content else httpx.Response(500)

    api = make_client(transport=httpx.MockTransport(handler), library=fixture_library(), judge=StubJudge())
    target_id = save_target(api)
    body = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"}).json()
    assert body["failure_step"] == "endpoint_error" and body["verdict"] is None
    assert api.get(f"/api/targets/{target_id}/runs").json()[0]["failure_step"] == "endpoint_error"


def test_a_second_run_while_one_is_in_progress_is_409(make_client, monkeypatch):
    """FR-010: the one-in-progress rule. Force a stuck in-progress row, then try again."""
    api = make_api(make_client)
    target_id = save_target(api)
    # Leave a run in progress directly in the store, mimicking a crash mid-run.
    store = api.app.state.store
    store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                    family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                    attacker_source="library:1.0.0")
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "run_in_progress"


def test_a_target_without_permission_cannot_be_attacked(make_client):
    """SC-009: no run, and no judge call, without a permission confirmation."""
    judge = StubJudge()
    api = make_api(make_client, judge=judge)
    # Save with permission, then clear it directly to simulate a target with none.
    target_id = save_target(api)
    store = api.app.state.store
    with store.connect() as db:
        db.execute("UPDATE targets SET permission_confirmed_at = '' WHERE id = ?", (target_id,))
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "permission_missing"
    assert store.list_runs(target_id) == [] and judge.calls == []


def test_a_target_on_old_terms_cannot_reach_the_judge(make_client):
    """SC-011: a target saved under old terms is refused before any run row or judge call."""
    judge = StubJudge()
    api = make_api(make_client, judge=judge)
    target_id = save_target(api)
    store = api.app.state.store
    with store.connect() as db:
        db.execute("UPDATE targets SET terms_version = '1' WHERE id = ?", (target_id,))
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "terms_outdated"
    assert store.list_runs(target_id) == [] and judge.calls == []


def test_the_header_value_never_appears_in_a_run_or_its_response(make_client):
    """FR-014, SC-006: the auth header value reaches only the target, never the run record or the API response."""
    api = make_api(make_client, reply="an ordinary answer")
    target_id = save_target(api)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert SECRET not in response.text
    run_id = response.json()["id"]
    assert SECRET not in api.get(f"/api/runs/{run_id}").text
