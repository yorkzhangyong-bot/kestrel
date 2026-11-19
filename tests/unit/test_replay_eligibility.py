"""`check_replayable` and `compute_replay_status` (data-model.md): which runs can be replayed, and what the API
tells the UI about a run it cannot replay (012/FR-004 to FR-006, FR-040, FR-042)."""
from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.fernet import Fernet

from kestrel.replay import (REPLAY_ADVISORY_OVER_TURN_LIMIT, REPLAY_BLOCKED_REASONS, NotReplayable, ReplayOfReplay,
                            ReplayStatus, check_replayable, compute_replay_status)
from kestrel.secrets import Vault
from kestrel.store import Run, Target, TargetNotFound, TargetStore

FEATURE = "012"

BASE_RUN = Run(id=1, target_id=1, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
               family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
               attacker_source="library:1.0.0", status="finished", started_at="2026-11-19T10:00:00Z",
               verdict="succeeded")

BASE_TARGET = Target(id=1, name="A", url="http://t/chat", method="POST", body_template="{}", response_path="$.reply",
                     permission_confirmed_at="2026-11-19T09:00:00Z", terms_version="10",
                     created_at="2026-11-19T09:00:00Z", updated_at="2026-11-19T09:00:00Z")


# ---- check_replayable: the truth table (data-model.md) ----


def test_a_replay_run_raises_replay_of_replay_naming_its_own_source():  # FR-005
    run = replace(BASE_RUN, mode="replay", source_run_id=7)
    with pytest.raises(ReplayOfReplay) as excinfo:
        check_replayable(run)
    assert excinfo.value.source_run_id == 7


def test_a_run_still_in_progress_is_not_replayable():  # FR-004
    run = replace(BASE_RUN, status="in_progress", verdict=None)
    with pytest.raises(NotReplayable) as excinfo:
        check_replayable(run)
    assert excinfo.value.reason == "in_progress"


@pytest.mark.parametrize("verdict, failure_step", [("failed", None), ("unclear", None), (None, "unreachable")])
def test_a_finished_run_that_did_not_succeed_is_not_replayable(verdict, failure_step):  # FR-004
    run = replace(BASE_RUN, verdict=verdict, failure_step=failure_step)
    with pytest.raises(NotReplayable) as excinfo:
        check_replayable(run)
    assert excinfo.value.reason == "not_succeeded"


@pytest.mark.parametrize("turns_used", [0, None])
def test_a_succeeded_adaptive_run_with_no_recorded_message_is_not_replayable(turns_used):  # FR-004 (defensive)
    run = replace(BASE_RUN, mode="adaptive", turns_used=turns_used)
    with pytest.raises(NotReplayable) as excinfo:
        check_replayable(run)
    assert excinfo.value.reason == "no_message"


def test_a_succeeded_single_turn_run_is_eligible():  # FR-004
    check_replayable(BASE_RUN)   # returns normally; no recorded-message check applies to single-turn


def test_a_succeeded_adaptive_run_with_a_recorded_message_is_eligible():  # FR-004
    check_replayable(replace(BASE_RUN, mode="adaptive", turns_used=3))


# ---- list_replayable_runs: the batch's own ordered query (data-model.md) ----


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


def _claim(store: TargetStore, target_id: int, **overrides) -> int:
    fields = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
                 owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    fields.update(overrides)
    return store.claim_run(target_id, **fields)


def test_list_replayable_runs_returns_only_eligible_runs_of_one_target_oldest_first(store):  # FR-028, FR-029
    target_a = store.create_target(name="A", url="http://a/chat", method="POST", headers=[], body_template="{}",
                                   response_path="$.reply", terms_version="10")
    target_b = store.create_target(name="B", url="http://b/chat", method="POST", headers=[], body_template="{}",
                                   response_path="$.reply", terms_version="10")

    eligible_old = _claim(store, target_a.id)
    store.finish_run(eligible_old, verdict="succeeded", hard_evidence=True)
    eligible_new = _claim(store, target_a.id)
    store.finish_run(eligible_new, verdict="succeeded")
    failed = _claim(store, target_a.id)
    store.finish_run(failed, verdict="failed")
    other_target = _claim(store, target_b.id)
    store.finish_run(other_target, verdict="succeeded")
    _claim(store, target_a.id)   # left in progress on purpose (only one in_progress run per target: claimed last)

    replayable = store.list_replayable_runs(target_a.id)

    assert [r.id for r in replayable] == [eligible_old, eligible_new]


