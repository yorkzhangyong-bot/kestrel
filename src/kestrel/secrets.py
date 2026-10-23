"""The encryption key, encrypting auth header values, and masking them in text (research R5, R9)."""
from __future__ import annotations

import logging
import os
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken

from kestrel.settings import Settings, SettingsError

MASK = "••••"
MIN_MASK_LENGTH = 4  # FR-004 rejects shorter header values; this is a guard against garbling text


def load_or_create_key(settings: Settings, logger: logging.Logger) -> tuple[bytes, str]:
    """Return the Fernet key and where it came from: "env", "file" or "generated"."""
    if settings.secret_key:
        key = settings.secret_key.strip().encode("ascii", errors="replace")
        _check_key(key, "KESTREL_SECRET_KEY")
        return key, "env"

    path = settings.key_file
    if path.exists():
        key = path.read_bytes().strip()
        _check_key(key, f"The key file {path}")
        source = "file"
    else:
        key = Fernet.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key + b"\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # not supported on every OS; the file still sits in the user's own folder
        logger.warning("Generated a new encryption key at %s; back this file up, because saved auth header "
                       "values can't be read without it.", path)
        source = "generated"

    if settings.mode == "hosted":
        logger.warning("Running hosted with the encryption key in a file (%s). A redeploy may lose the file; "
                       "set KESTREL_SECRET_KEY instead.", path)
    return key, source


def _check_key(key: bytes, where: str) -> None:
    try:
        Fernet(key)
    except (ValueError, TypeError):
        raise SettingsError(f"{where} is not a valid Fernet key (32 url-safe base64-encoded bytes).") from None


class Vault:
    """Encrypts and decrypts auth header values."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str | None:
        """Return the value, or None when this key can't decrypt the token."""
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


def mask_values(text: str, values: Iterable[str]) -> str:
    """Replace every occurrence of each value (4+ characters) with MASK, longest values first."""
    for value in sorted({v for v in values if v and len(v) >= MIN_MASK_LENGTH}, key=len, reverse=True):
        text = text.replace(value, MASK)
    return text
