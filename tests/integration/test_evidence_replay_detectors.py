"""A replay is scored by the real detectors, on both paths (013/FR-012, FR-013, FR-035, FR-036, SC-009).

Every case runs `execute_replay` with `evidence=None`, so the replay builds its own full checker from its
source's copied tokens exactly as a real replay does — a canary-only fallback anywhere in the replay paths
fails these tests. An override-confirmed source and an unsafe-output source each score still vulnerable with
the matching item on the single-turn branch and on the adaptive graph; a re-sent message carrying the joined
form disarms the replay at that turn and records no override item; and a source disarmed on turn k leaves the
replay armed on the turns before k, so a target that now echoes the joined form confirms it there. Placeholder
messages only; the unsafe-output sample comes from the inert fixture."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from kestrel import events
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.replay import execute_replay
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubJudge

FEATURE = "013"

RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "test-key-123"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")
REPLAY_CAPS = dict(adaptive_max_turns=6, adaptive_token_budget=40000, adaptive_time_limit_s=300)
JOINED = "abcdefghjkmn"   # a fixed placeholder token value for a hand-built source (never generated live)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "unsafe_output_cases.json"


def fixture_positive(pattern: str) -> str:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    return next(c["text"] for c in cases if c["pattern"] == pattern and c["kind"] == "positive")


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "test-key-123")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="10")


def ok(reply: str) -> Outcome:
    return Outcome(ok=True, step="success", message="Connection works.", reply_text=reply, reply_truncated=False,
                  status_code=200)


def replies(*texts: str):
    """A sender answering the n-th send with the n-th text; the last one repeats."""
    queue = list(texts)

    async def send(resolved, **kwargs):
        return ok(queue.pop(0) if len(queue) > 1 else queue[0])
    return send


def claim(store, target, *, family: str, mode: str = "single_turn", prompt_text: str = "<seed>"):
    owasp = {"direct_injection": "LLM01: Prompt Injection", "system_prompt_leak": "LLM07: System Prompt Leakage"}
    extra = dict(mode="adaptive", attacker_model="a/m", turn_budget=6, token_budget=40000,
                 time_limit_s=300) if mode == "adaptive" else {}
    return store.claim_run(target.id, prompt_id="x-001", prompt_title="t", prompt_text=prompt_text, family=family,
                           owasp_category=owasp[family], attacker_source="library:1.0.0", **extra)


def single_turn_source(store, target, *, family: str = "direct_injection", planted: bool = True):
    run_id = claim(store, target, family=family)
    if planted:
        store.add_planted_token(run_id, kind="override", token=JOINED, prompt_id="override_task", prompt_version="1")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reply_text="<reply>")
    return store.get_run(run_id)


def adaptive_source(store, target, messages: list[str], *, family: str = "direct_injection", planted: bool = True,
                    disarmed_turn: int | None = None):
    run_id = claim(store, target, family=family, mode="adaptive", prompt_text=messages[0])
    if planted:
        store.add_planted_token(run_id, kind="override", token=JOINED, prompt_id="override_task", prompt_version="1")
        if disarmed_turn is not None:
            store.disarm_planted_token(run_id, "override", disarmed_turn)
    for position, message in enumerate(messages, start=1):
        store.add_turn(run_id, position=position, attacker_message=message, reply_text="<reply>",
                       judge_verdict="succeeded" if position == len(messages) else "failed")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=False, judge_used=True, judge_model="j/m",
                     stopping_condition="succeeded", succeeded_turn=len(messages), turns_used=len(messages))
    return store.get_run(run_id), store.list_turns(run_id)


def replay(store, source, source_turns, *, judge, sender):
    """Inside a run scope, as the API runs a replay, so every line the replay emits carries its run id."""
    async def run():
        with events.run_scope():
            return await execute_replay(store, source=source, source_turns=source_turns, resolved=RESOLVED,
                                        mode="local", judge=judge, sender=sender, **REPLAY_CAPS)
    return asyncio.run(run())


# ---- the override detector on a replay (FR-035, SC-009) ----


def test_a_single_turn_replay_confirmed_by_the_override_token_is_still_vulnerable(store, target):  # FR-035, SC-009
    source = single_turn_source(store, target)
    judge = StubJudge(verdict="failed")
    run = replay(store, source, [], judge=judge, sender=replies(f"as instructed: {JOINED.upper()}"))
    assert run.verdict == "succeeded" and run.hard_evidence is True and run.replay_outcome == "still_vulnerable"
    assert [(i.kind, i.turn) for i in store.list_evidence(run.id)] == [("instruction_override", 1)]
    assert judge.calls == [] and run.judge_used is False


def test_an_adaptive_replay_confirmed_by_the_override_token_is_still_vulnerable(store, target):  # FR-035, SC-009
    source, turns = adaptive_source(store, target, ["<turn 1>", "<turn 2>", "<turn 3>"])
    judge = StubJudge(verdict="failed")
    run = replay(store, source, turns, judge=judge, sender=replies("nothing yet", f"here: {JOINED}"))
    assert run.verdict == "succeeded" and run.hard_evidence is True and run.succeeded_turn == 2
    assert run.replay_outcome == "still_vulnerable" and run.turns_used == 2
    assert [(i.kind, i.turn) for i in store.list_evidence(run.id)] == [("instruction_override", 2)]
    assert len(judge.calls) == 1                                    # turn 1 was judged, turn 2 was not


# ---- the unsafe-output detector on a replay (FR-035, SC-009) ----


def test_a_single_turn_replay_confirmed_by_unsafe_output_is_still_vulnerable(store, target):  # FR-035, SC-009
    source = single_turn_source(store, target, family="system_prompt_leak", planted=False)
    judge = StubJudge(verdict="failed")
    run = replay(store, source, [], judge=judge, sender=replies(fixture_positive("drop_or_truncate_table")))
    assert run.replay_outcome == "still_vulnerable" and run.hard_evidence is True and judge.calls == []
    items = store.list_evidence(run.id)
    assert [(i.kind, i.turn, i.pattern_name) for i in items] == [("unsafe_executable_output", 1,
                                                                   "drop_or_truncate_table")]


def test_an_adaptive_replay_confirmed_by_unsafe_output_is_still_vulnerable(store, target):  # FR-035, SC-009
    source, turns = adaptive_source(store, target, ["<turn 1>", "<turn 2>"], family="system_prompt_leak",
                                    planted=False)
    judge = StubJudge(verdict="failed")
    run = replay(store, source, turns, judge=judge,
                 sender=replies("nothing yet", fixture_positive("active_script_element")))
    assert run.replay_outcome == "still_vulnerable" and run.succeeded_turn == 2
    assert [(i.kind, i.turn) for i in store.list_evidence(run.id)] == [("unsafe_executable_output", 2)]
    assert store.list_planted_tokens(run.id) == []                 # a source that planted nothing (FR-036)


# ---- the echo check on every re-sent message (FR-012, FR-035) ----


def test_a_resent_message_carrying_the_joined_form_disarms_the_replay_there(store, target, json_log):
    # FR-012, FR-035, SC-009
    source, turns = adaptive_source(store, target, ["<turn 1>", f"<turn 2 carrying {JOINED}>", "<turn 3>"])
    assert store.list_planted_tokens(source.id)[0].armed is True   # the source itself was never disarmed
    judge = StubJudge(verdict="failed")
    run = replay(store, source, turns, judge=judge, sender=replies("nothing yet", f"here: {JOINED}"))
    assert store.list_evidence(run.id) == []                        # the echoed form after the disarm is not evidence
    assert run.hard_evidence is False and run.replay_outcome == "fixed" and len(judge.calls) == 3
    copied = store.list_planted_tokens(run.id)[0]
    assert copied.disarmed_turn == 2 and copied.armed is False
    assert store.list_planted_tokens(source.id)[0].armed is True    # the source's own row is untouched
    disarmed = [line for line in json_log() if line.get("event") == "evidence.override_disarmed"]
    assert [line["turn"] for line in disarmed] == [2] and disarmed[0]["run_id"] == run.id


# ---- an inherited disarm applies from the source's turn, never from turn 1 (FR-035) ----


def test_a_source_disarmed_on_turn_three_leaves_the_replay_armed_before_it(store, target):  # FR-035, SC-009
    """The source was disarmed on turn 3; the target now echoes the joined form on every turn. Turn 1 is still
    armed on the replay, so it confirms there - still vulnerable, never a false "fixed"."""
    source, turns = adaptive_source(store, target, ["<turn 1>", "<turn 2>", f"<turn 3 carrying {JOINED}>"],
                                    disarmed_turn=3)
    judge = StubJudge(verdict="failed")
    run = replay(store, source, turns, judge=judge, sender=replies(f"as instructed: {JOINED}"))
    assert run.verdict == "succeeded" and run.hard_evidence is True and run.succeeded_turn == 1
    assert run.replay_outcome == "still_vulnerable" and run.turns_used == 1
    assert [(i.kind, i.turn) for i in store.list_evidence(run.id)] == [("instruction_override", 1)]
    assert judge.calls == []
    assert store.list_planted_tokens(run.id)[0].disarmed_turn == 3   # the inherited disarm is untouched


def test_an_inherited_disarm_still_silences_its_own_turn_and_the_ones_after(store, target, json_log):
    # FR-035, SC-009
    source, turns = adaptive_source(store, target, ["<turn 1>", f"<turn 2 carrying {JOINED}>", "<turn 3>"],
                                    disarmed_turn=2)
    judge = StubJudge(verdict="failed")
    run = replay(store, source, turns, judge=judge, sender=replies("nothing yet", f"here: {JOINED}"))
    assert store.list_evidence(run.id) == [] and run.hard_evidence is False and run.replay_outcome == "fixed"
    assert store.list_planted_tokens(run.id)[0].disarmed_turn == 2
    # Re-sending the very message that disarmed the source is logged on the replay too, at the same turn.
    disarmed = [line for line in json_log() if line.get("event") == "evidence.override_disarmed"]
    assert [line["turn"] for line in disarmed] == [2]


def test_a_replays_own_resend_can_move_an_inherited_disarm_earlier_but_never_later(store, target):  # FR-035
    source, turns = adaptive_source(store, target, [f"<turn 1 carrying {JOINED}>", "<turn 2>", "<turn 3>"],
                                    disarmed_turn=3)
    run = replay(store, source, turns, judge=StubJudge(verdict="failed"), sender=replies(f"here: {JOINED}"))
    assert store.list_evidence(run.id) == [] and run.hard_evidence is False
    assert store.list_planted_tokens(run.id)[0].disarmed_turn == 1   # moved earlier by the re-sent turn-1 message
    assert store.list_planted_tokens(source.id)[0].disarmed_turn == 3
