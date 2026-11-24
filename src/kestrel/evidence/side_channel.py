"""The side channel a cooperating target exposes (feature 013, FR-019 to FR-026, FR-032 to FR-034, FR-071;
`contracts/side-channel.md`; research D7).

Three read-only GETs under one base URL — the descriptor the connection test checks, the tool-call log read by
correlation id, and the protected-state snapshot — every one bounded the same way: through the address guard in
hosted mode, with the configured auth header, no body, no redirects, a 1 MiB cap and the configured timeout.
Every failure is one of six named steps (`STEPS`), raised as `SideChannelUnavailable(step)`; the connection test
turns the same step into its exact message (`MESSAGES`). A stored auth header the current key cannot decrypt is
the `side_channel_header_unreadable` step **before** anything is sent (FR-071). Nothing here is logged with a URL,
a header value, a tool argument or a state value: the caller emits the catalogued lines with the step only.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from kestrel.connection.address_guard import Resolver, default_resolver, is_allowed
from kestrel.connection.tester import TestOutcome
from kestrel.store import ResolvedSideChannel

__all__ = ["CHECKED_MESSAGE", "MESSAGES", "STEPS", "ResolvedSideChannel", "SideChannelClient",
           "SideChannelUnavailable", "ToolCall", "check_side_channel", "find_strings"]

USER_AGENT = "Kestrel/0.1 (side channel)"
MAX_BYTES = 1_048_576
DESCRIPTOR_VERSION = 1
REQUIRED_CAPABILITIES = ("tool_calls", "state")

STEPS = ("side_channel_address_not_allowed", "side_channel_unreachable", "side_channel_auth_rejected",
         "side_channel_timed_out", "side_channel_invalid", "side_channel_header_unreadable")
# Kestrel's own wording (contracts/api.md); the timeout message is formatted with the configured timeout.
MESSAGES = {
    "side_channel_address_not_allowed": "The side-channel address is on a local or private network. Such addresses "
                                        "only work when Kestrel runs on your own machine.",
    "side_channel_unreachable": "Kestrel couldn't connect to the side-channel URL.",
    "side_channel_auth_rejected": "The side channel refused the request as unauthorized. Check its auth header.",
    "side_channel_timed_out": "The side channel didn't answer within {n} seconds.",
    "side_channel_invalid": "The side channel answered, but not with the shape Kestrel expects.",
    "side_channel_header_unreadable": "The stored side-channel auth header can't be read with the current "
                                      "encryption key. Re-enter it, or restore the old key.",
}
CHECKED_MESSAGE = "Side channel checked."


class SideChannelUnavailable(Exception):
    """A side-channel request failed; `step` is one of `STEPS` (FR-021, FR-034)."""

    def __init__(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown side-channel step {step!r}")
        super().__init__(step)
        self.step = step


@dataclass(frozen=True)
class ToolCall:
    """One recorded tool call of a run (contracts/side-channel.md): `seq` is the de-duplication key (FR-024) and
    `arguments` is searched for canaries as decoded strings, never as a JSON rendering (FR-026)."""
    seq: int
    name: str
    arguments: dict[str, Any]


def message_for(step: str, timeout_s: float | int) -> str:
    """The exact message of a step, with the configured timeout substituted where the text carries it."""
    n = int(timeout_s) if float(timeout_s).is_integer() else timeout_s
    return MESSAGES[step].format(n=n)


class SideChannelClient:
    """The three bounded GETs of the contract, over one resolved side channel."""

    def __init__(self, resolved: ResolvedSideChannel, *, mode: str, transport: Any = None,
                 resolver: Resolver = default_resolver, timeout_s: float = 10.0) -> None:
        self._resolved = resolved
        self._mode = mode
        self._transport = transport
        self._resolver = resolver
        self._timeout_s = float(timeout_s)

    @property
    def honeypot_tool(self) -> str | None:
        return self._resolved.honeypot_tool

    @property
    def header_value(self) -> str | None:
        """The decrypted auth value, for the run's mask list (FR-071); None without a header or when unreadable."""
        return None if self._resolved.header is None else self._resolved.header[1]

    async def describe(self) -> dict[str, Any]:
        """`GET {base}/describe`: the descriptor, refused as `side_channel_invalid` unless it carries
        `kestrel_side_channel: 1` and both capabilities."""
        document = await self._get("describe")
        if (not isinstance(document, dict) or document.get("kestrel_side_channel") != DESCRIPTOR_VERSION
                or not isinstance(document.get("capabilities"), list)
                or any(c not in document["capabilities"] for c in REQUIRED_CAPABILITIES)):
            raise SideChannelUnavailable("side_channel_invalid")
        return document

    async def tool_calls(self, correlation_id: str) -> list[ToolCall]:
        """`GET {base}/tool-calls?correlation_id=…`: every call recorded under the id, in the log's own order."""
        document = await self._get("tool-calls", params={"correlation_id": correlation_id})
        if not isinstance(document, dict) or not isinstance(document.get("calls"), list):
            raise SideChannelUnavailable("side_channel_invalid")
        calls = []
        for entry in document["calls"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("seq"), int) or isinstance(entry.get("seq"), bool):
                raise SideChannelUnavailable("side_channel_invalid")
            arguments = entry.get("arguments")
            calls.append(ToolCall(seq=entry["seq"], name=str(entry.get("name", "")),
                                  arguments=arguments if isinstance(arguments, dict) else {}))
        return calls

    async def state(self) -> dict[str, Any]:
        """`GET {base}/state`: the protected-state snapshot, an object whose values Kestrel treats as opaque."""
        document = await self._get("state")
        if not isinstance(document, dict) or not isinstance(document.get("state"), dict):
            raise SideChannelUnavailable("side_channel_invalid")
        return document["state"]

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        if self._resolved.header_unreadable:
            raise SideChannelUnavailable("side_channel_header_unreadable")   # never a request without the header
        url = f"{self._resolved.url.rstrip('/')}/{path}"
        if not await asyncio.to_thread(is_allowed, url, self._mode, self._resolver):
            raise SideChannelUnavailable("side_channel_address_not_allowed")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self._resolved.header is not None and self._resolved.header[1] is not None:
            headers[self._resolved.header[0]] = self._resolved.header[1]
        timeout = httpx.Timeout(self._timeout_s, connect=min(10.0, self._timeout_s))
        try:
            async with asyncio.timeout(self._timeout_s):
                async with httpx.AsyncClient(transport=self._transport, follow_redirects=False,
                                             timeout=timeout) as client:
                    async with client.stream("GET", url, headers=headers, params=params) as response:
                        status = response.status_code
                        if status in (401, 403):
                            raise SideChannelUnavailable("side_channel_auth_rejected")
                        if not 200 <= status < 300:
                            raise SideChannelUnavailable("side_channel_invalid")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_BYTES:
                                raise SideChannelUnavailable("side_channel_invalid")
        except SideChannelUnavailable:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise SideChannelUnavailable("side_channel_timed_out") from None
        except httpx.TransportError:
            raise SideChannelUnavailable("side_channel_unreachable") from None
        try:
            return json.loads(bytes(raw))
        except ValueError:
            raise SideChannelUnavailable("side_channel_invalid") from None


async def check_side_channel(resolved: ResolvedSideChannel, *, mode: str, transport: Any = None,
                             resolver: Resolver = default_resolver, timeout_s: float = 10.0) -> TestOutcome:
    """The connection test's side-channel half (FR-021): one `describe`, answered as a `TestOutcome` whose step
    and message are the contract's - `success` with `CHECKED_MESSAGE`, or one of the six steps with its exact
    message, the timeout one carrying the configured value."""
    client = SideChannelClient(resolved, mode=mode, transport=transport, resolver=resolver, timeout_s=timeout_s)
    try:
        await client.describe()
    except SideChannelUnavailable as error:
        return TestOutcome(ok=False, step=error.step, message=message_for(error.step, timeout_s))
    return TestOutcome(ok=True, step="success", message=CHECKED_MESSAGE)


def find_strings(value: Any):
    """Every decoded string inside a JSON value, recursively (FR-026): each string itself, and every string nested
    in a list or an object - never a JSON rendering, so a quotation mark, a backslash or a non-ASCII character in
    a canary is matched as the character it is."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for inner in value.values():
            yield from find_strings(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from find_strings(inner)
