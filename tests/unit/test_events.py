"""The run scope and the one structured emission API (010/FR-001, 010/FR-005, 010/FR-010, 010/SC-005).

The scope is opened by the code that starts a run; `run_started` emits `run.start` once the row is claimed and binds
the run's identifiers; the scope's exit emits `run.end` as the last record, after whatever the body did (the
write-back); a record emitted under a run *reference* names the run but is never kept."""
import asyncio
import logging
from dataclasses import dataclass

import pytest

from kestrel import events

FEATURE = "010"


@dataclass(frozen=True)
class FakeRun:
    """The fields of a finished Run that `run.end` and a reference binding read."""
    id: int = 7
    target_id: int = 3
    mode: str = "adaptive"
    family: str = "direct_injection"
    verdict: str | None = "failed"
    hard_evidence: bool = False
    stopping_condition: str | None = "turn_cap"
    failure_step: str | None = None
    turns_used: int | None = 2
    tokens_used: int | None = 240
    succeeded_turn: int | None = None


@pytest.fixture
def records():
    """Every LogRecord the `kestrel` logger handles, so a test can read `kestrel_keep` beside the fields."""
    class Collect(logging.Handler):
        def __init__(self):
            super().__init__()
            self.items = []

        def emit(self, record):
            self.items.append(record)

    logger = logging.getLogger("kestrel")
    handler, level = Collect(), logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield handler.items
    logger.removeHandler(handler)
    logger.setLevel(level)


def fields(record) -> dict:
    return record.kestrel_fields


def names(items) -> list[str]:
    return [record.kestrel_event for record in items]


def start(**extra):
    events.run_started(None, run_id=7, target_id=3, mode="adaptive", family="direct_injection", **extra)


def test_a_scope_emits_nothing_by_itself(records):  # FR-001
    with events.run_scope():
        pass
    assert records == []


def test_run_started_emits_run_start_and_binds_the_run_on_every_record(records):  # FR-001, FR-005
    with events.run_scope():
        start(prompt_id="dir-001", attacker_source="library:1.0.0", attacker_model="a/m", judge_model="j/m",
              attacker_prompt="attacker:direct_injection@1", judge_prompt="judge@1", turn_budget=6,
              token_budget=40000, time_limit_s=300, use_prior_experience=True)
        events.emit("memory.retrieval", turn=2, warm=False, pattern_count=0, memory_count=0, pattern_ids=[])
    first, second = records[0], records[1]
    assert first.kestrel_event == "run.start"
    assert fields(first) == {"run_id": 7, "target_id": 3, "mode": "adaptive", "family": "direct_injection",
                             "prompt_id": "dir-001", "attacker_source": "library:1.0.0", "attacker_model": "a/m",
                             "judge_model": "j/m", "attacker_prompt": "attacker:direct_injection@1",
                             "judge_prompt": "judge@1", "turn_budget": 6, "token_budget": 40000,
                             "time_limit_s": 300, "use_prior_experience": True}
    assert {k: fields(second)[k] for k in ("run_id", "target_id", "mode", "family")} == {
        "run_id": 7, "target_id": 3, "mode": "adaptive", "family": "direct_injection"}
    assert first.kestrel_keep is True and second.kestrel_keep is True


def test_the_scope_exit_emits_run_end_last_after_the_write_back(records):  # FR-001, FR-010
    with events.run_scope():
        start()
        events.turn_started(1)
        events.judge_requested("judge@1")
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=20, reply_truncated=False,
                          canary_hit=False, hard_evidence=False, judged=True, verdict="failed",
                          attacker_generated=False)
        events.run_finished(FakeRun())
        events.memory_writeback(written=True, pattern_written=False)   # the caller's write-back, inside the scope
    assert names(records) == ["run.start", "turn", "memory.writeback", "run.end"]
    end = fields(records[-1])
    assert end["verdict"] == "failed" and end["hard_evidence"] is False and end["stopping_condition"] == "turn_cap"
    assert end["judge_used"] is True and end["turns_used"] == 2 and end["tokens_used"] == 240
    assert end["memory_written"] is True and end["duration_ms"] >= 0 and end["cost_usd"] == 0.0
    assert "error" not in end and "turn" not in end and records[-1].levelno == logging.INFO


