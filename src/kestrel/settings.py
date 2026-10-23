"""Kestrel's settings, read from KESTREL_* environment variables (research R5, R6, R8)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

# src/kestrel/settings.py -> the folder holding pyproject.toml
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path("data") / "kestrel.db"
DEFAULT_KEY_FILE = "~/.kestrel/secret.key"

Mode = Literal["local", "hosted"]


class SettingsError(Exception):
    """A setting is invalid, so Kestrel refuses to start."""


@dataclass(frozen=True)
class Settings:
    mode: Mode
    db_path: Path
    key_file: Path
    secret_key: str | None


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

    return Settings(mode=mode, db_path=db_path, key_file=key_file, secret_key=env.get("KESTREL_SECRET_KEY") or None)
