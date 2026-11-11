# Quickstart / Validation: Versioned Prompts (009)

Proves US1–US5 end to end. Shapes and column names: see `data-model.md` and `contracts/`. PowerShell first (Windows
dev), bash where useful.

## Prerequisites
- Python 3.12 + uv (`uv sync`).
- Offline suite needs no keys. The A/B arm (US4), judge eval (US5), and the e2e run need `OPENROUTER_API_KEY`.
- For the e2e run, the HS-code target running (see project `CLAUDE.md` → "HS-code target").

## US1 — provenance is recorded (offline + e2e)
Offline integration test (no keys): drive an adaptive run against a stub target and assert each `run_turns` row
carries `attacker_prompt_id/attacker_prompt_version` and `judge_prompt_id/judge_prompt_version`, and the `runs`
verdict carries `judge_prompt_id/judge_prompt_version`, all at `1.0.0` and all present in the registry.
```
uv run pytest tests/unit tests/integration -k provenance
```
Expected: ids are `attacker:<family>` / `judge`; versions `1.0.0`; a run created before the migration reads back
the `not recorded` marker (NULL). The one e2e (marker `e2e`) against the HS-code target shows the same on a real run.

## US2 — a prompt cannot change silently (offline, the headline guard)
```
uv run pytest tests/unit -k prompt_registry       # verify_lock() == [] today
```
Demonstrate the guard bites: temporarily edit one character of `judge` `SYSTEM_PROMPT` in `judge/client.py` **without**
touching the lock, re-run — the guard test FAILS and names `judge`. Revert the edit (or bump the version and append
the new fingerprint to `prompt_versions.lock.json`) → green again. (SC-002.)

## US3 — see the active prompt versions (API + UI)
API / command-line view:
```
# local mode
curl http://127.0.0.1:8000/api/config | jq '.prompts'
# hosted mode: add -H "X-Kestrel-Token: $env:KESTREL_API_TOKEN"
```
Expected: a list of `{id, version}` for attacker families, judge, recommender — **no** prompt text. UI: the active
versions appear on screen (read from the same `/api/config`). (SC-004.)

## US4 — A/B two versions of one prompt (needs models)
Create an experiment whose arms differ only by `prompt_arm_target="judge"`, `prompt_arm_version` `1.0.0` vs a second
registered judge version; run it. Expected: it completes; `ExperimentResultOut.diff` contains
`prompt: A=judge@1.0.0, B=judge@<v2>`; the comparison reports confirmed/suspected separately with the Wilson
interval and two-proportion note. An arm targeting `recommender`, or a `(target, version)` absent from the registry,
is refused before any model call (422). (SC-005.)

## US5 — judge accuracy per prompt version (needs OPENROUTER_API_KEY)
```
uv run pytest -m judge_eval
```
Expected: output groups metrics under `judge_prompt_version=1.0.0` and still enforces `recall >= 0.80`. (SC-006.)

## No behaviour drift by default (SC-003)
With every prompt at seeded `1.0.0`, the judge golden set and the e2e HS-code run produce the same outcomes as
before 009 — only provenance is now recorded.

## Quality gate (must stay green)
```
uv run ruff check src ui tests
uv run pytest tests/unit tests/integration        # coverage >= 85% on src
```
No new runtime dependency is introduced (Principle X): fingerprints use stdlib `hashlib`, version strings are
validated with stdlib `re`, and the schema step is the additive `6 → 7` migration.
