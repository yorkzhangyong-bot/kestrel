"""Kestrel's settings, read from KESTREL_* environment variables (research R5, R6, R8)."""
from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlsplit

# src/kestrel/settings.py -> the folder holding pyproject.toml
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path("data") / "kestrel.db"
DEFAULT_KEY_FILE = "~/.kestrel/secret.key"
# The judge that decides a run when no canary matched (research R1, contracts/judge.md).
DEFAULT_JUDGE_MODEL = "google/gemini-3.8-flash"
DEFAULT_JUDGE_BASE_URL = "https://openrouter.ai/api/v1"
# The attacker that drives an adaptive run (feature 003): a current DeepSeek chat model via OpenRouter,
# capable, inexpensive and comparatively unrestricted. (The older deepseek-v3.2 slug is now commonly blocked
# by OpenRouter account guardrails; the v4 line is the current, permitted equivalent.)
DEFAULT_ATTACKER_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_ATTACKER_BASE_URL = "https://openrouter.ai/api/v1"
# Hard caps on an adaptive run (Principle VIII; feature 003, research R3).
DEFAULT_ADAPTIVE_MAX_TURNS = 6
DEFAULT_ADAPTIVE_TOKEN_BUDGET = 40000
DEFAULT_ADAPTIVE_TIME_LIMIT_S = 300
# The experience store (feature 004): local ChromaDB next to the SQLite file, and retrieval bounds (research R12).
DEFAULT_CHROMA_PATH = Path("data") / "chroma"
DEFAULT_EXPERIENCE_PATTERN_K = 5
DEFAULT_EXPERIENCE_MEMORY_CAP = 10
# Retrieval controls (feature 011, research D6): a candidate farther than the floor from the query is dropped, and
# hits or successes within the threshold of each other are near-identical. Both are collection `l2` distances
# (squared Euclidean between normalised vectors, 0–4) measured on the shipped model `all-MiniLM-L6-v2`; a different
# embedding model needs retuned values. `None` switches a control off (the literal `off` in the environment).
DEFAULT_EXPERIENCE_DISTANCE_FLOOR = 1.8
DEFAULT_EXPERIENCE_DEDUPE_THRESHOLD = 0.15
# Experiment hard-cap defaults (feature 007, Principle VIII; research R9). Finite and overridable per experiment.
DEFAULT_EXPERIMENT_MAX_RUNS = 50
DEFAULT_EXPERIMENT_TOKEN_BUDGET = 500_000
DEFAULT_EXPERIMENT_WALL_CLOCK_S = 3600
# Regression replay (feature 012): the most replayable runs one batch replay processes for a target (FR-031),
# confirmed with the product owner (spec.md Clarifications, 2026-11-19).
DEFAULT_REPLAY_BATCH_MAX_RUNS = 20
# Behavioural evidence (feature 013): the canary callback listener's bounded wait after each reply of a run that
# planted a URL (FR-030), and the side-channel request timeout (FR-021); the listener's public base URL has no
# default (unset = disabled, FR-027). The base URL's path must end in the listener route's own prefix.
DEFAULT_CALLBACK_WAIT_S = 2.0
DEFAULT_SIDE_CHANNEL_TIMEOUT_S = 10
CALLBACK_PATH_SUFFIX = "/callback"
# LangGraph checkpointer and idle auto-stop (feature 014, research D28): a paused/resumable/stoppable row with
# nobody acting on it this long is stopped automatically. Ten years is a sentinel upper bound, not a real wait.
DEFAULT_RESUME_IDLE_HOURS = 24.0
MAX_RESUME_IDLE_HOURS = 87_600.0

Mode = Literal["local", "hosted"]
LogFormat = Literal["json", "text"]


class SettingsError(Exception):
    """A setting is invalid, so Kestrel refuses to start."""


@dataclass(frozen=True)
class RetrievalSettings:
    """What one pattern retrieval reads (feature 011): the bound k, the distance floor and the near-identical
    threshold — each of the last two `None` when switched off."""
    k: int
    distance_floor: float | None
    dedupe_threshold: float | None


