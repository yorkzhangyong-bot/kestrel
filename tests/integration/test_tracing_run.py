"""Tracing on, through the API and an experiment: only Kestrel's spans, one parentless kestrel.run per run covering
every turn, model request and target request, no known string in any attribute, and no trace header to the target;
tracing off: no span at all (010/FR-013, 010/SC-002, 010/SC-004). Real clients over the offline transport, the SDK's
in-process span collector; placeholders only."""
import dataclasses

from kestrel import tracing
from tests.support import (ATTACK_TEXT, MODEL_KEY, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL, await_experiment,
                           fixture_library, model_settings, real_attacker, real_judge, saved_target)

FEATURE = "010"

ARM = {"attacker_model": "deepseek/deepseek-v4.1-flash", "judge_model": "google/gemini-3.8-flash", "turn_cap": 2,
       "token_budget": 40000, "write_back": True}
TRACE_HEADERS = ("traceparent", "tracestate", "baggage")


def spans_of(collector):
    tracing.current().force_flush()
    return list(collector.get_finished_spans())


def trees(spans):
    """{run_id: (root, [descendants])} — every span sorted under the root sharing its trace id."""
    roots = {span.context.trace_id: span for span in spans if span.name == "kestrel.run"}
    out = {}
    for trace_id, root in roots.items():
        out[root.attributes["kestrel.run_id"]] = (root, [s for s in spans if s.context.trace_id == trace_id
                                                         and s is not root])
    return out


def check_tree(root, children, json_log):
    """One run's trace against its lines: a parentless root, a turn span per turn line, a request span per
    model.request and target.request line, each request under its turn."""
    run_id = root.attributes["kestrel.run_id"]
    lines = [r for r in json_log() if r.get("run_id") == run_id]
    assert root.parent is None
    turns = {s.attributes["kestrel.turn"]: s for s in children if s.name == "kestrel.turn"}
    assert sorted(turns) == [r["turn"] for r in lines if r["event"] == "turn"]
    assert all(t.parent.span_id == root.context.span_id for t in turns.values())
    requests = [s for s in children if s.name in ("kestrel.model_request", "kestrel.target_request")]
    model_lines = [r for r in lines if r["event"] == "model.request"]
    target_lines = [r for r in lines if r["event"] == "target.request"]
    assert sum(s.name == "kestrel.model_request" for s in requests) == len(model_lines)
    assert sum(s.name == "kestrel.target_request" for s in requests) == len(target_lines)
    turn_ids = {t.context.span_id for t in turns.values()}
    assert all(s.parent.span_id in turn_ids for s in requests)
    assert {s.name for s in children} <= {"kestrel.turn", "kestrel.model_request", "kestrel.target_request"}


def traced_api(make_client, settings, model_transport, span_collector, **kwargs):
    return make_client(dataclasses.replace(settings, tracing=True), transport=model_transport.transport,
                       library=fixture_library(), span_exporter=span_collector, **kwargs)


def test_an_api_run_and_a_two_run_experiment_are_three_traces_of_their_own(make_client, settings, model_transport,
                                                                           span_collector, json_log):
    # FR-013, SC-004
    api = traced_api(make_client, model_settings(settings), model_transport, span_collector,
                     judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    target = saved_target(api.app.state.store)
    run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                      "mode": "adaptive"}).json()
    created = api.post("/api/experiments", json={
        "target_id": target.id, "mode": "adaptive", "families": ["system_prompt_leak"], "reps": 1,
        "arm_a": {**ARM, "use_prior_experience": False}, "arm_b": {**ARM, "use_prior_experience": True}})
    assert created.status_code == 201, created.text
    assert await_experiment(api, created.json()["id"])["status"] == "finished"

    spans = spans_of(span_collector)
    assert spans and all(span.name.startswith("kestrel.") for span in spans)   # no request span, nothing else
    by_run = trees(spans)
    assert run["id"] in by_run and len(by_run) == 3                          # three runs, three trace ids
    assert len({root.context.trace_id for root, _ in by_run.values()}) == 3
    for root, children in by_run.values():
        check_tree(root, children, json_log)
    assert sum(1 for span in spans if span.name == "kestrel.run") == 3


def test_a_single_turn_run_is_a_one_turn_tree_with_the_judge_under_the_turn(make_client, settings, model_transport,
                                                                           span_collector, json_log):  # FR-013
    api = traced_api(make_client, settings, model_transport, span_collector, judge=real_judge(model_transport))
    target = saved_target(api.app.state.store)
    run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak"}).json()
    root, children = trees(spans_of(span_collector))[run["id"]]
    check_tree(root, children, json_log)
    turn = next(s for s in children if s.name == "kestrel.turn")
    judge = next(s for s in children if s.name == "kestrel.model_request")
    assert judge.attributes["kestrel.kind"] == "judge" and judge.parent.span_id == turn.context.span_id
    assert root.attributes["kestrel.mode"] == "single_turn" and root.attributes["kestrel.memory_written"] is True


def test_no_attribute_carries_a_known_string_and_no_trace_header_reaches_the_target(make_client, settings,
                                                                                     model_transport,
                                                                                     span_collector):
    # FR-009, FR-013, SC-002
    api = traced_api(make_client, settings, model_transport, span_collector, judge=real_judge(model_transport),
                     attacker=real_attacker(model_transport))
    target = saved_target(api.app.state.store)
    for mode in ("single_turn", "adaptive"):
        api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak", "mode": mode})
    spans = spans_of(span_collector)
    values = [str(value) for span in spans for value in span.attributes.values()]
    values += [str(value) for span in spans for value in span.resource.attributes.values()]
    for known in (SECRET, TARGET_URL, "target.kestrel.test", TARGET_NAME, ATTACK_TEXT, REPLY_TEXT, MODEL_KEY):
        assert not any(known in value for value in values), known
    sent = model_transport.target_requests()
    assert sent and not any(header in request.headers for request in sent for header in TRACE_HEADERS)


def test_with_the_flag_off_no_span_exists(make_client, settings, model_transport, span_collector):  # FR-013
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), span_exporter=span_collector)
    target = saved_target(api.app.state.store)
    api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak"})
    assert tracing.current().enabled is False and list(span_collector.get_finished_spans()) == []
