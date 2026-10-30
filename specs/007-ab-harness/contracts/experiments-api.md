# Contract: Experiments API (feature 007)

FastAPI endpoints added to `src/kestrel/api/main.py`, schemas in `src/kestrel/api/schemas.py`. Error bodies reuse the existing shapes: `{"errors": [{field, message}]}` for 422, `{"error": {code, field, message}}` otherwise. No endpoint ever returns a header value, key, or secret (Principle IV, FR-011).

## POST /api/experiments → 201 (FR-012, FR-001/002/003/008)

Create and start an experiment. Returns immediately; the run executes in the background.

Request:
```json
{
  "target_id": 1,
  "mode": "adaptive",
  "families": ["direct_injection", "system_prompt_leak"],   // optional; default = all four
  "reps": 3,                                                  // optional; default 3
  "caps": { "max_runs": 50, "token_budget_total": 500000, "wall_clock_s": 3600 },  // optional; finite defaults
  "arm_a": { "attacker_model": "...", "judge_model": "...", "use_prior_experience": false,
             "turn_cap": 6, "token_budget": 40000, "write_back": false },
  "arm_b": { "attacker_model": "...", "judge_model": "...", "use_prior_experience": true,
             "turn_cap": 6, "token_budget": 40000, "write_back": true }
}
```
Response `201`: `{ "id": 7, "status": "running" }`.

Validation / preconditions (checked before any row is written):
- `target_id` exists, else `404 not_found`.
- Permission + terms gate, reusing the `POST /api/runs` checks: `409 permission_missing` / `409 terms_outdated` (FR-015, Principle VIII).
- Arms **must differ** in ≥ 1 field, else `422` `{field: "arm_b", message: "The two arms must differ in at least one setting."}` (FR-003).
- `mode == "adaptive"` requires a configured attacker, else `409 attacker_unavailable`.
- Caps must be finite and ≥ 1 (defaults applied when omitted); a non-finite/0 cap is `422` (FR-008).
- Only **one running experiment per target**: a second is `409 experiment_in_progress` (also covers the single active-run slot).
- Arm payloads carry only model names + numeric settings; any extra credential-shaped field is ignored/rejected (FR-011).

## GET /api/experiments/{id}/status → 200 (FR-012, US4)

```json
{
  "id": 7, "status": "running",
  "planned_runs": 48, "completed_runs": 11,
  "tokens_used": 220345, "cost": 0.73,            // cost null when any running arm's price is unconfigured
  "arms": [ { "label": "A", "run_order": 1, "completed": 11, "planned": 24 },
            { "label": "B", "run_order": 2, "completed": 0,  "planned": 24 } ],
  "stopped_reason": null
}
```
`404 not_found` for an unknown id. Progress is read from the DB, so it is correct across restarts (R4).

## GET /api/experiments/{id}/result → 200 (FR-006, FR-007, FR-009, FR-010)

Returns the comparison, computed on demand from stored runs (available while running = partial, and when finished). Shape:
```json
{
  "id": 7, "status": "finished", "stopped_reason": "completed",
  "mode": "adaptive", "families": ["..."], "reps": 3,
  "diff": ["use_prior_experience: A=off, B=on"],              // the recorded arm diff (FR-003)
  "order": "A then B", "warming": "A cold (no write-back); B warm",   // FR-005
  "arms": [
    { "label": "A", "attacker_model": "...", "judge_model": "...",   // the model slug names model+version (Principle III)
      "turn_cap": 6, "token_budget": 40000,                          // the arm's budget (Principle III: model, version, budget)
      "completed": 24, "send_failures": 0,
      "confirmed": { "rate": 0.17, "ci": [0.07, 0.35], "n": 24, "successes": 4 },
      "suspected": { "rate": 0.33, "ci": [0.18, 0.52], "n": 24, "successes": 8 },
      "mean_turns_to_success": 3.5, "mean_tokens": 5120, "cost": 0.41,   // cost "unavailable" => null + note
      "by_family": [ { "family": "...", "confirmed": 1, "suspected": 2, "n": 6 } ],
      "by_owasp":  [ { "owasp_class": "LLM01: Prompt Injection", "confirmed": 1, "suspected": 2, "n": 6 } ] },
    { "label": "B", "...": "..." }
  ],
  "comparison": {
    "confirmed": { "diff": 0.12, "z": 1.1, "p_value": 0.27, "significant": false,
                   "small_sample": true, "caveat": "Small sample (n<30 per arm); treat the difference as indicative." },
    "suspected": { "diff": 0.08, "note": "descriptive (suspected = judge opinion, Principle II)" }
  }
}
```
Rules:
- Success is split into **confirmed** (hard evidence) and **suspected** (judge) and never conflated (FR-006, SC-002).
- The significance indicator is on the **overall confirmed** rate; small samples carry the caveat and never a bare % (FR-007, SC-003). A rate over 0 scored runs is `"no data"`, not 0%.
- `cost` is `null` with a `"cost_note": "unavailable (no configured price for <model>)"` when the arm's **primary-model** price is unset — the attacker model for an adaptive arm, the judge model for a single-turn arm (FR-006, R3). Tokens are reported for both modes.
- Both attacker model slugs (model+version) and judge models are named, with each arm's budget (turn_cap/token_budget) — Principle III (model, version, budget) (FR-009).
- `by_owasp` maps to the OWASP LLM Top 10 (FR-010, Principle VI).

## GET /api/experiments/{id}/report?format=md|html → 200 (FR-014)

The downloadable report (Markdown or HTML) built by `report/experiment.py`, reusing `render_html`. `format` other than `md`/`html` → `422`. Read-only (no run, no send, no store write), like the feature-005 report.

## GET /api/experiments and GET /api/targets/{id}/experiments → 200 (UI support, FR-013)

List experiment summaries `[{id, target_id, status, mode, created_at, finished_at}]` for the Experiments screen.

## UI client (`ui/api_client.py`) + screen (`ui/app.py`)

- `create_experiment(payload)`, `experiment_status(id)`, `experiment_result(id)`, `experiment_report(id, fmt)`, `list_experiments()` — thin wrappers mirroring the endpoints (FR-013).
- `render_experiments(config, targets)` adds an Experiments section: pick a target, edit arm A and arm B (the FR-002 fields), set families/reps/caps, **Start**; show live progress (poll status); show the side-by-side result table (confirmed/suspected per arm + the significance note); a **Download report** control (md/html). No secrets are shown or entered for an arm (Principle IV).
