"""Wilson interval + two-proportion z-test, stdlib only (feature 007). Traces 007/FR-007."""
from kestrel.experiments import stats

FEATURE = "007"


def test_wilson_known_values():
    low, high = stats.wilson_interval(5, 10)
    assert round(low, 3) == 0.237 and round(high, 3) == 0.763
    low, high = stats.wilson_interval(1, 10)
    assert 0.0 < low < 0.05 and 0.40 < high < 0.41


def test_wilson_zero_successes_is_valid_data():
    low, high = stats.wilson_interval(0, 20)
    assert low == 0.0 and 0.0 < high < 0.2


def test_wilson_no_data_is_none():
    assert stats.wilson_interval(0, 0) is None


def test_two_proportion_small_sample_flagged():
    r = stats.two_proportion(2, 10, 5, 10)
    assert round(r["diff"], 3) == 0.3 and r["small_sample"] is True and r["caveat"]


def test_two_proportion_large_sample_significant():
    r = stats.two_proportion(10, 100, 30, 100)
    assert r["small_sample"] is False and r["p_value"] < 0.05 and r["significant"] is True


def test_two_proportion_no_data():
    r = stats.two_proportion(0, 0, 1, 5)
    assert r["no_data"] is True and r["diff"] is None
