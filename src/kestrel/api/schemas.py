"""Request and response models for Kestrel's API, and form validation (contracts/kestrel-api.md, FR-004)."""
from __future__ import annotations

import re
import uuid
from typing import Literal, Protocol
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


class AttackerOut(BaseModel):
    model: str
    configured: bool  # False when no attacker key is set; an adaptive run then cannot start (FR-016)


class AdaptiveCapsOut(BaseModel):
    max_turns: int
    token_budget: int
    time_limit_s: int


class ExperienceOut(BaseModel):
    pattern_k: int
    memory_cap: int
    use_prior_experience_default: bool  # the screen defaults the toggle to this (feature 004, FR-014)


class ConfigOut(BaseModel):
    mode: Literal["local", "hosted"]
    defaults: FormDefaults
    terms: TermsOut
    judge: JudgeOut
    attacker: AttackerOut
    adaptive: AdaptiveCapsOut
    experience: ExperienceOut


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
    description: str | None = None  # feature 004: optional one-line purpose, non-secret (FR-020)


class RunRequest(BaseModel):
    target_id: int
    family: str
    prompt_id: str | None = None  # None lets Kestrel pick one from the family (FR-007)
    mode: Literal["single_turn", "adaptive"] = "single_turn"  # adaptive = the multi-turn loop (feature 003)
    use_prior_experience: bool = True  # feature 004: warm (default) retrieves patterns/memory; cold is feature 003


class TurnOut(BaseModel):
    """One turn of an adaptive run's conversation, masked (feature 003, FR-020)."""
    position: int
    attacker_message: str
    reply_text: str | None
    reply_truncated: bool
    judge_verdict: str | None
    judge_reason: str | None
    judge_progress: str | None


class RunSummary(BaseModel):
    id: int
    target_id: int
    mode: str
    prompt_id: str
    prompt_title: str
    family: str
    owasp_category: str
    verdict: str | None
    hard_evidence: bool
    judge_used: bool
    judge_model: str | None  # in the summary so the runs table can show "judge · <model>" (contracts/ui-screen.md)
    failure_step: str | None
    started_at: str
    finished_at: str | None
    memory_written: bool | None = None  # feature 004: null not attempted, false failed (warning), true written
    use_prior_experience: bool = True   # feature 004: warm or cold, recorded on the run (FR-014)


class RunDetail(RunSummary):
    status: str
    prompt_text: str
    reply_text: str | None
    reply_truncated: bool
    reason: str | None
    attacker_source: str
    # Adaptive runs (feature 003); null/empty for single-turn.
    attacker_model: str | None = None
    turn_budget: int | None = None
    turns_used: int | None = None
    token_budget: int | None = None
    tokens_used: int | None = None
    time_limit_s: int | None = None
    stopping_condition: str | None = None
    succeeded_turn: int | None = None
    turns: list[TurnOut] = Field(default_factory=list)


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
    description: str | None = None  # feature 004 (FR-020)


class TargetDetail(TargetSummary):
    body_template: str
    response_path: str
    headers: list[HeaderOut]
    canaries: list[str]


class FamilyCount(BaseModel):
    family: str
    count: int


class VerdictCount(BaseModel):
    verdict: str
    count: int


class RecentMemory(BaseModel):
    summary: str
    family: str
    verdict: str
    created_at: str


class ProfileOut(BaseModel):
    """A per-target summary from its memory records — summaries and non-secret metadata only (FR-023)."""
    target_id: int
    total_runs: int
    by_family: list[FamilyCount]
    by_verdict: list[VerdictCount]
    recent: list[RecentMemory]


# ---- experiments (feature 007, A/B harness) ----

class ArmIn(BaseModel):
    """One arm's configuration (FR-002). Model names and settings only - never a secret (Principle IV)."""
    attacker_model: str
    judge_model: str
    use_prior_experience: bool
    turn_cap: int = 6
    token_budget: int = 40000
    write_back: bool = True


class CapsIn(BaseModel):
    """Hard caps; each None falls back to the configured default (FR-008)."""
    max_runs: int | None = None
    token_budget_total: int | None = None
    wall_clock_s: int | None = None


class CreateExperimentRequest(BaseModel):
    target_id: int
    mode: Literal["single_turn", "adaptive"] = "adaptive"
    families: list[str] | None = None   # None = all families (FR-001)
    reps: int = 3
    caps: CapsIn = Field(default_factory=CapsIn)
    arm_a: ArmIn
    arm_b: ArmIn


