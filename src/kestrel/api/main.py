"""Kestrel's FastAPI app. Run it with: uvicorn --factory kestrel.api.main:create_app"""
from __future__ import annotations

import logging
import sys
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kestrel.api.schemas import ConfigOut, FormDefaults
from kestrel.secrets import Vault, load_or_create_key
from kestrel.settings import Settings, load_settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULTS = FormDefaults(method="POST", body_template='{"message": "{{prompt}}"}', response_path="$.reply")


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
               resolver: Any = None) -> FastAPI:
    """Build the app. Tests pass settings, an httpx transport standing in for targets, and a fake resolver."""
    settings = settings or load_settings()
    logger = _configure_logging()
    key, _source = load_or_create_key(settings, logger)

    app = FastAPI(title="Kestrel API", version="0.1.0")
    app.state.settings = settings
    app.state.vault = Vault(key)
    app.state.transport = transport
    app.state.resolver = resolver
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/api/config", response_model=ConfigOut)
    def get_config() -> ConfigOut:
        return ConfigOut(mode=settings.mode, defaults=DEFAULTS)

    return app


def form_errors(errors: list[dict[str, str]]) -> JSONResponse:
    """A 422 in the contract's format; messages never contain submitted values."""
    return JSONResponse(status_code=422, content={"errors": errors})


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default handler echoes the submitted input; this one keeps only field and message (research R9).
    return form_errors([_field_error(error) for error in exc.errors()])


def _field_error(error: dict[str, Any]) -> dict[str, str]:
    if error.get("type") == "json_invalid":
        return {"field": "body", "message": "The request body isn't valid JSON."}
    field = ".".join(str(part) for part in error.get("loc", ()) if part != "body") or "body"
    message = str(error.get("msg") or "Invalid value.").removeprefix("Value error, ")
    return {"field": field, "message": message}


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("kestrel")
    logger.setLevel(logging.INFO)
    if not any(getattr(handler, "_kestrel", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._kestrel = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger
