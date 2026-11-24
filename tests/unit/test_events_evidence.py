"""The log lines feature 013 adds and changes (013/FR-047, FR-048; contracts/log-records-delta.md).

Every new field is a count, a status, a kind, a step or a turn number — never a token, a URL, a correlation id,
an auth value, an evidence detail, reply text or attack text. The four `run.start` fields follow the one 010
convention (omitted when they do not apply, never null); the `turn` and `run.end` fields are always present."""
import logging

import pytest

from kestrel import events

FEATURE = "013"


@pytest.fixture
def records(caplog):
    caplog.set_level(logging.DEBUG, logger="kestrel")
    return [record for record in caplog.records]


@pytest.fixture
def captured(caplog):
    caplog.set_level(logging.DEBUG, logger="kestrel")

    def read(event: str | None = None) -> list[dict]:
        out = []
        for record in caplog.records:
            if event is None or getattr(record, "kestrel_event", None) == event:
                out.append({"event": getattr(record, "kestrel_event", None),
                            "level": record.levelno, **getattr(record, "kestrel_fields", {})})
        return out
    return read


class FakeRun:
    id, target_id, mode, family = 7, 3, "single_turn", "direct_injection"
    verdict, hard_evidence, stopping_condition, failure_step = "succeeded", True, "succeeded", None
    turns_used, tokens_used, succeeded_turn, replay_outcome = 1, 0, 1, None


def start(**extra):
    events.run_started(None, run_id=7, target_id=3, mode="single_turn", family="direct_injection", **extra)


def test_run_start_carries_the_four_evidence_fields_when_they_are_passed(captured):  # FR-047
    with events.run_scope():
        start(side_channel="not_configured", callback_listener="off", override_planted=True,
              callback_planted=False)
    line = captured("run.start")[0]
    assert line["side_channel"] == "not_configured" and line["callback_listener"] == "off"
    assert line["override_planted"] is True and line["callback_planted"] is False


def test_run_start_omits_each_evidence_field_that_is_not_passed(captured):  # FR-047 (the 010 convention)
    with events.run_scope():
        start()
    line = captured("run.start")[0]
    for field in ("side_channel", "callback_listener", "override_planted", "callback_planted"):
        assert field not in line       # absent, never null


def test_the_turn_line_carries_the_kinds_and_the_count(captured):  # FR-047
    with events.run_scope():
        start()
        events.turn_started(1)
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=20,
                          reply_truncated=False, canary_hit=False, hard_evidence=True, judged=False, verdict=None,
                          attacker_generated=False, evidence_kinds=["instruction_override"], evidence_count=1)
    line = captured("turn")[0]
    assert line["evidence_kinds"] == ["instruction_override"] and line["evidence_count"] == 1
    # `hard_evidence` on this row now means "this turn produced at least one evidence item of any kind";
    # `canary_hit` keeps its narrower meaning.
    assert line["hard_evidence"] is True and line["canary_hit"] is False


def test_a_turn_without_evidence_still_carries_both_fields(captured):  # FR-047
    with events.run_scope():
        start()
        events.turn_started(1)
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=20,
                          reply_truncated=False, canary_hit=False, hard_evidence=False, judged=True,
                          verdict="failed", attacker_generated=False)
    line = captured("turn")[0]
    assert line["evidence_kinds"] == [] and line["evidence_count"] == 0


def test_the_evidence_check_line_carries_the_checks_run_and_what_they_found(captured):  # FR-047, FR-048
    with events.run_scope():
        start()
        events.turn_started(1)
        events.evidence_check(checks=["canary", "instruction_override", "unsafe_executable_output"],
                              evidence_kinds=["instruction_override"], evidence_count=1,
                              side_channel_status="not_configured")
    line = captured("evidence.check")[0]
    assert line["checks"] == ["canary", "instruction_override", "unsafe_executable_output"]
    assert line["evidence_kinds"] == ["instruction_override"] and line["evidence_count"] == 1
    assert line["side_channel_status"] == "not_configured" and line["turn"] == 1
    assert "callback_wait_ms" not in line and "state_changed_keys" not in line   # omitted when they do not apply
    assert line["level"] == logging.INFO


