"""Response paths: `$`, `.field` and `[n]`, for example `$.choices[0].message.content` (research R4)."""
from __future__ import annotations

import re
from typing import Any

_STEP = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")
SYNTAX_MESSAGE = "Start the response path with $ and use .field and [n] steps, for example $.choices[0].message.content."


class PathSyntaxError(ValueError):
    pass


class PathNotFound(LookupError):
    pass


def parse(path: str) -> list[str | int]:
    if not path.startswith("$"):
        raise PathSyntaxError(SYNTAX_MESSAGE)
    steps: list[str | int] = []
    position = 1
    while position < len(path):
        match = _STEP.match(path, position)
        if match is None:
            raise PathSyntaxError(SYNTAX_MESSAGE)
        name, index = match.groups()
        steps.append(name if name is not None else int(index))
        position = match.end()
    return steps


def extract(document: Any, path: str) -> Any:
    current = document
    for step in parse(path):
        if isinstance(step, str):
            if not isinstance(current, dict) or step not in current:
                raise PathNotFound(path)
        elif not isinstance(current, list) or step >= len(current):
            raise PathNotFound(path)
        current = current[step]
    return current
