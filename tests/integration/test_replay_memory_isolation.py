"""A replay never queries or writes the shared pattern pool or a target's memory, under any outcome
(012/FR-025, FR-026, SC-003)."""
from __future__ import annotations

from pathlib import Path

from tests.support import StubEmbeddingFunction, SpyExperienceStore, TARGET_URL, real_judge, saved_target

FEATURE = "012"

CLAIM = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
            owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def run_attack(client, target_id: int, *, mode: str = "single_turn") -> dict:
    response = client.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": mode})
    assert response.status_code == 201, response.text
    return response.json()


def claim_adaptive_source(store, target_id: int, *, turns: int) -> int:
    run_id = store.claim_run(target_id, mode="adaptive", attacker_model="a/m", turn_budget=6, token_budget=40000,
                             time_limit_s=300, **CLAIM)
    for position in range(1, turns + 1):
        store.add_turn(run_id, position=position, attacker_message=f"<turn {position}>", reply_text="<reply>",
                       judge_verdict="failed")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=False, judge_used=True, judge_model="j/m",
                     stopping_condition="succeeded", succeeded_turn=turns, turns_used=turns)
    return run_id


def spy_client(make_client, settings, *, transport, judge):
    """A client whose experience store is a SpyExperienceStore, so a test can read what it received."""
    spy = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    return make_client(settings, transport=transport, judge=judge, experience=spy), spy


def assert_spy_untouched(spy: SpyExperienceStore) -> None:
    assert spy.queries == [] and spy.pattern_writes == [] and spy.memory_writes == []


def reset_spy(spy: SpyExperienceStore) -> None:
    """Forget whatever the source run itself legitimately wrote back, so only the replay's own calls (there
    must be none) are being asserted on below."""
    spy.queries.clear()
    spy.pattern_writes.clear()
    spy.memory_writes.clear()


def test_a_single_turn_replay_touches_the_experience_store_under_no_outcome(make_client, settings, model_transport):
    model_transport.verdict = "succeeded"
    client, spy = spy_client(make_client, settings, transport=model_transport.transport,
                             judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    source = run_attack(client, target.id)   # a normal run: writes back as usual, not asserted on here
    reset_spy(spy)

    for verdict, outcome in (("failed", "fixed"), ("succeeded", "still_vulnerable")):
        model_transport.verdict = verdict
        replay = client.post(f"/api/runs/{source['id']}/replay").json()
        assert replay["replay_outcome"] == outcome
        assert replay["memory_written"] is None
        assert_spy_untouched(spy)


def test_a_replay_that_fails_to_answer_is_inconclusive_and_still_untouched(make_client, settings, model_transport):
    model_transport.verdict = "succeeded"
    client, spy = spy_client(make_client, settings, transport=model_transport.transport,
                             judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    source = run_attack(client, target.id)
    reset_spy(spy)

    model_transport.target_status = 500
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    assert replay["replay_outcome"] == "inconclusive" and replay["memory_written"] is None
    assert_spy_untouched(spy)


def test_an_adaptive_replay_touches_the_experience_store_under_no_outcome(make_client, settings, model_transport):
    client, spy = spy_client(make_client, settings, transport=model_transport.transport,
                             judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source_id = claim_adaptive_source(store, target.id, turns=2)
    assert_spy_untouched(spy)   # building the source directly, bypassing the live loop, touches no store either

    for verdict, outcome in (("failed", "fixed"), ("succeeded", "still_vulnerable")):
        model_transport.verdict = verdict
        replay = client.post(f"/api/runs/{source_id}/replay").json()
        assert replay["replay_outcome"] == outcome
        assert replay["memory_written"] is None
        assert_spy_untouched(spy)


def test_an_adaptive_replay_that_fails_to_answer_is_inconclusive_and_still_untouched(make_client, settings,
                                                                                      model_transport):
    client, spy = spy_client(make_client, settings, transport=model_transport.transport,
                             judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source_id = claim_adaptive_source(store, target.id, turns=2)

    model_transport.target_status = 500
    replay = client.post(f"/api/runs/{source_id}/replay").json()

    assert replay["replay_outcome"] == "inconclusive" and replay["memory_written"] is None
    assert_spy_untouched(spy)


def test_replay_and_graph_modules_never_import_the_experience_package():
    """Structural guard, defence in depth (research "Experience isolation" code-fact): the absence of the import
    from kestrel.replay and kestrel.attack.graph's own source is itself a guarantee, not just a runtime
    behaviour a particular test happened to exercise. AST-based, so it cannot be fooled by - or falsely flag -
    prose mentioning "kestrel.experience" in a docstring or comment."""
    import ast

    import kestrel.attack.graph as graph_module
    import kestrel.replay as replay_module

    for module in (replay_module, graph_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("kestrel.experience") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("kestrel.experience")