def test_run_end_names_the_class_of_an_exception_that_escaped_never_its_text(records):  # FR-001, FR-009
    with pytest.raises(KeyError):
        with events.run_scope():
            start()
            raise KeyError("text that must not be logged")
    end = records[-1]
    assert end.kestrel_event == "run.end" and fields(end)["error"] == "KeyError" and end.levelno == logging.ERROR
    assert "must not be logged" not in repr(fields(end))


def test_a_scope_whose_claim_failed_emits_nothing(records):  # FR-001 (RunInProgress: no run.start, no run.end)
    with pytest.raises(RuntimeError):
        with events.run_scope():
            raise RuntimeError("claim refused")
    assert records == []


def test_judge_used_means_a_judge_request_was_made(records):  # FR-001
    with events.run_scope():
        start()
        events.run_finished(FakeRun())
    assert fields(records[-1])["judge_used"] is False


def test_an_experiment_binding_stamps_every_record_of_a_scope_opened_inside_it(records):  # FR-005, SC-008
    with events.bind_experiment(5):
        events.emit("experiment.start", experiment_id=5, target_id=3, mode="adaptive", families=["x"], reps=1,
                    max_runs=2, token_budget_total=10, wall_clock_s=60, arms=[])
        with events.bind_experiment(5, "A"), events.run_scope():
            start()
            events.memory_writeback(written=True, pattern_written=False)
    assert fields(records[0])["experiment_id"] == 5 and "arm" not in fields(records[0])
    assert names(records[1:]) == ["run.start", "memory.writeback", "run.end"]
    for record in records[1:]:
        assert fields(record)["experiment_id"] == 5 and fields(record)["arm"] == "A"


def test_a_run_reference_names_the_run_emits_no_run_lines_and_is_never_kept(records):  # FR-005, FR-010
    with events.bind_run_reference(FakeRun(id=9, target_id=4, mode="single_turn", family="tool_exfiltration")):
        events.model_request(kind="recommender", model="j/m", prompt="recommender@1", latency_ms=5, ok=True,
                             status=200, attempts=1, prompt_tokens=1, completion_tokens=1, total_tokens=2)
    assert names(records) == ["model.request"]
    assert {k: fields(records[0])[k] for k in ("run_id", "target_id", "mode", "family")} == {
        "run_id": 9, "target_id": 4, "mode": "single_turn", "family": "tool_exfiltration"}
    assert records[0].kestrel_keep is False


def test_a_reference_to_the_run_whose_scope_is_open_keeps_the_runs_own_lines(records):  # FR-010 (write-back)
    with events.run_scope():
        start()
        with events.bind_run_reference(FakeRun(id=7)):
            events.memory_writeback(written=True, pattern_written=False)
    writeback = next(r for r in records if r.kestrel_event == "memory.writeback")
    assert writeback.kestrel_keep is True and fields(records[-1])["memory_written"] is True


def test_with_no_scope_open_run_started_is_null_safe_and_run_finished_does_nothing(records):  # SC-005
    start(prompt_id="dir-001")
    events.run_finished(FakeRun())
    assert names(records) == ["run.start"]
    assert fields(records[0]).get("run_id") is None and records[0].kestrel_keep is False


def test_the_turn_on_the_shared_context_is_seen_from_a_child_task(records):  # FR-005
    async def go():
        with events.run_scope():
            start()
            events.turn_started(3)

            async def child():
                events.emit("memory.retrieval", warm=False, pattern_count=0, memory_count=0, pattern_ids=[])

            await asyncio.create_task(child())
    asyncio.run(go())
    retrieval = next(r for r in records if r.kestrel_event == "memory.retrieval")
    assert fields(retrieval)["turn"] == 3


def _request(total):
    events.model_request(kind="attacker", model="a/m", prompt="attacker:direct_injection@1", latency_ms=1, ok=True,
                         status=200, attempts=1, prompt_tokens=total - 20, completion_tokens=20, total_tokens=total,
                         message_chars=12)


def _end_turn(turn):
    events.turn_ended(turn=turn, source="attacker:direct_injection@1", message_chars=12, reply_chars=5,
                      reply_truncated=False, canary_hit=False, hard_evidence=False, judged=False, verdict=None,
                      attacker_generated=True)


