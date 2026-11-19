"""Feature-012 setting: the batch-replay cap (spec.md Clarifications, 2026-11-19)."""
import pytest

from kestrel.settings import SettingsError, load_settings

FEATURE = "012"


def test_defaults_to_20_when_unset():  # FR-031
    assert load_settings({}).replay_batch_max_runs == 20


def test_a_positive_value_overrides_the_default():  # FR-031
    assert load_settings({"KESTREL_REPLAY_BATCH_MAX_RUNS": "5"}).replay_batch_max_runs == 5


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_an_invalid_value_refuses_to_start_naming_the_variable(value):  # FR-031
    with pytest.raises(SettingsError, match="KESTREL_REPLAY_BATCH_MAX_RUNS"):
        load_settings({"KESTREL_REPLAY_BATCH_MAX_RUNS": value})