def test_list_replayable_runs_excludes_a_replay_mode_run_even_if_succeeded(store):  # FR-028
    target = store.create_target(name="A", url="http://a/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="10")
    source = _claim(store, target.id)
    store.finish_run(source, verdict="succeeded")
    replay_run = _claim(store, target.id, mode="replay", source_run_id=source)
    store.finish_run(replay_run, verdict="succeeded", replay_outcome="still_vulnerable")

    assert [r.id for r in store.list_replayable_runs(target.id)] == [source]


def test_list_replayable_runs_is_unaffected_by_a_concurrent_in_progress_run(store):  # 012/FR-029 (research D10)
    """`compute_replay_status`'s "another run in progress" reason is a display-time concern, never folded into
    this query - the batch plans from the full eligible set before claiming anything itself."""
    target = store.create_target(name="A", url="http://a/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="10")
    source = _claim(store, target.id)
    store.finish_run(source, verdict="succeeded")

    assert [r.id for r in store.list_replayable_runs(target.id)] == [source]


def test_list_replayable_runs_raises_target_not_found_for_an_unknown_target(store):  # FR-028
    with pytest.raises(TargetNotFound):
        store.list_replayable_runs(999)


# ---- compute_replay_status: the display fields, from the run AND its target (research D10) ----


def test_replay_of_replay_status_names_the_source_word_for_word():  # FR-005, FR-042
    run = replace(BASE_RUN, mode="replay", source_run_id=9)
    status = compute_replay_status(run, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(False, "This run is itself a replay of run #9.", None)


@pytest.mark.parametrize("run, reason_key", [
    (replace(BASE_RUN, status="in_progress", verdict=None), "in_progress"),
    (replace(BASE_RUN, verdict="failed"), "not_succeeded"),
    (replace(BASE_RUN, mode="adaptive", turns_used=None), "no_message"),
])
def test_check_replayable_reasons_render_the_pinned_strings_word_for_word(run, reason_key):  # FR-004, FR-042
    status = compute_replay_status(run, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(False, REPLAY_BLOCKED_REASONS[reason_key], None)


def test_replayable_depends_on_the_targets_permission_not_the_run_alone():  # FR-006, FR-042, research D10
    target = replace(BASE_TARGET, permission_confirmed_at="")
    status = compute_replay_status(BASE_RUN, target, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(False, REPLAY_BLOCKED_REASONS["permission_missing"], None)


def test_replayable_depends_on_the_targets_current_terms_version():  # FR-006, FR-042
    status = compute_replay_status(BASE_RUN, BASE_TARGET, terms_version="11", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(False, REPLAY_BLOCKED_REASONS["terms_outdated"], None)


def test_replayable_is_false_while_another_run_is_in_progress_on_the_target():  # FR-006, FR-042
    status = compute_replay_status(BASE_RUN, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=True)
    assert status == ReplayStatus(False, REPLAY_BLOCKED_REASONS["run_in_progress"], None)


def test_an_eligible_run_on_a_current_target_with_nothing_else_in_progress_is_replayable():  # FR-004 to FR-006
    status = compute_replay_status(BASE_RUN, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(True, None, None)


def test_a_source_with_more_recorded_turns_than_the_current_limit_carries_the_advisory():  # FR-040
    run = replace(BASE_RUN, mode="adaptive", turns_used=8)
    status = compute_replay_status(run, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(True, None, REPLAY_ADVISORY_OVER_TURN_LIMIT)


def test_a_source_within_the_current_turn_limit_carries_no_advisory():  # FR-040
    run = replace(BASE_RUN, mode="adaptive", turns_used=6)
    status = compute_replay_status(run, BASE_TARGET, terms_version="10", adaptive_max_turns=6,
                                    target_has_other_run_in_progress=False)
    assert status == ReplayStatus(True, None, None)
