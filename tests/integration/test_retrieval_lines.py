"""The retrieval line carries the controls in effect and the selection's outcome, and the write-back line says
whether a success was added or merged (011/FR-003, 011/FR-008, 011/FR-013, 011/FR-015, 011/FR-017, 011/SC-003,
011/SC-007). Warm runs through the API on a store seeded with the fixture library, the shipped defaults unless a
test replaces one; the lexical stub's scale. Placeholders only — and none of them reaches the stream."""
import dataclasses

import httpx

from tests.support import (JUDGE_PROGRESS, JUDGE_REASON, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL, StubAttacker,
                           StubJudge, fixture_library, saved_target)

FAMILY = "system_prompt_leak"
SEED_ID = "spl-001"
REPLY = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": REPLY_TEXT}))


def warm_app(make_client, settings, *, transport=REPLY, judge=None, **changes):
    app_settings = dataclasses.replace(settings, adaptive_max_turns=4, **changes)
    api = make_client(app_settings, transport=transport, library=fixture_library(),
                      judge=judge or StubJudge(reason=JUDGE_REASON, progress=JUDGE_PROGRESS), attacker=StubAttacker())
    target = saved_target(api.app.state.store)
    return api, target


def start(api, target_id, **body):
    response = api.post("/api/runs", json={"target_id": target_id, "family": FAMILY, "prompt_id": SEED_ID,
                                           "mode": "adaptive", **body})
    assert response.status_code == 201, response.text
    return response.json()


def lines_of(json_log, run_id, event):
    return [record for record in json_log() if record.get("run_id") == run_id and record["event"] == event]


# ---- the retrieval line (US2) ----


def test_every_retrieval_line_carries_the_settings_and_counts_that_add_up(make_client, settings, json_log):
    # 011/FR-013, 011/SC-003, 011/SC-007
    api, target = warm_app(make_client, settings)
    run = start(api, target.id)
    lines = lines_of(json_log, run["id"], "memory.retrieval")
    assert [line["turn"] for line in lines] == [2, 3, 4]
    for line in lines:
        assert line["k"] == 5 and line["distance_floor"] == 1.8 and line["dedupe_threshold"] == 0.15
        for field in ("candidate_count", "dropped_floor", "dropped_duplicate", "pattern_count"):
            assert isinstance(line[field], int) and line[field] >= 0
        assert line["candidate_count"] == line["dropped_floor"] + line["dropped_duplicate"] + line["pattern_count"]
        distances = line["distances"]
        assert distances == sorted(distances) and all(value <= 1.8 for value in distances)
        assert len(distances) == line["pattern_count"] == len(line["pattern_ids"]) >= 1
        assert line["warm"] is True
    assert [line["query_messages"] for line in lines] == [1, 2, 2]   # the seed alone, then two attacker messages


def test_a_control_switched_off_renders_null_on_the_line(make_client, settings, json_log):  # 011/FR-013
    api, target = warm_app(make_client, settings, experience_distance_floor=None)
    run = start(api, target.id)
    lines = lines_of(json_log, run["id"], "memory.retrieval")
    assert lines and all("distance_floor" in line and line["distance_floor"] is None for line in lines)
    assert all(line["dedupe_threshold"] == 0.15 and line["dropped_floor"] == 0 for line in lines)


def test_a_floor_nothing_passes_selects_nothing_and_the_run_still_finishes(make_client, settings, json_log):
    # 011/FR-003, 011/FR-013
    api, target = warm_app(make_client, settings, experience_distance_floor=0.0001)
    run = start(api, target.id)
    assert run["verdict"] == "failed" and run["turns_used"] == 4   # the same outcome as with the default floor
    lines = lines_of(json_log, run["id"], "memory.retrieval")
    assert len(lines) == 3
    for line in lines:
        assert line["pattern_count"] == 0 and line["warm"] is False and line["pattern_ids"] == []
        assert line["dropped_floor"] == line["candidate_count"] > 0 and line["distances"] == []


def test_no_query_reply_judge_or_pattern_text_reaches_the_stream(make_client, settings, json_log):
    # 011/FR-017, 011/SC-007
    api, target = warm_app(make_client, settings)
    run = start(api, target.id)
    assert lines_of(json_log, run["id"], "memory.retrieval")
    text = json_log.text()
    known = {"seed text": fixture_library().pick(FAMILY, SEED_ID).text, "attacker message": "<attacker turn 2>",
             "reply": REPLY_TEXT, "judge reason": JUDGE_REASON, "judge progress": JUDGE_PROGRESS,
             "auth header value": SECRET, "target URL": TARGET_URL, "display name": TARGET_NAME}
    for label, value in known.items():
        assert text.count(value) == 0, label
    for prompt in fixture_library().prompts:
        assert text.count(prompt.text) == 0, prompt.id


# ---- the write-back line (US3) ----

CANARY = "KESTREL-CANARY-placeholder-2211"
ARM = {"attacker_model": "m", "judge_model": "j", "turn_cap": 4, "token_budget": 40000, "write_back": True}
ECHO = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": f"placeholder {CANARY}"}))


