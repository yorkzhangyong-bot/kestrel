"""Harness for the judge-accuracy evaluation (tests/eval).

Like the e2e suite, every test here makes a real judge call, so it needs OPENROUTER_API_KEY and is marked
``judge_eval`` — the offline suite (``-m 'not e2e and not judge_eval'``) skips it. Run it with
``uv run pytest -m judge_eval``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(EVAL_DIR):
            item.add_marker(pytest.mark.judge_eval)


@pytest.fixture(scope="session", autouse=True)
def _needs_openrouter_key():
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY is not set; the judge-accuracy eval makes real judge calls.")
