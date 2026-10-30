# Research: A/B Harness (feature 007)

Decisions that shape the design. Each resolves a choice the spec or plan left open; nothing here contradicts the approved spec or the clarifications (significance overall-arm on the confirmed rate; Wilson + two-proportion z-test; cost = tokens × configured per-model price).

## R1 — Statistics in the standard library

- **Decision**: implement the Wilson score interval and a two-proportion z-test in a new `experiments/stats.py` using only `math` (the normal CDF via `math.erf`). The significance comparison runs at the **overall-arm** level on the **confirmed (hard-evidence)** success rate (primary) and also reports a Wilson interval for the suspected rate (descriptive). Per-family and per-OWASP figures are descriptive counts only — no per-cell test.
- **Rationale**: Principle X forbids casual new dependencies; SciPy/statsmodels would be the only reason to add one, and the two formulas are a few lines each. Keeping them pure makes them trivially unit-testable against known values.
- **Alternatives considered**: SciPy/statsmodels (rejected — a heavy dependency for two closed-form functions); bootstrap resampling (rejected — needless at these sample sizes and non-deterministic in tests).

## R2 — Small-sample caveat threshold

- **Decision**: flag a comparison as small-sample when either arm has fewer than **30** scored runs in the metric being compared, or when a two-proportion normal approximation is unsafe (any expected success/failure count < 5). When flagged, the result still shows the difference **with** the interval and the caveat; it never shows a bare percentage (FR-007, SC-003). A rate over **zero** scored runs is reported as "no data", not 0% (spec edge case).
- **Rationale**: the default campaign (3 reps) is deliberately small; the honest-statistics story (US2) is the whole point. A fixed, documented threshold is predictable and testable.
- **Alternatives considered**: continuity-corrected tests or exact (Fisher) tests (rejected — more code for no meaningful gain at this scale; the caveat already tells the user not to over-read a small sample).

## R3 — Cost from a configured per-model price

- **Decision**: add `model_prices: Mapping[str, float]` to `Settings` (USD per 1,000 tokens), loaded from `KESTREL_MODEL_PRICES` (format `model=price,model=price`). Per-arm **cost = Σ run.tokens_used ÷ 1000 × price(primary model)**, where the primary model is the arm's **attacker model** for an adaptive arm and its **judge model** for a single-turn arm — the model that actually consumed the run's tokens. Tokens are always reported (summed/averaged from `runs.tokens_used`); cost is marked **"unavailable"** when the primary model has no configured price. No live billing lookup.
- **Rationale**: matches the clarified decision and keeps Kestrel offline-friendly and deterministic.
- **Prerequisite (foundational task)**: record the judge's tokens on **single-turn** runs so every mode reports tokens and cost. The change is tiny and non-breaking — `JudgeClient.judge()` already returns `ParsedVerdict.tokens` (parsed from the OpenRouter `usage`), the `runs.tokens_used` column already exists, and `finish_run(..., tokens_used=...)` already accepts it. `execute_run` simply threads `verdict.tokens` into its judged-branch `_finish(...)` and records `0` on the no-model-call branches (canary match, no judge configured, deadline, failed send). No schema change, no new field; no existing test asserts single-turn `tokens_used is None`. This **replaces** the earlier limitation that single-turn arms could not report tokens/cost.
- **Alternatives considered**: a single fixed price for all models (rejected at clarification — mixes cheap/expensive models misleadingly); live provider billing (rejected — network dependency, non-deterministic, out of the offline model).

## R4 — A-then-B execution, sequential, in the background

