"""Significance statistics for the A/B comparison (feature 007, FR-007), standard-library ``math`` only.

A Wilson score interval per rate, and a two-proportion z-test for the difference, with a small-sample caveat. No
new dependency (Principle X): the normal CDF comes from ``math.erf``. These are pure functions, unit-tested against
known values. The comparison is applied at the overall-arm level on the confirmed (hard-evidence) rate (clarified
2026-10-29); per-family / per-OWASP figures are descriptive, never tested here.
"""
from __future__ import annotations

import math

Z_95 = 1.959963984540054   # the two-sided 95% normal quantile
SMALL_SAMPLE_N = 30        # below this per arm, flag the comparison as small-sample
MIN_EXPECTED = 5           # below this expected count, the normal approximation is unsafe

SMALL_SAMPLE_CAVEAT = ("Small sample: treat this difference as indicative, not conclusive - a few more runs could "
                       "change it.")


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """The Wilson score confidence interval for a proportion, clamped to [0, 1].

    Returns None when ``n == 0`` (no data), so callers render "no data" rather than a spurious 0%. ``successes == 0``
    over ``n > 0`` is valid data (a 0% rate with a real interval).
    """
    if n <= 0:
        return None
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _is_small_sample(s_a: int, n_a: int, s_b: int, n_b: int) -> bool:
    if min(n_a, n_b) < SMALL_SAMPLE_N:
        return True
    pool = (s_a + s_b) / (n_a + n_b)
    expected = (n_a * pool, n_a * (1 - pool), n_b * pool, n_b * (1 - pool))
    return any(e < MIN_EXPECTED for e in expected)


def two_proportion(s_a: int, n_a: int, s_b: int, n_b: int) -> dict:
    """Two-proportion z-test for the difference p_b - p_a.

    Returns a dict with: diff, z, p_value, significant (p < 0.05, advisory), small_sample, caveat, no_data.
    When either arm has no scored runs the result is ``no_data`` with no z/p (callers render "no data").
    """
    if n_a <= 0 or n_b <= 0:
        return {"diff": None, "z": None, "p_value": None, "significant": False,
                "small_sample": True, "caveat": "No data in at least one arm; no comparison.", "no_data": True}
    p_a, p_b = s_a / n_a, s_b / n_b
    diff = p_b - p_a
    pool = (s_a + s_b) / (n_a + n_b)
    se = math.sqrt(pool * (1 - pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        z, p_value = 0.0, 1.0
    else:
        z = diff / se
        p_value = 2 * (1 - _normal_cdf(abs(z)))
    small = _is_small_sample(s_a, n_a, s_b, n_b)
    return {"diff": diff, "z": z, "p_value": p_value, "significant": p_value < 0.05,
            "small_sample": small, "caveat": SMALL_SAMPLE_CAVEAT if small else None, "no_data": False}
