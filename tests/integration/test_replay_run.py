"""Replaying a single-turn and an adaptive source: verbatim resend, no attacker-model call, scored exactly as a
live run, stopping at the first success (012/FR-001 to FR-024, SC-001, SC-002)."""
from __future__ import annotations

import asyncio
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel import events
from kestrel.attack.attacker import AttackerReply
from kestrel.attack.graph import run_adaptive
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.judge.client import JudgeError
from kestrel.judge.verdict import ParsedVerdict
from kestrel.replay import ReplayFailed, execute_replay
from kestrel.runs import execute_run
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "012"

SEED = AttackPrompt(id="spl-001", title="t", text="<seed message>", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "test-key-123"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")
SRC = "library:1.0.0"
LIVE_CAPS = dict(max_turns=6, token_budget=40000, time_limit_s=300.0)
REPLAY_CAPS = dict(adaptive_max_turns=6, adaptive_token_budget=40000, adaptive_time_limit_s=300)


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "test-key-123")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="10")


class StubJudge:
    """Returns a fixed verdict (or raises) every call; records every call it receives."""

    def __init__(self, verdict="failed", error=None, configured=True, tokens=120, model="stub/judge"):
        self.model = model
        self.configured = configured
        self._v, self._err, self._tokens = verdict, error, tokens
        self.calls: list[dict] = []

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        self.calls.append({"attack": attack, "reply": reply, "conversation": conversation, "timeout": timeout})
        if self._err is not None:
            raise self._err
        return ParsedVerdict(self._v, "reason", progress="progress", tokens=self._tokens)


class SequencedJudge:
    """Returns one entry of `results` per call, in order; the last repeats. An entry that is an Exception is
    raised instead of returned."""

    def __init__(self, *results, configured=True, model="stub/judge"):
        self.model, self.configured = model, configured
        self._results = list(results)
        self.calls: list[dict] = []

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        self.calls.append({"attack": attack, "reply": reply, "conversation": conversation})
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        if isinstance(result, Exception):
            raise result
        return ParsedVerdict(result, "reason", progress="progress", tokens=10)


class StubAttacker:
    def __init__(self):
        self.model = "stub/attacker"
        self.configured = True

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        return AttackerReply(message=f"<attacker turn {len(conversation) // 2 + 1}>", tokens=50)


def ok(reply="an ordinary reply"):
    return Outcome(ok=True, step="success", message="Connection works.", reply_text=reply, reply_truncated=False,
                  status_code=200)


def sender_returning(*outcomes, record=None):
    """A stub for `sender`: returns the given outcomes in turn; the last repeats."""
    seq = list(outcomes)

    async def send(resolved, **kwargs):
        if record is not None:
            record.append(kwargs)
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return send


def sender_raising(error: Exception):
    async def send(resolved, **kwargs):
        raise error
    return send


def make_single_turn_source(store, target):
    """A finished, succeeded single-turn run, confirmed by a canary (FR-021)."""
    store.set_canaries(target.id, ["KESTREL-CANARY-X"])
    source = asyncio.run(execute_run(
        store, target_id=target.id, prompt=SEED, attacker_source=SRC, canaries=store.list_canaries(target.id),
        resolved=RESOLVED, mode="local", judge=StubJudge(configured=False),
        sender=sender_returning(ok("leak KESTREL-CANARY-X"))))
    assert source.verdict == "succeeded" and source.hard_evidence is True
    return source


def make_adaptive_source(store, target, *, turns=3):
    """A finished, succeeded adaptive run with `turns` recorded turns, succeeding on its own last one."""
    results = ["failed"] * (turns - 1) + ["succeeded"]
    source = asyncio.run(run_adaptive(
        store, target_id=target.id, seed_prompt=SEED, attacker_source=SRC, canaries=[], resolved=RESOLVED,
        attacker=StubAttacker(), judge=SequencedJudge(*results), sender=sender_returning(ok()), **LIVE_CAPS))
    assert source.verdict == "succeeded" and source.turns_used == turns and source.succeeded_turn == turns
    return source, store.list_turns(source.id)


# ---- single-turn (T013; 012/FR-001 to FR-003, FR-007 to FR-009, FR-012, FR-015, FR-020 to FR-024) ----