class RateOut(BaseModel):
    successes: int
    n: int
    rate: float | None                  # None = no data (never a spurious 0%)
    ci: tuple[float, float] | None


class CategoryCountOut(BaseModel):
    key: str
    confirmed: int
    suspected: int
    n: int


class ArmResultOut(BaseModel):
    label: str
    attacker_model: str
    judge_model: str
    run_order: int | None
    completed: int
    send_failures: int
    confirmed: RateOut
    suspected: RateOut
    mean_turns_to_success: float | None
    mean_tokens: float | None
    cost: float | None
    cost_note: str | None
    by_family: list[CategoryCountOut]
    by_owasp: list[CategoryCountOut]


class ComparisonOut(BaseModel):
    confirmed: dict                     # two_proportion(...) on the confirmed rate (the primary verdict)
    suspected_diff: float | None        # descriptive only (judge opinion, Principle II)


class ArmProgressOut(BaseModel):
    label: str
    run_order: int | None
    completed: int
    planned: int


class ExperimentStatusOut(BaseModel):
    id: int
    status: str
    stopped_reason: str | None
    planned_runs: int
    completed_runs: int
    tokens_used: int
    cost: float | None
    arms: list[ArmProgressOut]


class ExperimentResultOut(BaseModel):
    id: int
    status: str
    stopped_reason: str | None
    mode: str
    families: list[str]
    reps: int
    diff: list[str]                     # the recorded arm diff (FR-003)
    order: str                          # e.g. "A then B" (FR-005)
    warming: str                        # e.g. "A cold (no write-back); B warm" (FR-005)
    arms: list[ArmResultOut]
    comparison: ComparisonOut


class ExperimentSummaryOut(BaseModel):
    id: int
    target_id: int
    status: str
    mode: str
    created_at: str
    finished_at: str | None


ARM_DIFF_FIELDS = ("attacker_model", "judge_model", "use_prior_experience", "turn_cap", "token_budget")


def validate_experiment(request: CreateExperimentRequest, known_families: list[str]) -> list[dict[str, str]]:
    """Arms must differ in >=1 field; families (if given) known and non-empty; reps/caps sane (FR-003, FR-008)."""
    errors: list[dict[str, str]] = []
    if all(getattr(request.arm_a, f) == getattr(request.arm_b, f) for f in ARM_DIFF_FIELDS):
        errors.append({"field": "arm_b", "message": "The two arms must differ in at least one setting."})
    if request.families is not None:
        if not request.families:
            errors.append({"field": "families", "message": "Choose at least one attack family."})
        for i, family in enumerate(request.families):
            if family not in known_families:
                errors.append({"field": f"families.{i}", "message": f"Unknown attack family {family!r}."})
    if request.reps < 1:
        errors.append({"field": "reps", "message": "reps must be at least 1."})
    for name in ("max_runs", "token_budget_total", "wall_clock_s"):
        value = getattr(request.caps, name)
        if value is not None and value < 1:
            errors.append({"field": f"caps.{name}", "message": f"{name} must be at least 1."})
    return errors


class _ArmLike(Protocol):
    """Either an ArmIn (request) or a store ExperimentArm; both carry the arm fields (read-only suffices)."""
    @property
    def attacker_model(self) -> str: ...
    @property
    def judge_model(self) -> str: ...
    @property
    def use_prior_experience(self) -> bool: ...
    @property
    def turn_cap(self) -> int: ...
    @property
    def token_budget(self) -> int: ...


def experiment_diff(arm_a: _ArmLike, arm_b: _ArmLike) -> list[str]:
    """Human-readable differences between the two arms (FR-003)."""
    labels = {"use_prior_experience": "retrieval"}
    out = []
    for field in ARM_DIFF_FIELDS:
        a, b = getattr(arm_a, field), getattr(arm_b, field)
        if a != b:
            name = labels.get(field, field)
            if isinstance(a, bool):
                a, b = ("on" if a else "off"), ("on" if b else "off")
            out.append(f"{name}: A={a}, B={b}")
    return out


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
    if request.description is not None and len(request.description.strip()) > 200:
        errors.append({"field": "description", "message": "Keep the description to 200 characters or fewer."})
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
