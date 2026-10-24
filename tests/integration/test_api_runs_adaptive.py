"""POST /api/runs with mode=adaptive, through the API, with a stub attacker and judge (contracts/kestrel-api.md).

Covers FR-001, FR-003, FR-004, SC-008. The target send goes through a MockTransport; no network, no attack text.
"""
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


def target_replying(reply: str):
    return httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": reply}))


def make_api(make_client, *, reply="an ordinary answer", judge=None, attacker=None):
    return make_client(transport=target_replying(reply), library=fixture_library(),
                       judge=judge or StubJudge(), attacker=attacker or StubAttacker())


def save_target(client, *, canaries=None, terms=CURRENT_TERMS):
    form_id = str(uuid.uuid4())
    assert client.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                      "settings": connection()}).json()["ok"]
    body = {"form_id": form_id, "name": "HS Agent", "settings": connection(), "permission_confirmed": True,
            "terms_version": terms}
    if canaries is not None:
        body["canaries"] = canaries
    r = client.post("/api/targets", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def adaptive(api, target_id, **extra):
    return api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                       "mode": "adaptive", **extra})


def test_an_adaptive_run_returns_a_finished_detail_with_the_conversation(make_client):
    api = make_api(make_client)
    tid = save_target(api)
    body = adaptive(api, tid).json()
    assert body["mode"] == "adaptive" and body["status"] == "finished"
    assert body["attacker_model"] == "deepseek/deepseek-v3.2"
    assert isinstance(body["turns"], list) and len(body["turns"]) >= 1
    assert body["turns"][0]["attacker_message"] and "judge_progress" in body["turns"][0]
    assert body["turn_budget"] == 6 and body["token_budget"] == 40000


def test_a_single_turn_request_still_behaves_as_feature_002(make_client):
    api = make_api(make_client)
    tid = save_target(api)
    body = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak"}).json()
    assert body["mode"] == "single_turn" and body["turns"] == []


def test_a_canary_match_ends_an_adaptive_run_by_hard_evidence(make_client):
    judge = StubJudge(verdict="failed")  # must not be consulted for the canary turn
    api = make_api(make_client, reply="leaked KESTREL-CANARY-7Q4M2X", judge=judge)
    tid = save_target(api, canaries=["KESTREL-CANARY-7Q4M2X"])
    body = adaptive(api, tid).json()
    assert body["verdict"] == "succeeded" and body["hard_evidence"] is True and body["judge_used"] is False


def test_an_unknown_target_is_404(make_client):
    assert adaptive(make_api(make_client), 999).status_code == 404


def test_an_unknown_family_is_422(make_client):
    api = make_api(make_client)
    tid = save_target(api)
    r = api.post("/api/runs", json={"target_id": tid, "family": "nope", "mode": "adaptive"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "family"


def test_permission_missing_blocks_an_adaptive_run_with_no_row(make_client):
    api = make_api(make_client)
    tid = save_target(api)
    store = api.app.state.store
    with store.connect() as db:
        db.execute("UPDATE targets SET permission_confirmed_at='' WHERE id=?", (tid,))
    r = adaptive(api, tid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "permission_missing"
    assert store.list_runs(tid) == []


def test_old_terms_block_an_adaptive_run(make_client):
    api = make_api(make_client)
    tid = save_target(api)
    store = api.app.state.store
    with store.connect() as db:
        db.execute("UPDATE targets SET terms_version='2' WHERE id=?", (tid,))
    r = adaptive(api, tid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "terms_outdated"
    assert store.list_runs(tid) == []


def test_an_adaptive_run_is_refused_without_an_attacker(make_client):
    api = make_api(make_client, attacker=StubAttacker(configured=False))
    tid = save_target(api)
    r = adaptive(api, tid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "attacker_unavailable"
    assert api.app.state.store.list_runs(tid) == []


def test_cross_mode_one_run_at_a_time(make_client):
    """FR-004: the lock is per target, not per mode. A stuck in-progress run blocks the other mode."""
    api = make_api(make_client)
    tid = save_target(api)
    store = api.app.state.store
    store.claim_run(tid, prompt_id="spl-001", prompt_title="t", prompt_text="x", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    assert adaptive(api, tid).json()["error"]["code"] == "run_in_progress"
    assert api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak"}
                    ).json()["error"]["code"] == "run_in_progress"


def test_no_header_value_in_an_adaptive_run_or_its_response(make_client):
    api = make_api(make_client, reply="an ordinary answer")
    tid = save_target(api)
    response = adaptive(api, tid)
    assert SECRET not in response.text
    assert SECRET not in api.get(f"/api/runs/{response.json()['id']}").text
