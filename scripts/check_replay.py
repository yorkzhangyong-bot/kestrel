"""CI gate for regression replay (feature 012, contracts/ci-script.md): calls a running Kestrel API's
batch-replay endpoint for one target and turns the result into a process exit code a CI pipeline can gate on.

A standalone script: httpx and the standard library only, no import of kestrel's backend package or ui/
(research D13) - it talks to the API exactly the way the UI does.

Run it from anywhere the API is reachable:

    uv run python scripts/check_replay.py --target-id TARGET_ID

Exit codes:
  0 - the batch completed and every entry is fixed, or the target had nothing replayable.
  1 - at least one entry is still vulnerable, whether or not the batch completed - wins over every other case.
  2 - could not conclude the target is fixed: a completed batch with at least one inconclusive entry, or a
      batch that did not complete for any reason (an incomplete result is never scored as a pass).
  3 - a usage problem or an API-level failure: the API unreachable, an unknown target, or the batch refused for
      a precondition (permission, terms, the batch-size cap, or another run already in progress).

Never prints attack text, reply text, the target's URL, or a header value.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"


def base_url() -> str:
    return os.environ.get("KESTREL_API_URL", DEFAULT_API_URL).rstrip("/")


def headers() -> dict[str, str]:
    token = os.environ.get("KESTREL_API_TOKEN", "").strip()
    return {"X-Kestrel-Token": token} if token else {}


def default_timeout(config: dict[str, Any]) -> float:
    """`cap * per_replay_time_limit_s + 60` (research D13): the batch is synchronous and can legitimately run
    for as long as the cap's worth of replays, far beyond httpx's 5s default."""
    replay = config["replay"]
    return replay["max_batch_runs"] * replay["per_replay_time_limit_s"] + 60


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = (body.get("error") or {}).get("message")
    return message or f"HTTP {response.status_code}."


def _evidence(hard_evidence: bool) -> str:
    return "canary" if hard_evidence else "judge"


def _entry_line(entry: dict[str, Any], *, is_crashed: bool) -> str:
    source_evidence = _evidence(entry["source_hard_evidence"])
    replay_evidence = "none" if is_crashed else _evidence(entry["replay_hard_evidence"])
    return (f"run {entry['source_run_id']} -> replay {entry['replay_run_id']}: {entry['family']}: "
           f"{entry['outcome']} (source: {source_evidence}, replay: {replay_evidence})")


def _summary_line(result: dict[str, Any]) -> str:
    counts = result["counts"]
    entries = result["entries"]
    not_replayed = result["not_replayed_source_ids"]
    if result["complete"]:
        return (f"{len(entries)} replays, complete: {counts['fixed']} fixed, {counts['still_vulnerable']} "
               f"still_vulnerable, {counts['inconclusive']} inconclusive")
    total = len(entries) + len(not_replayed)
    runs = ", ".join(str(i) for i in not_replayed)
    return (f"batch stopped early ({result['stop_reason']}): {len(entries)} of {total} replayed, "
           f"{len(not_replayed)} not replayed (runs {runs})")


def _exit_code(result: dict[str, Any]) -> int:
    counts = result["counts"]
    if counts["still_vulnerable"] > 0:
        return 1
    if not result["complete"]:
        return 2
    if counts["inconclusive"] > 0:
        return 2
    return 0


def check(target_id: int, *, timeout: float | None = None, client: httpx.Client | None = None,
         out=sys.stdout, err=sys.stderr) -> int:
    """`client` is injectable (a `transport=httpx.MockTransport(...)`-backed one for tests); production builds
    its own, against the real network."""
    url, auth = base_url(), headers()
    owns_client = client is None
    client = client or httpx.Client()
    try:
        try:
            config_response = client.get(f"{url}/api/config", headers=auth, timeout=30.0)
        except httpx.HTTPError as error:
            print(f"Could not reach the Kestrel API at {url!r}: {type(error).__name__}.", file=err)
            return 3
        if config_response.status_code >= 400:
            print(_error_message(config_response), file=err)
            return 3
        config = config_response.json()

        batch_timeout = timeout if timeout is not None else default_timeout(config)
        try:
            response = client.post(f"{url}/api/targets/{target_id}/replays", headers=auth, timeout=batch_timeout)
        except httpx.HTTPError as error:
            print(f"Could not reach the Kestrel API at {url!r}: {type(error).__name__}.", file=err)
            return 3
        if response.status_code >= 400:
            print(_error_message(response), file=err)
            return 3

        result = response.json()
        entries = result["entries"]
        crashed_index = len(entries) - 1 if (not result["complete"] and result["stop_reason"] == "replay_failed"
                                             and entries) else None
        for index, entry in enumerate(entries):
            print(_entry_line(entry, is_crashed=index == crashed_index), file=out)
        print(_summary_line(result), file=out)
        return _exit_code(result)
    except Exception as error:
        # Anything unexpected - a pre-012 API with no "replay" config key, a non-JSON or malformed 2xx body, an
        # invalid KESTREL_API_URL (httpx.InvalidURL is not an httpx.HTTPError, so it would otherwise slip past
        # every catch above) - must exit 3, never Python's default 1, which this script reserves for "still
        # vulnerable" (FR-036). The class name only: never the response body or the URL.
        print(f"Unexpected error: {type(error).__name__}.", file=err)
        return 3
    finally:
        if owns_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-replay a target's past findings through a running Kestrel API and exit non-zero if "
                    "any is still vulnerable (or the result could not be determined).",
        epilog="Exit codes: 0 all fixed or nothing to replay; 1 at least one still vulnerable (wins over "
              "everything else); 2 could not conclude the target is fixed (an inconclusive entry, or an "
              "incomplete batch); 3 a usage or API-level error (unreachable API, unknown target, or the batch "
              "refused for a precondition, including the batch-size cap).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-id", type=int, required=True, help="the target to batch-replay")
    parser.add_argument("--timeout", type=float, default=None,
                        help="override the batch call's HTTP timeout in seconds (default: "
                             "max_batch_runs x per_replay_time_limit_s + 60, from GET /api/config)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        # argparse exits 0 for --help (kept as-is) and 2 for a usage error (missing/invalid --target-id); FR-036
        # reserves this script's own usage/API-error code for 3, not argparse's default.
        return 0 if error.code == 0 else 3
    return check(args.target_id, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
