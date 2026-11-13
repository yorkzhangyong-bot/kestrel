"""A shared retry for the model HTTP calls: transient statuses, bounded by the run's deadline (FR-013/FR-016).

The attacker and the judge each make one OpenAI-compatible POST per call. A 429 or a 5xx (500/502/503/504) is
usually transient, so ``post_with_retry`` retries up to ``RETRY_ATTEMPTS`` times with exponential backoff and
jitter, honouring a ``Retry-After`` header, but never sleeping past what is left of the run's deadline. The tokens
every attempt reports are summed, so a retry can't hide spend from the run's token budget (R7). Any ``httpx``
transport error propagates unchanged — both clients already turn that into their own "unreachable" error. Feature 010:
the result also counts the attempts and sums each usage kind the provider reported, for the model-request line.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 3
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 8.0


@dataclass(frozen=True)
class RetryResult:
    response: httpx.Response
    tokens: int   # summed usage tokens across every attempt, retried ones included (R7)
    # Feature 010 (FR-003): the HTTP posts made, and each usage kind summed over the attempts that reported it —
    # None when no attempt did (`tokens` keeps its integer budget meaning, 0 when nothing was reported).
    attempts: int = 1
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


USAGE_KINDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _usage(response: httpx.Response) -> dict[str, int]:
    """The usage counts a JSON body reports, by kind; empty when the body is missing, non-JSON, or has no usage."""
    try:
        body = response.json()
    except (ValueError, TypeError):
        return {}
    if not isinstance(body, dict) or not isinstance(body.get("usage"), dict):
        return {}
    counts: dict[str, int] = {}
    for kind in USAGE_KINDS:
        value = body["usage"].get(kind)
        if value is None:
            continue
        try:
            counts[kind] = int(value)
        except (TypeError, ValueError):
            continue
    return counts



def _retry_after_s(response: httpx.Response) -> float | None:
    """The ``Retry-After`` delay in seconds, when given as a number; an HTTP-date form falls back to backoff."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff_s(attempt: int, rng: Callable[[], float]) -> float:
    """Exponential backoff with full jitter for a 1-based attempt number."""
    ceiling = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** (attempt - 1)))
    return rng() * ceiling


async def post_with_retry(http: httpx.AsyncClient, url: str, *, json: dict, headers: dict,
                          attempts: int = RETRY_ATTEMPTS, remaining: Callable[[], float] | None = None,
                          sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                          rng: Callable[[], float] = random.random) -> RetryResult:
    """POST ``json`` to ``url``, retrying a transient status up to ``attempts`` times.

    Returns the final response — which may still carry an error status, so the caller decides what a non-200
    means — and the tokens summed over every attempt. ``remaining()`` returns the seconds left in the run's
    deadline; a backoff that would overrun it is skipped (we return the transient response and let the caller
    fail) rather than blowing the deadline.
    """
    tokens = 0
    made = 0
    usage: dict[str, int] = {}
    response: httpx.Response | None = None
    for attempt in range(1, attempts + 1):
        response = await http.post(url, json=json, headers=headers)
        made = attempt
        reported = _usage(response)
        tokens += reported.get("total_tokens", 0)
        for kind, value in reported.items():
            usage[kind] = usage.get(kind, 0) + value
        if response.status_code not in RETRYABLE_STATUSES or attempt == attempts:
            break
        wait = _retry_after_s(response)
        if wait is None:
            wait = _backoff_s(attempt, rng)
        if remaining is not None:
            left = remaining()
            if left <= 0 or wait >= left:
                break
        await sleep(wait)
    assert response is not None  # the loop always runs at least once
    return RetryResult(response=response, tokens=tokens, attempts=made, prompt_tokens=usage.get("prompt_tokens"),
                       completion_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"))
