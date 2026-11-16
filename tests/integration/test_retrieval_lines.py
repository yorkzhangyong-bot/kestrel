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
