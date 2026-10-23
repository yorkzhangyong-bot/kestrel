"""The single client factory for chat and embedding models, structured calls with retries,
usage and cost recording (research.md R-01, R-02, R-06, R-07).

Every model call in CargoLint goes through `get_client()`; tests inject a fake backend with
`set_client_factory()`.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from agent.config import DATA_DIR, MAX_SCHEMA_RETRIES, OPENROUTER_BASE_URL, Settings, get_settings
from agent.routing import SchemaError
from agent.schemas import Usage

log = logging.getLogger(__name__)

PRICES_PATH = DATA_DIR / "model_prices.json"


class UnknownModelError(KeyError):
    pass


# --------------------------------------------------------------------------- prices and cost
@dataclass(frozen=True)
class PriceTable:
    as_of: str
    models: dict[str, dict[str, float]]


def load_prices(path: Path | None = None) -> PriceTable:
    data = json.loads(Path(path or PRICES_PATH).read_text(encoding="utf-8"))
    return PriceTable(as_of=data.get("as_of", ""), models=data.get("models", {}))


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int, prices: PriceTable, usd_eur: float) -> tuple[float, float]:
    """USD and EUR cost from token counts and the price table (USD per 1M tokens)."""
    if model not in prices.models:
        raise UnknownModelError(f"no price recorded for model {model!r}; run `python -m agent.llm --refresh-prices`")
    p = prices.models[model]
    usd = prompt_tokens / 1_000_000 * float(p.get("input", 0.0)) + completion_tokens / 1_000_000 * float(p.get("output", 0.0))
    return usd, usd * usd_eur


def usage_from_tokens(model: str, prompt_tokens: int, completion_tokens: int, prices: PriceTable, usd_eur: float) -> Usage:
    usd, eur = compute_cost(model, prompt_tokens, completion_tokens, prices, usd_eur)
    return Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                 total_tokens=prompt_tokens + completion_tokens, cost_usd=usd, cost_eur=eur, calls=1)


# --------------------------------------------------------------------------- error classification (R-07)
def classify_error(exc: BaseException) -> tuple[bool, str]:
    """(retryable, clerk-facing message) for a transport or provider error."""
    text = str(exc)
    status = getattr(exc, "status_code", None)
    if status == 402 or "402" in text or "insufficient credits" in text.lower():
        return False, "OpenRouter credits are exhausted — top up the account and try again."
    if status == 403:
        return False, "The request was refused (moderation or budget). Check the OpenRouter account settings."
    if status == 429 or "rate limit" in text.lower():
        return True, "The model is rate-limited; retrying shortly."
    if status in (502, 503) or "no provider" in text.lower():
        return True, "The model provider is temporarily unavailable; retrying."
    if "finish_reason" in text and "error" in text:
        return True, "The model stream ended with an error; retrying."
    module = type(exc).__module__.split(".")[0]
    transport = status is not None or module in ("openai", "httpx", "httpcore") or isinstance(exc, (TimeoutError, ConnectionError))
    if not transport:
        return False, "The app hit an internal error in this step, not a model problem. Try again; if it repeats, report the message below."
    return True, "Temporary problem talking to the model; retrying."


# --------------------------------------------------------------------------- structured calls
class StructuredCaller:
    """Validates every model output against its Pydantic schema, retrying with feedback (FR-044)."""

    def __init__(self, raw: Any, model_name: str, prices: PriceTable | None, usd_eur: float,
                 usage_sink: Callable[[Usage], None] | None = None, max_retries: int = MAX_SCHEMA_RETRIES) -> None:
        self.raw = raw
        self.model_name = model_name
        self.prices = prices
        self.usd_eur = usd_eur
        self.usage_sink = usage_sink
        self.max_retries = max_retries

    def call(self, schema: type[BaseModel], system: str, user: str) -> BaseModel:
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            out = self.raw.raw_structured(schema, system, user + feedback)
            self._record_usage()
            try:
                if isinstance(out, schema):
                    return out
                return schema.model_validate(out)
            except ValidationError as exc:
                last_error = exc
                feedback = ("\n\nYour previous answer was invalid: " + str(exc).splitlines()[0]
                            + ". Return only valid JSON that matches the schema.")
                log.info("structured output invalid (attempt %s/%s) for %s", attempt + 1, self.max_retries + 1, schema.__name__)
        raise SchemaError(f"{schema.__name__}: invalid after {self.max_retries + 1} attempts: {last_error}")

    def _record_usage(self) -> None:
        if self.usage_sink is None:
            return
        meta = getattr(self.raw, "last_usage", None) or {}
        prompt = int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0)
        completion = int(meta.get("output_tokens") or meta.get("completion_tokens") or 0)
        if self.prices is not None and self.model_name in self.prices.models:
            usage = usage_from_tokens(self.model_name, prompt, completion, self.prices, self.usd_eur)
        else:
            usage = Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion, calls=1)
        self.usage_sink(usage)


class OpenRouterRawClient:
    """Real backend: ChatOpenAI pointed at OpenRouter, native JSON-schema structured output."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_usage: dict[str, int] = {}
        self._model = get_chat_model(settings)
        self._structured: dict[type, Any] = {}

    def raw_structured(self, schema: type[BaseModel], system: str, user: str) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage

        runnable = self._structured.get(schema)
        if runnable is None:
            method = self.settings.structured_method or "json_schema"
            runnable = self._model.with_structured_output(schema, method=method, include_raw=True)
            self._structured[schema] = runnable
        result = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw_msg = result.get("raw") if isinstance(result, dict) else None
        meta = getattr(raw_msg, "usage_metadata", None) or {}
        self.last_usage = {"input_tokens": int(meta.get("input_tokens", 0)), "output_tokens": int(meta.get("output_tokens", 0))}
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if parsed is not None:
            return parsed
        content = getattr(raw_msg, "content", "") if raw_msg is not None else ""
        try:
            return json.loads(content) if isinstance(content, str) else {}
        except json.JSONDecodeError:
            return {"_invalid": True, "content": str(content)[:500]}


