"""model_prices + experiment cap defaults (feature 007). Traces 007/FR-006, 007/FR-008."""
import pytest

from kestrel.settings import SettingsError, load_settings

FEATURE = "007"

BASE = {"KESTREL_MODE": "local"}


def test_prices_parse():
    s = load_settings({**BASE, "KESTREL_MODEL_PRICES": "a/b=0.3, c/d=0.2"})
    assert s.model_prices == {"a/b": 0.3, "c/d": 0.2}


def test_prices_default_empty():
    assert load_settings(BASE).model_prices == {}


def test_bad_price_raises():
    with pytest.raises(SettingsError):
        load_settings({**BASE, "KESTREL_MODEL_PRICES": "a/b=notanumber"})


def test_cap_defaults():
    s = load_settings(BASE)
    assert s.experiment_max_runs == 50
    assert s.experiment_token_budget == 500_000
    assert s.experiment_wall_clock_s == 3600


def test_cap_override():
    assert load_settings({**BASE, "KESTREL_EXPERIMENT_MAX_RUNS": "5"}).experiment_max_runs == 5


def test_bad_cap_raises():
    with pytest.raises(SettingsError):
        load_settings({**BASE, "KESTREL_EXPERIMENT_MAX_RUNS": "0"})