- **Decision**: `POST /api/experiments` validates, claims an `experiments` row (`status = running`), and schedules the engine as a background asyncio task; it returns `201` immediately with the id. The engine runs **arm A's whole campaign, then arm B's** (recording `run_order` on each arm), one run at a time, writing progress to the DB as it goes. `GET …/status` and `GET …/result` read the DB, so the database is the single source of truth and status survives a worker restart.
- **Rationale**: an experiment is far longer than a request; a synchronous `POST` would time out. Sequential execution respects the existing per-target single-active-run index (`uq_runs_active`) with no new locking, and A-then-B is the warming model the spec describes.
- **Alternatives considered**: interleaving A/B runs (rejected — the spec's warming control assumes a clean A-then-B order and it complicates cap accounting); a worker/queue system (rejected — overkill for single-user MVP; an asyncio task suffices).

## R5 — The campaign fixes the attack set; both arms run the identical set

- **Decision**: when the experiment starts, the engine selects the seed prompt per family **once** (via `library.pick(family)`), records the chosen prompt ids on the experiment, and **both arms replay the identical seeds**. Reps repeat the same seed; variation comes from the stochastic adaptive attacker and the target.
- **Rationale**: a fair A/B test must hold the attack constant so the arm configuration is the only variable. Recording the seed ids keeps the experiment reproducible and auditable (FR-016).
- **Alternatives considered**: re-picking prompts per arm (rejected — introduces a confound); enumerating every prompt in a family (rejected — N reps is the spec's unit of repetition, not "all prompts").

## R6 — Per-arm judge and attacker clients from settings, never per-arm secrets

- **Decision**: for each arm the engine builds a `JudgeClient(model=arm.judge_model, …)` and an `AttackerClient(model=arm.attacker_model, …)` using the **API keys already in `Settings`** (the OpenRouter key path). Arms persist only model names and numeric settings (Principle IV).
- **Rationale**: reuses the exact clients `create_app` builds; an arm is a configuration, not a credential holder.
- **Alternatives considered**: per-arm API keys (rejected — would put secrets in an arm, violating Principle IV; out of scope).

## R7 — Persistence: extend `TargetStore`, schema v6 (additive)

- **Decision**: add three tables (`experiments`, `experiment_arms`, `experiment_runs`) to the `store.py` SCHEMA, bump `SCHEMA_VERSION` to `"6"`, and add `"5"` to the set of versions the migration will upgrade from. No existing table changes, so the migration is a pure `CREATE IF NOT EXISTS` (like v2/v3/v5 did for new tables). Experiment query methods live on `TargetStore`, beside runs.
- **Rationale**: matches the established one-store convention (runs, canaries, recommendations already live on `TargetStore`) and the existing additive-migration pattern; an `experiment_runs` join to the generic `runs` table reuses every per-run field (verdict, hard_evidence, tokens_used, attacker_model, use_prior_experience) without duplicating it.
- **Alternatives considered**: a second store class on the same file (rejected — duplicate connection/migration handling); columns on `runs` to tag experiment/arm (rejected — pollutes the hot runs table; a join table keeps runs generic while still "tagging" each run, FR-004).

## R8 — The experiment report reuses the feature-005 renderer

- **Decision**: a new `report/experiment.py` builds a comparison-shaped model and a `render_experiment_markdown()`; HTML is produced by reusing `report.render.render_html` (same escaping + self-contained style), and the per-category table reuses `report.owasp.TESTED`. Downloaded as Markdown and HTML (FR-014).
- **Rationale**: the comparison is a different shape from the single-target report, but the output **formats** and the OWASP mapping are shared; reusing `render_html` keeps the two reports visually and security-consistent (fenced, escaped run-derived content).
- **Alternatives considered**: forcing the comparison into the existing `ReportModel` (rejected — its shape is per-target findings, not a two-arm comparison); a brand-new HTML renderer (rejected — would duplicate the escaping/style the security tests already cover).

## R9 — Caps and clean partial results

- **Decision**: experiment caps are **max total runs**, **total token budget**, and **wall-clock seconds**, with finite defaults in `Settings` (overridable per experiment, never unset). The engine checks all three **before each run**; on a hit it stops at the run boundary, records `stopped_reason` (`max_runs` / `token_budget` / `wall_clock`), sets `status = stopped`, and the result endpoint returns the partial comparison naming the cap (FR-008, SC-004). Per-arm turn cap and token budget remain the existing per-run adaptive caps passed through to `execute_adaptive_run`.
- **Rationale**: bounded harm (Principle VIII) and an always-usable result. Checking at the run boundary avoids leaving a run half-finished or the target locked.
- **Alternatives considered**: mid-run cancellation (rejected — would leave an in-progress run row and a locked target; run-boundary checks are clean and already align with the per-run deadlines).