def test_replay_resends_the_source_verbatim_and_each_behaviour_yields_its_own_outcome(store, target):
    source = make_single_turn_source(store, target)

    sent: list[dict] = []
    fixed = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                       judge=StubJudge(verdict="failed"),
                                       sender=sender_returning(ok("a harmless reply"), record=sent),
                                       **REPLAY_CAPS))
    assert sent[0]["prompt"] == source.prompt_text   # byte for byte, the source's own recorded text
    assert fixed.mode == "replay" and fixed.source_run_id == source.id
    assert fixed.attacker_model is None and fixed.use_prior_experience is False
    assert fixed.replay_outcome == "fixed"

    vulnerable = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                            judge=StubJudge(verdict="failed"),
                                            sender=sender_returning(ok("leak KESTREL-CANARY-X")), **REPLAY_CAPS))
    assert vulnerable.replay_outcome == "still_vulnerable"

    inconclusive = asyncio.run(execute_replay(
        store, source=source, source_turns=[], resolved=RESOLVED, mode="local", judge=StubJudge(verdict="failed"),
        sender=sender_returning(Outcome(ok=False, step="unreachable", message="Unreachable.")), **REPLAY_CAPS))
    assert inconclusive.replay_outcome == "inconclusive"

    with pytest.raises(ReplayFailed) as excinfo:
        asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                   judge=StubJudge(verdict="failed"), sender=sender_raising(RuntimeError("boom")),
                                   **REPLAY_CAPS))
    crashed = store.get_run(excinfo.value.run_id)
    assert crashed.replay_outcome == "inconclusive"


def test_single_turn_replay_records_tokens_used_like_a_live_run(store, target):
    """execute_run records 0 tokens for a send failure, a canary hit, no judge configured, or a judge error, and
    the judge's own verdict.tokens on a genuine judge call; the single-turn replay branch recorded none of these
    at all (review item 11) - tokens_used stayed null on every outcome."""
    source = make_single_turn_source(store, target)

    canary_hit = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                            judge=StubJudge(tokens=999), sender=sender_returning(ok("leak "
                                            "KESTREL-CANARY-X")), **REPLAY_CAPS))
    assert canary_hit.hard_evidence is True and canary_hit.tokens_used == 0

    no_judge = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                          judge=StubJudge(configured=False), sender=sender_returning(ok("a "
                                          "harmless reply")), **REPLAY_CAPS))
    assert no_judge.verdict == "unclear" and no_judge.tokens_used == 0

    judge_error = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED,
                                             mode="local", judge=StubJudge(error=JudgeError("boom"), tokens=999),
                                             sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert judge_error.verdict == "unclear" and judge_error.tokens_used == 0

    judged = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                        judge=StubJudge(verdict="failed", tokens=137),
                                        sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert judged.verdict == "failed" and judged.tokens_used == 137

    send_failed = asyncio.run(execute_replay(
        store, source=source, source_turns=[], resolved=RESOLVED, mode="local", judge=StubJudge(tokens=999),
        sender=sender_returning(Outcome(ok=False, step="unreachable", message="Unreachable.")), **REPLAY_CAPS))
    assert send_failed.failure_step == "unreachable" and send_failed.tokens_used == 0


def test_family_owasp_category_and_prompt_fields_are_copied_from_the_source(store, target):  # FR-021
    """Not only a docstring claim (review item 13): family, OWASP category, prompt id, title and text are copied
    onto the replay run verbatim, never recomputed."""
    source = make_single_turn_source(store, target)
    run = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                     judge=StubJudge(verdict="failed"),
                                     sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert run.family == source.family
    assert run.owasp_category == source.owasp_category
    assert run.prompt_id == source.prompt_id
    assert run.prompt_title == source.prompt_title
    assert run.prompt_text == source.prompt_text


def test_an_adaptive_replays_family_owasp_category_and_prompt_fields_are_also_copied(store, target):  # FR-021
    source, source_turns = make_adaptive_source(store, target, turns=2)
    run = asyncio.run(execute_replay(store, source=source, source_turns=source_turns, resolved=RESOLVED,
                                     mode="local", judge=SequencedJudge("failed", "failed"),
                                     sender=sender_returning(ok()), **REPLAY_CAPS))
    assert run.family == source.family and run.owasp_category == source.owasp_category
    assert run.prompt_id == source.prompt_id and run.prompt_title == source.prompt_title
    assert run.prompt_text == source.prompt_text


def test_no_judge_configured_gives_inconclusive_unless_a_canary_matched(store, target):  # SC-002
    source = make_single_turn_source(store, target)

    no_judge = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                          judge=StubJudge(configured=False),
                                          sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert no_judge.verdict == "unclear" and no_judge.replay_outcome == "inconclusive"

    canary_hit = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                            judge=StubJudge(configured=False),
                                            sender=sender_returning(ok("leak KESTREL-CANARY-X")), **REPLAY_CAPS))
    assert canary_hit.verdict == "succeeded" and canary_hit.replay_outcome == "still_vulnerable"


