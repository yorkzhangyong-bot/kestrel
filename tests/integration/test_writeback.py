"""Write-back after every run: one memory record always, a pattern on success, and fail-loud (FR-006/9/10/11/12)."""
import logging

import pytest
from cryptography.fernet import Fernet

from kestrel.experience.store import ExperienceStore
from kestrel.experience.writeback import write_back
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubEmbeddingFunction

FEATURE = "004"

SECRET = "s3cret-header-value"


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def experience(tmp_path) -> ExperienceStore:
    return ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())


def a_target(store) -> int:
    t = store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", SECRET)],
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="4")
    return t.id


def single_turn(store, tid, *, verdict="failed"):
    run_id = store.claim_run(tid, prompt_id="spl-001", prompt_title="t", prompt_text="<seed prompt>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    return store.finish_run(run_id, verdict=verdict, reason="held", judge_used=True,
                            judge_model="google/gemini-3.8-flash", reply_text="<reply>")


def adaptive_success(store, tid):
    run_id = store.claim_run(tid, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", mode="adaptive",
                             attacker_model="deepseek/deepseek-v3.2", turn_budget=6)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>", judge_verdict="failed",
                   judge_progress="a step closer")
    store.add_turn(run_id, position=2, attacker_message="<m2 winning>", reply_text="<r2>", judge_verdict="succeeded",
                   judge_progress="it leaked")
    return store.finish_run(run_id, verdict="succeeded", judge_used=True, judge_model="google/gemini-3.8-flash",
                            succeeded_turn=2, turns_used=2)


def test_every_run_writes_exactly_one_memory_record(store, experience):
    tid = a_target(store)
    run = single_turn(store, tid)
    assert write_back(experience, store, run, store.list_turns(run.id)) is True
    assert experience.count("memory", target_id=tid) == 1          # SC-001
    assert store.get_run(run.id).memory_written is True


def test_memory_holds_no_secret_and_no_raw_reply(store, experience):
    tid = a_target(store)
    run = single_turn(store, tid)
    write_back(experience, store, run, store.list_turns(run.id))
    got = experience._collection.get(where={"type": "memory"})
    blob = str(got["documents"]) + str(got["metadatas"])
    assert SECRET not in blob and "http://t/chat" not in blob and "<reply>" not in blob   # SC-004, SC-008
    meta = got["metadatas"][0]
    assert meta["target_id"] == tid and meta["family"] == "system_prompt_leak" and meta["verdict"] == "failed"


def test_success_also_writes_one_pattern_with_the_winning_messages(store, experience):
    tid = a_target(store)
    run = adaptive_success(store, tid)
    before = experience.count("pattern")
    write_back(experience, store, run, store.list_turns(run.id))
    assert experience.count("pattern") == before + 1               # SC-003
    got = experience._collection.get(where={"type": "pattern"})
    doc = got["documents"][0]
    assert "<m2 winning>" in doc and "<r1>" not in doc             # winning attacker messages, never a reply (FR-009)


def test_non_success_writes_no_pattern(store, experience):
    tid = a_target(store)
    run = single_turn(store, tid, verdict="unclear")
    write_back(experience, store, run, store.list_turns(run.id))
    assert experience.count("pattern") == 0                        # SC-003


class FailingExperience:
    """Stands in for an experience store that cannot be written."""
    def write_memory(self, **kw):
        raise RuntimeError("store down")
    def write_pattern(self, **kw):
        raise RuntimeError("store down")


def test_write_back_fails_loud_but_keeps_the_run(store, caplog):
    tid = a_target(store)
    run = single_turn(store, tid)
    with caplog.at_level(logging.ERROR, logger="kestrel"):
        ok = write_back(FailingExperience(), store, run, store.list_turns(run.id))
    assert ok is False
    assert store.get_run(run.id).memory_written is False           # FR-010
    assert store.get_run(run.id).verdict == "failed"               # the attack result is kept
    assert "write" in caplog.text.lower() and str(run.id) in caplog.text  # SC-011: logged loudly
