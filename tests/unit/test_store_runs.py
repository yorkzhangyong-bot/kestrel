"""Run rows: claimed before the send, finished at the end, swept at start-up (FR-005, FR-010, FR-019, FR-027 to FR-031)."""
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import RunInProgress, TargetNotFound, TargetStore

FEATURE = "002"

PROMPT = dict(prompt_id="spl-002", prompt_title="Ask for the system prompt verbatim", prompt_text="<prompt text>",
              family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
              attacker_source="library:1.0.0")


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


def create(store, name="HS Agent"):
    return store.create_target(name=name, url="http://agent.test/chat", method="POST",
                               headers=[("X-API-Key", "test-key-123")], body_template='{"message": "{{prompt}}"}',
                               response_path="$.reply", terms_version="2")


def claim(store, target_id, **over):
    return store.claim_run(target_id, **{**PROMPT, **over})


def test_claiming_writes_an_in_progress_row_carrying_the_attacker_source(store):
    """Principle III: a run must say which set of prompts attacked, even before it has a verdict (FR-005, FR-019)."""
    target = create(store)
    run = store.get_run(claim(store, target.id))
    assert run.status == "in_progress"
    assert run.attacker_source == "library:1.0.0"
    assert run.prompt_id == "spl-002" and run.family == "system_prompt_leak"
    assert run.verdict is None and run.finished_at is None


def test_a_second_claim_on_the_same_target_is_refused_while_one_is_open(store):
    target = create(store)
    claim(store, target.id)
    with pytest.raises(RunInProgress):
        claim(store, target.id)


def test_two_targets_can_run_at_the_same_time(store):
    first, second = create(store, "First"), create(store, "Second")
    claim(store, first.id)
    claim(store, second.id)  # the lock is per target, not global


def test_a_new_run_can_start_once_the_previous_one_finished(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, verdict="failed", reason="Held.", judge_used=True, judge_model="google/gemini-3.8-flash")
    claim(store, target.id)


def test_finishing_records_the_verdict_and_leaves_the_attacker_source_alone(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reason="Canary found.",
                     reply_text="...", reply_truncated=True)
    run = store.get_run(run_id)
    assert run.status == "finished" and run.verdict == "succeeded"
    assert run.hard_evidence is True and run.reason == "Canary found."
    assert run.reply_truncated is True and run.finished_at is not None
    assert run.attacker_source == "library:1.0.0"
    assert run.judge_used is False and run.judge_model is None


def test_a_judged_run_records_the_model_it_used(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, verdict="failed", reason="The agent refused.", judge_used=True,
                     judge_model="google/gemini-3.8-flash")
    run = store.get_run(run_id)
    assert run.judge_used is True and run.judge_model == "google/gemini-3.8-flash"
    assert run.hard_evidence is False


def test_a_failed_send_finishes_with_a_step_and_no_verdict(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, failure_step="unreachable")
    run = store.get_run(run_id)
    assert run.status == "finished" and run.failure_step == "unreachable"
    assert run.verdict is None and run.judge_used is False


def test_runs_are_listed_newest_first(store):
    target = create(store)
    for prompt_id in ("one-001", "two-002", "three-003"):
        run_id = claim(store, target.id, prompt_id=prompt_id)
        store.finish_run(run_id, verdict="failed", reason="Held.")
    assert [r.prompt_id for r in store.list_runs(target.id)] == ["three-003", "two-002", "one-001"]


def test_runs_belong_to_their_own_target(store):
    first, second = create(store, "First"), create(store, "Second")
    store.finish_run(claim(store, first.id), verdict="failed", reason="Held.")
    assert len(store.list_runs(first.id)) == 1
    assert store.list_runs(second.id) == []


def test_deleting_the_target_deletes_its_runs(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, verdict="failed", reason="Held.")
    store.delete_target(target.id)
    with pytest.raises(TargetNotFound):
        store.list_runs(target.id)


def test_an_interrupted_run_is_closed_as_unclear_at_start_up(store):
    """Nothing else closes it, so without the sweep the target would stay locked forever (FR-031)."""
    target = create(store)
    run_id = claim(store, target.id)
    assert store.close_interrupted_runs() == 1
    run = store.get_run(run_id)
    assert run.status == "finished" and run.verdict == "unclear"
    assert "interrupted" in run.reason.lower()
    assert run.judge_used is False and run.hard_evidence is False


def test_the_sweep_unblocks_the_target(store):
    target = create(store)
    claim(store, target.id)
    store.close_interrupted_runs()
    claim(store, target.id)  # no RunInProgress


def test_the_sweep_leaves_finished_runs_alone(store):
    target = create(store)
    run_id = claim(store, target.id)
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reason="Canary found.")
    assert store.close_interrupted_runs() == 0
    assert store.get_run(run_id).verdict == "succeeded"


def test_an_unknown_run_or_target_is_refused(store):
    with pytest.raises(LookupError):
        store.get_run(999)
    with pytest.raises(TargetNotFound):
        store.list_runs(999)
    with pytest.raises(TargetNotFound):
        claim(store, 999)
