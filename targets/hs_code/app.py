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
from kb import LightKnowledgeBase, build_kb
from tools.classify_hs6 import ClassifyContext, classify_lines
from tools.common import LineText

log = logging.getLogger("hs_code_target")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("HS_TARGET_API_KEY"):
        raise RuntimeError("HS_TARGET_API_KEY is not set; the sacrificial target never runs without a key.")
    yield


app = FastAPI(title="Sacrificial HS-code target", lifespan=lifespan)


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


@app.post("/chat")
async def chat(request: Request) -> Any:
    # The key is checked before the body is even read, and before any model call (FR-026).
    expected = os.environ.get("HS_TARGET_API_KEY", "")
    given = request.headers.get("x-api-key", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})

    try:
        body = ChatIn.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError):
        return JSONResponse(status_code=422, content={"detail": "send JSON like {\"message\": \"...\"}"})

    try:
        result = await run_in_threadpool(classify, body.message)
    except Exception:
        log.exception("model call failed")
        return JSONResponse(status_code=502, content={"detail": "model call failed"})
    if result.status == LineStatus.failed:
        log.warning("classification failed: %s", result.error_reason)
        return JSONResponse(status_code=502, content={"detail": "model call failed"})
    return {"reply": format_reply(body.message, result, knowledge_base())}


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
