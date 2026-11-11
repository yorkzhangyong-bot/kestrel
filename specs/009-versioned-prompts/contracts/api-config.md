# Contract: `GET /api/config` — active prompt versions

Extends the existing config endpoint (`main.py:144`, `response_model=ConfigOut`). No new endpoint.

## Response (additive field on `ConfigOut`)

```jsonc
{
  "mode": "local",
  "defaults": { /* unchanged */ },
  "terms": { /* unchanged */ },
  "judge": { "model": "google/gemini-3.8-flash", "configured": true },
  "attacker": { "model": "deepseek/deepseek-v4.1-flash", "configured": true },
  "adaptive": { /* unchanged */ },
  "experience": { /* unchanged */ },
  "prompts": [                                   // NEW — active registry entries
    { "id": "attacker:direct_injection", "version": "1.0.0" },
    { "id": "judge", "version": "1.0.0" },
    { "id": "recommender", "version": "1.0.0" }
  ]
}
```

- `prompts[*]` = `PromptVersionOut { id: str, version: str }`, one per active registry entry, sorted by `id`.
- **Never** includes `text` or `fingerprint` (FR-007/SC-004); no secrets (FR-012).
- Source: the in-process registry's active entries — not the DB.

## Invariants / behaviour
- Every `prompts[*].id` is a registry id; every `version` exists in the fingerprint lock (FR-009).
- Auth unchanged: hosted mode requires a matching `X-Kestrel-Token`; local mode requires none. The "command-line
  view" is `curl <base>/api/config` (plus the token header in hosted mode).
- Adding/disabling a prompt never leaves a dangling reference: the list is generated from the registry each call.

## Consumers
- UI (`ui/app.py`) already calls `api_client.get_config()`; it renders `config["prompts"]` as id + version.
- No UI logic beyond display (the UI holds no logic — project rule).