@dataclass(frozen=True)
class Settings:
    mode: Mode
    db_path: Path
    key_file: Path
    secret_key: str | None
    judge_model: str = DEFAULT_JUDGE_MODEL
    judge_base_url: str = DEFAULT_JUDGE_BASE_URL
    judge_api_key: str | None = field(default=None, repr=False)  # a key never belongs in a repr
    attacker_model: str = DEFAULT_ATTACKER_MODEL
    attacker_base_url: str = DEFAULT_ATTACKER_BASE_URL
    attacker_api_key: str | None = field(default=None, repr=False)
    api_token: str | None = field(default=None, repr=False)  # hosted API access token (require_token); never logged
    adaptive_max_turns: int = DEFAULT_ADAPTIVE_MAX_TURNS
    adaptive_token_budget: int = DEFAULT_ADAPTIVE_TOKEN_BUDGET
    adaptive_time_limit_s: int = DEFAULT_ADAPTIVE_TIME_LIMIT_S
    chroma_path: Path = REPO_ROOT / DEFAULT_CHROMA_PATH
    experience_pattern_k: int = DEFAULT_EXPERIENCE_PATTERN_K
    experience_memory_cap: int = DEFAULT_EXPERIENCE_MEMORY_CAP
    # Feature 011: the retrieval controls; None = off.
    experience_distance_floor: float | None = DEFAULT_EXPERIENCE_DISTANCE_FLOOR
    experience_dedupe_threshold: float | None = DEFAULT_EXPERIENCE_DEDUPE_THRESHOLD
    # Feature 007 (A/B harness).
    model_prices: Mapping[str, float] = field(default_factory=dict)  # USD per 1,000 tokens (FR-006)
    experiment_max_runs: int = DEFAULT_EXPERIMENT_MAX_RUNS
    experiment_token_budget: int = DEFAULT_EXPERIMENT_TOKEN_BUDGET
    experiment_wall_clock_s: int = DEFAULT_EXPERIMENT_WALL_CLOCK_S
    # Feature 012 (regression replay).
    replay_batch_max_runs: int = DEFAULT_REPLAY_BATCH_MAX_RUNS
    # Feature 013 (behavioural evidence): the callback listener's base URL (None = disabled), its bounded wait, and
    # the side-channel request timeout. The URL names Kestrel's own listener, never a target: not a secret.
    callback_base_url: str | None = None
    callback_wait_s: float = DEFAULT_CALLBACK_WAIT_S
    side_channel_timeout_s: int = DEFAULT_SIDE_CHANNEL_TIMEOUT_S
    # Feature 010: the stream's format (JSON Lines by default) and the optional OpenTelemetry tracing flag.
    log_format: LogFormat = "json"
    tracing: bool = False
    # Feature 014: the idle auto-stop window for a paused/resumable/stoppable checkpointed run (research D28).
    resume_idle_hours: float = DEFAULT_RESUME_IDLE_HOURS

    @property
    def judge_configured(self) -> bool:
        """Without a key there is no judge, but canary evidence still decides runs (FR-021)."""
        return self.judge_api_key is not None

    @property
    def attacker_configured(self) -> bool:
        """Without a key there is no attacker, so an adaptive run cannot start (FR-016)."""
        return self.attacker_api_key is not None

    @property
    def retrieval(self) -> RetrievalSettings:
        """The one value the retrieval path reads (feature 011, contracts/retrieval.md)."""
        return RetrievalSettings(k=self.experience_pattern_k, distance_floor=self.experience_distance_floor,
                                 dedupe_threshold=self.experience_dedupe_threshold)


def _parse_prices(raw: str) -> dict[str, float]:
    """Parse ``KESTREL_MODEL_PRICES`` ("model=price,model=price") into a mapping (feature 007, FR-006)."""
    prices: dict[str, float] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, value = entry.partition("=")
        name = name.strip()
        if not sep or not name:
            raise SettingsError(f"KESTREL_MODEL_PRICES entries look like 'model=price', not {entry!r}.")
        try:
            price = float(value.strip())
        except ValueError:
            raise SettingsError(
                f"KESTREL_MODEL_PRICES price for {name!r} must be a number, not {value.strip()!r}.") from None
        if price < 0:
            raise SettingsError(f"KESTREL_MODEL_PRICES price for {name!r} must not be negative.")
        prices[name] = price
    return prices


def callback_base_class(url: str) -> str:
    """How the listener's host would look to a target (feature 013, FR-068): `loopback`, `private` (a private,
    link-local or otherwise non-routable address, or a name under `.localhost`) or `public` (a public address, or a
    host name Kestrel does not resolve here — the per-run check compares it with the target's own host). Pure:
    never resolves a name, so loading the settings costs no network call."""
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return "loopback"
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return "public"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved or ip.is_multicast:
        return "private"
    return "private" if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10") else "public"