def test_the_evidence_check_line_carries_the_part_two_fields_when_they_apply(captured):  # FR-047, FR-033
    with events.run_scope():
        start()
        events.turn_started(2)
        events.evidence_check(checks=["canary", "tool_calls", "callback", "state"], evidence_kinds=[],
                              evidence_count=0, side_channel_status="checked", callback_wait_ms=2000,
                              state_changed_keys=3)
    line = captured("evidence.check")[0]
    assert line["callback_wait_ms"] == 2000 and line["state_changed_keys"] == 3   # a count only, never a key name


def test_the_run_end_line_sums_the_kinds_and_the_count_across_the_run(captured):  # FR-047
    with events.run_scope():
        start()
        events.turn_started(1)
        events.evidence_check(checks=["canary"], evidence_kinds=["canary_in_reply"], evidence_count=1,
                              side_channel_status="not_configured")
        events.turn_started(2)
        events.evidence_check(checks=["canary", "unsafe_executable_output"],
                              evidence_kinds=["unsafe_executable_output"], evidence_count=2,
                              side_channel_status="checked")
        events.run_finished(FakeRun())
    end = captured("run.end")[0]
    assert end["evidence_kinds"] == ["canary_in_reply", "unsafe_executable_output"]   # distinct, detection order
    assert end["evidence_count"] == 3
    assert end["side_channel_status"] == "checked"


def test_a_run_that_found_nothing_still_carries_the_three_fields(captured):  # FR-047
    with events.run_scope():
        start()
        events.run_finished(FakeRun())
    end = captured("run.end")[0]
    assert end["evidence_kinds"] == [] and end["evidence_count"] == 0
    assert end["side_channel_status"] == "not_configured"


def test_the_override_disarmed_warning_renders_with_its_turn(captured):  # FR-047
    with events.run_scope():
        start()
        events.turn_started(2)
        events.emit("evidence.override_disarmed", logging.WARNING)
    line = captured("evidence.override_disarmed")[0]
    assert line["turn"] == 2 and line["run_id"] == 7 and line["level"] == logging.WARNING


def test_none_of_the_new_fields_is_dropped_as_unknown(captured):  # FR-047
    with events.run_scope():
        start(side_channel="configured", callback_listener="on", override_planted=True, callback_planted=True)
        events.turn_started(1)
        events.evidence_check(checks=["canary"], evidence_kinds=[], evidence_count=0,
                              side_channel_status="unavailable", callback_wait_ms=0, state_changed_keys=0)
        events.emit("evidence.override_disarmed", logging.WARNING)
        events.turn_ended(turn=1, source="library:dir-001", message_chars=1, reply_chars=1, reply_truncated=False,
                          canary_hit=False, hard_evidence=False, judged=False, verdict=None,
                          attacker_generated=False, evidence_kinds=[], evidence_count=0)
        events.run_finished(FakeRun())
    assert captured("log.unknown_field") == []


def test_the_catalogue_names_every_part_one_field():  # FR-047
    assert {"side_channel", "callback_listener", "override_planted",
            "callback_planted"} <= set(events.CATALOGUE["run.start"])
    assert {"evidence_kinds", "evidence_count"} <= set(events.CATALOGUE["turn"])
    assert {"evidence_kinds", "evidence_count", "side_channel_status"} <= set(events.CATALOGUE["run.end"])
    assert set(events.CATALOGUE["evidence.check"]) == {"checks", "evidence_kinds", "evidence_count",
                                                        "side_channel_status", "callback_wait_ms",
                                                        "state_changed_keys"}
    assert events.CATALOGUE["evidence.override_disarmed"] == ()
    # Part 2's three events join the catalogue with the lines that emit them; `callback.ignored` carries
    # `reason_kind`, never `reason` (the deny-list `test_events.py` enforces over every catalogued field).
    for event in ("evidence.side_channel_unavailable", "callback.hit", "callback.ignored"):
        assert event not in events.CATALOGUE
