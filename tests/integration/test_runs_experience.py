"""Warm/cold retrieval through the API: the switch is recorded, warm runs prime the attacker, cold runs do not
(FR-014, FR-015, FR-016, SC-005). Single-turn runs record the setting with no retrieval effect (C1)."""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubAttacker, StubJudge, fixture_library

FEATURE = "004"

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
REPLY = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))  # no canary → judge decides


def connection(**changes):
    base = {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def save_target(api):
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS Agent", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS}).json()["id"]


def run(api, tid, *, mode="adaptive", warm=True):
    return api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": mode,
                                       "use_prior_experience": warm}).json()


def test_a_run_records_the_setting_defaulting_to_warm(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    tid = save_target(api)
    body = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive"}).json()
    assert body["use_prior_experience"] is True   # default (FR-014)


def test_a_single_turn_run_records_the_setting_even_though_it_has_no_effect(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    tid = save_target(api)
    body = run(api, tid, mode="single_turn", warm=False)   # C1
    assert body["use_prior_experience"] is False


def test_a_warm_second_run_gives_the_attacker_memory_from_the_first(make_client):
    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(progress="a step closer"),
                      attacker=attacker)
    tid = save_target(api)
    run(api, tid, warm=True)                         # run 1 writes memory (summary has "a step closer")
    calls_after_first = len(attacker.calls)
    run(api, tid, warm=True)                         # run 2 should receive that memory as a hint
    second_run_hints = [c["hints"] for c in attacker.calls[calls_after_first:]]
    assert any(h and "a step closer" in h for h in second_run_hints)   # SC-005


def test_a_cold_run_adds_no_hints(make_client):
    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=attacker)
    tid = save_target(api)
    run(api, tid, warm=True)                         # seed some memory first
    attacker.calls.clear()
    run(api, tid, warm=False)                        # cold: no patterns, no memory (FR-015, SC-005)
    assert attacker.calls, "the attacker still drove the cold run"
    assert all(c["hints"] is None for c in attacker.calls)