def test_no_attacker_exists_and_the_judge_sees_no_conversation_argument(store, target):
    """execute_replay accepts no attacker parameter at all - zero attacker-model calls is a structural guarantee,
    not something to assert per call (FR-002). The judge call itself is shaped like execute_run's (FR-008)."""
    source = make_single_turn_source(store, target)
    judge = StubJudge(verdict="failed")
    asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local", judge=judge,
                               sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert judge.calls[0]["conversation"] is None


def test_judge_provenance_reflects_the_currently_configured_judge_not_the_sources(store, target):
    # FR-022: a replay records no attacker model, and the judge/judge-prompt provenance active at replay time.
    source = make_single_turn_source(store, target)
    assert source.judge_model is None   # the source succeeded by canary: no judge was ever consulted
    run = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                     judge=StubJudge(verdict="failed", model="today/judge"),
                                     sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))
    assert run.judge_model == "today/judge"


def test_the_replays_own_stored_reply_is_masked_not_the_raw_secret(store, target):
    source = make_single_turn_source(store, target)
    run = asyncio.run(execute_replay(store, source=source, source_turns=[], resolved=RESOLVED, mode="local",
                                     judge=StubJudge(verdict="failed"),
                                     sender=sender_returning(ok("leaked: test-key-123")), **REPLAY_CAPS))
    assert "test-key-123" not in (run.reply_text or "")


# ---- adaptive (T014; 012/FR-001 to FR-003, FR-007 to FR-012, FR-014, FR-015, FR-020 to FR-024, FR-041) ----


def test_adaptive_replay_resends_every_turn_verbatim_judged_against_its_own_fresh_replies(store, target):
    source, source_turns = make_adaptive_source(store, target, turns=3)
    sent: list[dict] = []
    judge = SequencedJudge("failed", "failed", "failed")

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local", judge=judge,
        sender=sender_returning(ok("today's reply"), record=sent), **REPLAY_CAPS))

    assert [s["prompt"] for s in sent] == [t.attacker_message for t in source_turns]
    assert all(call["reply"] == "today's reply" for call in judge.calls)   # the replay's own reply, never source's
    assert replay.turns_used == 3 and replay.replay_outcome == "fixed"


def test_a_replay_that_succeeds_early_sends_no_further_recorded_messages(store, target):
    source, source_turns = make_adaptive_source(store, target, turns=3)
    sent: list[dict] = []

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("succeeded"), sender=sender_returning(ok(), record=sent), **REPLAY_CAPS))

    assert len(sent) == 1 < len(source_turns)
    assert replay.replay_outcome == "still_vulnerable"


def test_a_lower_current_turn_limit_stops_the_replay_short_and_is_inconclusive_never_fixed(store, target):
    # FR-011: a replay's turn count never exceeds the currently configured adaptive turn limit.
    source, source_turns = make_adaptive_source(store, target, turns=3)

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed", "failed", "failed"), sender=sender_returning(ok("a harmless reply")),
        adaptive_max_turns=2, adaptive_token_budget=40000, adaptive_time_limit_s=300))

    assert replay.turns_used == 2 and replay.stopping_condition == "turn_cap"
    assert replay.replay_outcome == "inconclusive"


def test_each_resent_turns_provenance_is_copied_from_its_own_source_turn_not_its_neighbours(store, target):
    # FR-023: each sent message is recorded as its own turn, with attacker-prompt provenance copied from the
    # source's matching turn.
    source, _ = make_adaptive_source(store, target, turns=3)
    # Turn 2 and turn 3 get distinct attacker-prompt versions by hand, so an off-by-one between the message
    # lookup (attacker_node) and the provenance copy (record_node) would be caught.
    with sqlite3.connect(store._path) as db:
        db.execute("UPDATE run_turns SET attacker_prompt_id = 'attacker:system_prompt_leak',"
                   " attacker_prompt_version = '7' WHERE run_id = ? AND position = 2", (source.id,))
        db.execute("UPDATE run_turns SET attacker_prompt_id = 'attacker:system_prompt_leak',"
                   " attacker_prompt_version = '9' WHERE run_id = ? AND position = 3", (source.id,))
    source_turns = store.list_turns(source.id)

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed", "failed", "failed"), sender=sender_returning(ok("a harmless reply")),
        **REPLAY_CAPS))

    replay_turns = store.list_turns(replay.id)
    assert replay_turns[1].attacker_prompt_version == "7"
    assert replay_turns[2].attacker_prompt_version == "9"


