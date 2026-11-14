"""A report generated after a run calls the recommender outside the run's scope: its model.request line names the
finding's run on the stream, while the run's kept log — normal or truncated at the cap — stays byte-identical
(010/FR-003, 010/FR-010, 010/SC-009). Real judge client over the offline transport; placeholders only."""
import pytest

from kestrel import store as store_module
from tests.support import fixture_library, real_judge, saved_target

FEATURE = "010"


def kept_rows(store, run_id) -> int:
    with store.connect() as db:
        return db.execute("SELECT COUNT(*) FROM run_log WHERE run_id = ?", (run_id,)).fetchone()[0]


def recommender_lines(json_log):
    return [r for r in json_log.of("model.request") if r["kind"] == "recommender"]


@pytest.fixture
def succeeded_run(make_client, settings, model_transport):
    """A judged single-turn success (a suspected finding), so the report asks the recommender for its fix."""
    model_transport.verdict = "succeeded"
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport))
    target = saved_target(api.app.state.store)

    def run():
        response = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak"})
        assert response.status_code == 201 and response.json()["verdict"] == "succeeded"
        return api, target, response.json()["id"]
    return run


@pytest.mark.parametrize("cap", [None, 3])
def test_a_report_leaves_the_kept_log_unchanged_and_logs_the_recommender_on_the_stream(succeeded_run, monkeypatch,
                                                                                       json_log, cap):
    # FR-003, FR-010, SC-009
    if cap is not None:
        monkeypatch.setattr(store_module, "RUN_LOG_CAP", cap)
    api, target, run_id = succeeded_run()
    store = api.app.state.store
    before, rows = api.get(f"/api/runs/{run_id}/log").text, kept_rows(store, run_id)
    if cap is not None:
        body = api.get(f"/api/runs/{run_id}/log").json()
        assert body["truncated"] is True and body["lines"][-1]["event"] == "log.truncated" and body["kept"] == cap

    assert api.get(f"/api/targets/{target.id}/report").status_code == 200
    lines = recommender_lines(json_log)
    assert len(lines) == 1
    assert (lines[0]["run_id"], lines[0]["target_id"], lines[0]["mode"], lines[0]["family"]) == (
        run_id, target.id, "single_turn", "system_prompt_leak")
    assert lines[0]["prompt"] == "recommender@1" and lines[0]["ok"] is True
    assert api.get(f"/api/runs/{run_id}/log").text == before and kept_rows(store, run_id) == rows

    assert api.get(f"/api/targets/{target.id}/report").status_code == 200   # cached: no second model call
    assert len(recommender_lines(json_log)) == 1
    assert api.get(f"/api/runs/{run_id}/log").text == before and kept_rows(store, run_id) == rows
