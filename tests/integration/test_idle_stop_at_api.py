"""`idle_stop_at` on the run-detail and run-list endpoints, and `needs_attention` on the target list/detail and
target-save responses (014/FR-061, FR-062, SC-022, research D30, D31): computed alongside `run_state` from the
same classification call, never a second store read; the grace case keeps an already-overdue run honest across a
restart; and the target-list cue and the target-detail field can never disagree."""
from datetime import datetime, timedelta, timezone

from tests.integration.test_idle_auto_stop import _resumable_run
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library

FEATURE = "014"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_run_detail_and_list_report_idle_stop_at_for_a_resumable_run(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    run_id = _resumable_run(store, "A")
    run = store.get_run(run_id)
    window = timedelta(hours=settings.resume_idle_hours)
    expected = _iso(datetime.fromisoformat(run.last_activity_at) + window)

    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["idle_stop_at"] == expected

    listing = api.get(f"/api/targets/{run.target_id}/runs").json()
    assert {r["id"]: r["idle_stop_at"] for r in listing}[run_id] == expected


def test_idle_stop_at_is_null_for_a_finished_run(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store, "A")
    run_id = _claim_checkpointed(store, target_id)
    store.finish_run(run_id, verdict="failed", stopping_condition="turn_cap")

    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["idle_stop_at"] is None


def test_idle_stop_at_grace_case_for_a_run_overdue_before_a_restart(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    run_id = _resumable_run(store, "A")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    past = now - timedelta(hours=48)   # older than the 24h window: already overdue
    store.touch_last_activity(run_id, now=past)
    api.app.state.started_at = now

    window = timedelta(hours=settings.resume_idle_hours)
    expected = _iso(now + min(timedelta(hours=1), window))   # never a time already in the past
    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["idle_stop_at"] == expected


def test_get_api_targets_reports_needs_attention(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    attention_run = _resumable_run(store, "A")   # a resumable run: needs attention
    attention_target = store.get_run(attention_run).target_id
    quiet_target = _target(store, "B")           # no runs at all

    targets = api.get("/api/targets").json()
    by_id = {t["id"]: t for t in targets}
    assert by_id[attention_target]["needs_attention"] is True
    assert by_id[quiet_target]["needs_attention"] is False

    # The detail endpoint reports the identical value, never disagreeing with the list.
    assert api.get(f"/api/targets/{attention_target}").json()["needs_attention"] is True
    assert api.get(f"/api/targets/{quiet_target}").json()["needs_attention"] is False
