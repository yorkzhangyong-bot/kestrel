# Quickstart / Validation: Versioned Prompts (009)

Proves US1–US5 end to end. Shapes and column names: see `data-model.md` and `contracts/`. PowerShell first (Windows
dev), bash where useful. *Amended by the PR #19 review: prompts are files, versions are integers.*

## Prerequisites
- Python 3.12 + uv (`uv sync`).
- Offline suite needs no keys. The A/B arm (US4), judge eval (US5), and the e2e run need `OPENROUTER_API_KEY`.
- For the e2e run, the HS-code target running (see project `CLAUDE.md` → "HS-code target").

## Where the prompts are
```
src/kestrel/prompts/
  attacker_direct_injection.v1.md   attacker_indirect_injection.v1.md
  attacker_system_prompt_leak.v1.md attacker_tool_exfiltration.v1.md
  judge.v1.md                       recommender.v1.md
src/kestrel/prompt_versions.lock.json     # {id: {version: sha256}}
```
Each file is a two-line YAML front-matter (`id`, `version`) above the text; the highest `N` is the active version.
```
uv run python -c "from kestrel import prompt_registry as pr; print(pr.load_prompt('judge')[1])"   # judge@1
```

## US1 — provenance is recorded (offline + e2e)
Offline integration test (no keys): drive an adaptive run against a stub target and assert each `run_turns` row
carries `attacker_prompt_id/attacker_prompt_version` and `judge_prompt_id/judge_prompt_version`, and the `runs`
verdict carries `judge_prompt_id/judge_prompt_version`, all at version `1` and all present in the registry.
```
uv run pytest tests/unit tests/integration -k "provenance or header_prompts"
```
Expected: ids are `attacker:<family>` / `judge`; versions `1`; a run created before the migration reads back
the `not recorded` marker (NULL), and the report header prints `· prompt(s): judge@1` next to the judge model (or
`not recorded`). The one e2e (marker `e2e`) against the HS-code target shows the same on a real run.

## US2 — a prompt cannot change silently (offline, the headline guard)
```
uv run pytest tests/unit -k "prompt_guard or prompt_registry or bump_prompt"   # verify_lock() == [] today
```
Demonstrate the guard bites: temporarily edit one character of the text in `src/kestrel/prompts/judge.v1.md`
**without** touching the lock, re-run — the guard test FAILS and names `judge`. Revert the edit → green again.
The real bump flow:
```
uv run python scripts/bump_prompt.py judge          # judge.v1.md -> judge.v2.md, ready to edit
# edit src/kestrel/prompts/judge.v2.md
uv run python scripts/bump_prompt.py judge --lock   # records judge@2; the guard is green and judge@2 is active
```
(SC-002.) `judge.v1.md` stays in the folder as the non-active version an A/B arm can pin.

## US3 — see the active prompt versions (API + UI)
API / command-line view:
```
# local mode
curl http://127.0.0.1:8000/api/config | jq '.prompts'
# hosted mode: add -H "X-Kestrel-Token: $env:KESTREL_API_TOKEN"
```
Expected: a list of `{id, version}` for attacker families, judge, recommender — **no** prompt text. UI: the active
versions appear in the sidebar's "Prompt versions" expander (read from the same `/api/config`). (SC-004.)

## US4 — A/B two versions of one prompt (needs models)
Bump the judge prompt as above (so `judge.v1.md` and `judge.v2.md` both exist and are locked), then create an
experiment whose arms differ only by `prompt_arm_target="judge"`, `prompt_arm_version` `1` vs `2`; run it.
Expected: it completes; `ExperimentResultOut.diff` contains `prompt: A=judge@1, B=judge@2`; the comparison reports
confirmed/suspected separately with the Wilson interval and two-proportion note. An arm targeting `recommender`, or
a `(target, version)` with no file, is refused before any model call (422). (SC-005.)

## US5 — judge accuracy per prompt version (needs OPENROUTER_API_KEY)
```
uv run pytest -m judge_eval
```
Expected: output groups metrics under `judge_prompt_version=1` and still enforces `recall >= 0.80`. (SC-006.)

## No behaviour drift by default (SC-003)
With every prompt at seeded version `1` — the file texts are byte-identical to the constants they replaced, with the
same fingerprints — the judge golden set and the e2e HS-code run produce the same outcomes as before 009; only
provenance is now recorded and shown.

## Quality gate (must stay green)
```
uvx ruff check src ui tests scripts
uv run pytest tests/unit tests/integration        # coverage >= 85% on src
```
No new runtime dependency is introduced (Principle X): fingerprints use stdlib `hashlib`, versions and the
front-matter are read with stdlib `re`/string handling, and the schema step is the additive `6 → 7` migration.