def canary_app(make_client, settings, *, transport=ECHO, **changes):
    """A warm app whose target declares the canary, so the stub target's echo decides a run as hard evidence."""
    app_settings = dataclasses.replace(settings, adaptive_max_turns=4, **changes)
    api = make_client(app_settings, transport=transport, library=fixture_library(),
                      judge=StubJudge(reason=JUDGE_REASON, progress=JUDGE_PROGRESS), attacker=StubAttacker())
    target = saved_target(api.app.state.store, canaries=[CANARY])
    return api, target


def echo_on_even_requests():
    """Reply with the canary on every second request: an adaptive run then succeeds on turn 2, not turn 1."""
    seen = {"count": 0}

    def handle(request):
        seen["count"] += 1
        reply = f"placeholder {CANARY}" if seen["count"] % 2 == 0 else REPLY_TEXT
        return httpx.Response(200, json={"reply": reply})
    return httpx.MockTransport(handle)


def writeback_line(json_log, run_id):
    lines = lines_of(json_log, run_id, "memory.writeback")
    assert len(lines) == 1
    return lines[0]


def test_a_single_turn_success_that_replays_its_seed_merges_into_the_seed(make_client, settings, json_log):
    # 011/FR-008, 011/FR-013
    api, target = canary_app(make_client, settings)
    run = start(api, target.id, mode="single_turn")
    assert run["verdict"] == "succeeded" and run["hard_evidence"] is True
    line = writeback_line(json_log, run["id"])
    assert line["written"] is True and line["pattern_written"] is True and line["level"] == "INFO"
    assert line["pattern_outcome"] == "merged" and line["pattern_id"] == f"pattern:lib:{SEED_ID}"
    assert line["hit_count"] == 2 and line["pattern_distance"] == 0.0
    second = start(api, target.id, mode="single_turn")
    again = writeback_line(json_log, second["id"])
    assert again["pattern_outcome"] == "merged" and again["hit_count"] == 3
    assert api.app.state.experience.count("pattern") == len(fixture_library().prompts)   # no copy was added


def test_an_adaptive_success_on_turn_two_is_added_and_its_repeat_merges_into_it(make_client, settings, json_log):
    # 011/FR-006, 011/FR-013
    api, target = canary_app(make_client, settings, transport=echo_on_even_requests())
    first = start(api, target.id)
    assert first["verdict"] == "succeeded" and first["succeeded_turn"] == 2
    line = writeback_line(json_log, first["id"])
    assert line["pattern_outcome"] == "added" and line["pattern_id"] == f"pattern:run:{first['id']}"
    assert line["hit_count"] == 1
    assert isinstance(line["pattern_distance"], float) and line["pattern_distance"] > 0.15
    second = start(api, target.id)
    assert second["succeeded_turn"] == 2
    again = writeback_line(json_log, second["id"])
    assert again["pattern_outcome"] == "merged" and again["pattern_id"] == f"pattern:run:{first['id']}"
    assert again["hit_count"] == 2 and again["pattern_distance"] == 0.0


def test_a_failed_run_carries_no_outcome_fields(make_client, settings, json_log):  # 011/FR-008, 011/FR-013
    api, target = warm_app(make_client, settings)
    run = start(api, target.id)
    assert run["verdict"] == "failed"
    line = writeback_line(json_log, run["id"])
    assert line["written"] is True and line["pattern_written"] is False
    assert all(field not in line for field in ("pattern_outcome", "pattern_id", "hit_count", "pattern_distance"))


def test_with_de_duplication_off_a_success_is_added_with_a_null_distance(make_client, settings, json_log):
    # 011/FR-008, 011/FR-013
    api, target = canary_app(make_client, settings, experience_dedupe_threshold=None)
    run = start(api, target.id, mode="single_turn")
    line = writeback_line(json_log, run["id"])
    assert line["pattern_outcome"] == "added" and line["pattern_id"] == f"pattern:run:{run['id']}"
    assert line["hit_count"] == 1 and "pattern_distance" in line and line["pattern_distance"] is None
    assert api.app.state.experience.count("pattern") == len(fixture_library().prompts) + 1


def test_an_experiments_write_back_arms_carry_the_outcome_on_their_lines(make_client, settings, json_log):
    # 011/FR-013, 011/FR-015: the engine passes the threshold too
    from tests.support import await_experiment

    api, target = canary_app(make_client, settings)
    body = {"target_id": target.id, "mode": "single_turn", "families": [FAMILY], "reps": 1,
            "arm_a": {**ARM, "use_prior_experience": False}, "arm_b": {**ARM, "use_prior_experience": True}}
    response = api.post("/api/experiments", json=body)
    assert response.status_code == 201, response.text
    experiment_id = response.json()["id"]
    assert await_experiment(api, experiment_id)["status"] == "finished"
    store = api.app.state.store
    run_ids = [run.id for arm in store.get_experiment(experiment_id).arms
               for run in store.arm_runs(experiment_id, arm.id)]
    lines = [writeback_line(json_log, run_id) for run_id in run_ids]
    assert len(lines) == 2 and all(line["pattern_outcome"] == "merged" for line in lines)
    assert all(line["pattern_id"].startswith("pattern:lib:spl-") for line in lines)
    assert sorted(line["hit_count"] for line in lines) == [2, 3]   # both runs replayed the experiment's one seed
