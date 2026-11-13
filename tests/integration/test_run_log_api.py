"""GET /api/runs/{run_id}/log serves a run's kept lines in order — run.start first, the write-back before run.end,
run.end last — an empty list for a run without kept lines, the lines so far for a run in progress, 404 for an unknown
run, and the hosted token like every endpoint (010/FR-011, 010/SC-002, 010/SC-003). Stubs and placeholders only."""
from tests.support import (ATTACK_TEXT, MODEL_KEY, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL, StubAttacker, StubJudge,
                           fixture_library, real_attacker, real_judge, saved_target)

FEATURE = "010"


def api_with_target(make_client, settings, model_transport, **clients):
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(), **clients)
    return api, saved_target(api.app.state.store)


def test_a_finished_run_serves_its_kept_lines_in_order(make_client, settings, model_transport):  # FR-011, SC-003
    api, target = api_with_target(make_client, settings, model_transport, judge=StubJudge(),
                                  attacker=StubAttacker())
    run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                      "mode": "adaptive"}).json()
    body = api.get(f"/api/runs/{run['id']}/log").json()
    events = [line["event"] for line in body["lines"]]
    assert body["run_id"] == run["id"] and events[0] == "run.start" and events[-1] == "run.end"
    assert events[-2] == "memory.writeback" and events.count("turn") == run["turns_used"]
    assert body["kept"] == len(body["lines"]) and body["dropped"] == 0 and body["truncated"] is False
    assert all(line["run_id"] == run["id"] for line in body["lines"])


def test_a_run_without_kept_lines_answers_an_empty_list(make_client, settings, model_transport):  # FR-011
    api, target = api_with_target(make_client, settings, model_transport)
    run_id = api.app.state.store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                                           family="system_prompt_leak", owasp_category="LLM07",
                                           attacker_source="library:1.0.0")   # a run from before the feature
    api.app.state.store.finish_run(run_id, verdict="failed")
    response = api.get(f"/api/runs/{run_id}/log")
    assert response.status_code == 200
    assert response.json() == {"run_id": run_id, "lines": [], "kept": 0, "dropped": 0, "truncated": False}


def test_a_run_in_progress_serves_the_lines_kept_so_far(make_client, settings, model_transport):  # FR-011
    api, target = api_with_target(make_client, settings, model_transport)
    store = api.app.state.store
    run_id = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07", attacker_source="library:1.0.0")
    store.add_log_line(run_id, seq=1, ts="2026-11-13T10:00:00.000Z", event="run.start",
                       record=f'{{"event":"run.start","run_id":{run_id}}}')
    body = api.get(f"/api/runs/{run_id}/log").json()
    assert store.get_run(run_id).status == "in_progress"
    assert body["lines"] == [{"event": "run.start", "run_id": run_id}] and body["kept"] == 1


def test_an_unknown_run_is_404(make_client, settings, model_transport):  # FR-011
    api, _target = api_with_target(make_client, settings, model_transport)
    response = api.get("/api/runs/999/log")
    assert response.status_code == 404
    assert response.json()["error"] == {"code": "not_found", "field": None, "message": "No run with id 999."}


def test_hosted_mode_needs_the_token(make_client, hosted_settings, model_transport):  # FR-011
    import dataclasses
    api = make_client(dataclasses.replace(hosted_settings, api_token="t0ken-for-tests"),
                      transport=model_transport.transport, library=fixture_library())
    assert api.get("/api/runs/1/log").status_code == 401
    assert api.get("/api/runs/1/log", headers={"X-Kestrel-Token": "t0ken-for-tests"}).status_code == 404


def test_no_served_line_carries_a_known_string(make_client, settings, model_transport):  # FR-009, SC-002
    api, target = api_with_target(make_client, settings, model_transport, judge=real_judge(model_transport),
                                  attacker=real_attacker(model_transport))
    texts = []
    for mode in ("single_turn", "adaptive"):
        run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                          "mode": mode}).json()
        response = api.get(f"/api/runs/{run['id']}/log")
        assert response.json()["lines"]
        texts.append(response.text)
    for value in (SECRET, TARGET_URL, "target.kestrel.test", TARGET_NAME, ATTACK_TEXT, REPLY_TEXT, MODEL_KEY):
        assert all(value not in text for text in texts), value
