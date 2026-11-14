"""The two feature-010 settings: the stream format and the tracing flag (010/FR-006, 010/FR-013)."""
import pytest

from kestrel.settings import SettingsError, load_settings

FEATURE = "010"


def test_the_stream_is_json_by_default():  # FR-006
    assert load_settings({}).log_format == "json"


@pytest.mark.parametrize("raw, expected", [("json", "json"), ("text", "text"), (" text ", "text"), ("", "json")])
def test_the_log_format_accepts_json_and_text(raw, expected):  # FR-006
    assert load_settings({"KESTREL_LOG_FORMAT": raw}).log_format == expected


def test_any_other_log_format_is_refused():  # FR-006
    with pytest.raises(SettingsError, match="KESTREL_LOG_FORMAT"):
        load_settings({"KESTREL_LOG_FORMAT": "xml"})


def test_tracing_is_off_by_default():  # FR-013
    assert load_settings({}).tracing is False


@pytest.mark.parametrize("raw, expected", [("on", True), ("off", False), (" on ", True), ("", False)])
def test_the_tracing_flag_accepts_on_and_off(raw, expected):  # FR-013
    assert load_settings({"KESTREL_TRACING": raw}).tracing is expected


@pytest.mark.parametrize("raw", ["yes", "true", "1", "ON-ish"])
def test_any_other_tracing_value_is_refused(raw):  # FR-013
    with pytest.raises(SettingsError, match="KESTREL_TRACING"):
        load_settings({"KESTREL_TRACING": raw})
