"""Kestrel's settings, read from KESTREL_* environment variables (research R5, R6, R8)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping

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

Mode = Literal["local", "hosted"]


class SettingsError(Exception):
    """A setting is invalid, so Kestrel refuses to start."""


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
    adaptive_max_turns: int = DEFAULT_ADAPTIVE_MAX_TURNS
    adaptive_token_budget: int = DEFAULT_ADAPTIVE_TOKEN_BUDGET
    adaptive_time_limit_s: int = DEFAULT_ADAPTIVE_TIME_LIMIT_S
    chroma_path: Path = REPO_ROOT / DEFAULT_CHROMA_PATH
    experience_pattern_k: int = DEFAULT_EXPERIENCE_PATTERN_K
    experience_memory_cap: int = DEFAULT_EXPERIENCE_MEMORY_CAP

    @property
    def judge_configured(self) -> bool:
        """Without a key there is no judge, but canary evidence still decides runs (FR-021)."""
        return self.judge_api_key is not None

    @property
    def attacker_configured(self) -> bool:
        """Without a key there is no attacker, so an adaptive run cannot start (FR-016)."""
        return self.attacker_api_key is not None


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

    return Settings(mode=mode, db_path=db_path, key_file=key_file,
                    secret_key=env.get("KESTREL_SECRET_KEY") or None,
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
                    experience_memory_cap=positive_int("KESTREL_EXPERIENCE_MEMORY_CAP", DEFAULT_EXPERIENCE_MEMORY_CAP))
