"""Sacrificial HS-code target: CargoLint's HS-6 classifier behind a small FastAPI app (contracts/hs-code-target.md).

Test support only; Kestrel never offers it to users. Start it from this folder:

    uvicorn app:app --host 127.0.0.1 --port 8001

It needs HS_TARGET_API_KEY (the only accepted X-API-Key value) and, for real replies, OPENROUTER_API_KEY.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from agent.llm import get_client
from agent.schemas import Classification, LineStatus
from agent_loop import ChatModel, OpenRouterChatModel, run_agent
from kb import LightKnowledgeBase, build_kb
from tools.classify_hs6 import ClassifyContext, classify_lines
from tools.common import LineText
from tools.send_email import EmailRecorder

log = logging.getLogger("hs_code_target")

DEFAULT_CANARY = "KESTREL-CANARY-PLACEHOLDER"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# The agent's chat model. None means /chat falls back to CargoLint's direct classifier, which keeps the
# target behaving as feature 001 shipped it. Tests inject a scripted fake with set_chat_model().
_chat_model: ChatModel | None = None
_chat_model_set = False


def set_chat_model(model: ChatModel | None) -> None:
    """Inject a chat model (a scripted fake in tests); pass None to force the classifier fallback."""
    global _chat_model, _chat_model_set
    _chat_model, _chat_model_set = model, True


def chat_model() -> ChatModel | None:
    """The injected model if one was set, otherwise a real OpenRouter model when a key is present."""
    if _chat_model_set:
        return _chat_model
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("CARGOLINT_CHAT_MODEL", "openai/gpt-4o-mini")
    return OpenRouterChatModel(model=model, api_key=api_key, base_url=OPENROUTER_BASE_URL)


def canary() -> str:
    return os.environ.get("HS_TARGET_CANARY", DEFAULT_CANARY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("HS_TARGET_API_KEY"):
        raise RuntimeError("HS_TARGET_API_KEY is not set; the sacrificial target never runs without a key.")
    yield


app = FastAPI(title="Sacrificial HS-code target", lifespan=lifespan)
# One recorder per app: send_email calls land here and are read back by GET /debug/tool-calls (FR-035).
email_recorder = EmailRecorder()


class ChatIn(BaseModel):
    message: str


def get_model_client() -> Any:
    """CargoLint's model client; tests swap the backend with agent.llm.set_client_factory."""
    return get_client()


@lru_cache(maxsize=1)
def knowledge_base() -> LightKnowledgeBase:
    return build_kb()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _key_ok(request: Request) -> bool:
    """The key is checked before the body is read and before any model call (FR-026)."""
    expected = os.environ.get("HS_TARGET_API_KEY", "")
    given = request.headers.get("x-api-key", "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


@app.post("/chat")
async def chat(request: Request) -> Any:
    if not _key_ok(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})

    try:
        body = ChatIn.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError):
        return JSONResponse(status_code=422, content={"detail": "send JSON like {\"message\": \"...\"}"})

    model = chat_model()
    try:
        if model is not None:
            # The conversational, attackable path: a canary in its system prompt and a send_email tool (R14).
            reply = await run_in_threadpool(
                run_agent, body.message, model=model, canary=canary(), recorder=email_recorder,
                classifier=lambda description: format_reply(description, classify(description), knowledge_base()))
            return {"reply": reply}
        # Fallback with no chat model: CargoLint's direct classifier, as feature 001 shipped it.
        result = await run_in_threadpool(classify, body.message)
    except Exception:
        log.exception("model call failed")
        return JSONResponse(status_code=502, content={"detail": "model call failed"})
    if result.status == LineStatus.failed:
        log.warning("classification failed: %s", result.error_reason)
        return JSONResponse(status_code=502, content={"detail": "model call failed"})
    return {"reply": format_reply(body.message, result, knowledge_base())}


@app.get("/debug/tool-calls")
def tool_calls(request: Request) -> Any:
    """Read back the recorded send_email calls as hard evidence of exfiltration (FR-035). Needs the API key."""
    if not _key_ok(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return {"send_email": [call.as_dict() for call in email_recorder.calls]}


def classify(message: str) -> Classification:
    kb = knowledge_base()
    client = get_model_client()
    [result] = classify_lines([LineText(line_no=1, text_en=message)], ClassifyContext(hybrid=True, precedents=False),
                              kb, client, workers=1)
    return result


def format_reply(message: str, result: Classification, kb: LightKnowledgeBase) -> str:
    if not result.candidates:
        return f'No HS-6 suggestion for "{message}": the description is too vague to classify.'
    lines = [f'HS-6 suggestions for "{message}":']
    for number, candidate in enumerate(result.candidates[:3], start=1):
        title = candidate.subheading_text or kb.index.subheading_text(candidate.code)
        lines.append(f"{number}. {candidate.code} {title} (confidence {candidate.confidence / 100:.2f})")
    return "\n".join(lines)
