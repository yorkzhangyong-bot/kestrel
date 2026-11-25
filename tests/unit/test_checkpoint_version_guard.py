"""The start-up version guard (014/FR-037, SC-011): a monkeypatched installed version outside either declared
range fails loudly, naming the installed version and the declared range; `pyproject.toml` names the identical
range."""
import re
import tomllib

import pytest

from kestrel.checkpointing import (CheckpointVersionError, SUPPORTED_LANGGRAPH, SUPPORTED_LANGGRAPH_CHECKPOINT,
                                   _in_range, check_supported_versions)
from kestrel.settings import REPO_ROOT

FEATURE = "014"


def test_a_version_inside_both_ranges_passes_silently():  # FR-037
    check_supported_versions(langgraph_version="1.2.17", langgraph_checkpoint_version="4.3.0")
    check_supported_versions(langgraph_version="1.2.99", langgraph_checkpoint_version="4.3.99")


def test_langgraph_outside_its_range_fails_loudly_naming_the_version_and_the_range():  # FR-037
    with pytest.raises(CheckpointVersionError) as info:
        check_supported_versions(langgraph_version="1.3.0", langgraph_checkpoint_version="4.3.0")
    assert "langgraph" in str(info.value) and "1.3.0" in str(info.value) and SUPPORTED_LANGGRAPH in str(info.value)


def test_langgraph_checkpoint_outside_its_range_fails_loudly_independently():  # FR-037
    with pytest.raises(CheckpointVersionError) as info:
        check_supported_versions(langgraph_version="1.2.17", langgraph_checkpoint_version="4.4.0")
    assert "langgraph-checkpoint" in str(info.value) and "4.4.0" in str(info.value)
    assert SUPPORTED_LANGGRAPH_CHECKPOINT in str(info.value)


def test_a_version_below_the_lower_bound_also_fails():  # FR-037
    with pytest.raises(CheckpointVersionError):
        check_supported_versions(langgraph_version="1.2.16", langgraph_checkpoint_version="4.3.0")


def test_the_parser_accepts_a_two_component_upper_bound():  # FR-037
    # SUPPORTED_LANGGRAPH's own declared upper bound ("1.3") has only two components; a version parser that
    # demanded exactly three would fail on the declared range itself.
    assert _in_range("1.2.17", SUPPORTED_LANGGRAPH) is True
    assert _in_range("1.3.0", SUPPORTED_LANGGRAPH) is False
    assert _in_range("1.2.99", SUPPORTED_LANGGRAPH) is True


_DEP_RE = re.compile(r"^([a-zA-Z0-9_.-]+)(.*)$")


def _specifier(deps: list[str], name: str) -> str | None:
    for entry in deps:
        match = _DEP_RE.match(entry)
        if match and match.group(1) == name:
            return match.group(2)
    return None


def test_pyprojects_own_declared_ranges_agree_with_the_savers_constants():  # FR-037, SC-011
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert _specifier(deps, "langgraph") == SUPPORTED_LANGGRAPH
    assert _specifier(deps, "langgraph-checkpoint") == SUPPORTED_LANGGRAPH_CHECKPOINT


def test_the_agreement_check_actually_compares_rather_than_trivially_passing():  # FR-037, SC-011
    # A deliberately mismatched fixture proves the assertion above is a real comparison, not a tautology.
    mismatched = """
[project]
dependencies = ["langgraph>=0.2", "langgraph-checkpoint>=4.3.0,<4.4.0"]
"""
    data = tomllib.loads(mismatched)
    deps = data["project"]["dependencies"]
    assert _specifier(deps, "langgraph") != SUPPORTED_LANGGRAPH
