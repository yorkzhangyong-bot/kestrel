# Kestrel — project memory for Claude

Autonomous red-teaming agent for tool-using AI agents: register an HTTP chat target you own, pick an attack
family, and Kestrel runs single-turn or adaptive multi-turn attacks, judges them (hard evidence first), learns
across runs, and reports mapped to the OWASP LLM Top 10. Features 001–008 are merged.

## Working with me
- Keep replies short.
- Windows 11 dev; I run commands in **PowerShell**. Give PowerShell variants (and bash where useful).
- Spec Kit scripts: `powershell -NoProfile -File .specify/scripts/powershell/<script>.ps1` (`pwsh` is not installed).

## Stack (fixed — Principle X; a new dependency needs a one-line justification in the plan)
Python 3.12, uv, FastAPI, Streamlit, LangGraph, httpx, SQLite (stdlib `sqlite3`), ChromaDB, pytest, markdown-it-py.
Statistics use stdlib `math` only. Models via OpenRouter: attacker default `deepseek/deepseek-v4.1-flash`, judge
default `google/gemini-3.8-flash`.

## Layout
- `src/kestrel/` — `api/` (FastAPI), `attack/` (LangGraph adaptive loop), `attacks/` (library), `connection/`
  (target transport + address guard), `experience/` (ChromaDB store), `experiments/` (007 A/B harness), `judge/`,
  `report/`, `store.py` (SQLite), `settings.py`, `runs.py`, `secrets.py`.
- `ui/` — Streamlit `app.py` + `api_client.py`; the UI only calls the API, never holds logic.
- `targets/hs_code/` — sacrificial CargoLint HS-6 target (test support only).
- `tests/` — `unit/` + `integration/` (offline, no keys); `e2e/` (marker `e2e`); `eval/` (marker `judge_eval`).
  Both markers are excluded from the offline suite and need `OPENROUTER_API_KEY`.
- `scripts/` — CI helpers (`check_spec.py`, `check_traceability.py`, `ai_review.py`), `import_attacks.py`,
  `export_judge_samples.py`.
- `specs/<nnn>-*/` — `spec.md`, `plan.md`, `tasks.md`, `contracts/`, `checklists/`, `traceability.md`.
- `.specify/` — `memory/constitution.md`, `scripts/powershell/`, templates. `docs/` — design, QA pipeline, scorecard.

## Spec Kit flow (per feature)
`/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.
- **Spec-only PR first**: commit only `specs/<nnn>-*/` (spec + checklists). The code owner approves before implementation.
- **Implementation PR** then carries a `Spec-PR: #n` line in its description (the traceability gate requires it on
  any PR that touches code dirs).
- A PR that edits a spec file alongside a `src/` change needs a `spec-change:` note.

## Traceability & tests
- Every test cites its feature: a scoped token `<nnn>/FR-001` or `<nnn>-FR-001`, **or** a module-level
  `FEATURE = "<nnn>"` marker (then bare `FR-###`/`SC-###` count for that feature).
- Untraced ids are justified in `specs/<nnn>-*/traceability.md` as `<nnn>/FR-00x: <reason>`.
- Tests-first (TDD). One e2e per feature against the HS-code target.
- Quality gate: **ruff clean** (`E4,E7,E9,F`, line length 120, over `src ui tests`), **mypy** advisory on `src`,
  **coverage ≥ 85%** on `src` (`uv run pytest tests/unit tests/integration`), gitleaks, pip-audit.
- **Conventional commit messages.**

## Hard rules
- **No attack-prompt text** in code, comments, tests, fixtures, or commits — behaviour only. **Single documented
  exception:** `tests/eval/judge_samples.json` (judge-accuracy golden set) carries short, generic injection
  `attack` strings against the owned HS-code target, so the judge is graded on a real attack/reply pair.
- **Secrets never leave the vault (Principle IV).** Auth header values are Fernet-encrypted; never logged, shown in
  the UI, or written to reports, memory, or vector-store metadata. The judge/attacker never receive an auth value,
  the target URL, or the target name.
