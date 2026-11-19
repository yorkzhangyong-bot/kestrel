"""Tracing is an optional extra, never a required dependency (Principle X): the OpenTelemetry SDK and the OTLP/HTTP
exporter are named only by the `otel` extra and the `dev` group (010/FR-014, 010/SC-007). Feature 011 adds no
dependency at all: the required list is exactly the fixed stack and the `otel` extra is unchanged (011/FR-016,
011/SC-008)."""
import tomllib
from pathlib import Path

FEATURE = "010"

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
OTEL_PACKAGES = {"opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"}
# The fixed MVP stack (Principle X): the eight required packages, none other (feature 011, FR-016).
FIXED_STACK = {"chromadb", "cryptography", "fastapi", "httpx", "langgraph", "markdown-it-py", "streamlit",
               "uvicorn"}


def _names(requirements: list[str]) -> set[str]:
    """The distribution names of PEP 508 requirement strings (the part before any version marker)."""
    names = set()
    for requirement in requirements:
        name = requirement.split(";")[0]
        for stop in "<>=!~[ ":
            name = name.split(stop)[0]
        names.add(name.strip().lower())
    return names


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_no_tracing_package_is_a_required_dependency():  # FR-014, SC-007
    required = _names(_project()["project"]["dependencies"])
    assert not any(name.startswith("opentelemetry") for name in required)


def test_the_otel_extra_names_exactly_the_sdk_and_the_http_exporter():  # FR-014
    extra = _project()["project"]["optional-dependencies"]["otel"]
    assert _names(extra) == OTEL_PACKAGES


def test_the_dev_group_installs_them_for_the_test_suite():  # FR-014, SC-007
    assert OTEL_PACKAGES <= _names(_project()["dependency-groups"]["dev"])


def test_the_required_dependencies_are_exactly_the_fixed_stack():  # 011/FR-016, 011/SC-008
    """The retrieval controls use ChromaDB's own distances and the standard library: nothing was added."""
    assert _names(_project()["project"]["dependencies"]) == FIXED_STACK


def test_the_retrieval_controls_left_the_optional_extras_unchanged():  # 011/FR-016
    extras = _project()["project"]["optional-dependencies"]
    assert set(extras) == {"otel"} and _names(extras["otel"]) == OTEL_PACKAGES
