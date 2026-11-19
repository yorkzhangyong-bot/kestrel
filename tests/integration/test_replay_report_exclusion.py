"""A replay leaves no trace in a target's OWASP report or its run-list headline counts (012/FR-027, SC-004)."""
from __future__ import annotations

from tests.support import TARGET_URL, real_judge, saved_target

FEATURE = "012"

CLAIM = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
            owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def section(markdown: str, heading: str, next_heading: str) -> str:
    start = markdown.index(heading)
    end = markdown.index(next_heading, start)
    return markdown[start:end]


def finding_count(markdown: str) -> int:
    findings = section(markdown, "## Findings", "## Failed and unclear runs")
    return findings.count("\n### ")


def run_attack(client, target_id: int) -> dict:
    response = client.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                               "mode": "single_turn"})
    assert response.status_code == 201, response.text
    return response.json()


def test_replaying_an_existing_finding_leaves_the_report_unchanged(make_client, model_transport):
    model_transport.verdict = "succeeded"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    source = run_attack(client, target.id)
    assert source["verdict"] == "succeeded"

    before = client.get(f"/api/targets/{target.id}/report").text
    before_coverage = section(before, "## OWASP coverage", "## Findings")
    before_findings = finding_count(before)
    recommender_calls_before = len(model_transport.model_requests("recommender"))

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source['id']}/replay").json()
    assert replay["replay_outcome"] == "fixed"

    after = client.get(f"/api/targets/{target.id}/report").text
    after_coverage = section(after, "## OWASP coverage", "## Findings")
    after_findings = finding_count(after)
    recommender_calls_after = len(model_transport.model_requests("recommender"))

    assert before_coverage == after_coverage
    assert before_findings == after_findings == 1   # the replay never appears as a second finding
    # The second report build makes no new recommender call: the cached recommendation still serves run 1,
    # and the replay (excluded entirely) never reaches recommendations_for in the first place.
    assert recommender_calls_after == recommender_calls_before


def test_a_target_whose_only_succeeded_run_is_a_replay_has_zero_findings(make_client, model_transport):
    model_transport.verdict = "succeeded"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source = run_attack(client, target.id)

    model_transport.verdict = "succeeded"   # the replay also "succeeds" - still must not count as a finding
    replay = client.post(f"/api/runs/{source['id']}/replay").json()
    assert replay["verdict"] == "succeeded" and replay["mode"] == "replay"

    # Remove the source directly, leaving the replay as the target's only succeeded run. source_run_id is
    # declared ON DELETE CASCADE, so the replay's own link must be cleared BEFORE the source is deleted, or the
    # cascade would remove the replay too.
    with store.connect() as db:
        db.execute("UPDATE runs SET source_run_id = NULL WHERE id = ?", (replay["id"],))
        db.execute("DELETE FROM runs WHERE id = ?", (source["id"],))

    report = client.get(f"/api/targets/{target.id}/report").text
    # With its only remaining run excluded entirely, the target has nothing left to report - the same empty
    # shape a target with zero runs at all gets, never a "## Findings" section claiming the replay as one.
    assert "No runs to report yet" in report and "## Findings" not in report


def test_the_finding_flag_is_true_only_for_a_succeeded_non_replay_run(make_client, model_transport):
    model_transport.verdict = "succeeded"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    source = run_attack(client, target.id)

    model_transport.verdict = "succeeded"   # a still-vulnerable replay: verdict "succeeded", finding still False
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    model_transport.verdict = "failed"
    failed = run_attack(client, target.id)

    runs = {r["id"]: r for r in client.get(f"/api/targets/{target.id}/runs").json()}
    assert runs[source["id"]]["finding"] is True
    assert runs[replay["id"]]["finding"] is False and runs[replay["id"]]["verdict"] == "succeeded"
    assert runs[failed["id"]]["finding"] is False
