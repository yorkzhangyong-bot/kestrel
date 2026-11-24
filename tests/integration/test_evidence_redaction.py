"""Across a confirmed override run's whole log stream, nothing of the run's own evidence material appears
(013/FR-048, SC-007): no token or token part, no joined form, no evidence detail, no reply or attack text.

Counted with the run's real per-run markers — read back from the store — not with fixed strings, so the check
cannot pass because a placeholder happened to be absent. The part-2 markers (a correlation id, a callback URL,
a tool-argument value, a state key or value) join this file with the lines that could carry them."""
from __future__ import annotations

import httpx

from kestrel.evidence import override
from tests.support import (ATTACK_TEXT, SECRET, TARGET_NAME, TARGET_URL, StubAttacker, StubJudge, fixture_library,
                           in_progress_run_id, planted_values, saved_target)

FEATURE = "013"

CANARY = "KESTREL-CANARY-PLACEHOLDER-77"


def confirmed_run(make_client, settings, json_log):
    """A direct-injection run the target confirms by writing the run's own joined form into its reply."""
    state: dict = {}

    def reply(request: httpx.Request) -> httpx.Response:
        store = state.get("store")
        run_id = in_progress_run_id(store) if store is not None else None
        joined = planted_values(store, run_id).get("joined", "") if run_id is not None else ""
        return httpx.Response(200, json={"reply": f"{CANARY} as instructed: {joined}"})

    api = make_client(settings, transport=httpx.MockTransport(reply), library=fixture_library(),
                      judge=StubJudge(verdict="failed"), attacker=StubAttacker())
    state["store"] = api.app.state.store
    target = saved_target(api.app.state.store, canaries=[CANARY])
    response = api.post("/api/runs", json={"target_id": target.id, "family": "direct_injection",
                                           "prompt_id": "dir-001", "mode": "single_turn"})
    assert response.status_code == 201, response.text
    return api, response.json()


def test_no_line_carries_a_token_a_detail_or_any_text_of_the_run(make_client, settings, json_log):
    # FR-048, SC-007
    api, run = confirmed_run(make_client, settings, json_log)
    store = api.app.state.store
    values = planted_values(store, run["id"])
    items = store.list_evidence(run["id"])
    assert run["hard_evidence"] is True and {i.kind for i in items} == {"canary_in_reply", "instruction_override"}

    stream = json_log.text()
    markers = {
        "the joined form": values["joined"],
        "the first token part": values["first"],
        "the second token part": values["second"],
        "the planted task wording": override.override_task_paragraph(
            override.OverrideToken(values["first"], values["second"]))[0],
        "the canary (an evidence detail)": CANARY,
        "an evidence detail": items[0].detail,
        "the reply text": run["reply_text"],
        "the attack text as sent": run["prompt_text"],
        "the target's auth value": SECRET,
        "the target's URL": TARGET_URL,
        "the target's display name": TARGET_NAME,
        "the attacker's message text": ATTACK_TEXT,
    }
    for label, marker in markers.items():
        assert marker, f"{label} must be a non-empty marker for this count to mean anything"
        assert stream.count(marker) == 0, f"{label} reached the log stream"


def test_the_stream_still_carries_the_kinds_and_the_counts(make_client, settings, json_log):  # FR-047
    api, run = confirmed_run(make_client, settings, json_log)
    lines = [line for line in json_log() if line.get("run_id") == run["id"]]
    start = next(line for line in lines if line["event"] == "run.start")
    check = next(line for line in lines if line["event"] == "evidence.check")
    turn = next(line for line in lines if line["event"] == "turn")
    end = next(line for line in lines if line["event"] == "run.end")

    assert start["override_planted"] is True and start["callback_planted"] is False
    assert start["side_channel"] == "not_configured" and start["callback_listener"] == "off"
    assert check["checks"] == ["canary", "instruction_override", "unsafe_executable_output"]
    assert check["evidence_kinds"] == ["canary_in_reply", "instruction_override"] and check["evidence_count"] == 2
    assert turn["evidence_kinds"] == check["evidence_kinds"] and turn["evidence_count"] == 2
    assert turn["canary_hit"] is True and turn["hard_evidence"] is True
    assert end["evidence_kinds"] == check["evidence_kinds"] and end["evidence_count"] == 2
    assert end["side_channel_status"] == "not_configured"
