"""One connection test: guard, send, name the outcome, mask, cut, log one line (research R1, R2, R9)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from kestrel.connection.address_guard import Resolver, default_resolver, is_allowed
from kestrel.connection.response_path import PathNotFound, extract
from kestrel.connection.template import build_request
from kestrel.secrets import mask_values

log = logging.getLogger("kestrel.connection")

GREETING = "Hello"
USER_AGENT = "Kestrel/0.1 (connection test)"
TOO_LARGE = "Response larger than 1 MB"

# Kestrel's own wording, shown with st.success / st.error (contracts/kestrel-api.md).
MESSAGES = {
    "success": "Connection works.",
    "address_not_allowed": "This address is on a local or private network. Such addresses only work when Kestrel "
                           "runs on your own machine.",
    "credentials_unreadable": "The stored auth headers can't be read with the current encryption key. Re-enter "
                              "them, or restore the old key.",
    "unreachable": "Kestrel couldn't connect to this URL.",
    "timed_out": "The agent didn't answer within 60 seconds.",
    "auth_rejected": "The agent refused the request as unauthorized. Check the auth headers.",
    "endpoint_error": "The endpoint answered with an error.",
    "non_json": "The endpoint answered, but not with JSON.",
    "path_not_found": "Response path not found in the agent's reply.",
    "not_text": "The response path points to something that isn't text.",
}


@dataclass(frozen=True)
class ResolvedSettings:
    """Connection settings with every header value known (kept values already looked up)."""
    url: str
    method: str
    headers: tuple[tuple[str, str], ...]
    body_template: str
    response_path: str

    def __repr__(self) -> str:  # header values never appear in a repr, log or traceback (research R9)
        names = [name for name, _ in self.headers]
        return (f"ResolvedSettings(url={_loggable_url(self.url)!r}, method={self.method!r}, header_names={names!r}, "
                f"response_path={self.response_path!r})")


@dataclass
class TestOutcome:
    ok: bool
    step: str
    message: str
    detail: str | None = None
    status_code: int | None = None
    reply_text: str | None = None
    reply_truncated: bool = False
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def outcome(step: str, *, detail: str | None = None, status: int | None = None) -> TestOutcome:
    return TestOutcome(ok=step == "success", step=step, message=MESSAGES[step], detail=detail, status_code=status)


async def run_test(settings: ResolvedSettings, *, mode: str, display_name: str = "",
                   transport: httpx.AsyncBaseTransport | None = None, resolver: Resolver = default_resolver,
                   deadline_s: float = 60.0, connect_timeout_s: float = 10.0, max_bytes: int = 1_048_576,
                   max_reply_chars: int = 2000) -> TestOutcome:
    started = time.perf_counter()
    result = await _run(settings, mode, transport, resolver, deadline_s, connect_timeout_s, max_bytes)

    secrets = [value for _, value in settings.headers]
    if result.detail is not None:
        result.detail = mask_values(result.detail, secrets)
    if result.reply_text is not None:
        reply = mask_values(result.reply_text, secrets)  # mask before cutting, so no value is half shown
        result.reply_truncated = len(reply) > max_reply_chars
        result.reply_text = reply[:max_reply_chars]
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    _log(result, settings, display_name)
    return result


def refused(step: str, settings: ResolvedSettings, display_name: str = "") -> TestOutcome:
    """An outcome decided before anything is sent (for example credentials_unreadable), logged like any test."""
    result = outcome(step)
    _log(result, settings, display_name)
    return result


def _log(result: TestOutcome, settings: ResolvedSettings, display_name: str) -> None:
    log.info("connection test target=%r url=%r method=%s step=%s status=%s duration_ms=%d",
             display_name or "(unsaved)", _loggable_url(settings.url), settings.method, result.step,
             result.status_code if result.status_code is not None else "-", result.duration_ms)


async def _run(settings: ResolvedSettings, mode: str, transport: httpx.AsyncBaseTransport | None, resolver: Resolver,
               deadline_s: float, connect_timeout_s: float, max_bytes: int) -> TestOutcome:
    if not await asyncio.to_thread(is_allowed, settings.url, mode, resolver):
        return outcome("address_not_allowed")

    url, body = build_request(settings.method, settings.url, settings.body_template, GREETING)
    headers = dict(settings.headers)
    lower = {name.lower() for name in headers}
    if body is not None and "content-type" not in lower:
        headers["Content-Type"] = "application/json"
    if "user-agent" not in lower:
        headers["User-Agent"] = USER_AGENT

    timeout = httpx.Timeout(deadline_s, connect=connect_timeout_s)
    try:
        async with asyncio.timeout(deadline_s):
            async with httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=timeout) as client:
                async with client.stream(settings.method, url, headers=headers, content=body) as response:
                    status = response.status_code
                    if status in (401, 403):
                        return outcome("auth_rejected", detail=f"Status {status}", status=status)
                    if 300 <= status < 400:
                        location = response.headers.get("location", "")
                        return outcome("endpoint_error", status=status,
                                       detail=f"Status {status}, redirect to {location}; Kestrel doesn't follow "
                                              f"redirects, so use the final URL")
                    if not 200 <= status < 300:
                        return outcome("endpoint_error", detail=f"Status {status}", status=status)
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > max_bytes:
                        return outcome("endpoint_error", detail=TOO_LARGE, status=status)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > max_bytes:
                            return outcome("endpoint_error", detail=TOO_LARGE, status=status)
    except TimeoutError:
        return outcome("timed_out")
    except httpx.ConnectTimeout:
        return outcome("unreachable", detail="The connection timed out")
    except httpx.TimeoutException:
        return outcome("timed_out")
    except httpx.TransportError as error:
        return outcome("unreachable", detail=_error_kind(error))

    try:
        document = json.loads(bytes(raw))
    except ValueError:
        return outcome("non_json", status=status)
    try:
        value = extract(document, settings.response_path)
    except PathNotFound:
        return outcome("path_not_found", status=status)
    if not isinstance(value, str):
        return outcome("not_text", detail=f"Found: {_json_type(value)}", status=status)
    result = outcome("success", status=status)
    result.reply_text = value
    return result


def _error_kind(error: Exception) -> str:
    text = str(error).strip() or type(error).__name__
    return text[:300]


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    return "object"


def _loggable_url(url: str) -> str:
    """Scheme, host, port and path only: never the query string or user info (research R9)."""
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]
    return f"{parts.scheme}://{host}{parts.path}"
