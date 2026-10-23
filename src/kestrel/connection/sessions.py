"""Form sessions, in memory: one test at a time per form, and "save only what was tested" (FR-009, FR-012; R7).

The API must run as a single process, because these sessions live in its memory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from kestrel.connection.tester import ResolvedSettings

SESSION_TTL_SECONDS = 3600.0


@dataclass
class _Session:
    in_flight: bool = False
    last_success: str | None = None
    touched_at: float = 0.0


class FormSessions:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_seconds: float = SESSION_TTL_SECONDS,
                 key: bytes | None = None) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._key = key or os.urandom(32)  # lives only in this process; fingerprints never leave it
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def start(self, form_id: str) -> bool:
        """Mark a test as running; False when this form already has one in flight."""
        with self._lock:
            self._expire()
            session = self._sessions.setdefault(form_id, _Session())
            if session.in_flight:
                return False
            session.in_flight = True
            session.touched_at = self._clock()
            return True

    def finish(self, form_id: str, fingerprint: str | None) -> None:
        """End the running test; record its fingerprint if it succeeded, clear the old one if it failed."""
        with self._lock:
            session = self._sessions.setdefault(form_id, _Session())
            session.in_flight = False
            session.last_success = fingerprint
            session.touched_at = self._clock()

    def last_success(self, form_id: str) -> str | None:
        with self._lock:
            self._expire()
            session = self._sessions.get(form_id)
            return session.last_success if session else None

    def fingerprint(self, settings: ResolvedSettings) -> str:
        """HMAC of the connection settings; the display name isn't part of it (FR-012)."""
        canonical = json.dumps({
            "url": settings.url,
            "method": settings.method,
            "headers": sorted([name.lower(), value] for name, value in settings.headers),
            "body_template": settings.body_template,
            "response_path": settings.response_path,
        }, sort_keys=True, ensure_ascii=False)
        return hmac.new(self._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _expire(self) -> None:
        cutoff = self._clock() - self._ttl
        for form_id in [fid for fid, session in self._sessions.items() if session.touched_at < cutoff]:
            del self._sessions[form_id]
