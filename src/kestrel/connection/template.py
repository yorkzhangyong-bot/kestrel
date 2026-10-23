"""The prompt placeholder and building the request (FR-003, FR-004, FR-006; research R3)."""
from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

PLACEHOLDER = "{{prompt}}"
JSON_MESSAGE = "The request body template must be valid JSON with {{prompt}} inside a string value."


class TemplateError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def validate(method: str, url: str, body_template: str) -> None:
    """Raise TemplateError naming the field at fault when the placeholder rules are broken."""
    if method == "GET":
        if url.count(PLACEHOLDER) != 1 or PLACEHOLDER not in urlsplit(url).query:
            raise TemplateError("settings.url", "For GET, put {{prompt}} exactly once in the URL's query string.")
        return
    if PLACEHOLDER in url:
        raise TemplateError("settings.url", "For POST, put {{prompt}} in the request body template, not the URL.")
    if body_template.count(PLACEHOLDER) != 1:
        raise TemplateError("settings.body_template", "The request body template must contain {{prompt}} exactly once.")
    _parse_with_sentinel(body_template)


def build_request(method: str, url: str, body_template: str, prompt: str) -> tuple[str, bytes | None]:
    """Return the URL and body to send; the body stays valid JSON whatever the prompt contains."""
    if method == "GET":
        return url.replace(PLACEHOLDER, quote(prompt, safe="")), None
    document, sentinel = _parse_with_sentinel(body_template)
    filled = _substitute(document, sentinel, prompt)
    return url, json.dumps(filled, ensure_ascii=False).encode("utf-8")


def _parse_with_sentinel(body_template: str) -> tuple[Any, str]:
    # Parse first, then fill in: the prompt never has to be escaped by hand.
    sentinel = f"__kestrel_prompt_{uuid.uuid4().hex}__"
    try:
        document = json.loads(body_template.replace(PLACEHOLDER, sentinel))
    except ValueError:
        raise TemplateError("settings.body_template", JSON_MESSAGE) from None
    if _sentinel_in_keys(document, sentinel) or not _sentinel_in_values(document, sentinel):
        raise TemplateError("settings.body_template", JSON_MESSAGE)
    return document, sentinel


def _sentinel_in_keys(node: Any, sentinel: str) -> bool:
    if isinstance(node, dict):
        return any(sentinel in key or _sentinel_in_keys(value, sentinel) for key, value in node.items())
    if isinstance(node, list):
        return any(_sentinel_in_keys(item, sentinel) for item in node)
    return False


def _sentinel_in_values(node: Any, sentinel: str) -> bool:
    if isinstance(node, str):
        return sentinel in node
    if isinstance(node, dict):
        return any(_sentinel_in_values(value, sentinel) for value in node.values())
    if isinstance(node, list):
        return any(_sentinel_in_values(item, sentinel) for item in node)
    return False


def _substitute(node: Any, sentinel: str, prompt: str) -> Any:
    if isinstance(node, str):
        return node.replace(sentinel, prompt)
    if isinstance(node, dict):
        return {key: _substitute(value, sentinel, prompt) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(item, sentinel, prompt) for item in node]
    return node
