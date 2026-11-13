# Contract: `GET /api/runs/{run_id}/log` — a run's kept log lines

New read-only endpoint beside `GET /api/runs/{run_id}` (`src/kestrel/api/main.py`). The screen's log viewer is its
only consumer; it reads the `run_log` table through the store and nothing else.

## Request

`GET /api/runs/{run_id}/log` — no query parameters. Hosted mode: the app-wide `X-Kestrel-Token` dependency applies
(401 `unauthorized` without it); local mode needs no token.

## Response `200` — `RunLogOut`

```jsonc
{
  "run_id": 42,
  "lines": [                         // the kept records, parsed, in emission order
    {"ts": "2026-11-13T10:15:00.004Z", "level": "INFO", "logger": "kestrel", "event": "run.start",
     "run_id": 42, "target_id": 3, "mode": "adaptive", "family": "direct_injection",
     "prompt_id": "dir-003", "attacker_source": "library:1.0.0", "attacker_model": "deepseek/deepseek-v4.1-flash",
     "judge_model": "google/gemini-3.8-flash", "attacker_prompt": "attacker:direct_injection@1",
     "judge_prompt": "judge@1", "turn_budget": 6, "token_budget": 40000, "time_limit_s": 300,
     "use_prior_experience": true},
    /* … target.request, model.request, turn, … */
    {"ts": "2026-11-13T10:15:09.771Z", "level": "INFO", "logger": "kestrel", "event": "run.end",
     "run_id": 42, "target_id": 3, "mode": "adaptive", "family": "direct_injection",
     "verdict": "failed", "hard_evidence": false, "stopping_condition": "turn_cap", "failure_step": null,
     "judge_used": true, "turns_used": 2, "tokens_used": 1606, "succeeded_turn": null, "memory_written": true,
     "duration_ms": 9767,
     "cost_usd": null, "cost_note": "unavailable (no configured price for deepseek/deepseek-v4.1-flash)"}
  ],
  "kept": 9,
  "dropped": 0,
  "truncated": false
}
```

- `lines[*]` are exactly the records emitted inside the run's scope — from `run.start` to `run.end` inclusive,
  `memory.writeback` included — as they went to the stream (contracts/log-records.md); when the cap was hit the
  last line is the `log.truncated` marker `{"event": "log.truncated", "run_id": 42, "kept": 1000, "dropped": n}`.
  A record emitted for the run after its scope closed (the recommender's line at report time) is never part of
  the response: generating a report leaves this endpoint's answer byte-identical, marker included.
- A run with no kept lines (one that predates schema v8, or one whose sink failed throughout) answers `200` with
  `lines: []`, `kept: 0`, `dropped: 0`, `truncated: false` — the viewer renders the explicit empty state.
- A run in progress answers with the lines kept so far.

## Errors

| Case | Status | Body |
|------|--------|------|
| Unknown run id | 404 | `{"error": {"code": "not_found", "field": null, "message": "No run with id 42."}}` |
| Hosted mode, missing or wrong token | 401 | the existing `unauthorized` body |

## Invariants

- No field of any line is outside the FR-009 allow-list; the endpoint adds nothing of its own (no target name, no
  URL, no prompt or reply text) — it serves the kept records as they are.
- Read-only: no run, no send, no store write.
- The order is `seq` ascending; `kept + dropped` is the number of records the run's scope emitted.
