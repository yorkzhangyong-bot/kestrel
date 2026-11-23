# Quickstart & validation: Behavioural Evidence (013)

Per-story offline validation, the manual migration check, and the two end-to-end scenarios. Commands are
PowerShell-first (Windows 11 dev); a bash variant follows where it differs. Everything offline runs with no API
keys, a temporary database and a temporary `chroma_path`.

## Prerequisites

```powershell
uv sync
```

## The offline suite (every FR/SC except the live e2e)

```powershell
uv run pytest tests/unit tests/integration
```

New test files this feature adds (each cites `013/FR-###`/`013/SC-###` or a module-level `FEATURE = "013"`):

| File | Covers |
|------|--------|
| `tests/unit/test_evidence_model.py` | the kind table, labels, locations, `category_for`, `evidence_line` (FR-004) |
| `tests/unit/test_override_detector.py` | token generation, the joined-form check, case-insensitivity, the normalised disarm rule, 1,000-token opening-message safety, the word between the parts (FR-008 to FR-013, SC-001) |
| `tests/unit/test_override_placement.py` | the task is framed as the injected override and, for an indirect seed, lands inside its injected content, never in Kestrel's voice (FR-064, SC-014) |
| `tests/unit/test_unsafe_output.py` | the fixture: ≥3 positive / ≥3 negative **per named pattern**, 100% positive / 0% negative, one item per category, the echo rule, the pattern name and set version on each match; it also parses `contracts/detectors.md`'s named-pattern table and set version and asserts they equal the module's `PATTERNS` and `PATTERN_SET_VERSION` (FR-015 to FR-017, FR-065, SC-002) |
| `tests/unit/test_strip_planted_tasks.py` | stripping removes the run's exact filled task text (both placements, plus the callback task), and value scrubbing removes the parts, the joined form and the URL wherever else they appear (FR-063) |
| `tests/unit/test_settings_evidence.py` | the three new settings parse and refuse bad values (data-model) |
| `tests/unit/test_events_evidence.py` | the new/changed catalogue entries and the omit-when-absent rule (FR-047, FR-048) |
| `tests/unit/test_store_migration_v11.py` | the additive v11 migration, old rows readable, a second `_migrate` a no-op (FR-057) |
| `tests/integration/test_evidence_detectors.py` | a run confirmed by override / unsafe output: verdict, hard evidence, items, zero judge calls on the turn; the sent message never carries the joined form (SC-001, SC-003) |
| `tests/integration/test_evidence_store_isolation.py` | `SpyExperienceStore`: no token part, joined form, URL or task wording in any pattern write, memory record, memory summary or query — with a stub attacker that repeats the parts in turn 2+ and a stub judge that repeats them in its progress notes — while the run's own message keeps them (FR-063, SC-013) |
| `tests/integration/test_evidence_part1_replay.py` | part 1's own replay/experiment coverage: the token copy keeps its armed state, a re-sent message disarms the replay, **any** evidence item scores still vulnerable, a pre-feature source skips the planted checks, both experiment arms detect alike (FR-035, FR-036, FR-037, SC-009) |
| `tests/integration/test_side_channel_config.py` | register/validate/encrypt the side channel; the connection test's six steps and messages; save-only-what-was-tested (FR-019 to FR-021) |
| `tests/integration/test_side_channel_checks.py` | honeypot, canary-in-argument, state change confirm; other-id / already-counted / identical-snapshot do not; mid-run failure leaves the run clean with the notice (FR-024 to FR-026, FR-032, FR-034, SC-005) |
| `tests/integration/test_callback_listener.py` | a planted hit confirms; an unknown or expired token records nothing; the route needs no access token; redaction (keyed on the planted token, so a replay's old URL is still redacted) keeps the URL off model inputs; the placeholder is restored on send and the stored message equals the sent one; an unusable base plants nothing with a stated reason; a replay whose URL can no longer reach the listener is never fixed (FR-027 to FR-031, FR-068, FR-069, FR-070, SC-006, SC-015) |
| `tests/integration/test_evidence_api_ui.py` | the run summary/detail shapes, the headline, the Evidence section, the run-list column (runs without items keep today's text), the side-channel form section, the sidebar's "Callback listener: on/off" caption, the config (FR-038 to FR-043, SC-004) |
| `tests/unit/test_report_coverage.py`, `tests/unit/test_report_findings.py` (extended, T032) | items per finding, the LLM05 coverage row, LLM05 off the Not-tested list, a cross-class item **not** confirming the family's class, replays excluded (FR-044 to FR-046) |
| `tests/integration/test_evidence_redaction.py` | 0 stream lines carry a token/URL/correlation id/argument/state/detail/reply/attack text (SC-007) |

The sacrificial target's own offline tests (not run by CI — run them when touching part 2):

```powershell
uv run --directory targets/hs_code pytest
```

## Per-story smoke checks

- **US1 (override)**: `uv run pytest tests/integration/test_evidence_detectors.py -k override`. A reply carrying
  the joined form → `verdict=succeeded`, `hard_evidence=true`, one `instruction_override` item, `judge_used`
  false; the parts split or the request quoted → no item, judged as before.
- **US2 (unsafe output)**: `uv run pytest tests/unit/test_unsafe_output.py`. The fixture passes 100% positive /
  0% negative **per named pattern**, and a pattern missing cases fails the test.
- **US3 (evidence surfaces)**: `uv run pytest tests/integration/test_evidence_api_ui.py
  tests/unit/test_report_coverage.py tests/unit/test_report_findings.py`. The headline, the Evidence section, the
  run-list column and the report list every item with the exact FR-039/FR-044 texts.
- **US4/US5/US7 (side channel)**: `uv run pytest tests/integration/test_side_channel_config.py
  tests/integration/test_side_channel_checks.py`.
- **US6 (callback)**: `uv run pytest tests/integration/test_callback_listener.py`.
- **US8 (the target's own side)**: `uv run --directory targets/hs_code pytest` — including the refused-URL case
  (no request sent) and the flag-off case (today's tool set), which continuous integration does not run for you.

## The manual migration check (FR-057)

An additive bump, so no `runs` rebuild, but confirm an existing database upgrades cleanly and stays readable:

```powershell
# Point the API at a copy of a real v10 database, start it, and read a pre-feature run back.
$env:KESTREL_MODE="local"; $env:KESTREL_DB_PATH="$env:TEMP\kestrel-v10-copy.db"
uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000
# In another shell: GET /api/targets, GET /api/targets/{id}/runs — a pre-feature confirmed run still shows
# evidence_kinds ["canary_in_reply"], evidence_labels ["canary"], side_channel_status "not_configured".
```

`tests/unit/test_store_migration_v11.py` is the automated form; this is the human spot-check CLAUDE.md asks for on
a schema bump.

## End-to-end, against the owned HS-code target (SC-010; needs `OPENROUTER_API_KEY`)

Start the target (its default model is a ZDR, tool-capable endpoint):

```powershell
$env:HS_TARGET_API_KEY="test-key-123"; $env:HS_TARGET_CANARY="KESTREL-CANARY-<something>"
uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
```

```powershell
uv run pytest -m e2e tests/e2e/test_us013_detectors.py tests/e2e/test_us013_side_channel.py
```

- **Part 1** (`test_us013_detectors.py`, API in-process as 012's e2e runs): register the target, run a
  direct-injection attack, assert the structure — a new run, an override token planted and **absent in its joined
  form from the sent message** (checked on the normalised text), items (if any) of known kinds, and the judge
  prompt version recorded when no deterministic evidence was found. It does not assert which evidence the live
  model produces on the day. The shared `kestrel_api` fixture pops `KESTREL_CALLBACK_BASE_URL` from the
  environment it copies, so a developer who exports it cannot silently change what the e2e tests plant; the
  part-2 fixture sets it explicitly.
- **Part 2** (`test_us013_side_channel.py`, API started with `KESTREL_CALLBACK_BASE_URL` so the target can reach
  the listener): register the target **with** its side channel, assert the connection test (chat and side channel)
  succeeds and a run completes with `side_channel_status="checked"` and any items of known kinds. Structure only.

## What "done" looks like

- The offline suite is green, every new test cites its feature, and `uvx ruff check src ui tests` and `mypy src`
  are clean.
- `uv run python scripts/check_spec.py specs/013-behavioural-evidence` (spec PR) and `uv run python
  scripts/check_traceability.py` (implementation PR) pass; coverage on `src` stays ≥ 85%.
- `uv run python -c "from kestrel import prompt_registry as p; print(p.verify_lock())"` prints `[]` (the five
  new/bumped prompt files are locked: the two task templates and the three attacker bumps).
- `tests/unit/test_unsafe_output.py` parses `contracts/detectors.md`'s named-pattern table and set version and
  asserts they equal the module's `PATTERNS` (names and categories) and `PATTERN_SET_VERSION`, so the contract, the
  module and the fixture cannot drift — the reviewable chain FR-015 asks for.
- Both e2e scenarios pass against the live target.
