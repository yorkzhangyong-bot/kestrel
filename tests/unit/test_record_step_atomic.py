"""`add_turn_with_evidence` writes a turn row and its evidence items as one atomic unit, idempotent on a retry for
the same position (014/FR-012, research D6)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.evidence.model import EvidenceItem
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "014"


@pytest.fixture
def store_and_run(tmp_path):
    store = TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="10")
    run_id = store.claim_run(target.id, prompt_id="p", prompt_title="t", prompt_text="x", family="direct_injection",
                             owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0",
                             mode="adaptive")
    return store, run_id


def _item(turn: int) -> EvidenceItem:
    return EvidenceItem(kind="instruction_override", turn=turn, location="reply",
                        owasp_category="LLM01: Prompt Injection", detail="the planted marker appeared in the reply")


def test_the_turn_row_and_its_evidence_are_written_together(store_and_run):  # FR-012
    store, run_id = store_and_run
    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>", reply_text="<r1>",
                                 evidence_items=[_item(1)])
    assert len(store.list_turns(run_id)) == 1
    assert len(store.list_evidence(run_id)) == 1


def test_a_turn_with_no_evidence_items_writes_the_turn_alone(store_and_run):  # FR-012
    store, run_id = store_and_run
    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>")
    assert len(store.list_turns(run_id)) == 1
    assert store.list_evidence(run_id) == []


def test_has_turn_reflects_exactly_what_was_written(store_and_run):  # FR-012
    store, run_id = store_and_run
    assert store.has_turn(run_id, 1) is False
    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>")
    assert store.has_turn(run_id, 1) is True
    assert store.has_turn(run_id, 2) is False


def test_a_second_call_for_the_same_position_is_a_no_op_no_duplicate_no_exception(store_and_run):  # FR-012
    store, run_id = store_and_run
    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>", reply_text="<r1>",
                                 evidence_items=[_item(1)])
    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>", reply_text="<r1>",
                                 evidence_items=[_item(1)])   # must not raise, must not duplicate
    assert len(store.list_turns(run_id)) == 1
    assert len(store.list_evidence(run_id)) == 1


def test_a_failure_between_the_two_inserts_leaves_neither_durable_and_a_retry_leaves_both(store_and_run, monkeypatch):
    # 014/FR-012: both statements run inside the same connect()'s own transaction - a failure injected on the
    # evidence insert, right after the turn insert already executed, must roll back both; a real retry over the
    # same tmp_path database then leaves exactly one durably recorded turn and its evidence, never a turn row
    # with no evidence (or vice versa). sqlite3.Connection is an immutable builtin type (no monkeypatching its
    # own method slot directly), so the failure is injected through a real subclass instead, installed as the
    # connect() factory for this test only.
    store, run_id = store_and_run

    class _FlakyConnection(sqlite3.Connection):
        calls = 0

        def executemany(self, *args, **kwargs):
            type(self).calls += 1
            if type(self).calls == 1:
                raise sqlite3.OperationalError("simulated failure between the turn insert and the evidence insert")
            return super().executemany(*args, **kwargs)

    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda path: real_connect(path, factory=_FlakyConnection))
    with pytest.raises(sqlite3.OperationalError):
        store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>", evidence_items=[_item(1)])
    assert store.has_turn(run_id, 1) is False   # rolled back: never a turn row without its evidence
    assert store.list_evidence(run_id) == []

    store.add_turn_with_evidence(run_id, position=1, attacker_message="<m1>", evidence_items=[_item(1)])
    assert store.has_turn(run_id, 1) is True
    assert len(store.list_evidence(run_id)) == 1
