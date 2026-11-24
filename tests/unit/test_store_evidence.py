"""The store methods part 1 of feature 013 uses (013/FR-003, FR-006, FR-012, FR-034, FR-035, FR-038): evidence
items, planted tokens and their disarm rule, and the side-channel status written at claim time."""
import pytest
from cryptography.fernet import Fernet

from kestrel.evidence.model import EvidenceItem
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "013"

CLAIM = dict(prompt_id="dir-001", prompt_title="t", prompt_text="<seed>", family="direct_injection",
             owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0")


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                               response_path="$.reply", terms_version="10")


def item(kind: str, turn: int = 1, detail: str = "d") -> EvidenceItem:
    location = "reply" if kind in ("canary_in_reply", "instruction_override", "unsafe_executable_output") else "state"
    return EvidenceItem(kind=kind, turn=turn, location=location, owasp_category="LLM01: Prompt Injection",
                        detail=detail)


# ---- the side-channel status is written when the row is claimed (FR-034) ----


def test_the_side_channel_status_is_written_at_claim_time(store, target):  # FR-034
    plain = store.claim_run(target.id, **CLAIM)
    assert store.get_run(plain).side_channel_status == "not_configured"   # the default: no side channel
    store.finish_run(plain, verdict="failed")
    checked = store.claim_run(target.id, correlation_id="3f6b0b4a1c9e4d2f8a7e6c5b4d3c2b1a",
                              side_channel_status="checked", **CLAIM)
    run = store.get_run(checked)
    assert run.side_channel_status == "checked" and run.correlation_id == "3f6b0b4a1c9e4d2f8a7e6c5b4d3c2b1a"
    # A crashed or interrupted run keeps the status it was claimed with: the sweep never nulls it.
    assert store.close_interrupted_runs() == 1
    assert store.get_run(checked).side_channel_status == "checked"


def test_the_one_in_run_update_moves_the_status_to_unavailable(store, target):  # FR-034
    run_id = store.claim_run(target.id, side_channel_status="checked", **CLAIM)
    store.set_side_channel_status(run_id, "unavailable")
    assert store.get_run(run_id).side_channel_status == "unavailable"
    store.finish_run(run_id, verdict="failed")
    assert store.get_run(run_id).side_channel_status == "unavailable"   # finish_run leaves the column alone


def test_an_unknown_status_is_refused_at_claim_and_on_update(store, target):  # FR-034
    with pytest.raises(ValueError):
        store.claim_run(target.id, side_channel_status="bogus", **CLAIM)
    run_id = store.claim_run(target.id, **CLAIM)
    with pytest.raises(ValueError):
        store.set_side_channel_status(run_id, "bogus")
    with pytest.raises(LookupError):
        store.set_side_channel_status(run_id + 99, "unavailable")


# ---- evidence items (FR-003, FR-006, FR-038) ----


def test_items_are_listed_in_the_order_found_and_summarised_per_target(store, target):  # FR-003, FR-038
    first = store.claim_run(target.id, **CLAIM)
    store.add_evidence(first, [item("canary_in_reply", 1, "KESTREL-CANARY-X"), item("instruction_override", 1)])
    store.finish_run(first, verdict="succeeded", hard_evidence=True)
    second = store.claim_run(target.id, **CLAIM)
    store.add_evidence(second, [item("unsafe_executable_output", 2)])
    store.add_evidence(second, [item("unsafe_executable_output", 3), item("canary_in_reply", 3)])
    store.finish_run(second, verdict="succeeded", hard_evidence=True)
    third = store.claim_run(target.id, **CLAIM)
    store.finish_run(third, verdict="failed")

    listed = store.list_evidence(first)
    assert [(i.kind, i.turn, i.detail) for i in listed] == [("canary_in_reply", 1, "KESTREL-CANARY-X"),
                                                             ("instruction_override", 1, "d")]
    assert all(i.created_at for i in listed)
    assert [(i.kind, i.turn) for i in store.list_evidence(second)] == [
        ("unsafe_executable_output", 2), ("unsafe_executable_output", 3), ("canary_in_reply", 3)]
    # Distinct kinds in detection order, and the item count, one query each for the whole target.
    assert store.evidence_kinds_by_run(target.id) == {first: ["canary_in_reply", "instruction_override"],
                                                      second: ["canary_in_reply", "unsafe_executable_output"]}
    assert store.evidence_counts_by_run(target.id) == {first: 2, second: 3}
    assert store.list_evidence(third) == []


def test_deleting_the_target_removes_its_items_and_tokens(store, target):  # FR-003
    run_id = store.claim_run(target.id, **CLAIM)
    store.add_evidence(run_id, [item("canary_in_reply")])
    store.add_planted_token(run_id, kind="override", token="abcdefghjkmn", prompt_id="override_task",
                            prompt_version="1")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True)
    store.delete_target(target.id)
    assert store.list_evidence(run_id) == [] and store.list_planted_tokens(run_id) == []


# ---- planted tokens and the disarm rule (FR-012, FR-035) ----


def test_a_token_is_recorded_once_per_kind_and_disarms_only_toward_an_earlier_turn(store, target):
    # FR-012, FR-035
    run_id = store.claim_run(target.id, **CLAIM)
    store.add_planted_token(run_id, kind="override", token="abcdefghjkmn", prompt_id="override_task",
                            prompt_version="1")
    with pytest.raises(Exception):
        store.add_planted_token(run_id, kind="override", token="npqrstuvwxyz", prompt_id="override_task",
                                prompt_version="1")
    with pytest.raises(ValueError):
        store.add_planted_token(run_id, kind="bogus", token="x", prompt_id="override_task", prompt_version="1")
    token = store.list_planted_tokens(run_id)[0]
    assert token.armed is True and token.prompt_ref == "override_task@1" and token.created_at

    store.disarm_planted_token(run_id, "override", 3)
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 3
    store.disarm_planted_token(run_id, "override", 5)                 # later: a no-op
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 3
    store.disarm_planted_token(run_id, "override", 1)                 # earlier: moves
    assert store.list_planted_tokens(run_id)[0].disarmed_turn == 1
    assert store.list_planted_tokens(run_id)[0].armed is False


def test_a_replay_copies_the_tokens_with_their_disarmed_turn(store, target):  # FR-035
    source = store.claim_run(target.id, **CLAIM)
    store.add_planted_token(source, kind="override", token="abcdefghjkmn", prompt_id="override_task",
                            prompt_version="1")
    store.disarm_planted_token(source, "override", 2)
    store.finish_run(source, verdict="succeeded", hard_evidence=True)
    replay = store.claim_run(target.id, mode="replay", source_run_id=source, **CLAIM)
    assert store.copy_planted_tokens(source, replay) == 1
    copied = store.list_planted_tokens(replay)[0]
    assert (copied.token, copied.disarmed_turn, copied.prompt_ref) == ("abcdefghjkmn", 2, "override_task@1")
    assert "abcdefghjkmn" not in repr(copied)                         # the value never belongs in a repr
