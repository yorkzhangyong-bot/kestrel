"""The judge: one HTTPS call to an OpenAI-compatible endpoint, with httpx (contracts/judge.md, research R2).

No SDK and no new dependency. The judge sees only the attack prompt and the (already masked and cut) reply —
never an auth header value, the target URL, or the target name (FR-020). Untrusted text (the conversation, the
attack, the reply) is fenced before it enters the prompt, and the answer is validated against a Pydantic schema
with one retry on a schema violation; transient HTTP statuses are retried within the run's deadline. The judge and
recommender prompt texts are not in this module: they are read from the prompt registry (feature 009,
`src/kestrel/prompts/`), the active version unless an A/B arm pins one. Each judge or recommender call is one
`model.request` line (feature 010): the verdict category at most — never the reason, the progress note or the advice.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import httpx

from kestrel import events, prompt_registry
from kestrel.prompting import DATA_RULE, fence
from kestrel.retry import CallTally, post_with_retry
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
                 system_prompt: str | tuple[str, str] | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep
        # Feature 009: a prompt-version A/B arm pins a specific judge verdict prompt; None = the active one, read
        # from the registry at call time. Feature 010: the pin carries its reference, `(text, "judge@N")` (FR-007).
        self._system_prompt = system_prompt

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    @property
    def judge_prompt_ref(self) -> str | None:
        """The reference (`judge@N`) of the verdict prompt this client sends: a pinned arm's, or the registry's active
        one; None for a plain pinned text (its version is not known). The single source of the judge provenance and
        lines (feature 010, FR-007)."""
        if self._system_prompt is None:
            return prompt_registry.active_ref(prompt_registry.JUDGE_ID)
        return self._system_prompt[1] if isinstance(self._system_prompt, tuple) else None

    @property
    def recommender_prompt_ref(self) -> str | None:
        """The reference (`recommender@N`) of the fix-advice prompt: always the active one (arms never pin it)."""
        return prompt_registry.active_ref(prompt_registry.RECOMMENDER_ID)

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
        pinned = self._system_prompt
        system = (pinned[0] if isinstance(pinned, tuple) else pinned) or \
            prompt_registry.load_prompt(prompt_registry.JUDGE_ID)[0]
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
                               remaining: Callable[[], float], tally: CallTally | None = None) -> tuple[object, int]:
        """Up to two model calls: validate the answer; on a schema violation, retry once with the error as
        feedback (judge item 1). Returns (validated model, tokens summed over every call). Raises JudgeError on a
        bad status or a second failure; transient statuses are already retried inside post_with_retry (item 4).
        `tally` accumulates the attempts, status and usage for the model-request line (feature 010)."""
        tally = tally if tally is not None else CallTally()
        tokens = 0
        last_error: VerdictParseError | None = None
        for attempt in (1, 2):
            payload = {"model": self._model, "max_tokens": max_tokens, "temperature": 0, "messages": messages,
                       "response_format": {"type": "json_schema",
                                           "json_schema": {"name": schema_name, "strict": True, "schema": schema}}}
            try:
                result = await post_with_retry(http, f"{self._base_url}/chat/completions", json=payload,
                                               headers=self._headers(), remaining=remaining, sleep=self._sleep)
            except httpx.HTTPError:
                tally.failed_to_connect()
                raise
            tally.add(result)
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
        prompt_ref = self.judge_prompt_ref   # the reference this request sends, for its line
        tally, started = CallTally(), time.perf_counter()
        parsed: ParsedVerdict | None = None
        error_kind: str | None = None
        with events.child_span("kestrel.model_request") as span:
            try:
                async with httpx.AsyncClient(transport=self._transport, timeout=limit) as http:
                    model, tokens = await self._structured_call(
                        http, messages, max_tokens=MAX_ANSWER_TOKENS, schema_name="verdict", schema=RESPONSE_SCHEMA,
                        validate=validate_verdict, remaining=self._remaining(limit), tally=tally)
                assert isinstance(model, Verdict)
                progress = model.progress.strip() if model.progress and model.progress.strip() else None
                parsed = ParsedVerdict(verdict=model.verdict, reason=model.reason, progress=progress, tokens=tokens)
                return parsed
            except httpx.HTTPError as error:
                error_kind = type(error).__name__
                raise JudgeError(f"The judge could not be reached: {type(error).__name__}.") from error
            except BaseException as error:
                error_kind = error_kind or type(error).__name__
                raise
            finally:
                # The verdict category only: the reason and the progress note may quote the reply (FR-009).
                self._log_request("judge", prompt_ref, tally, started, ok=parsed is not None,
                                  error=error_kind, verdict=parsed.verdict if parsed is not None else None, span=span)

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
        prompt_ref = self.recommender_prompt_ref
        tally, started = CallTally(), time.perf_counter()
        done = False
        error_kind: str | None = None
        try:   # report time, outside any run: logged (on the stream only), never traced (FR-013)
            async with httpx.AsyncClient(transport=self._transport, timeout=limit) as http:
                model, tokens = await self._structured_call(
                    http, messages, max_tokens=MAX_RECOMMEND_TOKENS, schema_name="recommendation",
                    schema=RECOMMEND_SCHEMA, validate=validate_recommendation, remaining=self._remaining(limit),
                    tally=tally)
            assert isinstance(model, Recommendation)
            text = model.recommendation.strip()
            if not text:
                raise JudgeError("The judge returned an empty recommendation.")
            done = True
            return text, tokens
        except httpx.HTTPError as error:
            error_kind = type(error).__name__
            raise JudgeError(f"The judge could not be reached: {type(error).__name__}.") from error
        except BaseException as error:
            error_kind = error_kind or type(error).__name__
            raise
        finally:
            self._log_request("recommender", prompt_ref, tally, started, ok=done, error=error_kind)

    def _log_request(self, kind: str, prompt: str | None, tally: CallTally, started: float, *, ok: bool,
                     error: str | None, verdict: str | None = None, span=None) -> None:
        events.model_request(kind=kind, model=self._model, prompt=prompt,
                             latency_ms=int((time.perf_counter() - started) * 1000), ok=ok, status=tally.status,
                             attempts=tally.attempts, prompt_tokens=tally.prompt_tokens,
                             completion_tokens=tally.completion_tokens, total_tokens=tally.total_tokens,
                             error=None if ok else error or "JudgeError", verdict=verdict, span=span)
