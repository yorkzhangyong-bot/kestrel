"""Adaptive run storage: mode, budgets, the conversation turns and the outcome (data-model.md, FR-012/15/19/20)."""
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "003"

PROMPT = dict(prompt_id="spl-002", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
              owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "test-key-123")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="3")


def test_an_adaptive_run_records_its_mode_and_budgets(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="deepseek/deepseek-v3.2",
                             turn_budget=6, token_budget=40000, time_limit_s=300, **PROMPT)
    run = store.get_run(run_id)
    assert run.mode == "adaptive" and run.attacker_model == "deepseek/deepseek-v3.2"
    assert run.turn_budget == 6 and run.token_budget == 40000 and run.time_limit_s == 300
    assert run.status == "in_progress"


def test_turns_append_in_order_and_read_back(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="m", **PROMPT)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>", judge_verdict="failed",
                   judge_reason="held", judge_progress="close-ish")
    store.add_turn(run_id, position=2, attacker_message="<m2>", reply_text="<r2>", judge_verdict="unclear")
    turns = store.list_turns(run_id)
    assert [t.position for t in turns] == [1, 2]
    assert turns[0].attacker_message == "<m1>" and turns[0].reply_text == "<r1>"
    assert turns[0].judge_verdict == "failed" and turns[0].judge_progress == "close-ish"


def test_finishing_records_the_outcome_and_usage(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="m", turn_budget=6, **PROMPT)
    store.finish_run(run_id, verdict="failed", reason="held", judge_used=True, judge_model="google/gemini-3.8-flash",
                     stopping_condition="turn_cap", turns_used=6, tokens_used=31240)
    run = store.get_run(run_id)
    assert run.status == "finished" and run.verdict == "failed"
    assert run.stopping_condition == "turn_cap" and run.turns_used == 6 and run.tokens_used == 31240
    assert run.succeeded_turn is None


def test_a_succeeded_run_records_the_turn_it_won_at(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="m", **PROMPT)
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reason="canary",
                     stopping_condition="succeeded", succeeded_turn=3)
    run = store.get_run(run_id)
    assert run.verdict == "succeeded" and run.hard_evidence is True and run.succeeded_turn == 3


def test_deleting_the_target_deletes_the_runs_and_their_turns(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="m", **PROMPT)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>")
    store.delete_target(t.id)
    assert store.list_turns(run_id) == []  # cascaded away with the run
    with pytest.raises(LookupError):
        store.get_run(run_id)


def test_the_interrupted_sweep_marks_adaptive_runs(store):
    t = target(store)
    run_id = store.claim_run(t.id, mode="adaptive", attacker_model="m", **PROMPT)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>")
    assert store.close_interrupted_runs() == 1
    run = store.get_run(run_id)
    assert run.verdict == "unclear" and run.stopping_condition == "interrupted"
    assert len(store.list_turns(run_id)) == 1  # the turns so far are kept
