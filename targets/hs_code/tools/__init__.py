"""CargoLint tools package. The five agent tools register themselves in TOOLS when imported."""
from __future__ import annotations

from typing import Any

TOOLS: list[Any] = []


def register(tool: Any) -> Any:
    if all(getattr(t, "name", None) != getattr(tool, "name", None) for t in TOOLS):
        TOOLS.append(tool)
    return tool


def load_all() -> list[Any]:
    """Import every tool module that exists so that TOOLS is complete."""
    import importlib

    for name in ("parse_packing_list", "check_description", "classify_hs6", "lookup_precedent", "apply_shipper_reply"):
        try:
            importlib.import_module(f"tools.{name}")
        except ModuleNotFoundError as exc:  # a story not implemented yet
            if name not in str(exc):
                raise
    return TOOLS
