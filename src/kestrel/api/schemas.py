"""Request and response models for Kestrel's API (contracts/kestrel-api.md)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FormDefaults(BaseModel):
    method: Literal["POST", "GET"]
    body_template: str
    response_path: str


class ConfigOut(BaseModel):
    mode: Literal["local", "hosted"]
    defaults: FormDefaults
