# Quickstart & validation: A/B Harness (feature 007)

How to prove the feature works end to end. Commands run from the repo root with `uv`. Details live in [data-model.md](data-model.md), [contracts/](contracts/), and the [spec](spec.md); this is the run/validation guide.

## Prerequisites

- `uv sync` (no new dependency — statistics use stdlib `math`).
- For live runs, an OpenRouter key in `OPENROUTER_API_KEY` (judge + attacker reuse it). Offline tests use fakes and need no key.
- Optional cost output: set per-model prices, e.g. `KESTREL_MODEL_PRICES="deepseek/deepseek-v4.1-flash=0.30,google/gemini-3.8-flash=0.20"` (USD per 1,000 tokens). Unset → cost shows "unavailable", tokens still shown.

## Automated tests (tests-first — Principle VII)

```bash
uv run pytest tests/unit -q           # stats, pricing, results, engine (fakes), store v6, validation
uv run pytest tests/integration -q    # API create/status/result; UI boundary
uv run pytest tests/e2e -q            # the one e2e below
uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=85   # the QA gate's bar
```

Every new test is scoped for the feature-007 traceability gate (module-level `FEATURE = "007"`, or `007/FR-xxx` tokens where sample ids would otherwise be miscounted), so `uv run python scripts/check_traceability.py` counts the citations for 007.

## The end-to-end scenario (SC-009, FR-003/004/005/006/007)

A 2-arm experiment against the in-repo HS-code target, N=1, retrieval **off** (arm A, cold) vs **on** (arm B, warm):

1. The e2e harness (reusing `tests/e2e/conftest.py`) starts the HS-code target and a Kestrel app with a fake/offline attacker + judge so the outcome is deterministic.
2. Create the experiment: mode `adaptive`, families = all four, `reps = 1`, arm A `{use_prior_experience: false, write_back: false}`, arm B `{use_prior_experience: true, write_back: true}`, finite caps.
3. Poll `GET /api/experiments/{id}/status` until `finished`.
4. Assert `GET /api/experiments/{id}/result`:
   - both arms present, each with **confirmed** and **suspected** rates split (FR-006, SC-002);
   - a `comparison.confirmed` block with a significance indicator **and** a small-sample caveat (N=1 ⇒ `small_sample: true`), never a bare % (FR-007, SC-003);
   - the recorded `diff` (`use_prior_experience: A=off, B=on`) and `order`/`warming` (A ran first, cold; B warm) (FR-003, FR-005);
   - arm A's runs have `memory_written = null` (cold, no write-back); arm B's write back (SC-005).
5. Download the report (`?format=md` and `?format=html`): it names both attacker models + versions and judges (FR-009) and has a per-OWASP table (FR-010, FR-014).
6. Assert no header value / key / secret appears in the result JSON, the report, or the logs (FR-011, SC-007).

## Manual walkthrough (the Experiments screen — FR-013)

```bash
uv run uvicorn --factory kestrel.api.main:create_app      # API on :8000
uv run streamlit run ui/app.py                            # UI
```

1. Save (or pick) the HS-code target with its canary and permission ticked.
2. In **Experiments**: pick the target; edit arm A and arm B (attacker model, judge model, retrieval on/off, turn cap, token budget); choose families, reps, and caps; **Start** (the arms-must-differ check blocks identical arms — FR-003).
3. Watch progress (runs completed vs planned, spend) update as the experiment runs (US4).
4. Read the side-by-side table: confirmed vs suspected per arm, mean turns, mean tokens + cost (or "unavailable"), per-family and per-OWASP breakdowns, and the difference with its significance note.
5. **Download report** as Markdown or HTML.

## Cap behaviour (SC-004, FR-008)

Create an experiment with a low `max_runs` (or tiny `token_budget_total` / `wall_clock_s`): it stops cleanly within the wall-clock limit, `status = stopped`, `stopped_reason` names the cap, and `result` returns a usable partial comparison. No run is left in progress and the target is not left locked.

## Implementation PR

Open the implementation PR from `007-impl` to `master` with **`Spec-PR: #4`** in the body (feature-006 workflow). Run `uv run ruff check src ui tests` and the full suite before pushing.
