"""Shared test helpers. A synthetic attack library and a stub judge, so integration tests need no real content."""
from __future__ import annotations

import json
import math
import re
import zlib

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from kestrel.attacks.library import FAMILIES, build_library
from kestrel.experience.store import ExperienceStore
from kestrel.judge.verdict import ParsedVerdict

OWASP = {key: meta["owasp_category"] for key, meta in FAMILIES.items()}


def fixture_library_data(version: str = "1.0.0") -> dict:
    """A valid library with five placeholder prompts per family (20 total). Ids are '<abbr>-00N'; no real text."""
    abbr = {"direct_injection": "dir", "system_prompt_leak": "spl",
            "tool_exfiltration": "tex", "indirect_injection": "iin"}
    prompts = []
    for family, prefix in abbr.items():
        for n in range(1, 6):
            prompts.append({"id": f"{prefix}-00{n}", "title": f"{family} placeholder {n}",
                            "text": f"<placeholder {family} prompt {n}>", "family": family,
                            "owasp_category": OWASP[family], "source": "Fixture", "source_url": "https://example.test",
                            "licence": "CC BY 4.0"})
    return {"version": version, "prompts": prompts}


def fixture_library(version: str = "1.0.0"):
    return build_library(fixture_library_data(version))


class StubJudge:
    """A judge that returns a fixed verdict (or raises), without touching the network."""

    def __init__(self, verdict: str = "failed", reason: str = "The agent held.", *, configured: bool = True,
                 model: str = "google/gemini-3.8-flash", error: Exception | None = None,
                 progress: str | None = "a step closer", recommendation: str = "Harden the system prompt."):
        self._verdict, self._reason, self.configured, self.model = verdict, reason, configured, model
        self._error, self._progress, self._recommendation = error, progress, recommendation
        self.calls: list[dict] = []

    async def judge(self, *, attack: str, reply: str, conversation: str | None = None,
                    timeout: float | None = None) -> ParsedVerdict:
        self.calls.append({"attack": attack, "reply": reply, "conversation": conversation, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return ParsedVerdict(self._verdict, self._reason, progress=self._progress)

    async def recommend(self, *, family: str, owasp_category: str, attack: str, evidence: str,
                        timeout: float | None = None) -> tuple[str, int]:
        self.calls.append({"recommend": True, "family": family, "owasp_category": owasp_category,
                           "attack": attack, "evidence": evidence, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return self._recommendation, 42


class StubAttacker:
    """An attacker that emits a placeholder message each turn, without touching the network (feature 003)."""

    def __init__(self, *, configured: bool = True, model: str = "deepseek/deepseek-v3.2", tokens: int = 100,
                 error: Exception | None = None):
        self.configured, self.model, self._tokens, self._error = configured, model, tokens, error
        self.calls: list[dict] = []

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        from kestrel.attack.attacker import AttackerReply
        self.calls.append({"conversation": conversation, "family": family, "progress": progress, "hints": hints})
        if self._error is not None:
            raise self._error
        return AttackerReply(message=f"<attacker turn {len(conversation) // 2 + 1}>", tokens=self._tokens)

    @property
    def last_hints(self) -> str | None:
        """The hints block passed to the most recent next_message call (for warm/cold tests)."""
        return self.calls[-1]["hints"] if self.calls else None


_TOKEN = re.compile(r"[a-z0-9]+")


def lexical_tokens(text: str) -> list[str]:
    """The stub's tokens: lower-case alphanumeric runs (`direct_injection` is two tokens)."""
    return _TOKEN.findall(text.lower())


class StubEmbeddingFunction(EmbeddingFunction):
    """A deterministic, offline, *lexical* embedding function for ExperienceStore tests (004 research R2; 011 D8).

    A hashed bag of words: each token is hashed with a stable CRC-32 (never the per-process `hash()`) into one of
    `dim` buckets, counted, and the vector is L2-normalised. Under the collection's `l2` space identical texts are
    at squared distance 0, texts sharing no token (and no bucket) at 2, and one token of six changed at 2 − 2·5/6,
    so "near-identical" and "far" mean something offline and the floor and de-duplication tests state thresholds on
    this scale. Keeps `uv run pytest` free of model downloads and network; it measures lexical overlap, not
    embedding quality (that is the e2e's job). Inherits the chromadb EmbeddingFunction surface so the collection
    persists and reopens cleanly; the registered name is unchanged, the model name is what the store records.
    """

    MODEL_NAME = "kestrel-lexical-stub"
    DIM = 256

    def __init__(self, dim: int = DIM) -> None:
        self._dim = dim

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - chromadb's parameter name is `input`
        return [self.embed(document) for document in input]

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in lexical_tokens(text):
            vector[zlib.crc32(token.encode("utf-8")) % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector   # an empty text is the zero vector

    @staticmethod
    def name() -> str:
        return "kestrel_stub"

    def get_config(self) -> dict:
        return {"dim": self._dim}

    @classmethod
    def build_from_config(cls, config: dict) -> "StubEmbeddingFunction":
        return cls(dim=config.get("dim", cls.DIM))


class SpyExperienceStore(ExperienceStore):
    """A real stub-backed store that records every pattern query, every pattern write, and every memory write
    (feature 011, D9; feature 012, FR-025/FR-026), so a test can prove what text the store received and what
    each write-back did. Everything is delegated."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.queries: list[dict] = []
        self.pattern_writes: list = []
        self.memory_writes: list[dict] = []

    def query_patterns(self, *, family: str, query_text: str, n: int):
        self.queries.append({"family": family, "query_text": query_text, "n": n})
        return super().query_patterns(family=family, query_text=query_text, n=n)

    def write_pattern(self, **kwargs):
        result = super().write_pattern(**kwargs)
        self.pattern_writes.append(result)
        return result

    def write_memory(self, **kwargs):
        self.memory_writes.append(kwargs)
        return super().write_memory(**kwargs)


# ---- feature 010: known strings, and one offline transport for the target and the real model clients ----

# Known strings the redaction tests count on every surface (010/SC-002). Placeholders only, never attack text.
SECRET = "KESTREL-TEST-AUTH-VALUE-9f3a71"              # the target's auth header value
TARGET_URL = "http://target.kestrel.test/agent/chat"    # the target's URL
TARGET_NAME = "Redaction Probe Agent 7"                 # the target's display name
ATTACK_TEXT = "<attack message placeholder 4471>"       # the message sent to the target
REPLY_TEXT = "<target reply placeholder 8823>"          # the target's reply
JUDGE_REASON = "The reply quoted <target reply placeholder 8823> back."   # judge free text quoting the reply
JUDGE_PROGRESS = "progress note placeholder 5531"
PURPOSE_TEXT = "purpose placeholder 7719"               # the target's purpose description (feature 011)
MODEL_KEY = "KESTREL-TEST-MODEL-KEY-c0ffee"             # the attacker/judge API key
MODEL_BASE_URL = "http://models.kestrel.test/v1"        # the model endpoint the real clients call


async def no_sleep(_delay):
    return None


class ModelTransport:
    """One httpx.MockTransport for a whole offline run (010/T003): it answers the model endpoint — attacker, judge and
    recommender requests, told apart by the request's response_format — with canned OpenAI-style bodies carrying a
    `usage` object, the side-channel host (feature 013) through `side_channel`, and every other host as the stub
    target ({"reply": ...}). Every request is recorded with its headers, so a test can check what reached the
    target. Pass `.transport` both as the app's transport and as the real clients' transport.

    Feature 013: `target_reply` may be a callable `(request) -> str` for a reply that depends on what was sent
    (the run's real planted token, read back from the store), and `on_target_request` is called with every target
    request before it is answered, so a stub target can act on a planted callback URL it received."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.target_reply = REPLY_TEXT
        self.target_status = 200
        self.attacker_message = ATTACK_TEXT
        self.attacker_statuses: list[int] = []      # consumed one per attacker POST; 200 once empty
        self.verdict = "failed"
        self.judge_reason = JUDGE_REASON
        self.judge_progress = JUDGE_PROGRESS
        self.judge_statuses: list[int] = []
        self.recommendation = "Keep the system prompt out of replies."
        self.usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        self.error_usage: dict | None = None        # usage an error response reports (a retried, billed attempt)
        self.on_target_request = None               # feature 013: a hook `(request) -> None` per target request
        self.side_channel = SideChannelStub()       # feature 013: answers SIDE_CHANNEL_URL's three endpoints
        self.transport = httpx.MockTransport(self.handle)

    # -- what a test reads back --

    def target_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests
                if r.url.host not in (httpx.URL(MODEL_BASE_URL).host, httpx.URL(SIDE_CHANNEL_URL).host)]

    def model_requests(self, kind: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == httpx.URL(MODEL_BASE_URL).host and _kind(r) == kind]

    def side_channel_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == httpx.URL(SIDE_CHANNEL_URL).host]

    # -- the handler --

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == httpx.URL(SIDE_CHANNEL_URL).host:
            return self.side_channel.handle(request)
        if request.url.host != httpx.URL(MODEL_BASE_URL).host:
            if self.on_target_request is not None:
                self.on_target_request(request)
            reply = self.target_reply(request) if callable(self.target_reply) else self.target_reply
            return httpx.Response(self.target_status, json={"reply": reply})
        kind = _kind(request)
        if kind == "attacker":
            status = self.attacker_statuses.pop(0) if self.attacker_statuses else 200
            content = self.attacker_message
        elif kind == "judge":
            status = self.judge_statuses.pop(0) if self.judge_statuses else 200
            content = json.dumps({"verdict": self.verdict, "reason": self.judge_reason,
                                  "progress": self.judge_progress})
        else:
            status, content = 200, json.dumps({"recommendation": self.recommendation})
        if status != 200:
            body: dict = {"error": {"message": "placeholder provider error"}}
            if self.error_usage is not None:
                body["usage"] = dict(self.error_usage)
            return httpx.Response(status, json=body)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": dict(self.usage)})


def _kind(request: httpx.Request) -> str:
    """attacker (no response_format), judge (schema "verdict") or recommender (schema "recommendation")."""
    body = json.loads(request.content or b"{}")
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
    return {"verdict": "judge", "recommendation": "recommender"}.get(schema, "attacker")


def real_judge(model_transport: ModelTransport, *, model: str = "google/gemini-3.8-flash", system_prompt=None):
    """The real JudgeClient over the offline transport (010, research D10)."""
    from kestrel.judge.client import JudgeClient
    return JudgeClient(model=model, api_key=MODEL_KEY, base_url=MODEL_BASE_URL, transport=model_transport.transport,
                       sleep=no_sleep, system_prompt=system_prompt)


def real_attacker(model_transport: ModelTransport, *, model: str = "deepseek/deepseek-v4.1-flash",
                  system_overrides=None):
    """The real AttackerClient over the offline transport (010, research D10)."""
    from kestrel.attack.attacker import AttackerClient
    return AttackerClient(model=model, api_key=MODEL_KEY, base_url=MODEL_BASE_URL,
                          transport=model_transport.transport, sleep=no_sleep, system_overrides=system_overrides)


def saved_target(store, *, name: str = TARGET_NAME, url: str = TARGET_URL, secret: str = SECRET,
                 canaries: list[str] | None = None, description: str | None = None):
    """A saved, permission-confirmed target under the current terms, written straight to the store (feature 010)."""
    from kestrel.api.main import load_terms
    target = store.create_target(name=name, url=url, method="POST", headers=[("X-API-Key", secret)],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply",
                                 terms_version=load_terms().version, description=description)
    if canaries:
        store.set_canaries(target.id, canaries)
    return target


def model_settings(settings):
    """Settings whose model clients — built by the app or by the experiment engine's own factories — reach the
    offline model transport (feature 010, research D10)."""
    import dataclasses
    return dataclasses.replace(settings, judge_api_key=MODEL_KEY, judge_base_url=MODEL_BASE_URL,
                               attacker_api_key=MODEL_KEY, attacker_base_url=MODEL_BASE_URL)


def await_experiment(client, experiment_id: int, timeout_s: float = 30.0) -> dict:
    """Poll the status endpoint until the experiment leaves 'running'."""
    import time
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = client.get(f"/api/experiments/{experiment_id}/status").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"experiment {experiment_id} did not finish within {timeout_s}s")


# ---- feature 013: the side-channel stub, the planted-value helpers and the repeating doubles ----

SIDE_CHANNEL_URL = "http://sidechannel.kestrel.test/side-channel"   # the stub side channel's base URL


class SideChannelStub:
    """A scripted side channel (013/T006) behind `SIDE_CHANNEL_URL`, answered by `ModelTransport`: the descriptor,
    a per-correlation-id tool-call log whose calls carry `seq`, a sequence of state snapshots (the last one repeats)
    and six failure modes a test switches on with `failure`. Scaffolding for part 2's checks; part 1 never calls it."""

    FAILURES = ("unreachable", "unauthorized", "timeout", "invalid_shape", "error_status", "non_json")

    def __init__(self) -> None:
        self.descriptor: dict = {"kestrel_side_channel": 1, "capabilities": ["tool_calls", "state"], "tools": []}
        self.calls: dict[str, list[dict]] = {}      # correlation id -> the calls made under it, in order
        self.states: list[dict] = [{}]              # the snapshot sequence a run reads; the last repeats
        self.expected_header: tuple[str, str] | None = None   # (name, value) the stub insists on, or None
        self.failure: str | None = None             # one of FAILURES, or None
        self.requests: list[httpx.Request] = []
        self._state_reads = 0

    def add_call(self, correlation_id: str, name: str, arguments: dict) -> dict:
        """Record one tool call under a correlation id with the next `seq` for that id."""
        calls = self.calls.setdefault(correlation_id, [])
        call = {"seq": len(calls) + 1, "name": name, "arguments": arguments, "at": "2026-11-23T10:15:01Z"}
        calls.append(call)
        return call

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure == "unreachable":
            raise httpx.ConnectError("placeholder connect error", request=request)
        if self.failure == "timeout":
            raise httpx.ReadTimeout("placeholder timeout", request=request)
        if self.failure == "unauthorized" or (self.expected_header is not None
                                              and request.headers.get(self.expected_header[0]) != self.expected_header[1]):
            return httpx.Response(401, json={"detail": "unauthorized"})
        if self.failure == "error_status":
            return httpx.Response(500, json={"detail": "placeholder error"})
        if self.failure == "non_json":
            return httpx.Response(200, text="<html>placeholder</html>")
        if self.failure == "invalid_shape":
            return httpx.Response(200, json={"unexpected": True})
        path = request.url.path
        if path.endswith("/describe"):
            return httpx.Response(200, json=dict(self.descriptor))
        if path.endswith("/tool-calls"):
            correlation_id = request.url.params.get("correlation_id", "")
            return httpx.Response(200, json={"correlation_id": correlation_id,
                                             "calls": [dict(c) for c in self.calls.get(correlation_id, [])]})
        if path.endswith("/state"):
            snapshot = self.states[min(self._state_reads, len(self.states) - 1)]
            self._state_reads += 1
            return httpx.Response(200, json={"state": snapshot})
        return httpx.Response(404, json={"detail": "not found"})


def in_progress_run_id(store) -> int | None:
    """The one run currently in progress (every test here drives a single target at a time), or None."""
    with store.connect() as db:
        row = db.execute("SELECT id FROM runs WHERE status = 'in_progress' ORDER BY id DESC LIMIT 1").fetchone()
    return None if row is None else int(row["id"])


def planted_values(store, run_id: int) -> dict[str, str]:
    """A run's real planted values, read back from the store (013/T006): `first`/`second`/`joined` for an override
    token (the stored token is the joined form; the parts are its two halves) and `callback_url`'s last segment as
    `callback_token`. Empty when the run planted nothing."""
    out: dict[str, str] = {}
    for token in store.list_planted_tokens(run_id):
        if token.kind == "override":
            half = len(token.token) // 2
            out.update({"joined": token.token, "first": token.token[:half], "second": token.token[half:]})
        elif token.kind == "callback":
            out["callback_token"] = token.token
    return out


def _echo(store) -> str:
    """The run's real parts and callback token, written separately (never the joined form, which would disarm the
    detector): what the repeating doubles put into their later messages and progress notes."""
    run_id = in_progress_run_id(store)
    values = planted_values(store, run_id) if run_id is not None else {}
    bits = []
    if "first" in values:
        bits.append(f"first part {values['first']} then second part {values['second']}")
    if "callback_token" in values:
        bits.append(f"callback token {values['callback_token']}")
    return " ".join(bits)


class RepeatingStubAttacker(StubAttacker):
    """A stub attacker whose turn-2-and-later messages repeat the run's real token parts (and callback token) read
    back from the store, so an isolation test cannot pass vacuously (013/FR-063, SC-013)."""

    def __init__(self, store, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = store

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        reply = await super().next_message(conversation=conversation, family=family, progress=progress,
                                           hints=hints, timeout=timeout)
        from kestrel.attack.attacker import AttackerReply
        return AttackerReply(message=f"{reply.message} {_echo(self._store)}".strip(), tokens=reply.tokens)


class RepeatingStubJudge(StubJudge):
    """A stub judge whose progress notes repeat the run's real token parts (and callback token), read back from the
    store, so the memory summary built from them is a real test of the scrubbing (013/FR-063, SC-013)."""

    def __init__(self, store, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = store

    async def judge(self, *, attack: str, reply: str, conversation: str | None = None,
                    timeout: float | None = None) -> ParsedVerdict:
        verdict = await super().judge(attack=attack, reply=reply, conversation=conversation, timeout=timeout)
        progress = f"{verdict.progress or ''} {_echo(self._store)}".strip()
        return ParsedVerdict(verdict.verdict, verdict.reason, progress=progress, tokens=verdict.tokens)
