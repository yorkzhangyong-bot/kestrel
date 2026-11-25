#!/usr/bin/env python3
"""Recheck workflow step machine (feature 006, FR-019): re-runs the `traceability` job of the newest `qa.yml`
run for the current commit, so a pull-request body edit or a `refactor`/`bugfix` label change is re-evaluated
without a push, while `quality` and `review` keep their results. Run by `.github/workflows/qa-recheck.yml` after
`actions/checkout` and `actions/setup-python`, on a relevant event only (contracts/pr-rules.md "Recheck workflow").

Steps (contracts/pr-rules.md "Recheck script"):
  1. Find the newest `qa.yml` run for the pull request's head SHA.
  2. Wait until that run is `completed` (poll every 30 s).
  3. Find its `traceability` job.
  4. Skip the re-run if that job's latest attempt already started after this recheck run began (`already_fresh`);
     otherwise request a re-run. A refusal gets one immediate re-read of the run: not yet `completed` means
     another attempt is in progress (resume polling); still `completed` means the refusal is final.
  5. On anything that cannot be refreshed - no job, a final refusal, the 30-minute budget exhausted, or a
     client call that keeps failing - post one fixed-text pull-request comment naming only the reason class
     (`timeout`, `refused`, or `error`) and exit 1. Never prints or echoes the description or a label value.

Every API call in `RecheckApiClient` returns its declared value or raises `RecheckApiError` after its own
timeout: `get_latest_run`'s `None` and `get_job`'s `None` each mean only a genuine, successful empty result,
never a failure standing in for one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime

_GH_TIMEOUT_S = 30
_POLL_INTERVAL_S = 30
_BUDGET_S = 1800   # 30 minutes (steps 2-4; a failing step 1 is retried within the same budget)
_TRACEABILITY_JOB = "traceability"

_COMMENT_TEXT = {
    "timeout": "the recheck's 30-minute budget ran out while waiting for the QA run or a re-run attempt",
    "refused": "the re-run request was refused and no new attempt started",
    "error": "a GitHub API call kept failing",
}


class RecheckApiError(Exception):
    """Any client-call failure (a non-zero `gh` exit, a timeout, invalid JSON, no `gh` on the path, any other
    exception). Never a silent `None`/empty value standing in for one."""


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    status: str


@dataclass(frozen=True)
class JobInfo:
    job_id: str
    started_at: str | None


NOT_STARTED = ("action_required", "waiting")


def next_action(run_status: str | None, rerun_status: str | None, elapsed: float, budget: int = _BUDGET_S) -> str:
    """The recheck's steps 1-5 as a pure state machine (contracts/pr-rules.md "Recheck workflow" /
    "Recheck script"). ``run_status``: ``None`` (no QA run for the SHA), the run's own status, ``"error"`` (a
    failed read of steps 1-3 or the post-refusal re-read: never read as "no run"), or ``"no_job"`` (step 3 found
    the run completed with no job named ``traceability``: not transient, nothing to retry toward).
    ``rerun_status``: ``None`` (not requested yet), ``"accepted"``, or ``"refused"`` (any cause - GitHub's job
    re-run endpoint documents only `201`/`403` and sends the same `403` whether another attempt is in progress or
    the refusal is final, so a refusal is classified by re-reading the run, never by that code).
    """
    if run_status == "no_job":
        return "fail-error"                                  # step 3: completed, but no job to rerun - no retry
    if run_status == "error":
        return "wait" if elapsed < budget else "fail-error"   # a failed read: retry, or give up at the budget
    if run_status is None or run_status in NOT_STARTED:
        return "exit-0-no-run"                                # step 1: nothing to refresh
    if rerun_status == "accepted":
        return "exit-0-done"                                  # step 4: accepted
    if elapsed >= budget:
        return "fail-timeout"                                 # the budget ran out (waiting or retrying)
    if run_status != "completed":
        return "wait"                                         # step 2, or step 4's post-refusal re-read: retry
    if rerun_status is None:
        return "rerun"                                        # step 4: request it
    return "fail-refused"                                     # fork token, the 50-re-run cap, or a final refusal


def already_fresh(attempt_started_at: str | None, recheck_created_at: str | None) -> bool:
    """Step 4's pre-check: ``True`` when the traceability job's latest attempt already started no earlier than
    this recheck run's own creation, so its live read already includes the triggering change - skip the re-run
    request and exit 0 rather than spend one of GitHub's 50 re-runs per workflow run on it. Never raises: a
    missing or unparsable timestamp for either argument means "not fresh", so the re-run request is sent rather
    than silently skipped on bad or absent data."""

    def parse(value: str | None) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    attempt, created = parse(attempt_started_at), parse(recheck_created_at)
    if attempt is None or created is None:
        return False
    return attempt >= created


def _post_stale_result_comment(client, reason: str) -> None:
    text = (f"The `traceability` check's result for this commit may be stale (reason: {reason} - "
            f"{_COMMENT_TEXT[reason]}). Refresh it with a push, or a manual re-run of the `traceability` job, "
            "before merging.")
    for attempt in range(2):   # the comment POST is retried once
        try:
            client.post_comment(text)
            return
        except RecheckApiError:
            if attempt == 1:
                print(f"Could not post the stale-result comment (reason: {reason}); see the run log.")


def _find_run(client, head_sha: str, elapsed, budget_s: int, sleep, poll_interval_s: int,
              give_up) -> tuple[str, str] | int:
    """Step 1: find the newest run for this head SHA. Retried only on a failed read - never on a status that
    simply is not yet "completed" (step 2's polling, via `get_run`, is what waits for that). Returns
    ``(run_id, status)`` on success, or the script's exit code (int) on a terminal outcome."""
    while True:
        try:
            info = client.get_latest_run(head_sha)
        except RecheckApiError:
            action = next_action("error", None, elapsed(), budget_s)
            if action == "fail-error":
                return give_up("error")
            sleep(poll_interval_s)
            continue
        if info is None or info.status in NOT_STARTED:
            print("No active QA run to refresh for this commit (none found, or it has not started for lack "
                  "of approval).")
            return 0
        return info.run_id, info.status


def _poll(fetch, elapsed, budget_s: int, sleep, poll_interval_s: int, rerun_status: str | None,
          give_up) -> str | int:
    """Repeatedly calls ``fetch() -> status`` (raising ``RecheckApiError`` on failure) and asks `next_action`
    what to do next, sleeping between attempts, until the run is ``"completed"`` (returns that string) or a
    terminal action is reached (returns the script's exit code)."""
    while True:
        try:
            status = fetch()
        except RecheckApiError:
            status = "error"
        action = next_action(status, rerun_status, elapsed(), budget_s)
        if action == "exit-0-no-run":
            print("No QA run to refresh for this commit (none found, or it has not started for lack of "
                  "approval); nothing to do.")
            return 0
        if action in ("fail-timeout", "fail-error", "fail-refused"):
            return give_up({"fail-timeout": "timeout", "fail-error": "error", "fail-refused": "refused"}[action])
        if action == "wait":
            sleep(poll_interval_s)
            continue
        return status   # action in ("rerun", "exit-0-done"): status is "completed"


def run_recheck(client, head_sha: str, *, budget_s: int = _BUDGET_S, poll_interval_s: int = _POLL_INTERVAL_S,
                 sleep=time.sleep, now=time.monotonic) -> int:
    """Drives steps 1-5 against ``client`` (an injected API client; see ``RecheckApiClient`` for the real one).
    Never raises: any exception the steps below do not already turn into a retry or an `"error"`/`"no_job"`
    outcome still reaches the stale-result comment before returning 1 (a defect in this script can never look
    like a silent, uncommented success)."""
    start = now()

    def elapsed() -> float:
        return now() - start

    def give_up(reason: str) -> int:
        _post_stale_result_comment(client, reason)
        return 1

    try:
        # ---- step 1: find the run (retried only on error) ----
        found = _find_run(client, head_sha, elapsed, budget_s, sleep, poll_interval_s, give_up)
        if isinstance(found, int):
            return found
        run_id, status = found

        # ---- step 2: poll until it completes ----
        if status != "completed":
            status = _poll(lambda: client.get_run(run_id), elapsed, budget_s, sleep, poll_interval_s, None,
                           give_up)
            if isinstance(status, int):
                return status

        # ---- step 3: find the traceability job; a genuine miss is not transient ----
        job_holder: list[JobInfo] = []

        def fetch_job() -> str:
            job = client.get_job(run_id, _TRACEABILITY_JOB)
            if job is None:
                return "no_job"
            job_holder.append(job)
            return "completed"

        result = _poll(fetch_job, elapsed, budget_s, sleep, poll_interval_s, None, give_up)
        if isinstance(result, int):
            return result
        job = job_holder[0]

        # ---- step 4a: the freshness pre-check; never skips the re-run request on bad data, only on a real one ----
        while True:
            try:
                recheck_created_at = client.get_recheck_run_created_at()
            except RecheckApiError:
                action = next_action("error", None, elapsed(), budget_s)
                if action == "fail-error":
                    return give_up("error")
                sleep(poll_interval_s)
                continue
            break
        if already_fresh(job.started_at, recheck_created_at):
            print("The traceability job's latest attempt already started after this recheck run; nothing to "
                  "refresh.")
            return 0

        # ---- step 4b: request the re-run; a refusal gets one immediate re-read, then back to polling or step 5 ----
        while True:
            try:
                rerun_status = client.request_rerun(job.job_id)
            except RecheckApiError:
                action = next_action("error", None, elapsed(), budget_s)
                if action == "fail-error":
                    return give_up("error")
                sleep(poll_interval_s)
                continue
            if rerun_status == "accepted":
                print("Re-run of the traceability job requested.")
                return 0
            try:
                reread_status = client.get_run(run_id)
            except RecheckApiError:
                reread_status = "error"
            action = next_action(reread_status, "refused", elapsed(), budget_s)
            if action == "exit-0-no-run":
                print("The QA run no longer exists or has not started; nothing to refresh.")
                return 0
            if action in ("fail-timeout", "fail-error", "fail-refused"):
                return give_up({"fail-timeout": "timeout", "fail-error": "error",
                                "fail-refused": "refused"}[action])
            # action == "wait": another attempt is now running - resume polling, then retry the re-run request
            result = _poll(lambda: client.get_run(run_id), elapsed, budget_s, sleep, poll_interval_s, None,
                           give_up)
            if isinstance(result, int):
                return result
            continue   # result == "completed": loop back and request the re-run again
    except Exception:
        return give_up("error")


class RecheckApiClient:
    """The real client: `gh api` / `gh pr comment`, each with its own timeout. Any failure raises
    `RecheckApiError` - never a silent `None`/empty value standing in for one."""

    def __init__(self, repository: str, pr_number: str, run_id: str, timeout_s: float = _GH_TIMEOUT_S) -> None:
        self._repository = repository
        self._pr_number = pr_number
        self._own_run_id = run_id
        self._timeout_s = timeout_s

    def _gh(self, *args: str) -> str:
        try:
            done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=self._timeout_s)
        except Exception as exc:
            raise RecheckApiError(f"{args[0]} call failed: {type(exc).__name__}") from exc
        if done.returncode != 0:
            raise RecheckApiError(f"gh exited {done.returncode} for {args[0]}")
        return done.stdout

    def _gh_json(self, *args: str):
        try:
            return json.loads(self._gh(*args))
        except ValueError as exc:
            raise RecheckApiError("invalid JSON from gh") from exc

    def get_latest_run(self, head_sha: str) -> RunInfo | None:
        data = self._gh_json("api", f"repos/{self._repository}/actions/workflows/qa.yml/runs"
                                    f"?head_sha={head_sha}&event=pull_request&per_page=1")
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if not runs:
            return None
        run = runs[0]
        return RunInfo(run_id=str(run["id"]), status=run["status"])

    def get_run(self, run_id: str) -> str:
        data = self._gh_json("api", f"repos/{self._repository}/actions/runs/{run_id}")
        return data["status"]

    def get_job(self, run_id: str, name: str) -> JobInfo | None:
        data = self._gh_json("api", f"repos/{self._repository}/actions/runs/{run_id}/jobs?filter=latest")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        for job in jobs or []:
            if job.get("name") == name:
                return JobInfo(job_id=str(job["id"]), started_at=job.get("started_at"))
        return None

    def get_recheck_run_created_at(self) -> str:
        data = self._gh_json("api", f"repos/{self._repository}/actions/runs/{self._own_run_id}")
        return data["created_at"]

    def request_rerun(self, job_id: str) -> str:
        try:
            done = subprocess.run(
                ["gh", "api", "--method", "POST", f"repos/{self._repository}/actions/jobs/{job_id}/rerun"],
                capture_output=True, text=True, timeout=self._timeout_s)
        except Exception as exc:
            raise RecheckApiError(f"rerun call failed: {type(exc).__name__}") from exc
        return "accepted" if done.returncode == 0 else "refused"

    def post_comment(self, text: str) -> None:
        try:
            done = subprocess.run(["gh", "pr", "comment", self._pr_number, "--repo", self._repository,
                                   "--body", text], capture_output=True, text=True, timeout=self._timeout_s)
        except Exception as exc:
            raise RecheckApiError(f"comment post failed: {type(exc).__name__}") from exc
        if done.returncode != 0:
            raise RecheckApiError(f"gh exited {done.returncode} posting the comment")


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    head_sha = os.environ.get("HEAD_SHA", "")
    own_run_id = os.environ.get("GITHUB_RUN_ID", "")
    client = RecheckApiClient(repository, pr_number, own_run_id)
    return run_recheck(client, head_sha)


if __name__ == "__main__":
    sys.exit(main())