- Attack only owned/permitted targets; the permission box must be ticked; runs are plain conversation under hard
  caps (Principle VIII).

## Git / review
- Branch protection on `master`: 1 approval from the code owner `@ilikeandroid` (CODEOWNERS `* @ilikeandroid`,
  `/specs/`), plus required status checks. Feature branches named `<nnn>-*`, off `master`.
- **Workflow-editing PRs** (`.github/workflows/*`) can't be reviewed by the Claude Code Action (it refuses when a
  PR changes a workflow), so they are **admin-merged**.
- `SKIP_AI_REVIEW` repo variable currently **bypasses** the AI review gate (temporary; delete to restore fail-closed).
- Commit/push only when asked.

## HS-code target (local demo / e2e)
Start from the repo root (needs `OPENROUTER_API_KEY` for its conversational agent):
```
# PowerShell: $env:HS_TARGET_API_KEY="test-key-123"; $env:HS_TARGET_CANARY="KESTREL-CANARY-..."
uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
```
Register in Kestrel: URL `http://127.0.0.1:8001/chat`, method `POST`, header `X-API-Key` = `HS_TARGET_API_KEY`,
body `{"message": "{{prompt}}"}`, response path `$.reply`, canary = `HS_TARGET_CANARY`, tick "I own this agent or
have written permission".

## Gotchas (project memory)
- **OpenRouter guardrail:** this account 404s older DeepSeek/Qwen attacker slugs (e.g. `deepseek-v3.2`); the
  permitted default is `deepseek/deepseek-v4.1-flash`.
- **ChromaDB embedding function:** the store persists the embedding function by name, so a stub-EF store poisons
  the real app's `data/chroma`. Tests must use a tmp `chroma_path`, never the repo's.
- **No `.env` auto-load:** the app reads real environment variables and does **not** load `.env`. Export settings
  into the shell first (`set -a; . ./.env; set +a`) or pass `uvicorn --env-file`, then start the API.

## More
Longer detail lives under `docs/`: [technical-design.md](docs/technical-design.md),
[qa-pipeline.md](docs/qa-pipeline.md), [qa-scorecard.md](docs/qa-scorecard.md),
[branch-protection.md](docs/branch-protection.md), plus each feature's `specs/<nnn>-*/`.

When you discover something durable about this repo — a gotcha, a command, a convention — append it here in the
same commit. Before opening any implementation PR, review this file and add anything learned during the feature.

## Learned notes
- 2026-11-13 — **Prompt registry (009, after the PR #19 review).** Every model-facing prompt (attacker per
  family, judge, recommender) is a file `src/kestrel/prompts/<id with ':'→'_'>.v<N>.md` with a two-line YAML
  front-matter (`id`, `version`); **no prompt text lives in Python**. The files are the registry
  (`src/kestrel/prompt_registry.py`): the highest `N` is active, older files are the non-active versions an A/B
  arm can pin, and `load_prompt("judge")` returns `(text, "judge@1")`. Versions are plain integers, not semver.
  The committed lock `src/kestrel/prompt_versions.lock.json` (`{id: {version: sha256}}`) pins every file's
  fingerprint over the file text; the guard (`verify_lock()`, `tests/unit/test_prompt_guard.py`) fails CI on an
  edited file without a bump, a version file the lock does not pin, or a pinned version with no file. To change
  a prompt: `uv run python scripts/bump_prompt.py judge` (copies `judge.v1.md` → `judge.v2.md`), edit the new
  file, then `uv run python scripts/bump_prompt.py judge --lock` to record it. The OWASP report header prints the
  judge/attacker prompt versions recorded on the runs next to the model slugs. The memory summariser is
  deterministic (no model prompt) — three prompt kinds, not four. Schema is v7 (provenance columns on
  `run_turns`/`runs`, prompt-arm columns on `experiment_arms`). Gotcha: a colon is not a legal Windows file-name
  character, hence `attacker_direct_injection.v1.md`; the front-matter `id` (`attacker:direct_injection`) is
  authoritative. The experience store's pattern query uses the library's family label (the per-family goal
  sentences moved into the prompt files).