_client_factory: Callable[[], Any] | None = None
_chat_model_factory: Callable[[], Any] | None = None


def set_client_factory(factory: Callable[[], Any] | None) -> None:
    """Inject a raw structured backend (tests). `None` restores the OpenRouter client."""
    global _client_factory
    _client_factory = factory


def set_chat_model_factory(factory: Callable[[], Any] | None) -> None:
    """Inject a chat model for the agent loop (tests)."""
    global _chat_model_factory
    _chat_model_factory = factory


def get_client(usage_sink: Callable[[Usage], None] | None = None, settings: Settings | None = None) -> StructuredCaller:
    settings = settings or get_settings()
    raw = _client_factory() if _client_factory is not None else OpenRouterRawClient(settings)
    try:
        prices: PriceTable | None = load_prices()
    except (OSError, json.JSONDecodeError):
        prices = None
    return StructuredCaller(raw=raw, model_name=settings.chat_model, prices=prices, usd_eur=settings.usd_eur, usage_sink=usage_sink)


def get_chat_model(settings: Settings | None = None, **overrides: Any) -> Any:
    """ChatOpenAI configured for OpenRouter (R-02), or the injected test model."""
    if _chat_model_factory is not None:
        return _chat_model_factory()
    settings = settings or get_settings()
    if not settings.api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (environment or .env)")
    from langchain_openai import ChatOpenAI

    headers = {"X-OpenRouter-Title": settings.app_title}
    if settings.http_referer:
        headers["HTTP-Referer"] = settings.http_referer
    kwargs: dict[str, Any] = dict(
        model=settings.chat_model, base_url=OPENROUTER_BASE_URL, api_key=settings.api_key, default_headers=headers,
        stream_usage=True, use_responses_api=False, max_retries=3, temperature=0,
        extra_body={"provider": {"require_parameters": True}} if settings.structured_method == "json_schema" else None,
    )
    kwargs.update(overrides)
    return ChatOpenAI(**{k: v for k, v in kwargs.items() if v is not None})


# --------------------------------------------------------------------------- price refresh CLI
def refresh_prices(settings: Settings | None = None, path: Path | None = None) -> PriceTable:
    """Rewrite data/model_prices.json from OpenRouter's model lists (USD per 1M tokens)."""
    import datetime as _dt

    import requests

    settings = settings or get_settings()
    path = Path(path or PRICES_PATH)
    current = load_prices(path)
    wanted = set(current.models) | {settings.chat_model, settings.embed_model}
    found: dict[str, dict[str, float]] = {}
    for url in (f"{OPENROUTER_BASE_URL}/models", f"{OPENROUTER_BASE_URL}/embeddings/models"):
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        for m in resp.json().get("data", []):
            mid = m.get("id")
            if mid in wanted:
                pricing = m.get("pricing", {})
                found[mid] = {"input": float(pricing.get("prompt", 0)) * 1_000_000,
                              "output": float(pricing.get("completion", 0) or 0) * 1_000_000}
    models = dict(current.models)
    models.update(found)
    payload = {"as_of": _dt.date.today().isoformat(), "currency": "USD", "unit": "per_1M_tokens",
               "source": "https://openrouter.ai/api/v1/models and /api/v1/embeddings/models", "models": models}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_prices(path)


if __name__ == "__main__":
    if "--refresh-prices" in sys.argv:
        table = refresh_prices()
        print(f"prices refreshed ({table.as_of}): {', '.join(table.models)}")
    else:
        print("usage: python -m agent.llm --refresh-prices")
