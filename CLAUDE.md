# Kestrel — project memory for Claude

Autonomous red-teaming agent for tool-using AI agents: register an HTTP chat target you own, pick an attack
family, and Kestrel runs single-turn or adaptive multi-turn attacks, judges them (hard evidence first), learns
across runs, and reports mapped to the OWASP LLM Top 10. Features 001–010 are merged.

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
- **ChromaDB systems must be stopped in tests:** `SharedSystemClient.clear_system_cache()` only forgets chroma Systems; on Windows every seeded persistent store keeps 3–4 C-runtime descriptors (limit 8192) until `System.stop()`, so `tests/conftest.py::_release_chroma` stops every cached System after each test. Without it, running the integration suite before the unit suite fails the connection-tester test with "Too many open files".

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
- 2026-11-13 — **Structured logging and tracing (010).** Every line on stderr from the `kestrel` logger is one JSON
  object (`KESTREL_LOG_FORMAT=text` renders the same fields as `ts level event key=value`); uvicorn's own lines are
  not part of the stream. Emit only through `kestrel.events` (`emit(event, **fields)` or the helpers): values are
  fields, never %-interpolated — `tests/unit/test_events.py` fails CI on a `log.*(…, value)` call in `src/kestrel` —
  and `events.CATALOGUE` is the allow-list: a new field must be added there (and to
  `specs/010-*/contracts/log-records.md`) or it is dropped with a `log.unknown_field` warning. No URL, display name,
  auth value, prompt/reply text, judge reason/progress or exception message on any line; exceptions render as
  `exc_type` + `stack`. The **run scope** (`events.run_scope()`) is opened by the caller around the run function
  **and** `write_back` (`api/main.py::start_run`, `experiments/engine.py::_run_rep`); `run_started(store, …)` after
  `claim_run` binds the ids and the run's store, and the scope's exit emits `run.end` last. A line about a run outside
  its scope uses `events.bind_run_reference(run)` (stream only, never kept). Kept lines: schema **v8** `run_log`
  (cap `store.RUN_LOG_CAP = 1000` + one `log.truncated` marker), written by `logging_setup.RunLogHandler` through the
  record's own run-context store, served by `GET /api/runs/{id}/log`, shown in the run page's **Log** expander.
  **Tracing**: `KESTREL_TRACING=on` + `uv sync --extra otel` (dev group has it); standard `OTEL_EXPORTER_OTLP_*` /
  `OTEL_SERVICE_NAME` (default `kestrel`; the Python exporter reads `OTEL_EXPORTER_OTLP_TIMEOUT` in **seconds**).
  Gotchas: ChromaDB and FastAPI already pull the OpenTelemetry API/SDK (`import chromadb` loads the SDK), so "no
  tracing import with the flag off" means `kestrel/tracing.py` imports nothing at module level; FastAPI 0.161 traces
  every request natively once a global provider exists, so the app is created with
  `telemetry={"tracing": False, "metrics": False, "logs": False}` and Kestrel's provider is private (never
  `set_tracer_provider`); the SDK ignores its flush timeout and its shutdown can wait 30 s, so Kestrel joins it in a
  daemon thread for at most 5 s; an `InMemorySpanExporter` is dead after its provider shuts down (do not reuse one
  across `configure_tracing` calls). Tests: `caplog.text` shows only event names now — count secrets over the
  `json_log` fixture; pytest 9 attaches its capture handler to non-propagating loggers (probe the root logger, not
  caplog, for the silenced `opentelemetry` loggers), but only to those already non-propagating when a test phase
  starts: `configure_logging` makes `kestrel` non-propagating (no root handler may render an exception message), so
  `tests/conftest.py` does so at import and every test captures it alike; real clients run offline via the
  `model_transport` fixture (`tests/support.py`: `real_judge`, `real_attacker`, `model_settings`); experiments with
  pinned prompts need the engine's own factories (no injected doubles); UI tests get an autouse offline
  `get_run_log` stub (no `raising=False`; `tests/unit/test_api_client_run_log.py` puts the real client back).
  Every app's `configure_logging` installs the stream and the run log handler on the process-wide `kestrel` logger;
  the autouse `_reset_observability` takes them off after each test (`logging_setup.reset()`) — a leftover run log
  handler kept a later test's records twice. Provenance is now written from the reference the client actually
  sends (a pinned arm's version; a single-turn verdict's judge version), judge provenance only when a judge request
  was made. `KESTREL_TEST_BLOCK_OTLP=1` blocks the OTLP exporter import for a whole test session (SC-007).