def test_the_per_turn_totals_reset_on_each_new_turn(records):  # FR-002
    with events.run_scope():
        start(attacker_model="a/m", attacker_prompt="attacker:direct_injection@1")
        events.turn_started(1)
        _request(120)
        _end_turn(1)
        events.turn_started(2)
        _end_turn(2)
    turns = [fields(r) for r in records if r.kestrel_event == "turn"]
    assert (turns[0]["prompt_tokens"], turns[0]["completion_tokens"], turns[0]["total_tokens"]) == (100, 20, 120)
    assert (turns[1]["prompt_tokens"], turns[1]["completion_tokens"], turns[1]["total_tokens"]) == (None, None, None)
    assert turns[1]["cost_usd"] == 0.0 and "cost_note" not in turns[1]
    assert turns[0]["attacker_model"] == "a/m" and turns[0]["attacker_prompt"] == "attacker:direct_injection@1"


def test_fields_that_do_not_apply_are_omitted_not_null(records):  # FR-001, FR-002
    with events.run_scope():
        start(prompt_id="dir-001", turn_budget=1, time_limit_s=90)   # no judge, no attacker: single-turn, unjudged
        events.turn_started(1)
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=None,
                          reply_truncated=False, canary_hit=False, hard_evidence=False, judged=False, verdict=None,
                          attacker_generated=False)
    run_start, turn = fields(records[0]), fields(records[1])
    for absent in ("judge_model", "judge_prompt", "attacker_model", "attacker_prompt", "token_budget", "turn"):
        assert absent not in run_start, absent
    for absent in ("judge_model", "judge_prompt", "attacker_model", "attacker_prompt", "cost_note"):
        assert absent not in turn, absent
    assert turn["reply_chars"] is None and turn["verdict"] is None   # catalogued `| null`: present, unknown


def test_a_judge_configured_turn_without_a_judge_request_carries_a_null_judge_prompt(records):  # FR-002, FR-007
    with events.run_scope():
        start(judge_model="j/m", judge_prompt="judge@1")
        events.turn_started(1)    # a canary decided this turn: no judge request was made
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=20, reply_truncated=False,
                          canary_hit=True, hard_evidence=True, judged=False, verdict=None, attacker_generated=False)
    turn = fields(next(r for r in records if r.kestrel_event == "turn"))
    assert turn["judge_model"] == "j/m" and "judge_prompt" in turn and turn["judge_prompt"] is None
    assert turn["canary_hit"] is True and turn["hard_evidence"] is True


# ---- T025: the catalogue is the allow-list, and nothing interpolates values into text (FR-006, FR-009) ----

DENY_NAMES = {"url", "name", "reason", "progress", "message_text", "reply_text", "prompt_text", "value"}


def test_no_catalogued_field_can_carry_free_text():  # FR-009
    names = set(events.SCOPE_FIELDS) | set(events.ANY_EVENT_FIELDS)
    names |= {field for fields in events.CATALOGUE.values() for field in fields}
    assert not names & DENY_NAMES


def test_the_helpers_take_identifiers_lengths_and_categories_only():  # FR-009
    import inspect
    text_like = DENY_NAMES | {"text", "reply", "attack", "conversation", "headers", "display_name", "evidence"}
    for helper in (events.run_started, events.turn_ended, events.model_request, events.target_request,
                   events.connection_test, events.memory_retrieval, events.memory_writeback,
                   events.experiment_started, events.experiment_cap, events.experiment_ended):
        assert not set(inspect.signature(helper).parameters) & text_like, helper.__name__


def test_no_log_call_in_kestrel_interpolates_a_value():  # FR-006
    """Every value travels as a field: a logging call in src/kestrel passes its (constant) message and nothing to
    %-format into it."""
    import ast
    from pathlib import Path
    levels = {"debug", "info", "warning", "error", "exception", "critical"}
    offenders = []
    for path in sorted((Path(events.__file__).parent).rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in ("log", "logger")):
                continue
            allowed = 1 if node.func.attr in levels else 2 if node.func.attr == "log" else None
            if allowed is not None and len(node.args) > allowed:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
