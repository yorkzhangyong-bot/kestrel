"""The per-run cap on kept lines (010/FR-010, 010/SC-009): a run that emits more records than RUN_LOG_CAP keeps the
first RUN_LOG_CAP and one `log.truncated` marker whose drop count is the overflow, while the stream carries every
record and the run finishes normally. Stubs suffice; placeholders only."""
import dataclasses
import json

import httpx

from kestrel import store as store_module
from tests.support import StubAttacker, StubJudge, fixture_library, saved_target

FEATURE = "010"

CAP = 5


def test_a_run_over_the_cap_keeps_the_first_lines_and_one_marker(make_client, settings, monkeypatch, json_log):
    # FR-010, SC-009
    monkeypatch.setattr(store_module, "RUN_LOG_CAP", CAP)
    api = make_client(dataclasses.replace(settings, adaptive_max_turns=6),
                      transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "an answer"})),
                      library=fixture_library(), judge=StubJudge(verdict="failed"), attacker=StubAttacker())
    target = saved_target(api.app.state.store)
    run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                      "mode": "adaptive"}).json()
    assert run["status"] == "finished" and run["turns_used"] == 6 and run["stopping_condition"] == "turn_cap"

    streamed = [r for r in json_log() if r.get("run_id") == run["id"]]
    assert len(streamed) > CAP and streamed[-1]["event"] == "run.end"   # the stream keeps everything
    kept = api.app.state.store.list_log_lines(run["id"])
    assert [line.seq for line in kept] == list(range(1, CAP + 2))
    assert [json.loads(line.record) for line in kept[:CAP]] == streamed[:CAP]   # exactly the first CAP records
    marker = json.loads(kept[-1].record)
    assert kept[-1].event == marker["event"] == "log.truncated"
    assert (marker["kept"], marker["dropped"]) == (CAP, len(streamed) - CAP)

    body = api.get(f"/api/runs/{run['id']}/log").json()
    assert (body["kept"], body["dropped"], body["truncated"]) == (CAP, len(streamed) - CAP, True)
    assert body["lines"][-1]["event"] == "log.truncated" and len(body["lines"]) == CAP + 1


def test_the_shipped_cap_is_1000():  # SC-009
    assert store_module.RUN_LOG_CAP == 1000