- 2026-11-16 — **Retrieval controls (011).** Settings: `KESTREL_EXPERIENCE_DISTANCE_FLOOR=1.8` and
  `KESTREL_EXPERIENCE_DEDUPE_THRESHOLD=0.15` (both on by default; `off` disables one; a negative or non-numeric value
  refuses to start), parsed by `settings.non_negative_float_or_off`, read as `Settings.retrieval` →
  `RetrievalSettings(k, distance_floor, dedupe_threshold)`, reported on `GET /api/config`. Distances are the
  collection's own `l2` (squared Euclidean) values. **One retrieval path**: `experience/retrieval.py` —
  `background_provider(...)` is the per-turn callable both `api/main.py::start_run` and `experiments/engine.py::_run_rep`
  hand to the graph (`attack/graph.py` still takes a plain callable and never imports the store). The query is
  `family_label(family)` + the last `QUERY_MESSAGES = 2` messages whose role is exactly `attacker` (the graph's
  `(role, text)` list; `agent` replies are filtered, and the judge reason/progress, memory summaries and the purpose
  description are not in that list at all — `tests/integration/test_retrieval_query_isolation.py` proves it with the
  known markers through a `SpyExperienceStore`). Pool = `min(k × CANDIDATE_MULTIPLIER (4), family count)` from
  `ExperienceStore.query_patterns` (`Candidate`: id, document, distance, stored embedding); `select_patterns` walks
  nearest first — a candidate `> floor` ends the walk and every later one counts in `dropped_floor`; one whose squared
  distance to an already selected hit is `<= threshold` is skipped (`dropped_duplicate`, no slot spent); stop at `k`.
  The `memory.retrieval` line carries `k`, `distance_floor`, `dedupe_threshold` (`null` when off), `candidate_count`
  (always `dropped_floor + dropped_duplicate + pattern_count`), `distances` (4 decimals) and `query_messages`; a floor
  that admits nothing gives `pattern_count` 0 and the run goes on. **Write-back**: `write_pattern(...,
  dedupe_threshold=)` returns `PatternWrite` — the nearest same-family pattern (library seeds included) within the
  threshold gets `hit_count + 1` and `last_hit_run_id` (`merged`), else a new `pattern:run:<id>` with `hit_count` 1
  (`added`); `memory.writeback` carries `pattern_outcome`, `pattern_id`, `hit_count`, `pattern_distance`. ChromaDB
  metadata semantics that make this work: `upsert`/`update` with a metadata dict **merge keys** (an omitted key is
  kept — `seed_patterns` upserts existing seed ids without `hit_count`, so counts survive every start-up), while
  `collection.modify(metadata=...)` **replaces** the whole collection dict (the stamp rewrites all three keys).
  **Model stamp**: the collection is created with `configuration={"hnsw": {"space": "l2"}}` and metadata
  `kestrel_embedding_model` + `kestrel_distance_space`; the name comes from `embedding_model_name(ef)` — `None` or
  ChromaDB's `DefaultEmbeddingFunction` → `all-MiniLM-L6-v2` (`ONNXMiniLM_L6_V2.MODEL_NAME`; the default delegates
  every call to it), else the function's `MODEL_NAME`, else its `name()`; the stub's is `kestrel-lexical-stub`. The
  ctor keyword `embedding_model=` is the test seam for "another model" (ChromaDB's own check on the registered
  function *name* would fire first). `self_check` compares the space, then the name, before the probe:
  `SpaceMismatch` / `EmbeddingModelMismatch` → one ERROR `experience.unavailable` with `reason_kind`
  `space_mismatch`/`embedding_model_mismatch`, `stored_*`/`expected_*` fields and a mismatch-specific constant
  `message` with the remedy (`api/main.py::_unavailable_message`); the store is `None` for the session, runs record
  `memory_written` false. A feature-004 store (version only) is stamped on first open (one `message` line) — only if
  its index really is `l2`; a recorded name is never overwritten. Gotcha: `get_or_create_collection` **ignores a
  conflicting `configuration` on reopen**, so the actual space is read back from
  `collection.configuration_json["hnsw"]["space"]`, never assumed. **Offline scale**: `tests/support.py::
  StubEmbeddingFunction` is a hashed bag of words (`zlib.crc32(token) % 256`, L2-normalised): identical texts 0,
  disjoint 2.0, one token of six changed ≈ 0.333 — every offline floor/threshold test states values on this scale
  (the shipped 1.8/0.15 still behave against the placeholder seeds). **Recall fixture**:
  `tests/fixtures/retrieval_recall.json` (contract `specs/011-retrieval-controls/contracts/recall-fixture.md`): k 3,
  floor 0.8, threshold 0.5, a 21-word collision-free vocabulary; `tests/unit/test_retrieval_recall.py` reproduces the
  published distances rounded to 4 decimals and asserts a ≥ 0.1 margin from both controls — extend it only with words
  whose `crc32 % 256` bucket is free, and keep every text placeholder vocabulary. **Measured real-model distances**
  behind the defaults (research D6): seedless on-theme queries up to 1.74 from the nearest family seed, unrelated
  text 2.0–2.15; whitespace/spelling/one-word variants 0.004–0.088, a paraphrase 0.253, the nearest two shipped seeds
  of one family 0.543 — the e2e (`tests/e2e/test_us011_retrieval.py`, API in-process, up to four warm runs until one
  reaches a seedless turn-4 query) confirms merged at ~0.09 and added at ~0.25. The subprocess-based
  `assert_no_secret_in_logs` fixture does not apply to an in-process e2e; `json_log` captures the stream there.
