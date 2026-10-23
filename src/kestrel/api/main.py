"""Kestrel's FastAPI app. Run it with: uvicorn --factory kestrel.api.main:create_app"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kestrel.api.schemas import (ConfigOut, ConnectionSettingsIn, ConnectionTestRequest, ConnectionTestResult,
                                 FormDefaults, HeaderOut, SaveTargetRequest, TargetDetail, TargetSummary, TermsOut,
                                 validate_save, validate_settings)
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.sessions import FormSessions
from kestrel.connection.tester import ResolvedSettings, refused, run_test
from kestrel.secrets import Vault, load_or_create_key
from kestrel.settings import Settings, load_settings
from kestrel.store import NameTaken, Target, TargetNotFound, TargetStore

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULTS = FormDefaults(method="POST", body_template='{"message": "{{prompt}}"}', response_path="$.reply")
TERMS_PATH = Path(__file__).with_name("terms.md")
NOT_TESTED = "Run a successful test with these settings before saving."
NAME_TAKEN = "Another saved target already has this name."


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
               resolver: Any = None) -> FastAPI:
    """Build the app. Tests pass settings, an httpx transport standing in for targets, and a fake resolver."""
    settings = settings or load_settings()
    logger = _configure_logging()
    key, _source = load_or_create_key(settings, logger)
    vault = Vault(key)
    terms = load_terms()
    store = TargetStore(settings.db_path, vault)
    if not store.key_matches():
        logger.error("The encryption key doesn't match the one used to save targets, so saved auth header values "
                     "can't be read. Restore the old key, or re-enter the values.")

    app = FastAPI(title="Kestrel API", version="0.1.0")
    app.state.settings = settings
    app.state.vault = vault
    app.state.store = store
    app.state.transport = transport
    app.state.resolver = resolver or default_resolver
    app.state.sessions = FormSessions()
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/api/config", response_model=ConfigOut)
    def get_config() -> ConfigOut:
        return ConfigOut(mode=settings.mode, defaults=DEFAULTS, terms=terms)

    @app.post("/api/connection-tests", response_model=ConnectionTestResult)
    async def connection_test(body: ConnectionTestRequest, request: Request) -> Any:
        errors = validate_settings(body.settings, has_target=body.target_id is not None)
        if errors:
            return form_errors(errors)
        stored: dict[str, str | None] | None = None
        if body.target_id is not None:
            try:
                stored = stored_values(store, body.target_id)
            except TargetNotFound:
                return not_found(body.target_id)
            errors = kept_value_errors(body.settings, stored)
            if errors:
                return form_errors(errors)

        resolved = resolve(body.settings, stored)
        display_name = body.display_name.strip()
        form_id = str(body.form_id)
        sessions: FormSessions = request.app.state.sessions
        if not sessions.start(form_id):
            return api_error(409, "test_in_progress", "A test for this form is already running.")
        fingerprint = None
        try:
            if stored is not None and needs_unreadable_value(body.settings, stored):
                return refused("credentials_unreadable", resolved, display_name).as_dict()  # nothing is sent
            result = await run_test(resolved, mode=settings.mode, display_name=display_name,
                                    transport=request.app.state.transport, resolver=request.app.state.resolver)
            if result.ok:
                fingerprint = sessions.fingerprint(resolved)
        finally:
            sessions.finish(form_id, fingerprint)
        return result.as_dict()

    @app.get("/api/targets", response_model=list[TargetSummary])
    def list_targets() -> list[TargetSummary]:
        return [summary(target) for target in store.list_targets()]

    @app.post("/api/targets", status_code=201, response_model=TargetDetail)
    def save_target(body: SaveTargetRequest, request: Request) -> Any:
        errors = validate_settings(body.settings, has_target=False) + validate_save(body, terms.version)
        if errors:
            return form_errors(errors)
        resolved = resolve(body.settings)
        sessions: FormSessions = request.app.state.sessions
        if sessions.last_success(str(body.form_id)) != sessions.fingerprint(resolved):
            return api_error(409, "not_tested", NOT_TESTED)
        try:
            target = store.create_target(name=body.name.strip(), url=resolved.url, method=resolved.method,
                                         headers=list(resolved.headers), body_template=resolved.body_template,
                                         response_path=resolved.response_path, terms_version=terms.version)
        except NameTaken:
            return api_error(409, "name_taken", NAME_TAKEN, field="name")
        return detail(target)

    @app.get("/api/targets/{target_id}", response_model=TargetDetail)
    def get_target(target_id: int) -> Any:
        try:
            return detail(store.get_target(target_id))
        except TargetNotFound:
            return not_found(target_id)

    @app.put("/api/targets/{target_id}", response_model=TargetDetail)
    def update_target(target_id: int, body: SaveTargetRequest, request: Request) -> Any:
        try:
            existing = store.get_target(target_id)
            stored = stored_values(store, target_id)
        except TargetNotFound:
            return not_found(target_id)
        errors = (validate_settings(body.settings, has_target=True) + kept_value_errors(body.settings, stored)
                  + validate_save(body, terms.version))
        if errors:
            return form_errors(errors)

        resolved = resolve(body.settings, stored)
        current = ResolvedSettings(url=existing.url, method=existing.method,
                                   headers=tuple((h.name, stored[h.name.lower()] or "") for h in existing.headers),
                                   body_template=existing.body_template, response_path=existing.response_path)
        sessions: FormSessions = request.app.state.sessions
        changed = sessions.fingerprint(resolved) != sessions.fingerprint(current)  # a name-only edit needs no test
        if changed and sessions.last_success(str(body.form_id)) != sessions.fingerprint(resolved):
            return api_error(409, "not_tested", NOT_TESTED)
        try:
            target = store.update_target(target_id, name=body.name.strip(), url=resolved.url, method=resolved.method,
                                         headers=[(h.name.strip(), h.value) for h in body.settings.headers],
                                         body_template=resolved.body_template, response_path=resolved.response_path,
                                         terms_version=terms.version)
        except NameTaken:
            return api_error(409, "name_taken", NAME_TAKEN, field="name")
        return detail(target)

    @app.delete("/api/targets/{target_id}", status_code=204)
    def delete_target(target_id: int) -> Response:
        try:
            store.delete_target(target_id)
        except TargetNotFound:
            return not_found(target_id)
        return Response(status_code=204)

    return app


def stored_values(store: TargetStore, target_id: int) -> dict[str, str | None]:
    """Stored header values by lower-cased name; None for a value the current key can't decrypt."""
    return {h.name.lower(): h.value for h in store.resolve_headers(target_id)}


