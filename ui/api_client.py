"""Calls to Kestrel's API. The screen talks to Kestrel only through these functions (contracts/kestrel-api.md)."""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    """The API answered with an error status, or couldn't be reached (status 0)."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(f"Kestrel API error {status}")
        self.status = status
        self.body = body


def base_url() -> str:
    return os.environ.get("KESTREL_API_URL", DEFAULT_API_URL).rstrip("/")


def _request(method: str, path: str, *, json: Any = None, timeout: float = 10.0) -> Any:
    try:
        response = httpx.request(method, base_url() + path, json=json, timeout=timeout)
    except httpx.HTTPError:
        raise ApiError(0, {"error": {"code": "api_unreachable", "field": None,
                                     "message": "Kestrel's API isn't reachable. Is it running?"}}) from None
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {}
    if response.status_code >= 400:
        raise ApiError(response.status_code, body)
    return body


def get_config() -> dict[str, Any]:
    return _request("GET", "/api/config")


def test_connection(payload: dict[str, Any]) -> dict[str, Any]:
    # Longer than the API's 60-second deadline, so the API always answers first.
    return _request("POST", "/api/connection-tests", json=payload, timeout=90.0)
