"""Tracing is an optional extra, never a required dependency (Principle X): the OpenTelemetry SDK and the OTLP/HTTP
exporter are named only by the `otel` extra and the `dev` group (010/FR-014, 010/SC-007)."""
import tomllib
from pathlib import Path

FEATURE = "010"

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
OTEL_PACKAGES = {"opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"}


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
