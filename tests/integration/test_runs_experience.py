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


# ---- feature 011: the selection reaches the hints in order; cold and single-turn runs are unchanged ----

TECHNIQUES = "Techniques from earlier attempts in this family:"


def test_a_warm_runs_hints_list_the_selected_patterns_in_the_retrieval_lines_order(make_client, json_log):
    # 011/FR-005
    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=attacker)
    tid = save_target(api)
    body = run(api, tid, warm=True)
    lines = [r for r in json_log() if r.get("run_id") == body["id"] and r["event"] == "memory.retrieval"]
    assert len(lines) == len(attacker.calls) >= 2   # the background is built before each attacker turn, from turn 2
    collection = api.app.state.experience._collection
    for line, call in zip(lines, attacker.calls):
        got = collection.get(ids=line["pattern_ids"], include=["documents"])
        documents = dict(zip(got["ids"], got["documents"]))
        expected = [documents[pattern_id] for pattern_id in line["pattern_ids"]]
        assert expected, "the warm run selected at least one pattern"
        section = call["hints"].split(TECHNIQUES)[1]
        assert [text[2:] for text in section.splitlines() if text.startswith("- ")] == expected


def test_a_cold_runs_attacker_input_is_unchanged(make_client):  # 011/FR-015, 011/SC-009
    from kestrel.experience.hints import LABEL
    from tests.support import PURPOSE_TEXT, saved_target

    attacker = StubAttacker()
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=attacker)
    tid = save_target(api)
    run(api, tid, warm=True)                                   # warm the store first
    attacker.calls.clear()
    run(api, tid, warm=False)
    assert attacker.calls and all(c["hints"] is None for c in attacker.calls)   # no purpose: no hints at all
    described = saved_target(api.app.state.store, name="Described", description=PURPOSE_TEXT)
    attacker.calls.clear()
    run(api, described.id, warm=False)
    assert attacker.calls and all(c["hints"] == f"{LABEL}\nTarget purpose: {PURPOSE_TEXT}" for c in attacker.calls)


def test_a_single_turn_run_emits_no_retrieval_line(make_client, json_log):  # 011/FR-015
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    tid = save_target(api)
    body = run(api, tid, mode="single_turn", warm=True)
    assert body["status"] == "finished"
    assert not [r for r in json_log() if r.get("run_id") == body["id"] and r["event"] == "memory.retrieval"]


def test_the_same_stub_driven_run_uses_the_same_turns_and_tokens_as_before_the_feature(make_client, settings,
                                                                                     model_transport):
    # 011/SC-009: the values tests/integration/test_log_records_adaptive.py asserts for feature 010
    import dataclasses
    from tests.support import real_attacker, real_judge, saved_target

    three_turns = dataclasses.replace(settings, adaptive_max_turns=3)
    api = make_client(three_turns, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    target = saved_target(api.app.state.store)
    body = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                       "mode": "adaptive"}).json()
    assert body["turns_used"] == 3 and body["tokens_used"] == 120 + 240 + 240