def validate_callback_base(url: str) -> str:
    """The start-up check of `KESTREL_CALLBACK_BASE_URL` (feature 013, FR-027, FR-068): an http or https URL with
    a host, no credentials, no query or fragment, whose path ends in the listener route's own `/callback` prefix
    (Kestrel appends `/<token>` to it). Returns the base with any trailing slash removed; raises SettingsError
    loudly for anything else, so a base that could never reach the route is never accepted silently."""
    name = "KESTREL_CALLBACK_BASE_URL"
    malformed = SettingsError(f"{name} must be a full http:// or https:// URL ending in {CALLBACK_PATH_SUFFIX}.")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise malformed
    try:
        parts = urlsplit(url)
        parts.port   # raises ValueError for an invalid port
    except ValueError:
        raise malformed from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise malformed
    if "@" in parts.netloc:
        raise SettingsError(f"{name} must not carry credentials; the listener needs none.")
    if parts.query or parts.fragment:
        raise SettingsError(f"{name} must not carry a query or fragment; Kestrel appends the token to its path.")
    base = url.rstrip("/")
    if not base.endswith(CALLBACK_PATH_SUFFIX):
        raise SettingsError(f"{name} must end in {CALLBACK_PATH_SUFFIX}, the listener route's own prefix.")
    callback_base_class(base)   # classifiable now, so the per-run usability check (FR-068) never surprises later
    return base


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    raw_mode = (env.get("KESTREL_MODE") or "").strip()
    if not raw_mode:
        mode: Mode = "hosted"
    elif raw_mode in ("local", "hosted"):
        mode = raw_mode  # type: ignore[assignment]
    else:
        raise SettingsError(f"KESTREL_MODE must be 'local' or 'hosted', not {raw_mode!r}.")

    db_path = Path(env.get("KESTREL_DB_PATH") or DEFAULT_DB_PATH)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path

    chroma_path = Path(env.get("KESTREL_CHROMA_PATH") or DEFAULT_CHROMA_PATH)
    if not chroma_path.is_absolute():
        chroma_path = REPO_ROOT / chroma_path

    key_file = Path(env.get("KESTREL_KEY_FILE") or DEFAULT_KEY_FILE).expanduser()

    def setting(name: str, default: str = "") -> str:
        return (env.get(name) or "").strip() or default

    # KESTREL_JUDGE_API_KEY wins; OPENROUTER_API_KEY is the fallback, because the sacrificial
    # target already uses it and a single key is one less thing to set up (contracts/judge.md).
    judge_api_key = setting("KESTREL_JUDGE_API_KEY") or setting("OPENROUTER_API_KEY") or None
    attacker_api_key = setting("KESTREL_ATTACKER_API_KEY") or setting("OPENROUTER_API_KEY") or None

    def positive_int(name: str, default: int) -> int:
        raw = setting(name)
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a whole number, not {raw!r}.") from None
        if value <= 0:
            raise SettingsError(f"{name} must be greater than 0, not {value}.")
        return value

    def non_negative_float_or_off(name: str, default: float) -> float | None:
        """A retrieval control (feature 011): unset → the default; `off` → None; else a number >= 0."""
        raw = setting(name)
        if not raw:
            return default
        if raw.lower() == "off":
            return None
        try:
            value = float(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a non-negative number or 'off', not {raw!r}.") from None
        if not (math.isfinite(value) and value >= 0):   # NaN and ±inf are no usable distance either
            raise SettingsError(f"{name} must be a non-negative number or 'off', not {raw!r}.")
        return value

    def non_negative_float(name: str, default: float) -> float:
        """A bounded wait (feature 013): unset → the default; else a finite number >= 0 (`0` = check once)."""
        raw = setting(name)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a non-negative number, not {raw!r}.") from None
        if not (math.isfinite(value) and value >= 0):
            raise SettingsError(f"{name} must be a non-negative number, not {raw!r}.")
        return value

    def positive_hours_bounded(name: str, default: float, maximum: float) -> float:
        """Feature 014 (research D28): unset -> the default; else a strictly positive, finite number at most
        `maximum` - distinct from `non_negative_float_or_off`, which allows 0 and an `off` sentinel neither of
        which apply here (every checkpointed row is auto-stopped eventually, never left idle forever by a
        setting, and a wait of exactly 0 would stop a run the instant it paused)."""
        raw = setting(name)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a positive number of hours, not {raw!r}.") from None
        if not (math.isfinite(value) and 0 < value <= maximum):
            raise SettingsError(
                f"{name} must be a positive number of hours, at most {maximum:g}, not {raw!r}.")
        return value

    raw_callback_base = setting("KESTREL_CALLBACK_BASE_URL")
    callback_base_url = validate_callback_base(raw_callback_base) if raw_callback_base else None

    raw_format = setting("KESTREL_LOG_FORMAT", "json")
    if raw_format not in ("json", "text"):
        raise SettingsError(f"KESTREL_LOG_FORMAT must be 'json' or 'text', not {raw_format!r}.")
    log_format: LogFormat = raw_format  # type: ignore[assignment]
    raw_tracing = setting("KESTREL_TRACING", "off")
    if raw_tracing not in ("on", "off"):
        raise SettingsError(f"KESTREL_TRACING must be 'on' or 'off', not {raw_tracing!r}.")

    return Settings(mode=mode, db_path=db_path, key_file=key_file, log_format=log_format,
                    tracing=raw_tracing == "on",
                    secret_key=env.get("KESTREL_SECRET_KEY") or None,
                    api_token=setting("KESTREL_API_TOKEN") or None,
                    judge_model=setting("KESTREL_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
                    judge_base_url=setting("KESTREL_JUDGE_BASE_URL", DEFAULT_JUDGE_BASE_URL).rstrip("/"),
                    judge_api_key=judge_api_key,
                    attacker_model=setting("KESTREL_ATTACKER_MODEL", DEFAULT_ATTACKER_MODEL),
                    attacker_base_url=setting("KESTREL_ATTACKER_BASE_URL", DEFAULT_ATTACKER_BASE_URL).rstrip("/"),
                    attacker_api_key=attacker_api_key,
                    adaptive_max_turns=positive_int("KESTREL_ADAPTIVE_MAX_TURNS", DEFAULT_ADAPTIVE_MAX_TURNS),
                    adaptive_token_budget=positive_int("KESTREL_ADAPTIVE_TOKEN_BUDGET", DEFAULT_ADAPTIVE_TOKEN_BUDGET),
                    adaptive_time_limit_s=positive_int("KESTREL_ADAPTIVE_TIME_LIMIT_S", DEFAULT_ADAPTIVE_TIME_LIMIT_S),
                    chroma_path=chroma_path,
                    experience_pattern_k=positive_int("KESTREL_EXPERIENCE_PATTERN_K", DEFAULT_EXPERIENCE_PATTERN_K),
                    experience_memory_cap=positive_int("KESTREL_EXPERIENCE_MEMORY_CAP", DEFAULT_EXPERIENCE_MEMORY_CAP),
                    experience_distance_floor=non_negative_float_or_off("KESTREL_EXPERIENCE_DISTANCE_FLOOR",
                                                                        DEFAULT_EXPERIENCE_DISTANCE_FLOOR),
                    experience_dedupe_threshold=non_negative_float_or_off("KESTREL_EXPERIENCE_DEDUPE_THRESHOLD",
                                                                          DEFAULT_EXPERIENCE_DEDUPE_THRESHOLD),
                    model_prices=_parse_prices(setting("KESTREL_MODEL_PRICES")),
                    experiment_max_runs=positive_int("KESTREL_EXPERIMENT_MAX_RUNS", DEFAULT_EXPERIMENT_MAX_RUNS),
                    experiment_token_budget=positive_int("KESTREL_EXPERIMENT_TOKEN_BUDGET",
                                                         DEFAULT_EXPERIMENT_TOKEN_BUDGET),
                    experiment_wall_clock_s=positive_int("KESTREL_EXPERIMENT_WALL_CLOCK_S",
                                                         DEFAULT_EXPERIMENT_WALL_CLOCK_S),
                    replay_batch_max_runs=positive_int("KESTREL_REPLAY_BATCH_MAX_RUNS",
                                                       DEFAULT_REPLAY_BATCH_MAX_RUNS),
                    callback_base_url=callback_base_url,
                    callback_wait_s=non_negative_float("KESTREL_CALLBACK_WAIT_S", DEFAULT_CALLBACK_WAIT_S),
                    side_channel_timeout_s=positive_int("KESTREL_SIDE_CHANNEL_TIMEOUT_S",
                                                        DEFAULT_SIDE_CHANNEL_TIMEOUT_S),
                    resume_idle_hours=positive_hours_bounded("KESTREL_RESUME_IDLE_HOURS", DEFAULT_RESUME_IDLE_HOURS,
                                                            MAX_RESUME_IDLE_HOURS))
