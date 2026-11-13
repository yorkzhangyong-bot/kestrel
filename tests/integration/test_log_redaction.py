"""Nothing sensitive reaches a log line (010/FR-009, 010/SC-002): a target registered with a known auth header value,
URL and display name, a single-turn and an adaptive run whose attack message and reply are known strings, and a judge
whose reason quotes the reply — every one of those strings appears zero times on the stream. Real model clients over
the offline transport; placeholders only. (US3 and US4 extend the count to the log endpoint, the viewer and spans.)"""
import dataclasses
import uuid

from kestrel import tracing
from tests.support import (ATTACK_TEXT, JUDGE_PROGRESS, JUDGE_REASON, MODEL_KEY, REPLY_TEXT, SECRET, TARGET_NAME,
                           TARGET_URL, fixture_library, real_attacker, real_judge)

FEATURE = "010"

KNOWN = {"auth header value": SECRET, "target URL": TARGET_URL, "URL host": "target.kestrel.test",
         "display name": TARGET_NAME, "attack message": ATTACK_TEXT, "reply": REPLY_TEXT,
         "judge reason": JUDGE_REASON, "progress note": JUDGE_PROGRESS, "model API key": MODEL_KEY}


def register(api) -> int:
    """Register the target through the API: a connection test, then a save, as the screen does."""
    settings = {"url": TARGET_URL, "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
                "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    form_id = str(uuid.uuid4())
    tested = api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None,
                                                    "display_name": TARGET_NAME, "settings": settings})
    assert tested.json()["ok"] is True, tested.text
    terms = api.get("/api/config").json()["terms"]["version"]
    saved = api.post("/api/targets", json={"form_id": form_id, "name": TARGET_NAME, "settings": settings,
                                           "permission_confirmed": True, "terms_version": terms})
    assert saved.status_code == 201, saved.text
    target_id = saved.json()["id"]
    retest = api.post("/api/connection-tests", json={"form_id": str(uuid.uuid4()), "target_id": target_id,
                                                    "display_name": TARGET_NAME,
                                                    "settings": {**settings, "headers": [{"name": "X-API-Key",
                                                                                          "value": None}]}})
    assert retest.json()["ok"] is True, retest.text
    return target_id


def redaction_runs(make_client, settings, model_transport, span_exporter=None):
    """A single-turn and an adaptive run against the known target; returns the two run ids."""
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport),
                      span_exporter=span_exporter)
    target_id = register(api)
    seed_text = fixture_library().pick("system_prompt_leak").text
    single = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"}).json()
    adaptive = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "adaptive"}).json()
    assert single["status"] == adaptive["status"] == "finished"
    return api, (single["id"], adaptive["id"]), seed_text


def test_no_known_string_reaches_any_line(make_client, settings, model_transport, json_log):  # FR-009, SC-002
    _api, runs, seed_text = redaction_runs(make_client, settings, model_transport)
    text = json_log.text()
    for label, value in {**KNOWN, "library seed text": seed_text}.items():
        assert text.count(value) == 0, label
    lines = json_log()
    assert {r["run_id"] for r in lines if "run_id" in r} == set(runs)        # both runs logged
    assert any(r["event"] == "connection.test" for r in lines)               # the registration's lines too
    assert any(r["event"] == "model.request" and r["kind"] == "attacker" for r in lines)


def test_a_judged_line_carries_the_verdict_category_never_the_reason(make_client, settings, model_transport,
                                                                     json_log):  # FR-009 (US2 scenario 2)
    redaction_runs(make_client, settings, model_transport)
    judged = [r for r in json_log() if r["event"] in ("model.request", "turn") and r.get("judged", True)
              and r.get("kind", "judge") == "judge"]
    assert judged and all(r["verdict"] == "failed" for r in judged)
    assert all("reason" not in r and "progress" not in r for r in json_log())


def test_a_failing_model_request_logs_the_error_class_only(make_client, settings, model_transport, json_log):
    # FR-009 (US2 scenario 4)
    model_transport.judge_statuses = [400]
    redaction_runs(make_client, settings, model_transport)
    failed = [r for r in json_log() if r["event"] == "model.request" and r["ok"] is False]
    assert failed and all(r["error"] == "JudgeError" and r["status"] == 400 for r in failed)
    assert "placeholder provider error" not in json_log.text()


def test_the_log_endpoint_serves_none_of_them(make_client, settings, model_transport):  # FR-009, FR-011, SC-002
    api, runs, seed_text = redaction_runs(make_client, settings, model_transport)
    for run_id in runs:
        response = api.get(f"/api/runs/{run_id}/log")
        assert response.status_code == 200 and response.json()["lines"]
        for label, value in {**KNOWN, "library seed text": seed_text}.items():
            assert response.text.count(value) == 0, label


def test_no_span_attribute_carries_them(make_client, settings, model_transport, span_collector):  # FR-009, SC-002
    traced = dataclasses.replace(settings, tracing=True)
    _api, runs, seed_text = redaction_runs(make_client, traced, model_transport, span_exporter=span_collector)
    tracing.current().force_flush()
    spans = span_collector.get_finished_spans()
    assert {span.attributes.get("kestrel.run_id") for span in spans if span.name == "kestrel.run"} == set(runs)
    values = [str(value) for span in spans for value in span.attributes.values()]
    for label, value in {**KNOWN, "library seed text": seed_text}.items():
        assert not any(value in attribute for attribute in values), label
