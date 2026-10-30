# Contract: Statistics, cost, and result aggregation (feature 007)

Pure functions, standard-library `math` only — **no new dependency** (Principle X). Unit-tested against known values. Cover FR-006 (per-arm metrics), FR-007 (significance), and the clarified method (Wilson interval + two-proportion z-test; overall-arm on the confirmed rate).

## `src/kestrel/experiments/stats.py`

```python
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95%-default Wilson score interval for a proportion. n == 0 -> raise/return a 'no data' sentinel
    (callers render 'no data', never 0%)."""

def two_proportion(s_a: int, n_a: int, s_b: int, n_b: int) -> dict:
    """Two-proportion z-test for (p_b - p_a). Returns:
       { diff, z, p_value, significant (p < 0.05), small_sample, caveat }.
       p_value uses the normal CDF via math.erf. small_sample is True when min(n_a, n_b) < 30
       or any expected success/failure count < 5; caveat is a plain-language string when small_sample."""
```

Rules:
- `wilson_interval` is symmetric-in-code and clamped to [0, 1]; verified against textbook values (e.g. 1/10, 5/10, 0/20).
- `two_proportion` never raises on 0 successes; with `n == 0` on either side the comparison is `"no data"` (no z/p).
- `significant` is advisory; the caveat always accompanies a small sample so the UI/report never shows a bare percentage at small N (FR-007, SC-003).

## `src/kestrel/experiments/pricing.py`

```python
def arm_cost(total_tokens: int, price_model: str, model_prices: Mapping[str, float]) -> float | None:
    """total_tokens / 1000 * price[price_model]; None when the model has no configured price
    (caller renders 'unavailable'). price_model is the arm's primary model: the attacker model for an
    adaptive arm, the judge model for a single-turn arm (the model that consumed the run's tokens)."""
```

- `model_prices` comes from `Settings.model_prices` (USD per 1,000 tokens), parsed from `KESTREL_MODEL_PRICES` (`model=price,model=price`). Tokens are always reported; cost is `None` → "unavailable" when the price is missing (FR-006, R3).

## `src/kestrel/experiments/results.py`

```python
def arm_result(runs: list[Run], *, model_prices, attacker_model, judge_model) -> ArmResult: ...
def build_comparison(result_a: ArmResult, result_b: ArmResult) -> Comparison: ...
```

`arm_result` aggregates one arm's stored runs (newest-first is fine):
- **confirmed** = runs with `verdict == "succeeded" and hard_evidence` (Principle II); **suspected** = `verdict == "succeeded" and not hard_evidence`. Rates over scored runs (a sent, finished run), each with a Wilson interval (FR-006, SC-002).
- **mean_turns_to_success** over confirmed+suspected successes that recorded `succeeded_turn`/`turns_used`.
- **mean_tokens** over runs with non-null `tokens_used` (recorded for **both** modes — adaptive sums attacker+judge tokens, single-turn records the judge's tokens, 0 on a canary short-circuit); **cost** via `arm_cost(...)` using the arm's primary model (attacker for adaptive, judge for single-turn).
- **by_family** and **by_owasp**: descriptive counts of confirmed/suspected/n per family and per OWASP class (reusing `report.owasp.TESTED` for the class labels) — no per-cell test.
- **completed** vs **planned** and **send_failures** (from `experiment_runs`).

`build_comparison` (FR-007):
- For each headline metric, the difference B − A.
- On the **overall confirmed** rate: `two_proportion(confirmed_a, n_a, confirmed_b, n_b)` → the significance indicator + small-sample caveat (the primary verdict, per the clarification).
- The suspected-rate difference is reported descriptively (judge opinion, Principle II), without a significance claim.

## Report (`src/kestrel/report/experiment.py`)

```python
def build_experiment_report(experiment, result_a, result_b, comparison, *, now) -> ExperimentReportModel: ...
def render_experiment_markdown(model: ExperimentReportModel) -> str: ...
# HTML: reuse report.render.render_html(markdown)
```

The report (FR-009, FR-010, FR-014):
- Header names **both** arms' attacker model slugs (model+version) and judge models, and each arm's budget (turn_cap/token_budget) — Principle III (model, version, budget) — plus the recorded diff + warming/order.
- A side-by-side metric table (confirmed / suspected / mean turns / mean tokens / cost) with the significance note; small N shows the caveat, never a bare % (SC-003).
- A per-OWASP table mapping every row to an OWASP LLM Top 10 class (Principle VI); run-derived text is fenced and escaped by reusing `render_html` (same safety as feature 005).
- Downloadable as Markdown and HTML (FR-014, SC-008).
