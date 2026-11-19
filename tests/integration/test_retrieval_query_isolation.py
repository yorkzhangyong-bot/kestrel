"""Nothing the target writes reaches the retrieval query (011/FR-002, 011/SC-001). Two warm adaptive runs on one
stub target whose purpose description, replies and judge notes carry known markers — after the first run the
target's memory summary, built from the judge's progress notes, carries the progress marker too — and a warm
experiment arm: a spy store records every query it receives, each marker appears zero times, and the family label
and the attacker's own messages appear every time from turn 2 (the last two, in order; the seed leaves the window
on turn 4). A cold run and a single-turn run ask for nothing (011/FR-015). No auth header value, URL or display
name reaches a query (011/FR-017). Placeholders only."""
import dataclasses

import httpx

from kestrel.attacks.library import family_label
from tests.support import (JUDGE_PROGRESS, JUDGE_REASON, PURPOSE_TEXT, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL,
                           SpyExperienceStore, StubAttacker, StubEmbeddingFunction, StubJudge, await_experiment,
                           fixture_library, saved_target)

FAMILY = "system_prompt_leak"
SEED_ID = "spl-001"
LABEL = family_label(FAMILY)
MARKERS = {"reply": REPLY_TEXT, "judge reason": JUDGE_REASON, "judge progress": JUDGE_PROGRESS,
           "purpose description": PURPOSE_TEXT, "auth header value": SECRET, "target URL": TARGET_URL,
           "display name": TARGET_NAME}
ARM = {"attacker_model": "m", "judge_model": "j", "turn_cap": 4, "token_budget": 40000, "write_back": True}


def warm_app(make_client, settings):
    spy = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": REPLY_TEXT}))
    four_turns = dataclasses.replace(settings, adaptive_max_turns=4)
    api = make_client(four_turns, transport=transport, library=fixture_library(),
                      judge=StubJudge(verdict="failed", reason=JUDGE_REASON, progress=JUDGE_PROGRESS),
                      attacker=StubAttacker(), experience=spy)
    target = saved_target(api.app.state.store, description=PURPOSE_TEXT)
    return api, spy, target


def run(api, target_id, **body):
    response = api.post("/api/runs", json={"target_id": target_id, "family": FAMILY, "prompt_id": SEED_ID,
                                           "mode": "adaptive", **body})
    assert response.status_code == 201, response.text
    return response.json()


def seed_text() -> str:
    return fixture_library().pick(FAMILY, SEED_ID).text


def assert_attacker_only(queries, seed: str) -> None:
    """One run's three queries: turn 2 (label + seed), turn 3 (label + seed + turn 2), turn 4 (label + turns 2
    and 3 — the seed has left the window); every known marker appears zero times."""
    assert len(queries) == 3 and all(query["family"] == FAMILY for query in queries)
    texts = [query["query_text"] for query in queries]
    assert all(text.startswith(LABEL) for text in texts)
    assert texts[0] == f"{LABEL} {seed}"
    assert texts[1] == f"{LABEL} {seed} <attacker turn 2>"
    assert texts[2] == f"{LABEL} <attacker turn 2> <attacker turn 3>"
    for text in texts:
        for label, marker in MARKERS.items():
            assert text.count(marker) == 0, label


def test_two_warm_runs_query_with_the_attackers_words_only(make_client, settings):  # 011/FR-002, FR-017, SC-001
    api, spy, target = warm_app(make_client, settings)
    first = run(api, target.id, use_prior_experience=True)
    assert first["turns_used"] == 4 and first["verdict"] == "failed"
    assert_attacker_only(spy.queries, seed_text())
    # The first run wrote a memory summary built from the judge's progress notes: that marker is now in the store,
    # and the second run retrieves it as memory — yet it never enters a query.
    memory = api.app.state.experience.retrieve_memory(target_id=target.id, family=FAMILY, cap=10)
    assert len(memory) == 1 and JUDGE_PROGRESS in memory[0].summary
    second = run(api, target.id, use_prior_experience=True)
    assert second["turns_used"] == 4
    assert len(spy.queries) == 6
    assert_attacker_only(spy.queries[3:], seed_text())


def test_a_cold_run_and_a_single_turn_run_ask_for_nothing(make_client, settings):  # 011/FR-015
    api, spy, target = warm_app(make_client, settings)
    cold = run(api, target.id, use_prior_experience=False)
    assert cold["turns_used"] == 4 and spy.queries == []
    single = run(api, target.id, mode="single_turn", use_prior_experience=True)
    assert single["status"] == "finished" and spy.queries == []


def test_a_warm_experiment_arm_queries_with_the_same_rule(make_client, settings):  # 011/FR-002, SC-001
    api, spy, target = warm_app(make_client, settings)
    body = {"target_id": target.id, "mode": "adaptive", "families": [FAMILY], "reps": 1,
            "arm_a": {**ARM, "use_prior_experience": False}, "arm_b": {**ARM, "use_prior_experience": True}}
    response = api.post("/api/experiments", json=body)
    assert response.status_code == 201, response.text
    experiment_id = response.json()["id"]
    assert await_experiment(api, experiment_id)["status"] == "finished"
    store = api.app.state.store
    warm_arm = next(arm for arm in store.get_experiment(experiment_id).arms if arm.use_prior_experience)
    warm_run = store.arm_runs(experiment_id, warm_arm.id)[0]
    assert warm_run.turns_used == 4
    assert_attacker_only(spy.queries, warm_run.prompt_text)   # the cold arm asked for nothing
