"""`claim_run`'s new provenance-pin and approve-node keywords round-trip through `Run`, and the store itself
refuses `ask_before_each_turn=True` for any mode other than 'adaptive' (014/FR-002, FR-018, FR-047)."""
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "014"


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target_id(store) -> int:
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                               response_path="$.reply", terms_version="10").id


def test_the_new_keywords_round_trip_through_run(store, target_id):  # FR-002, FR-047
    run_id = store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x", family="direct_injection",
                             owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0",
                             mode="adaptive", ask_before_each_turn=True, is_checkpointed=True,
                             attacker_prompt_id="attacker:direct_injection", attacker_prompt_version="1",
                             judge_model="j/m", judge_prompt_id="judge", judge_prompt_version="1")
    run = store.get_run(run_id)
    assert run.ask_before_each_turn is True
    assert run.is_checkpointed is True
    assert run.attacker_prompt_id == "attacker:direct_injection" and run.attacker_prompt_version == "1"
    assert run.judge_model == "j/m" and run.judge_prompt_id == "judge" and run.judge_prompt_version == "1"


def test_ask_before_each_turn_is_refused_for_a_non_adaptive_mode(store, target_id):  # FR-002
    with pytest.raises(ValueError):
        store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x", family="direct_injection",
                        owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0",
                        mode="single_turn", ask_before_each_turn=True)


def test_ask_before_each_turn_is_refused_for_a_replay_claim(store, target_id):  # FR-002
    with pytest.raises(ValueError):
        store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x", family="direct_injection",
                        owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0",
                        mode="replay", ask_before_each_turn=True)


def test_a_claim_passing_none_of_the_new_keywords_defaults_them_all(store, target_id):  # FR-002, FR-047
    # A single-turn claim (never touches any of this feature's own keywords): every default is exactly as it was
    # before this feature, so no pre-existing caller is affected.
    run_id = store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    run = store.get_run(run_id)
    assert run.ask_before_each_turn is False and run.is_checkpointed is False
    assert run.attacker_prompt_id is None and run.attacker_prompt_version is None
    assert run.judge_model is None and run.judge_prompt_id is None and run.judge_prompt_version is None