def kept_value_errors(settings: ConnectionSettingsIn, stored: dict[str, str | None]) -> list[dict[str, str]]:
    """`value: null` only works for a header the target has stored."""
    return [{"field": f"settings.headers.{i}.value", "message": "Enter a value for this header."}
            for i, header in enumerate(settings.headers)
            if header.value is None and header.name.strip().lower() not in stored]


def needs_unreadable_value(settings: ConnectionSettingsIn, stored: dict[str, str | None]) -> bool:
    return any(h.value is None and stored.get(h.name.strip().lower()) is None for h in settings.headers)


def not_found(target_id: int) -> JSONResponse:
    return api_error(404, "not_found", f"No target with id {target_id}.")


def resolve(settings: ConnectionSettingsIn, stored: dict[str, str | None] | None = None) -> ResolvedSettings:
    """Connection settings with every header value known; `value: null` takes the stored value (FR-017)."""
    stored = stored or {}
    headers = []
    for header in settings.headers:
        name = header.name.strip()
        value = header.value if header.value is not None else stored.get(name.lower())
        headers.append((name, value or ""))
    return ResolvedSettings(url=settings.url.strip(), method=settings.method, headers=tuple(headers),
                            body_template=settings.body_template, response_path=settings.response_path.strip())


def summary(target: Target) -> TargetSummary:
    return TargetSummary(id=target.id, name=target.name, url=target.url, method=target.method,
                         permission_confirmed_at=target.permission_confirmed_at, terms_version=target.terms_version)


def detail(target: Target) -> TargetDetail:
    return TargetDetail(**summary(target).model_dump(), body_template=target.body_template,
                        response_path=target.response_path,
                        headers=[HeaderOut(name=h.name, has_value=True, readable=h.readable) for h in target.headers])


def load_terms(path: Path = TERMS_PATH) -> TermsOut:
    """terms.md starts with a `version: N` line; the rest is the text shown next to the permission checkbox."""
    first, _, rest = path.read_text(encoding="utf-8").partition("\n")
    if not first.startswith("version:"):
        raise RuntimeError(f"{path} must start with a 'version: N' line.")
    return TermsOut(version=first.split(":", 1)[1].strip(), text=rest.strip())


def form_errors(errors: list[dict[str, str]]) -> JSONResponse:
    """A 422 in the contract's format; messages never contain submitted values."""
    return JSONResponse(status_code=422, content={"errors": errors})


def api_error(status: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "field": field, "message": message}})


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
