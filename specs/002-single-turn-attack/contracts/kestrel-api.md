# Contract: Kestrel API — feature 002 additions

Additions and changes to [feature 001's API contract](../../001-register-target/contracts/kestrel-api.md), which still holds for everything not mentioned here. The UI calls only this API ([ui-screen.md](./ui-screen.md)).

- **Header values**: still never appear in any response body, error or log line.
- **Reply text**: masked for header values before it is stored, returned or sent to the judge.

## Error format additions

| Status | Code | When |
|---|---|---|
| 409 | `run_in_progress` | A run against this target is already in progress (FR-010) |
| 409 | `permission_missing` | The target has no permission confirmation (FR-009) |
| 409 | `terms_outdated` | The target's stored terms version is older than the current one; message tells the user to read the terms and confirm again (FR-023) |
| 422 | — | Unknown family or prompt id, on field `family` or `prompt_id` |

`permission_missing` and `terms_outdated` are checked before anything is sent and **create no run**. Anything the connection tester reports — including `address_not_allowed` and `credentials_unreadable` — does create a finished run carrying that `failure_step`, because by then the attack had been handed to the tester.

## Shared shapes

**Canary** — a plain string of at least 8 characters (FR-025). Targets carry `"canaries": ["KESTREL-CANARY-7Q4M2X"]`, ordered as entered. Not a credential, so it is returned in full.

**RunSummary**

```json
{"id": 12, "target_id": 1, "prompt_id": "spl-002", "prompt_title": "Ask for the system prompt verbatim",
 "family": "system_prompt_leak", "owasp_category": "LLM01: Prompt Injection",
 "verdict": "succeeded", "hard_evidence": true, "judge_used": false, "failure_step": null,
 "started_at": "2026-10-23T14:05:00Z", "finished_at": "2026-10-23T14:05:04Z"}
```

**RunDetail**: RunSummary plus `status`, `prompt_text`, `reply_text`, `reply_truncated`, `reason`, `judge_model`, `attacker_source`.

```json
{"status": "finished", "prompt_text": "...", "reply_text": "...", "reply_truncated": false,
 "reason": "The reply contains the declared canary string.",
 "judge_model": null, "attacker_source": "library:1.0.0"}
```

`judge_model` is null exactly when `judge_used` is false. `hard_evidence` is true only for a canary match, never from a judge answer (FR-018).

## Changed endpoints

### `GET /api/config`

Gains `judge` so the UI can say up front where replies go, and the terms move to version 2.

```json
{"mode": "local",
 "defaults": {"method": "POST", "body_template": "{\"message\": \"{{prompt}}\"}", "response_path": "$.reply"},
 "terms": {"version": "2", "text": "..."},
 "judge": {"model": "google/gemini-3.8-flash", "configured": true}}
```

`configured` is false when no judge key is set. The feature still works: canary evidence still settles runs, and judged runs end `unclear` (FR-021). The UI says so rather than hiding the Run button.

### `GET /api/targets/{id}`, `POST /api/targets`, `PUT /api/targets/{id}`

TargetDetail gains `canaries`. `POST` and `PUT` accept `canaries` as a list of strings; an entry shorter than 8 characters gets a 422 on `canaries.{i}`, and a duplicate within one target gets a 422 on the same field. Omitting `canaries` on `PUT` leaves the stored ones unchanged; sending `[]` clears them.

Changing canaries does **not** require a new connection test — they play no part in reaching the agent, so feature 001's FR-012 rule does not apply to them.

## New endpoints

### `GET /api/attack-families`

200: the four families, each with the OWASP category it maps to and how many prompts it holds.

```json
{"library_version": "1.0.0",
 "families": [{"key": "direct_injection", "label": "Direct prompt injection",
               "owasp_category": "LLM01: Prompt Injection", "prompt_count": 6}]}
```

### `GET /api/attack-prompts?family=<key>`

200: the prompts in that family, so the user can pick one (FR-008). 422 on `family` if the key is unknown.

```json
{"prompts": [{"id": "spl-002", "title": "Ask for the system prompt verbatim", "text": "...",
              "family": "system_prompt_leak", "owasp_category": "LLM01: Prompt Injection",
              "source": "OWASP LLM Top 10 (2025), LLM01 examples"}]}
```

`text` is included so the user can read what will be sent before sending it. The UI renders it as plain text (FR-032).

### `POST /api/runs`

Runs one attack end to end against the chosen target and family (FR-006) and answers when it is finished. Exactly one request reaches the target, built from its stored connection settings with the prompt placeholder replaced by the attack text (FR-011). Synchronous, and capped at 90 seconds by FR-013, so a client timeout above that is required — the UI uses 120.

Request:

```json
{"target_id": 1, "family": "system_prompt_leak", "prompt_id": "spl-002"}
```

`prompt_id` is optional; without it Kestrel picks one prompt from the family and the answer names which (FR-007).

- **201**: RunDetail, `status: "finished"`.
- **404**: unknown `target_id`.
- **409**: `run_in_progress`, `permission_missing`, `terms_outdated`.
- **422**: unknown `family` or `prompt_id`.

The order of work is fixed: check the target, the permission and the terms → claim the run row (`in_progress`) → send through feature 001's tester → mask the reply → match canaries → judge only if no canary matched → finish the row. A failure at any point after the row is claimed still finishes the row.

### `GET /api/targets/{id}/runs`

200: list of RunSummary for that target, newest first (FR-028). 404 if the target does not exist. An interrupted run that the start-up sweep has closed appears like any other, with `verdict: "unclear"`.

### `GET /api/runs/{id}`

200: RunDetail. 404 if it does not exist.

## Start-up

On start-up the API closes every run still marked `in_progress`, setting `verdict: "unclear"`, `judge_used: false` and a reason saying the run was interrupted (FR-031), and logs how many it closed. This is what releases the one-run-at-a-time lock after a crash.

## Logging

One INFO line per run, in feature 001's style: target name, family, prompt id, verdict, whether it was hard evidence, the judge model, and the duration. Never the prompt text, the reply, the reason or any header value (R13).