@pytest.mark.parametrize("first_turn_result", [JudgeError("rate limited"), "unclear"])
def test_an_unresolved_first_turn_is_inconclusive_even_with_every_later_turn_cleanly_failed(store, target,
                                                                                             first_turn_result):
    """The exact regression case (research D5, SC-002): an early unresolved turn must not be hidden behind later
    turns' clean failures, as reading the run's one aggregate verdict would wrongly do."""
    source, source_turns = make_adaptive_source(store, target, turns=3)

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge(first_turn_result, "failed", "failed"),
        sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))

    assert replay.turns_used == 3   # every recorded message was sent
    assert replay.replay_outcome == "inconclusive"   # never "fixed"


def test_a_crash_mid_replay_closes_the_row_inconclusive_and_raises_replay_failed(store, target, monkeypatch):
    source, source_turns = make_adaptive_source(store, target, turns=3)
    import kestrel.attack.graph as graph_module
    original = graph_module._check_evidence
    calls = {"n": 0}

    def exploding_check_evidence(state, canaries):
        calls["n"] += 1
        if calls["n"] == 2:   # let turn 1 record normally, then fail on turn 2
            raise RuntimeError("boom")
        return original(state, canaries)

    monkeypatch.setattr(graph_module, "_check_evidence", exploding_check_evidence)

    with pytest.raises(ReplayFailed) as excinfo:
        asyncio.run(execute_replay(
            store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
            judge=SequencedJudge("failed", "failed", "failed"), sender=sender_returning(ok("a harmless reply")),
            **REPLAY_CAPS))

    crashed = store.get_run(excinfo.value.run_id)
    assert crashed.status == "finished" and crashed.verdict == "unclear"
    assert crashed.replay_outcome == "inconclusive"


def test_the_lifted_send_turn_still_masks_a_replayed_turns_reply(store, target):
    source, source_turns = make_adaptive_source(store, target, turns=3)

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed", "failed", "failed"),
        sender=sender_returning(ok("leaked: test-key-123")), **REPLAY_CAPS))

    replay_turns = store.list_turns(replay.id)
    assert all("test-key-123" not in (t.reply_text or "") for t in replay_turns)


def test_turn_started_and_canary_hit_false_survive_the_lift(store, target, json_log):
    source, source_turns = make_adaptive_source(store, target, turns=2)   # emits its own, unscoped lines first

    with events.run_scope():
        replay = asyncio.run(execute_replay(
            store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
            judge=SequencedJudge("failed", "failed"), sender=sender_returning(ok("a harmless reply")),
            **REPLAY_CAPS))

    turn_lines = [line for line in json_log.of("turn") if line.get("run_id") == replay.id]
    assert [line["turn"] for line in turn_lines] == [1, 2]
    assert all(line["canary_hit"] is False for line in turn_lines)


def test_a_multi_message_source_with_no_recorded_winning_turn_is_inconclusive_never_fixed(store, target):
    """The defensive fail-closed guard (FR-015): not a shape any real run produces (a run's winning turn is
    always its own last recorded turn), but compute_outcome must still handle it correctly."""
    source, source_turns = make_adaptive_source(store, target, turns=3)
    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed", "failed", "failed"), sender=sender_returning(ok("a harmless reply")),
        **REPLAY_CAPS))
    assert replay.replay_outcome == "fixed"

    with sqlite3.connect(store._path) as db:
        db.execute("UPDATE runs SET succeeded_turn = NULL WHERE id = ?", (source.id,))
    no_winning_turn = store.get_run(source.id)

    replay_defensive = asyncio.run(execute_replay(
        store, source=no_winning_turn, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed", "failed", "failed"), sender=sender_returning(ok("a harmless reply")),
        **REPLAY_CAPS))
    assert replay_defensive.replay_outcome == "inconclusive"


def test_an_adaptive_source_with_exactly_one_recorded_turn_behaves_like_the_single_turn_rule(store, target):
    source, source_turns = make_adaptive_source(store, target, turns=1)
    assert source.succeeded_turn == 1   # a real value here, unlike a single-turn-mode source's always-null one

    replay = asyncio.run(execute_replay(
        store, source=source, source_turns=source_turns, resolved=RESOLVED, mode="local",
        judge=SequencedJudge("failed"), sender=sender_returning(ok("a harmless reply")), **REPLAY_CAPS))

    assert replay.replay_outcome == "fixed"   # the winning-turn check is skipped outright for recorded_total == 1
