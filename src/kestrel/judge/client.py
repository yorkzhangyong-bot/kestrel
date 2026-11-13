"""The judge: one HTTPS call to an OpenAI-compatible endpoint, with httpx (contracts/judge.md, research R2).

No SDK and no new dependency. The judge sees only the attack prompt and the (already masked and cut) reply —
never an auth header value, the target URL, or the target name (FR-020). Untrusted text (the conversation, the
attack, the reply) is fenced before it enters the prompt, and the answer is validated against a Pydantic schema
with one retry on a schema violation; transient HTTP statuses are retried within the run's deadline. The judge and
recommender prompt texts are not in this module: they are read from the prompt registry (feature 009,
`src/kestrel/prompts/`), the active version unless an A/B arm pins one.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import httpx

from kestrel import prompt_registry
from kestrel.prompting import DATA_RULE, fence
from kestrel.retry import post_with_retry
from kestrel.judge.verdict import (RECOMMEND_SCHEMA, RESPONSE_SCHEMA, ParsedVerdict, Recommendation, Verdict,
                                   VerdictParseError, validate_recommendation, validate_verdict)

MAX_REPLY_CHARS = 2_000     # the cut the screen already uses to display a reply (FR-022)
MAX_CONTEXT_CHARS = 6_000   # the conversation sent to the judge, kept from the TAIL so the latest turn is never cut
MAX_ANSWER_TOKENS = 600     # a verdict and one line, with headroom so a verbose model's JSON is not truncated (FR-022)
MAX_RECOMMEND_TOKENS = 400  # a few sentences of concrete fix advice (feature 005, FR-012)
DEFAULT_TIMEOUT_S = 30.0


class JudgeError(Exception):
    """The judge could not be reached or its answer could not be read; the run becomes "unclear" (FR-021)."""


def _content(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise JudgeError("The judge's response had an unexpected shape.") from error


class JudgeClient:
    def __init__(self, *, model: str, api_key: str | None, base_url: str,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = DEFAULT_TIMEOUT_S,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 system_prompt: str | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep
        # Feature 009: a prompt-version A/B arm pins a specific judge verdict prompt; None = the active one, read
        # from the registry at call time.
        self._system_prompt = system_prompt

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _remaining(limit: float) -> Callable[[], float]:
        end = time.monotonic() + limit
        return lambda: end - time.monotonic()

    def _judge_messages(self, attack: str, reply: str, conversation: str | None) -> list[dict[str, str]]:
        reply = reply[:MAX_REPLY_CHARS]
        if conversation is not None:
            # Adaptive: judge the latest reply in context; keep the TAIL so the newest attacker message survives.
            tail = conversation[-MAX_CONTEXT_CHARS:]
            user = (f"The conversation so far between the attacker and the agent:\n{fence(tail, 'conversation')}\n\n"
                    f"The agent's latest reply:\n{fence(reply, 'reply')}")
        else:
            user = f"Attack message sent to the agent:\n{fence(attack, 'attack')}\n\nThe agent's reply:\n{fence(reply, 'reply')}"
        system = self._system_prompt or prompt_registry.load_prompt(prompt_registry.JUDGE_ID)[0]
        return [{"role": "system", "content": f"{system}\n\n{DATA_RULE}"},
                {"role": "user", "content": user}]

    def _recommend_messages(self, family: str, owasp_category: str, attack: str, evidence: str) -> list[dict[str, str]]:
        user = (f"Attack family: {family}\nOWASP class: {owasp_category}\n\n"
                f"Winning attacker message:\n{fence(attack[:MAX_REPLY_CHARS], 'winning-message')}\n\n"
                f"Evidence the attack worked:\n{fence(evidence[:MAX_REPLY_CHARS], 'evidence')}")
        # The fix advice is derived only from non-secret inputs: the family, its OWASP class, the winning attacker
        # message and the evidence. It never sees an auth header value, the target URL, or the target name (FR-018).
        system = prompt_registry.load_prompt(prompt_registry.RECOMMENDER_ID)[0]
        return [{"role": "system", "content": f"{system}\n\n{DATA_RULE}"},
                {"role": "user", "content": user}]

    async def _structured_call(self, http: httpx.AsyncClient, messages: list[dict[str, str]], *, max_tokens: int,
                               schema_name: str, schema: dict, validate: Callable[[str], object],
                               remaining: Callable[[], float]) -> tuple[object, int]:
        """Up to two model calls: validate the answer; on a schema violation, retry once with the error as
        feedback (judge item 1). Returns (validated model, tokens summed over every call). Raises JudgeError on a
        bad status or a second failure; transient statuses are already retried inside post_with_retry (item 4)."""
        tokens = 0
        last_error: VerdictParseError | None = None
        for attempt in (1, 2):
            payload = {"model": self._model, "max_tokens": max_tokens, "temperature": 0, "messages": messages,
                       "response_format": {"type": "json_schema",
                                           "json_schema": {"name": schema_name, "strict": True, "schema": schema}}}
            result = await post_with_retry(http, f"{self._base_url}/chat/completions", json=payload,
                                           headers=self._headers(), remaining=remaining, sleep=self._sleep)
            tokens += result.tokens
            if result.response.status_code != 200:
                raise JudgeError(f"The judge answered with status {result.response.status_code}.")
            content = _content(result.response)
            try:
                return validate(content), tokens
            except VerdictParseError as error:
                last_error = error
                if attempt == 2:
                    break
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": ("Your previous reply did not match the required JSON schema "
                                                 f"({error}). Reply again with only the JSON object.")}]
        raise JudgeError(f"The judge's answer could not be read: {last_error}")

    async def judge(self, *, attack: str, reply: str, conversation: str | None = None,
                    timeout: float | None = None) -> ParsedVerdict:
        """Return a verdict, or raise JudgeError. The caller turns that into an "unclear" run (FR-021).

        Adaptive runs pass the masked `conversation` so far; single-turn runs pass just `attack` and `reply`."""
        if not self.configured:
            raise JudgeError("No judge is configured; set KESTREL_JUDGE_API_KEY or OPENROUTER_API_KEY.")
        limit = self._timeout if timeout is None else min(self._timeout, timeout)
        messages = self._judge_messages(attack, reply, conversation)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=limit) as http:
                model, tokens = await self._structured_call(
                    http, messages, max_tokens=MAX_ANSWER_TOKENS, schema_name="verdict", schema=RESPONSE_SCHEMA,
                    validate=validate_verdict, remaining=self._remaining(limit))
        except httpx.HTTPError as error:
            raise JudgeError(f"The judge could not be reached: {type(error).__name__}.") from error
        assert isinstance(model, Verdict)
        progress = model.progress.strip() if model.progress and model.progress.strip() else None
        return ParsedVerdict(verdict=model.verdict, reason=model.reason, progress=progress, tokens=tokens)

    async def recommend(self, *, family: str, owasp_category: str, attack: str, evidence: str,
                        timeout: float | None = None) -> tuple[str, int]:
        """One chat call for a fix suggestion, reusing the judge's model/key/base-url/transport.

        Inputs are non-secret (family, OWASP class, the winning attacker message, the evidence); no auth value,
        URL or target name is ever sent (FR-018). Raises JudgeError if not configured or the call fails; the
        caller then omits this recommendation (FR-013)."""
        if not self.configured:
            raise JudgeError("No judge is configured; set KESTREL_JUDGE_API_KEY or OPENROUTER_API_KEY.")
        limit = self._timeout if timeout is None else min(self._timeout, timeout)
        messages = self._recommend_messages(family, owasp_category, attack, evidence)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=limit) as http:
                model, tokens = await self._structured_call(
                    http, messages, max_tokens=MAX_RECOMMEND_TOKENS, schema_name="recommendation",
                    schema=RECOMMEND_SCHEMA, validate=validate_recommendation, remaining=self._remaining(limit))
        except httpx.HTTPError as error:
            raise JudgeError(f"The judge could not be reached: {type(error).__name__}.") from error
        assert isinstance(model, Recommendation)
        text = model.recommendation.strip()
        if not text:
            raise JudgeError("The judge returned an empty recommendation.")
        return text, tokens
