"""`scripts/check_replay.py`: the CI gate's exit codes and output, over a stubbed Kestrel API
(contracts/ci-script.md; 012/FR-034 to FR-037, SC-007, SC-008). The script is loaded from scripts/ by path,
since scripts/ is not on the import path (mirrors tests/unit/test_import_attacks.py)."""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import httpx
import pytest

from tests.support import ATTACK_TEXT, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL

FEATURE = "012"

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location("check_replay", REPO_ROOT / "scripts" / "check_replay.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_replay = _load_module()

CONFIG = {"replay": {"max_batch_runs": 20, "per_replay_time_limit_s": 300}}
MARKERS = (ATTACK_TEXT, REPLY_TEXT, SECRET, TARGET_URL, TARGET_NAME)


def entry(source_id, replay_id, family, outcome, *, source_hard_evidence=True, replay_hard_evidence=False,
         replay_verdict=None):
    return {"source_run_id": source_id, "replay_run_id": replay_id, "family": family, "outcome": outcome,
           "source_verdict": "succeeded", "source_hard_evidence": source_hard_evidence,
           "replay_verdict": replay_verdict or {"fixed": "failed", "still_vulnerable": "succeeded",
                                                "inconclusive": "unclear"}[outcome],
           "replay_hard_evidence": replay_hard_evidence,
           # Known markers in an unused field: the script must never print the whole body blindly (SC-008).
           "url": TARGET_URL, "name": TARGET_NAME, "attack": ATTACK_TEXT, "reply": REPLY_TEXT}


def batch_result(*, entries, complete, stop_reason=None, not_replayed=None):
    counts = {"fixed": sum(1 for e in entries if e["outcome"] == "fixed"),
             "still_vulnerable": sum(1 for e in entries if e["outcome"] == "still_vulnerable"),
             "inconclusive": sum(1 for e in entries if e["outcome"] == "inconclusive")}
    return {"target_id": 1, "entries": entries, "counts": counts, "complete": complete,
           "stop_reason": stop_reason, "not_replayed_source_ids": not_replayed or []}


def transport_for(*, batch_response=None, batch_status=200, config=CONFIG, config_status=200, error=None,
                  captured_timeouts=None):
    def handle(request: httpx.Request) -> httpx.Response:
        if error is not None and request.url.path.endswith("/replays"):
            raise error
        if request.url.path == "/api/config":
            return httpx.Response(config_status, json=config)
        if captured_timeouts is not None:
            captured_timeouts.append(request.extensions.get("timeout"))
        return httpx.Response(batch_status, json=batch_response)
    return httpx.MockTransport(handle)


def run_check(transport, *, target_id=1, timeout=None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = check_replay.check(target_id, timeout=timeout, client=httpx.Client(transport=transport), out=out,
                              err=err)
    return code, out.getvalue(), err.getvalue()


# ---- exit codes (contracts/ci-script.md's table; FR-036: 1 wins, then 2 for anything short of it, else 0) ----


def test_a_complete_all_fixed_batch_exits_0():
    result = batch_result(entries=[entry(12, 41, "direct_injection", "fixed")], complete=True)
    code, out, _ = run_check(transport_for(batch_response=result))
    assert code == 0
    assert "direct_injection" in out and "fixed" in out


def test_a_complete_batch_with_zero_entries_exits_0():
    result = batch_result(entries=[], complete=True)
    code, _, _ = run_check(transport_for(batch_response=result))
    assert code == 0


def test_a_complete_batch_with_a_still_vulnerable_entry_exits_1_even_alongside_inconclusive():
    result = batch_result(entries=[entry(12, 41, "direct_injection", "still_vulnerable"),
                                   entry(15, 42, "system_prompt_leak", "inconclusive")], complete=True)
    code, _, _ = run_check(transport_for(batch_response=result))
    assert code == 1


def test_a_complete_batch_with_only_inconclusive_entries_exits_2():
    result = batch_result(entries=[entry(12, 41, "direct_injection", "inconclusive")], complete=True)
    code, _, _ = run_check(transport_for(batch_response=result))
    assert code == 2


@pytest.mark.parametrize("stop_reason", ["run_in_progress", "replay_failed"])
def test_an_incomplete_batch_with_no_still_vulnerable_entry_exits_2_never_0(stop_reason):
    result = batch_result(entries=[entry(12, 41, "direct_injection", "fixed")], complete=False,
                          stop_reason=stop_reason, not_replayed=[19, 23])
    code, _, _ = run_check(transport_for(batch_response=result))
    assert code == 2


@pytest.mark.parametrize("stop_reason", ["run_in_progress", "replay_failed"])
def test_an_incomplete_batch_with_a_completed_still_vulnerable_entry_exits_1(stop_reason):
    result = batch_result(entries=[entry(12, 41, "direct_injection", "still_vulnerable")], complete=False,
                          stop_reason=stop_reason, not_replayed=[19])
    code, _, _ = run_check(transport_for(batch_response=result))
    assert code == 1


@pytest.mark.parametrize("status,body", [
    (404, {"error": {"code": "not_found", "field": None, "message": "No target with id 9."}}),
    (409, {"error": {"code": "permission_missing", "field": None, "message": "x"}}),
    (409, {"error": {"code": "terms_outdated", "field": None, "message": "x"}}),
    (409, {"error": {"code": "batch_too_large", "field": None, "message": "x"}}),
    (409, {"error": {"code": "run_in_progress", "field": None, "message": "x"}}),
])
def test_an_api_level_refusal_exits_3(status, body):
    code, _, err = run_check(transport_for(batch_response=body, batch_status=status))
    assert code == 3 and err.strip()


def test_a_transport_failure_exits_3():
    code, _, err = run_check(transport_for(error=httpx.ConnectError("refused")))
    assert code == 3 and err.strip()


@pytest.mark.parametrize("argv", [[], ["--target-id", "abc"]])
def test_a_missing_or_non_integer_target_id_exits_3(argv):
    assert check_replay.main(argv) == 3


# ---- the unknown-target worked example prints the API's own message verbatim ----


def test_an_unknown_target_prints_the_apis_own_message():
    body = {"error": {"code": "not_found", "field": None, "message": "No target with id 9."}}
    code, _, err = run_check(transport_for(batch_response=body, batch_status=404))
    assert code == 3
    assert err.strip() == "No target with id 9."


# ---- the default timeout (research D13) ----


def test_the_default_timeout_is_cap_times_per_replay_limit_plus_60():
    captured: list = []
    result = batch_result(entries=[], complete=True)
    transport = transport_for(batch_response=result, captured_timeouts=captured)
    run_check(transport)
    expected = CONFIG["replay"]["max_batch_runs"] * CONFIG["replay"]["per_replay_time_limit_s"] + 60
    assert captured[0]["read"] == expected == 6060


def test_an_explicit_timeout_overrides_the_computed_default():
    captured: list = []
    result = batch_result(entries=[], complete=True)
    transport = transport_for(batch_response=result, captured_timeouts=captured)
    run_check(transport, timeout=45.0)
    assert captured[0]["read"] == 45.0


# ---- output never carries anything but ids, family, outcome and both evidence kinds (FR-035, SC-008) ----


def test_output_never_carries_known_markers_seeded_in_unused_response_fields():
    result = batch_result(entries=[entry(12, 41, "direct_injection", "fixed", source_hard_evidence=True,
                                         replay_hard_evidence=False)], complete=True)
    code, out, err = run_check(transport_for(batch_response=result))
    for marker in MARKERS:
        assert marker not in out and marker not in err
    assert "run 12 -> replay 41: direct_injection: fixed (source: canary, replay: judge)" in out


def test_both_evidence_flags_are_printed_separately_since_they_can_differ():
    result = batch_result(entries=[entry(12, 41, "direct_injection", "fixed", source_hard_evidence=True,
                                         replay_hard_evidence=False)], complete=True)
    _, out, _ = run_check(transport_for(batch_response=result))
    assert "source: canary" in out and "replay: judge" in out


def test_the_crashed_entrys_own_replay_evidence_prints_none():
    """The one entry whose own replay crashed (research D17): outcome "inconclusive" with the batch's own
    stop_reason "replay_failed" - its replay evidence kind is "none", never "judge", since no judge call
    actually concluded it."""
    result = batch_result(
        entries=[entry(12, 41, "direct_injection", "fixed"),
                entry(15, 43, "system_prompt_leak", "inconclusive", source_hard_evidence=False,
                      replay_verdict="unclear")],
        complete=False, stop_reason="replay_failed", not_replayed=[19, 23])
    code, out, _ = run_check(transport_for(batch_response=result))
    assert code == 2
    assert "replay: none" in out
    assert "run 15 -> replay 43: system_prompt_leak: inconclusive (source: judge, replay: none)" in out
    assert "batch stopped early (replay_failed): 2 of 4 replayed, 2 not replayed (runs 19, 23)" in out


# ---- --help documents every exit code and the --timeout flag ----


def test_help_documents_every_exit_code_and_the_timeout_flag(capsys):
    code = check_replay.main(["--help"])
    assert code == 0
    text = capsys.readouterr().out
    for exit_code in ("0", "1", "2", "3"):
        assert exit_code in text
    assert "--timeout" in text
