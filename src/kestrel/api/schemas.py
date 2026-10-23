"""Request and response models for Kestrel's API, and form validation (contracts/kestrel-api.md, FR-004)."""
from __future__ import annotations

import re
import uuid
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, Field

from kestrel.connection.response_path import PathSyntaxError, parse
from kestrel.connection.template import TemplateError, validate

HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
RESERVED_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}
CREDENTIAL_WORDS = ("key", "token", "secret", "password", "auth", "api_key", "apikey", "access_token",
                    "code", "sig", "signature")
URL_CREDENTIALS_MESSAGE = "put credentials in an auth header, not the URL"
MIN_HEADER_VALUE_LENGTH = 4


class FormDefaults(BaseModel):
    method: Literal["POST", "GET"]
    body_template: str
    response_path: str


class TermsOut(BaseModel):
    version: str
    text: str


class JudgeOut(BaseModel):
    model: str
    configured: bool  # False when no judge key is set; canary evidence still works (FR-021)


class ConfigOut(BaseModel):
    mode: Literal["local", "hosted"]
    defaults: FormDefaults
    terms: TermsOut
    judge: JudgeOut


class HeaderIn(BaseModel):
    name: str
    value: str | None = Field(default=None, repr=False)  # None keeps the stored value; never in a repr


class ConnectionSettingsIn(BaseModel):
    url: str = ""
    method: Literal["POST", "GET"] = "POST"
    headers: list[HeaderIn] = Field(default_factory=list)
    body_template: str = ""
    response_path: str = ""


class ConnectionTestRequest(BaseModel):
    form_id: uuid.UUID
    target_id: int | None = None
    display_name: str = ""  # only used in the log line; required to save, not to test
    settings: ConnectionSettingsIn


class ConnectionTestResult(BaseModel):
    ok: bool
    step: str
    message: str
    detail: str | None
    status_code: int | None
    reply_text: str | None
    reply_truncated: bool
    duration_ms: int


class SaveTargetRequest(BaseModel):
    form_id: uuid.UUID
    name: str = ""
    settings: ConnectionSettingsIn
    permission_confirmed: bool = False
    terms_version: str = ""
    # None means "not provided" (on PUT, keep the stored canaries); [] clears them (contracts/kestrel-api.md).
    canaries: list[str] | None = None


class RunRequest(BaseModel):
    target_id: int
    family: str
    prompt_id: str | None = None  # None lets Kestrel pick one from the family (FR-007)


class RunSummary(BaseModel):
    id: int
    target_id: int
    prompt_id: str
    prompt_title: str
    family: str
    owasp_category: str
    verdict: str | None
    hard_evidence: bool
    judge_used: bool
    failure_step: str | None
    started_at: str
    finished_at: str | None


class RunDetail(RunSummary):
    status: str
    prompt_text: str
    reply_text: str | None
    reply_truncated: bool
    reason: str | None
    judge_model: str | None
    attacker_source: str


class AttackPromptOut(BaseModel):
    id: str
    title: str
    text: str
    family: str
    owasp_category: str
    source: str


class AttackFamilyOut(BaseModel):
    key: str
    label: str
    owasp_category: str
    prompt_count: int


class HeaderOut(BaseModel):
    """A stored header: its name only, never its value (FR-021)."""
    name: str
    has_value: bool
    readable: bool


class TargetSummary(BaseModel):
    id: int
    name: str
    url: str
    method: str
    permission_confirmed_at: str
    terms_version: str


class TargetDetail(TargetSummary):
    body_template: str
    response_path: str
    headers: list[HeaderOut]
    canaries: list[str]


def validate_save(request: SaveTargetRequest, terms_version: str) -> list[dict[str, str]]:
    """The save-only rules (FR-004, FR-011, FR-029); the connection settings are checked by validate_settings."""
    errors = []
    if not 1 <= len(request.name.strip()) <= 100:
        errors.append({"field": "name", "message": "Enter a display name of 1 to 100 characters."})
    if not request.permission_confirmed:
        errors.append({"field": "permission_confirmed",
                       "message": "Tick the box to confirm you own this agent or have written permission to test it."})
    if request.terms_version != terms_version:
        errors.append({"field": "terms_version",
                       "message": "The terms of service have changed; read them and tick the box again."})
    return errors


MIN_CANARY_LENGTH = 8


def validate_canaries(canaries: list[str] | None) -> list[dict[str, str]]:
    """Each canary at least 8 characters and unique within the target (FR-024, FR-025)."""
    if canaries is None:
        return []
    errors = []
    seen: set[str] = set()
    for i, value in enumerate(canaries):
        if len(value) < MIN_CANARY_LENGTH:
            errors.append({"field": f"canaries.{i}",
                           "message": f"A canary string must be at least {MIN_CANARY_LENGTH} characters."})
        elif value in seen:
            errors.append({"field": f"canaries.{i}", "message": "This canary string appears more than once."})
        seen.add(value)
    return errors


def url_carries_credentials(url: str) -> bool:
    """A user name or password before the host, or a query parameter named like a credential (research R9)."""
    parts = urlsplit(url)
    if "@" in parts.netloc:
        return True
    for name, _ in parse_qsl(parts.query, keep_blank_values=True):
        normalized = name.strip().lower().replace("-", "_")
        if normalized in CREDENTIAL_WORDS or any(normalized.endswith("_" + word) for word in CREDENTIAL_WORDS):
            return True
    return False


def _is_http_url(url: str) -> bool:
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # raises ValueError for an invalid port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def validate_settings(settings: ConnectionSettingsIn, *, has_target: bool) -> list[dict[str, str]]:
    """Every problem with the connection settings, one per field; messages never repeat submitted values."""
    errors: dict[str, str] = {}

    def add(field: str, message: str) -> None:
        errors.setdefault(field, message)

    url = settings.url.strip()
    if not url:
        add("settings.url", "Enter the endpoint URL.")
    elif not _is_http_url(url):
        add("settings.url", "Enter a full http:// or https:// address.")
    elif url_carries_credentials(url):
        add("settings.url", URL_CREDENTIALS_MESSAGE)

    path = settings.response_path.strip()
    if not path:
        add("settings.response_path", "Enter the response path, for example $.reply.")
    else:
        try:
            parse(path)
        except PathSyntaxError as error:
            add("settings.response_path", str(error))

    seen: set[str] = set()
    for i, header in enumerate(settings.headers):
        name = header.name.strip()
        if not HEADER_NAME.match(name):
            add(f"settings.headers.{i}.name", "Use a valid header name: letters, digits and !#$%&'*+-.^_`|~ only.")
        elif name.lower() in RESERVED_HEADERS:
            add(f"settings.headers.{i}.name", "Kestrel sets this header itself; remove it.")
        elif name.lower() in seen:
            add(f"settings.headers.{i}.name", "This header appears more than once.")
        seen.add(name.lower())
        if header.value is None:
            if not has_target:
                add(f"settings.headers.{i}.value", "Enter a value for this header.")
        elif len(header.value) < MIN_HEADER_VALUE_LENGTH:
            add(f"settings.headers.{i}.value", "Auth header values must be at least 4 characters.")

    if url:
        try:
            validate(settings.method, url, settings.body_template)
        except TemplateError as error:
            add(error.field, error.message)

    return [{"field": field, "message": message} for field, message in errors.items()]
