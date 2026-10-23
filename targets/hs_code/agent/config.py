"""Settings and named constants.

Caps, thresholds and model options are named here so that guardrails are enforced by
configuration constants, never by prompt text (constitution Principles I and II).
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STORE_DIR = ROOT / "store"
RULES_DIR = DATA_DIR / "rules"

# Input caps (FR-001, FR-002, FR-006)
MAX_FILE_BYTES = 20_971_520          # 20 MB
MAX_LINES = 200                      # lines per shipment
MAX_DESC_CHARS = 300                 # characters per description (truncated beyond)
MAX_PASTED_LINES = 50                # lines per pasted chat message
SUPPORTED_FILE_KINDS = ("xlsx", "csv", "pdf", "jpg", "jpeg", "png")

# Routing (FR-020, FR-021)
DEFAULT_THRESHOLD = 85
THRESHOLD_MIN = 60
THRESHOLD_MAX = 99
ASK_FLOOR = 50

# Agent and model behaviour (FR-044, FR-049)
MAX_SCHEMA_RETRIES = 2
MAX_TOOL_CALLS = 8
PER_LINE_TIMEOUT_S = 60
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Retrieval
RETRIEVAL_K = 6
RRF_K = 60

# TARIC snapshot (feature 002): digits 9-10 and measures, never embedded or indexed
TARIC_RAW_DIR = DATA_DIR / "raw" / "taric"
TARIC_SNAPSHOT = DATA_DIR / "taric.jsonl"
TARIC_KEY = DATA_DIR / "Tulltaxan_Fildistribution.asc"
TARIC_KEY_FINGERPRINT = "410160CE25CEC2FF322784E7302AC3C1D0E3E1C9"   # Swedish Customs "Taric Fildistribution" key
TARIC_OBJECTS = ("GoodsNomenclature", "Measure", "MeasureType", "GeographicalArea", "DutyExpression", "Regulation")
TARIC_SCHEMA = 2
TARIC_LOG_DIR = STORE_DIR / "logs"
GPG_ENV = "CARGOLINT_GPG"            # optional full path to gpg


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    http_referer: str | None
    app_title: str
    chat_model: str
    embed_model: str
    structured_method: str
    usd_eur: float
    workers: int
    ocr_min_score: float

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def load_settings(env: dict | None = None) -> Settings:
    """Read settings from the environment (a `.env` at the repo root is loaded if present)."""
    load_dotenv(ROOT / ".env", override=False)
    e = env if env is not None else os.environ
    return Settings(
        api_key=e.get("OPENROUTER_API_KEY") or None,
        http_referer=e.get("OPENROUTER_HTTP_REFERER") or None,
        app_title=e.get("OPENROUTER_APP_TITLE") or "CargoLint",
        chat_model=e.get("CARGOLINT_CHAT_MODEL") or "openai/gpt-4o-mini",
        embed_model=e.get("CARGOLINT_EMBED_MODEL") or "qwen/qwen3-embedding-8b",
        structured_method=e.get("CARGOLINT_STRUCTURED_METHOD") or "json_schema",
        usd_eur=float(e.get("CARGOLINT_USD_EUR") or 0.92),
        workers=int(e.get("CARGOLINT_WORKERS") or 6),
        ocr_min_score=float(e.get("CARGOLINT_OCR_MIN_SCORE") or 0.6),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def configure_logging(level: int = logging.INFO) -> None:
    """Plain stderr logging. Handlers never receive description or reply text (FR-046)."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
