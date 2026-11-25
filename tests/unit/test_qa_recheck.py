"""scripts/qa_recheck.py's step machine (feature 006, FR-019): traces 006/FR-019.

Covers the pure mirrors `next_action` and `already_fresh` (contracts/pr-rules.md "Recheck script"), and the full
`run_recheck()` orchestration against a stub, injected API client - no network, no `gh`. A `_FakeClock` stands in
for `time.sleep`/`time.monotonic` so a 30-minute budget runs in microseconds of real test time.
"""
import json

import pytest

import qa_recheck as qr


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _sequence(*items):
    """A callable (any arguments, ignored) returning or raising each item in turn; repeats the last item once
    exhausted. Stands in directly for a client method (`get_latest_run(head_sha)`, `get_run(run_id)`, ...)."""
    items = list(items)

    def call(*args, **kwargs):
        value = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(value, BaseException):
            raise value
        return value

    return call


class _Counting:
    """Wraps a `_sequence`-style callable and counts how many times it was actually called."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return self._inner()


_JOB = qr.JobInfo(job_id="9", started_at="2026-01-01T00:10:00Z")
_STALE_CREATED_AT = "2026-01-01T00:20:00Z"   # later than _JOB.started_at: not fresh, the POST proceeds
_FRESH_CREATED_AT = "2026-01-01T00:05:00Z"   # earlier than _JOB.started_at: already fresh, the POST is skipped


class StubClient:
    def __init__(self, *, get_latest_run=None, get_run=None, get_job=None,
                 get_recheck_run_created_at=None, request_rerun=None, post_comment_fails=0):
        self.get_latest_run = get_latest_run or _sequence(qr.RunInfo(run_id="1", status="completed"))
        self.get_run = get_run or _sequence("completed")
        self.get_job = _Counting(get_job or _sequence(_JOB))
        self.get_recheck_run_created_at = get_recheck_run_created_at or _sequence(_STALE_CREATED_AT)
        self.request_rerun = _Counting(request_rerun or _sequence("accepted"))
        self.comments: list[str] = []
        self._post_comment_fails = post_comment_fails

    def post_comment(self, text: str) -> None:
        if self._post_comment_fails > 0:
            self._post_comment_fails -= 1
            raise qr.RecheckApiError("boom")
        self.comments.append(text)


def _run(client, **kwargs) -> tuple[int, _FakeClock]:
    clock = _FakeClock()
    code = qr.run_recheck(client, "sha123", sleep=clock.sleep, now=clock.now, **kwargs)
    return code, clock


# ---- next_action: the pure state machine (contracts/pr-rules.md "Recheck script") ----

STEP_CASES = [
    (None, None, 0, "exit-0-no-run"),
    ("action_required", None, 0, "exit-0-no-run"),
    ("waiting", None, 0, "exit-0-no-run"),
    ("queued", None, 0, "wait"),
    ("in_progress", None, 1500, "wait"),
    ("in_progress", None, 1800, "fail-timeout"),
    ("completed", None, 10, "rerun"),
    ("completed", "accepted", 10, "exit-0-done"),
    ("in_progress", "refused", 10, "wait"),
    ("queued", "refused", 10, "wait"),
    ("in_progress", "refused", 1800, "fail-timeout"),
    ("completed", "refused", 10, "fail-refused"),
    ("completed", "refused", 1800, "fail-timeout"),
    ("error", None, 10, "wait"),
    ("error", None, 1799, "wait"),
    ("error", None, 1800, "fail-error"),
    ("error", None, 2400, "fail-error"),
    ("error", "refused", 10, "wait"),
    ("error", "accepted", 1800, "fail-error"),
    ("no_job", None, 0, "fail-error"),
    ("no_job", None, 1800, "fail-error"),
]


@pytest.mark.parametrize("run_status,rerun_status,elapsed,expected", STEP_CASES)
def test_next_action(run_status, rerun_status, elapsed, expected):
    assert qr.next_action(run_status, rerun_status, elapsed, 1800) == expected


# ---- already_fresh: never raises (review round 3) ----

FRESHNESS_CASES = [
    ("2026-11-24T10:00:05Z", "2026-11-24T10:00:00Z", True),
    ("2026-11-24T10:00:00Z", "2026-11-24T10:00:00Z", True),
    ("2026-11-24T09:59:59Z", "2026-11-24T10:00:00Z", False),
    (None, "2026-11-24T10:00:00Z", False),
    ("2026-11-24T10:00:00Z", None, False),
    (None, None, False),
    ("", "2026-11-24T10:00:00Z", False),
    ("2026-11-24T10:00:00Z", "", False),
    ("not a timestamp", "2026-11-24T10:00:00Z", False),
    ("2026-11-24T10:00:00Z", "not a timestamp", False),
    # review finding 5: a naive timestamp beside an aware one raises TypeError on `>=` in the stdlib; treated as
    # unparsable instead (never raises).
    ("2026-11-24T10:00:00Z", "2026-11-24T10:00:00", False),   # created naive, attempt aware
    ("2026-11-24T10:00:00", "2026-11-24T10:00:00Z", False),   # attempt naive, created aware
    ("2026-11-24T10:00:00", "2026-11-24T10:00:00", False),    # both naive
]


@pytest.mark.parametrize("attempt,created,expected", FRESHNESS_CASES)
def test_already_fresh(attempt, created, expected):
    assert qr.already_fresh(attempt, created) is expected


def test_already_fresh_tolerates_a_non_string_value():
    assert qr.already_fresh(12345, "2026-11-24T10:00:00Z") is False   # no AttributeError either


# ---- run_recheck: the full orchestration against a stub client ----

def test_no_run_for_the_head_sha_exits_0_no_comment():
    client = StubClient(get_latest_run=_sequence(None))
    code, _ = _run(client)
    assert code == 0 and client.comments == []


@pytest.mark.parametrize("status", ["action_required", "waiting"])
def test_a_run_awaiting_approval_exits_0_no_comment(status):
    client = StubClient(get_latest_run=_sequence(qr.RunInfo(run_id="1", status=status)))
    code, _ = _run(client)
    assert code == 0 and client.comments == []


def test_waiting_then_completed_requests_the_rerun_and_accepts():
    client = StubClient(
        get_latest_run=_sequence(qr.RunInfo(run_id="1", status="queued")),
        get_run=_sequence("in_progress", "in_progress", "completed"),
        request_rerun=_sequence("accepted"),
    )
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 1


def test_completed_with_no_rerun_requested_yet_requests_it():
    client = StubClient(get_latest_run=_sequence(qr.RunInfo(run_id="1", status="completed")))
    code, _ = _run(client)
    assert code == 0
    assert client.request_rerun.calls == 1
    assert client.comments == []


def test_refused_then_reread_shows_still_running_retries_then_accepts():
    client = StubClient(
        get_run=_sequence("in_progress", "completed"),   # the post-refusal re-read, then the resumed poll
        request_rerun=_sequence("refused", "accepted"),
    )
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 2


def test_refused_then_reread_shows_completed_is_final_posts_the_comment_exits_1():
    client = StubClient(get_run=_sequence("completed"), request_rerun=_sequence("refused"))
    code, _ = _run(client)
    assert code == 1
    assert len(client.comments) == 1
    assert "stale" in client.comments[0].lower()
    assert "refused" in client.comments[0]
    assert "do not merge" in client.comments[0].lower()   # finding 3: the contract's merge-rule sentence
    assert "VERDICT: PASS" not in client.comments[0] and "VERDICT: FAIL" not in client.comments[0]


def test_refusal_then_a_fresh_job_on_the_resumed_run_skips_the_second_post():
    """Review finding 1: the retry after a refusal must go back through step 3 (re-fetch the job) and step 4a
    (redo already_fresh) before any new POST - never re-POST the job id captured before the other attempt ran."""
    job_before = qr.JobInfo(job_id="9", started_at="2026-01-01T00:10:00Z")
    job_after = qr.JobInfo(job_id="99", started_at="2026-01-01T00:30:00Z")   # a new attempt's job, started later
    client = StubClient(
        get_job=_sequence(job_before, job_after),
        get_recheck_run_created_at=_sequence("2026-01-01T00:20:00Z"),
        get_run=_sequence("in_progress", "completed"),   # the post-refusal re-read, then the resumed poll
        request_rerun=_sequence("refused"),
    )
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 1   # never re-POSTed once the re-fetched job is fresh
    assert client.get_job.calls == 2         # re-fetched, not reused


def test_request_rerun_error_is_retried_via_a_reread_then_accepts():
    client = StubClient(request_rerun=_sequence(qr.RecheckApiError("boom"), "accepted"))
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 2


def test_error_on_the_post_refusal_reread_is_retried_then_accepts():
    client = StubClient(
        get_run=_sequence(qr.RecheckApiError("boom"), "completed"),
        request_rerun=_sequence("refused", "accepted"),
    )
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 2


def test_budget_exhausted_while_waiting_posts_the_comment_reason_timeout_exits_1():
    client = StubClient(
        get_latest_run=_sequence(qr.RunInfo(run_id="1", status="in_progress")),
        get_run=_sequence("in_progress"),   # never completes
    )
    code, clock = _run(client, budget_s=90, poll_interval_s=30)
    assert code == 1
    assert len(client.comments) == 1 and "timeout" in client.comments[0]
    assert clock.t >= 90


def test_already_fresh_skips_the_post_exits_0_no_comment_no_rerun_spent():
    client = StubClient(get_recheck_run_created_at=_sequence(_FRESH_CREATED_AT))
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []
    assert client.request_rerun.calls == 0


# ---- failure-handling rows (review round 3): every client call raises or returns, never a silent stand-in ----

def test_get_latest_run_raises_is_retried_never_read_as_no_run():
    client = StubClient(get_latest_run=_sequence(qr.RecheckApiError("boom"),
                                                 qr.RunInfo(run_id="1", status="completed")))
    code, _ = _run(client)
    assert code == 0
    assert client.comments == []


def test_get_latest_run_keeps_failing_until_the_budget_runs_out_posts_comment_reason_error_not_exit_0():
    client = StubClient(get_latest_run=_sequence(qr.RecheckApiError("boom")))
    code, clock = _run(client, budget_s=90, poll_interval_s=30)
    assert code == 1
    assert len(client.comments) == 1 and "error" in client.comments[0]
    assert clock.t >= 90


def test_get_run_error_during_step_2_is_retried_comment_when_budget_runs_out():
    client = StubClient(
        get_latest_run=_sequence(qr.RunInfo(run_id="1", status="in_progress")),
        get_run=_sequence(qr.RecheckApiError("boom")),
    )
    code, _ = _run(client, budget_s=90, poll_interval_s=30)
    assert code == 1
    assert len(client.comments) == 1 and "error" in client.comments[0]


def test_get_job_error_is_retried_like_any_other_step_3_failure():
    client = StubClient(get_job=_sequence(qr.RecheckApiError("boom")))
    code, _ = _run(client, budget_s=90, poll_interval_s=30)
    assert code == 1
    assert len(client.comments) == 1 and "error" in client.comments[0]


def test_get_job_succeeding_with_no_traceability_job_comments_at_once_no_retry_spent():
    client = StubClient(get_job=_sequence(None))
    code, clock = _run(client, budget_s=90, poll_interval_s=30)
    assert code == 1
    assert len(client.comments) == 1 and "error" in client.comments[0]
    assert client.get_job.calls == 1
    assert clock.t == 0   # no sleep spent: a completed run with no job is not transient


def test_get_recheck_run_created_at_error_is_retried_post_still_sent_once_it_succeeds():
    client = StubClient(get_recheck_run_created_at=_sequence(qr.RecheckApiError("boom"), _STALE_CREATED_AT))
    code, _ = _run(client)
    assert code == 0
    assert client.request_rerun.calls == 1   # the rerun request was never skipped


@pytest.mark.parametrize("created_at", [None, "", "not a timestamp"])
def test_already_fresh_given_a_missing_or_unparsable_timestamp_sends_the_post(created_at):
    client = StubClient(get_recheck_run_created_at=_sequence(created_at))
    code, _ = _run(client)
    assert code == 0
    assert client.request_rerun.calls == 1


def test_an_uncaught_exception_anywhere_still_posts_the_comment_before_exit_1():
    client = StubClient(get_job=_sequence(ValueError("a real bug, not RecheckApiError")))
    code, _ = _run(client)
    assert code == 1
    assert len(client.comments) == 1 and "error" in client.comments[0]


def test_the_comment_post_is_retried_once_before_giving_up():
    client = StubClient(get_run=_sequence("completed"), request_rerun=_sequence("refused"),
                        post_comment_fails=1)
    code, _ = _run(client)
    assert code == 1
    assert client.comments == ["The `traceability` check's result for this commit may be stale (reason: "
                                "refused - the re-run request was refused and no new attempt started). "
                                "Refresh it with a push, or a manual re-run of the `traceability` job. Do not "
                                "merge before a `traceability` attempt that started after this comment has "
                                "passed - a push, a manual re-run, or a later automatic recheck re-run all "
                                "count."]


def test_the_comment_post_failing_twice_still_exits_1_without_raising():
    client = StubClient(get_run=_sequence("completed"), request_rerun=_sequence("refused"),
                        post_comment_fails=2)
    code, _ = _run(client)
    assert code == 1
    assert client.comments == []


# ---- RecheckApiClient: the real client, subprocess.run monkeypatched (review findings 2 and 6) ----

class _Done:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _client() -> qr.RecheckApiClient:
    return qr.RecheckApiClient("o/r", "51", "777")


def test_request_rerun_201_is_accepted(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0))
    assert _client().request_rerun("9") == "accepted"


def test_request_rerun_403_is_refused(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run",
                        lambda *a, **k: _Done(1, stderr="gh: This workflow is already running (HTTP 403)"))
    assert _client().request_rerun("9") == "refused"


@pytest.mark.parametrize("stderr", ["gh: Bad Gateway (HTTP 502)", "error connecting to api.github.com",
                                    "gh: Not Found (HTTP 404)"])
def test_request_rerun_anything_else_raises(monkeypatch, stderr):
    # Finding 2: the endpoint documents only 201 and 403; a 5xx, a network error, 401/404/422 etc. must raise
    # RecheckApiError (retried as run_status="error"), never be read as "refused".
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(1, stderr=stderr))
    with pytest.raises(qr.RecheckApiError):
        _client().request_rerun("9")


def test_request_rerun_timeout_raises(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise qr.subprocess.TimeoutExpired(cmd="gh", timeout=30)
    monkeypatch.setattr(qr.subprocess, "run", raise_timeout)
    with pytest.raises(qr.RecheckApiError):
        _client().request_rerun("9")


@pytest.mark.parametrize("stdout", [
    "[]",                                     # a JSON array, not an object
    "{}",                                     # an object without workflow_runs
    '{"workflow_runs": null}',                # workflow_runs present but null
    '{"workflow_runs": [{"id": 5}]}',         # a run entry missing status
])
def test_get_latest_run_raises_on_a_malformed_2xx_body(monkeypatch, stdout):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, stdout))
    with pytest.raises(qr.RecheckApiError):
        _client().get_latest_run("abc")


def test_get_latest_run_returns_none_for_a_genuinely_empty_list(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, '{"workflow_runs": []}'))
    assert _client().get_latest_run("abc") is None


def test_get_latest_run_parses_a_well_formed_run(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run",
                        lambda *a, **k: _Done(0, '{"workflow_runs": [{"id": 5, "status": "completed"}]}'))
    assert _client().get_latest_run("abc") == qr.RunInfo(run_id="5", status="completed")


@pytest.mark.parametrize("stdout", ["[]", "{}"])
def test_get_run_raises_on_a_malformed_2xx_body(monkeypatch, stdout):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, stdout))
    with pytest.raises(qr.RecheckApiError):
        _client().get_run("5")


def test_get_run_parses_status(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, '{"status": "in_progress"}'))
    assert _client().get_run("5") == "in_progress"


@pytest.mark.parametrize("stdout", ["[]", "{}"])
def test_get_job_raises_on_a_malformed_2xx_body(monkeypatch, stdout):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, stdout))
    with pytest.raises(qr.RecheckApiError):
        _client().get_job("5", "traceability")


def test_get_job_returns_none_for_a_genuinely_missing_job(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run",
                        lambda *a, **k: _Done(0, json.dumps({"jobs": [{"id": 9, "name": "quality"}]})))
    assert _client().get_job("5", "traceability") is None


def test_get_job_parses_a_matching_job(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(
        0, json.dumps({"jobs": [{"id": 9, "name": "traceability", "started_at": "x"}]})))
    assert _client().get_job("5", "traceability") == qr.JobInfo(job_id="9", started_at="x")


def test_get_recheck_run_created_at_raises_on_a_malformed_2xx_body(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, "{}"))
    with pytest.raises(qr.RecheckApiError):
        _client().get_recheck_run_created_at()


def test_get_recheck_run_created_at_parses_a_well_formed_body(monkeypatch):
    monkeypatch.setattr(qr.subprocess, "run", lambda *a, **k: _Done(0, '{"created_at": "2026-11-24T10:00:00Z"}'))
    assert _client().get_recheck_run_created_at() == "2026-11-24T10:00:00Z"
