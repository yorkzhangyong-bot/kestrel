# Contract: Kestrel API — feature 003 additions

Additions to [feature 002's API contract](../../002-single-turn-attack/contracts/kestrel-api.md), which still holds. Only what changes is described here.

## Changed: `POST /api/runs`

Gains a `mode` field; everything else is as feature 002.

```json
{"target_id": 1, "family": "system_prompt_leak", "prompt_id": "spl-002", "mode": "adaptive"}
```

- `mode`: `"single_turn"` (default, feature 002 behaviour) or `"adaptive"`.
- `prompt_id` is still optional; for an adaptive run it chooses the **opening** message of the conversation.
- Preconditions are unchanged and still checked before any run row: 404 unknown target; 409 `run_in_progress`, `permission_missing`, `terms_outdated` (the current terms version is now **3**, R11); 422 unknown family or prompt id.
- An adaptive run is synchronous like a single-turn run, but longer; the client timeout must exceed the wall-clock cap (the UI uses the cap plus a margin).
- **201**: a RunDetail with `mode: "adaptive"` and its conversation (below).

## Changed: RunSummary and RunDetail

**RunSummary** gains `mode` so the runs list can show each run's kind:

```json
{"id": 20, "target_id": 1, "mode": "adaptive", "prompt_id": "spl-002",
 "prompt_title": "...", "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage",
 "verdict": "failed", "hard_evidence": false, "judge_used": true, "judge_model": "google/gemini-3.8-flash",
 "failure_step": null, "started_at": "...", "finished_at": "..."}
```

**RunDetail** adds the adaptive fields and the conversation. For a single-turn run `mode` is `"single_turn"`, `attacker_model` and the budgets are null, and `turns` is an empty list, so feature 002 clients are unaffected.

```json
{"...": "RunSummary fields",
 "status": "finished", "attacker_source": "library:1.0.0",
 "attacker_model": "deepseek/deepseek-v3.2",
 "turn_budget": 6, "turns_used": 6, "token_budget": 40000, "tokens_used": 31240,
 "time_limit_s": 300, "stopping_condition": "turn_cap", "succeeded_turn": null,
 "reason": "The agent held across all six turns.",
 "turns": [
   {"position": 1, "attacker_message": "<masked>", "reply_text": "<masked>", "reply_truncated": false,
    "judge_verdict": "failed", "judge_reason": "...", "judge_progress": "..."}
 ]}
```

- `turns` is the ordered conversation (FR-020); each entry is one attacker message and the target's reply, both masked, with that turn's judge verdict, reason and "how close" note.
- `prompt_text`/`reply_text` at the top level keep their feature-002 meaning for single-turn runs; for an adaptive run the conversation lives in `turns`.
- `attacker_model` and the four budget/usage numbers satisfy Principle III (FR-015); `stopping_condition` and `succeeded_turn` say how the run ended (FR-012, FR-019).

## Changed: `GET /api/config`

Gains an `attacker` block and the adaptive caps, so the screen can show what will run and offer the mode toggle:

```json
{"mode": "local", "defaults": {"...": "..."}, "terms": {"version": "3", "text": "..."},
 "judge": {"model": "google/gemini-3.8-flash", "configured": true},
 "attacker": {"model": "deepseek/deepseek-v3.2", "configured": true},
 "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300}}
```

- `attacker.configured` is false when no attacker key is set (`KESTREL_ATTACKER_API_KEY`, falling back to `OPENROUTER_API_KEY`); an adaptive run then cannot start and the UI says so, the same way the judge degrades in feature 002.
- `terms.version` is now `3`.

## Run history and single-run endpoints

`GET /api/targets/{id}/runs` and `GET /api/runs/{id}` are unchanged in shape; they now also return adaptive runs, each carrying `mode` and (for detail) the `turns` conversation. Deletion, listing order and the start-up sweep behave exactly as in feature 002, across both modes.

## Logging

One INFO line per run, extending feature 002's: target, mode, family, prompt id, verdict, evidence basis, attacker model, judge model, turns used, tokens used, duration. Never a message, a reply, a note, or a header value (R12).
