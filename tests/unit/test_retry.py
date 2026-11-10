"""The shared HTTP retry: transient statuses, backoff bounded by the deadline, tokens summed (FR-013/FR-016)."""
import asyncio

import httpx
import pytest

from kestrel.retry import RETRY_ATTEMPTS, RETRYABLE_STATUSES, post_with_retry

FEATURE = "003"
# Also traces feature 008 (hardening): 008/FR-009 (retry transient statuses), 008/FR-010 (deadline, tokens).


async def _noop(_delay: float) -> None:   # never actually sleep in tests
    return None


def run(handler, *, sleep=_noop, **kwargs):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await post_with_retry(http, "https://m.test/v1/chat/completions",
                                         json={"x": 1}, headers={}, sleep=sleep, **kwargs)
    return asyncio.run(go())


def test_a_200_is_returned_without_retrying():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 7}})
    result = run(handler)
    assert result.response.status_code == 200 and result.tokens == 7 and len(calls) == 1


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
def test_a_transient_status_is_retried_up_to_the_cap_and_tokens_are_summed(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"usage": {"total_tokens": 2}})
    result = run(handler)
    assert len(calls) == RETRY_ATTEMPTS            # three attempts in all
    assert result.response.status_code == status   # still failing; the caller decides what that means
    assert result.tokens == 2 * RETRY_ATTEMPTS     # every attempt's tokens count toward the budget


def test_a_non_retryable_status_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={})
    result = run(handler)
    assert len(calls) == 1 and result.response.status_code == 400


def test_a_retry_that_succeeds_returns_the_good_response_with_summed_tokens():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"usage": {"total_tokens": 1}})
        return httpx.Response(200, json={"usage": {"total_tokens": 5}})
    result = run(handler)
    assert len(calls) == 2 and result.response.status_code == 200 and result.tokens == 6


def test_no_time_left_in_the_deadline_stops_after_the_first_attempt():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={})
    result = run(handler, remaining=lambda: 0.0)
    assert len(calls) == 1 and result.response.status_code == 503


def test_retry_after_longer_than_the_deadline_stops_early():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "100"}, json={})
    run(handler, remaining=lambda: 1.0)   # a 100s wait won't fit in 1s left
    assert len(calls) == 1


def test_retry_after_is_used_as_the_backoff_delay():
    waits: list[float] = []

    async def record(delay):
        waits.append(delay)

    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json={})
    run(handler, sleep=record)
    assert waits and waits[0] == 2.0
