"""A resumed live run's evidence checker is rebuilt from its own stored override token and recorded prompt
version - never through the live-claim path (which would mint a new token) or the replay path (which never
regenerates text at all) - and the same rebuild behaves identically for a non-override family (014/FR-044, SC-016,
research D17).

A real run's own opening message carries the override token's two fragments *separately*, as instructions for the
target to combine (the token only disarms if *Kestrel's own* sent text later contains the joined form - a rare,
defensive case, never the normal path) - so these tests construct that sent text directly rather than relying on
`checker.opening_message`'s own realistic, un-joined framing, to exercise the disarm mechanism itself in isolation."""
import asyncio
import dataclasses

import pytest

from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver, classify
from kestrel.connection.tester import TestOutcome as SendOutcome
from kestrel.evidence.checker import build_checker, rebuild_live_checker
from tests.integration.test_stop_endpoint import _target
from tests.support import (StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge)
from tests.unit.test_adaptive_graph_state import make_deps
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _plant_and_claim(store, target_id, library, *, family: str, embed_token: bool = False):
    """Builds the one real checker/token this run plants, computes its opening text, claims and binds - all from
    the *same* checker instance (a second `build_checker` call would mint an unrelated, unused token)."""
    seed = library.pick(family, None)
    checker = build_checker(store=store, family=family, canaries=[], seed=seed)
    if embed_token:
        # Kestrel's own sent text normally carries the token's two fragments separately (an instruction for the
        # target to combine them) - never the joined form, so disarm-via-note_sent tests build it directly here.
        opening = f"<placeholder opening> marker {checker._override.token.joined}"
    else:
        opening = checker.opening_message(seed)
    run_id = store.claim_run(target_id, prompt_id=seed.id, prompt_title=seed.title, prompt_text=opening,
                             family=family, owasp_category=seed.owasp_category, attacker_source="library:1.0.0",
                             mode="adaptive", attacker_model="deepseek/x", turn_budget=6, token_budget=40000,
                             time_limit_s=300, is_checkpointed=True, judge_model="google/gemini-3.8-flash",
                             judge_prompt_id="judge", judge_prompt_version="1")
    checker.bind_run(run_id)
    return run_id, checker, seed, opening


def _sender(*, fail_on_call: int | None = None):
    calls = {"n": 0}

    async def send(resolved, **_kwargs):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise RuntimeError("simulated crash during send")
        return SendOutcome(ok=True, step="success", message="ok", reply_text="<reply>", reply_truncated=False,
                           status_code=200)
    return send


def _client(settings, make_client, model_transport):
    return make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                       judge=real_judge(model_transport), attacker=real_attacker(model_transport))


def test_a_non_override_family_resume_behaves_like_a_live_checker_with_no_planted_state(settings, make_client,
                                                                                         model_transport):
    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id, checker, seed, opening = _plant_and_claim(store, target_id, fixture_library(),
                                                      family="system_prompt_leak")
    assert checker.run_start_fields()["override_planted"] is False

    saver = _FailingPutSaver(store, 4)   # merely resumable: send not yet run
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=_sender(), judge=StubJudge(verdict="failed"), attacker=StubAttacker(),
                 max_turns=2),
        run_id=run_id, checker=checker, opening=opening, seed_prompt=seed)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"
    assert store.list_planted_tokens(run_id) == []


def test_cut_inside_send_before_it_commits_the_resumed_checker_has_not_yet_treated_it_as_sent(
        settings, make_client, model_transport, json_log):
    # 014/FR-044, research D17: from_step: "send", completed: false - the first test task's own node-raises-an-
    # exception technique (a crashing sender), never the saver fault-injection one, since send's own write (and
    # any real disarm) has not landed at all here. The opening message is built to contain the token's joined
    # form directly (never the realistic, fragments-only framing - see the module docstring).
    #
    # note_sent is called *before* the sender is awaited (013/FR-012), so the crashed attempt's own call already
    # disarmed the token for real (and logged it) even though send's own outcome was never received - "the
    # resumed checker has not yet treated it as sent" is about the *rebuilt checker's own* echo-rule input
    # (_sent.texts), seeded only from durably recorded turns (none yet, at this cut), never about disarmed_turn.
    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id, checker, seed, opening = _plant_and_claim(store, target_id, fixture_library(), family="direct_injection",
                                                      embed_token=True)
    assert store.list_planted_tokens(run_id)[0].disarmed_turn is None   # armed: turn 1 has not sent yet

    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=_sender(fail_on_call=1), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_id, checker=checker, opening=opening, seed_prompt=seed)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    status = asyncio.run(classify(copied, run_id, leased=False))
    assert status.from_step == "send" and status.completed is False
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 1   # the crashed send's own note_sent already ran

    rebuilt = rebuild_live_checker(store, fixture_library(), store.get_run(run_id), store.list_turns(run_id))
    assert rebuilt._sent.texts == []   # not yet treated as sent: no durably recorded turn exists for it yet

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"
    # send ran again on resume (and disarmed the token there, for the first and only time): exactly one event.
    disarm_lines = [r for r in json_log() if r.get("event") == "evidence.override_disarmed"]
    assert len(disarm_lines) == 1
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 1


def test_cut_in_sends_own_commit_window_the_resumed_checker_already_has_the_in_flight_message(
        settings, make_client, model_transport, json_log):
    # 014/FR-044, research D17: send's own write landed for real (it ran, disarming the token for real), but its
    # checkpoint commit did not (from_step: "evidence", i.e. past send, completed: true) - built via the saver
    # fault-injection technique T017 established, since a monkeypatched exception inside send cannot reproduce
    # this shape (send's own write already landed).
    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id, checker, seed, opening = _plant_and_claim(store, target_id, fixture_library(), family="direct_injection",
                                                      embed_token=True)

    saver = _FailingPutSaver(store, 5)   # send done (its own write - and disarm - landed), evidence pending
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=_sender(), judge=StubJudge(verdict="failed"), attacker=StubAttacker(),
                 max_turns=2),
        run_id=run_id, checker=checker, opening=opening, seed_prompt=seed)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    status = asyncio.run(classify(copied, run_id, leased=False))
    assert status.from_step == "evidence" and status.completed is True
    # The crashed attempt's own note_sent call already disarmed it for real, before any resume exists.
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 1
    disarm_lines_before = [r for r in json_log() if r.get("event") == "evidence.override_disarmed"]
    assert len(disarm_lines_before) == 1

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"
    # send never re-runs (evidence is next); execute_resume's own note_sent call for the in-flight message must
    # not re-emit a disarm event for a token the crashed attempt already disarmed for real.
    disarm_lines_after = [r for r in json_log() if r.get("event") == "evidence.override_disarmed"]
    assert len(disarm_lines_after) == 1
