"""Harness for the evaluation tool (tests/eval): the judge-accuracy evaluation and the retrieval (RAG) evaluation.

Every test here is marked ``judge_eval`` - the offline suite (``-m 'not e2e and not judge_eval'``) skips the whole
directory. Run the full evaluation with ``uv run pytest -m judge_eval``. The judge test makes real judge calls and
skips itself when no judge is configured; the retrieval evaluation uses only the local embedding model and runs
without a key. ``--judge-version N`` pins the judge prompt version the accuracy test scores.
"""
from __future__ import annotations

from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(EVAL_DIR):
            item.add_marker(pytest.mark.judge_eval)


def pytest_addoption(parser):
    parser.addoption("--judge-version", action="store", default=None,
                    help="judge prompt version the accuracy evaluation scores (default: the active one)")


@pytest.fixture
def judge_version(request):
    import os

    return request.config.getoption("--judge-version") or os.environ.get("KESTREL_JUDGE_VERSION") or None
