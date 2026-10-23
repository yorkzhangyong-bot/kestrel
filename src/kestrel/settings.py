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

    @property
    def judge_configured(self) -> bool:
        """Without a key there is no judge, but canary evidence still decides runs (FR-021)."""
        return self.judge_api_key is not None


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

    key_file = Path(env.get("KESTREL_KEY_FILE") or DEFAULT_KEY_FILE).expanduser()

    def setting(name: str, default: str = "") -> str:
        return (env.get(name) or "").strip() or default

    # KESTREL_JUDGE_API_KEY wins; OPENROUTER_API_KEY is the fallback, because the sacrificial
    # target already uses it and a single key is one less thing to set up (contracts/judge.md).
    judge_api_key = setting("KESTREL_JUDGE_API_KEY") or setting("OPENROUTER_API_KEY") or None

    return Settings(mode=mode, db_path=db_path, key_file=key_file,
                    secret_key=env.get("KESTREL_SECRET_KEY") or None,
                    judge_model=setting("KESTREL_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
                    judge_base_url=setting("KESTREL_JUDGE_BASE_URL", DEFAULT_JUDGE_BASE_URL).rstrip("/"),
                    judge_api_key=judge_api_key)
