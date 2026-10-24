"""The purpose description reaches the attacker as background before the first turn, warm or cold (FR-021)."""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubAttacker, StubJudge, fixture_library

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
REPLY = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))
PURPOSE = "a customs classification assistant"


def connection():
    return {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}


def save_target_with_purpose(api) -> int:
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "A", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS,
                                          "description": PURPOSE}).json()["id"]


def run(api, tid, *, warm):
    api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive",
                                "use_prior_experience": warm})


def test_purpose_is_fed_on_a_warm_run(make_client):
    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=attacker)
    run(api, save_target_with_purpose(api), warm=True)
    assert any(c["hints"] and PURPOSE in c["hints"] for c in attacker.calls)


def test_purpose_is_fed_on_a_cold_run_too(make_client):
    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=attacker)
    run(api, save_target_with_purpose(api), warm=False)
    assert attacker.calls, "the attacker drove the run"
    assert all(c["hints"] and PURPOSE in c["hints"] for c in attacker.calls)  # purpose regardless of the switch
    # cold means no retrieved experience: the block is purpose-only (no pattern/memory sections)
    assert all("Techniques" not in c["hints"] and "What happened before" not in c["hints"] for c in attacker.calls)
