# Kestrel — project memory for Claude

Autonomous red-teaming agent for tool-using AI agents: register an HTTP chat target you own, pick an attack
family, and Kestrel runs single-turn or adaptive multi-turn attacks, judges them (hard evidence first), learns
across runs, and reports mapped to the OWASP LLM Top 10. Features 001–012 are merged.

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
  any PR that touches `src/` or `ui/`) — or, for a refactor or bug fix that implements no spec, `Spec-PR: none` +
  `Spec-PR-reason: refactor` (+ the `refactor` label) or `Spec-PR-reason: bugfix: #<issue>` (+ the `bugfix` label,
  its issue checked to exist in this repository). See "Git / review" below.
- A PR that edits a spec file alongside a `src/` change needs a `spec-change:` note.

## Traceability & tests
- Every test cites its feature: a scoped token `<nnn>/FR-001` or `<nnn>-FR-001`, **or** a module-level
  `FEATURE = "<nnn>"` marker (then bare `FR-###`/`SC-###` count for that feature).
- Untraced ids are justified in `specs/<nnn>-*/traceability.md` as `<nnn>/FR-00x: <reason>`.
- Tests-first (TDD). One e2e per feature against the HS-code target.
- **No test pins wording or headings in docs** (roadmap, README, learned notes, design notes): a documentation
  requirement is justified in the feature's `traceability.md`, never asserted on prose. Owner rule, 2026-11-24,
  after `tests/unit/test_roadmap.py` broke master on a roadmap restructure that the docs-only CI path never ran.
  The rule covers docs prose only, not specification contracts: a test that parses a `specs/*/contracts/*.md`
  table to keep names or versions in step with the code (`tests/unit/test_unsafe_output.py`) is fine.
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
- **The Spec-PR rule** (any PR touching `src/` or `ui/`, any branch; `check_traceability.py`, 006): `Spec-PR: #<n>`,
  or the honest path — `Spec-PR: none` + exactly one `Spec-PR-reason:` line (`refactor`, or `bugfix: #<issue>`
  whose number the gate looks up live and must exist in this repository, open or closed) + the matching label
  (`refactor`/`bugfix`, created by hand, not the other one). Every keyed line starts in column 1 of the raw
  description; the gate reads the description and labels live (`gh pr view`) at evaluation time, never from the
  triggering event. A body edit or a `refactor`/`bugfix` label change re-runs only the `traceability` job via the
  non-required `.github/workflows/qa-recheck.yml`; nothing else re-runs for those events. Accepted forms and the
  fail-closed cases: `docs/qa-pipeline.md`; labels: `docs/branch-protection.md`.
- **Workflow-editing PRs** (`.github/workflows/*`) can't be reviewed by the Claude Code Action (it refuses when a
  PR changes a workflow), so they are **admin-merged**.
- `SKIP_AI_REVIEW` repo variable currently **bypasses** the AI review gate (temporary; delete to restore fail-closed).
- Commit/push only when asked.

## HS-code target (local demo / e2e)
Its conversational agent's default chat model is `openai/gpt-oss-120b` (`CARGOLINT_CHAT_MODEL`, one shared
`DEFAULT_CHAT_MODEL` constant in `targets/hs_code/agent/config.py`, read by both it and `app.py`) — a Zero Data
Retention (ZDR), tool-capable OpenRouter endpoint; see the Gotchas entry below for why.
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
- **ChromaDB mutates the collection configuration it is given:** `get_or_create_collection(configuration=...)`
  writes the call's embedding function into that dict (chromadb 1.5.9, `api/client.py`), so a dict shared between
  calls pins the first store's function onto every later store in the process — a default store silently built
  on the stub while recording `all-MiniLM-L6-v2`, or `ValueError: Multiple embedding functions provided` the other
  way round, and an order-dependent offline suite. Never share a mutable configuration between ChromaDB calls;
  `ExperienceStore.__init__` builds a fresh one per call (`tests/unit/test_experience_store_model.py` proves both
  orders).
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
  front-matter (`id`, `version`) — plus, since feature 013, one **optional** third key `framing`, which only a
  planting template carries (`framing: override`) and which a bump preserves; **no prompt text lives in Python**. The files are the registry
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
  `KESTREL_EXPERIENCE_DEDUPE_THRESHOLD=0.15` (both on by default; `off` disables one; a negative, non-finite or
  non-numeric value refuses to start), parsed by `settings.non_negative_float_or_off`, read as `Settings.retrieval` →
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
- 2026-11-17 — **Retrieval controls (011), independent-review fix.** `ExperienceStore.write_pattern`'s add path
  gives every added pattern a unique `pattern:run:<uuid4().hex>` id via `collection.add` (never `upsert`): the old
  `pattern:run:<run_id>` id assumed `run_id` was unique, but `runs.id` was `INTEGER PRIMARY KEY` without
  `AUTOINCREMENT`, so deleting a target (cascading its runs) freed its numeric ids for SQLite to reissue, and a
  later run that reused one silently overwrote an unrelated, still-shared pattern (same id, new document, `hit_count`
  reset to 1, stale `last_hit_run_id`) — reproduced in a temp directory by the reviewer. `run_id` now lives only in
  metadata (`origin_run_id`, `source`); a legacy `pattern:run:<run_id>` id from before this fix stays a valid merge
  target. Schema **v9**: `runs.id INTEGER PRIMARY KEY AUTOINCREMENT`, so a run id is never reissued once its row is
  gone. SQLite can't `ALTER` AUTOINCREMENT into a column, so an existing database's `runs` is rebuilt following
  SQLite's documented procedure (lang_altertable.html, "Making Other Kinds Of Table Schema Changes"): a `runs_new`
  built from the same column list (now with AUTOINCREMENT), `INSERT ... SELECT` by explicit column name (read live
  from `PRAGMA table_info(runs)`, so it can't drift from whatever columns the additive migrations just added),
  `DROP TABLE runs`, rename back, reindex, `PRAGMA foreign_key_check` required empty before commit. Gotcha:
  `PRAGMA foreign_keys` is a no-op inside an open transaction — Python's sqlite3 (legacy mode) only auto-opens one
  before INSERT/UPDATE/DELETE, never before CREATE/DROP/ALTER, so `PRAGMA foreign_keys = OFF` still takes effect
  right before the rebuild's own first `INSERT ... SELECT` opens one; four tables reference `runs` (`run_turns`,
  `report_recommendations`, `run_log` all `ON DELETE CASCADE`, `experiment_runs` `ON DELETE SET NULL`), and with
  foreign keys on, `DROP TABLE runs` performs an implicit DELETE that fires those actions and wipes or nulls every
  child row. A second gotcha: `db.executescript(...)` commits any open transaction before running, so the rebuild's
  two index-recreation statements are issued as separate `db.execute()` calls, not one script, or the commit would
  land before `foreign_key_check` gets to refuse it. Both gotchas were verified empirically (a standalone sqlite3
  script) before being committed, not just reasoned about. `sqlite_sequence` carries over the highest copied id, so
  an id freed by a deletion *before* this migration can be reissued once — harmless now that pattern ids are never
  derived from it. Migration tests that pin "the current schema version" as a literal string needed only the digit
  bumped (`8` → `9`) wherever one already existed; the new `tests/unit/test_store_migration_v9.py` follows the
  `test_store_migration_v<N>.py` convention each version bump has used since v3.
- 2026-11-19 — **Regression replay (012).** A replay re-sends a past, succeeded run's own recorded attacker
  message(s) verbatim, in order, with **no attacker-model call**, scores each reply canary-then-judge exactly as
  a live run does, and records one outcome against the source: `fixed` / `still_vulnerable` / `inconclusive`
  (`replay.py::compute_outcome`). **Never read a replay's outcome off the run's own aggregate `verdict`** — a
  later turn's clean `"failed"` can silently overwrite an earlier turn's unresolved `"unclear"` (a `JudgeError`
  or "no judge configured" turn leaves `last_verdict` untouched and the graph keeps going), so `compute_outcome`
  is fed the *sequence of per-turn results*, captured live inside the replay's own `record_node` as it runs, never
  reconstructed from stored `run_turns` rows afterward. For a **multi-message** source, `fixed` additionally
  requires the source's own **winning turn** (`runs.succeeded_turn`) to have itself been sent and judged
  `"failed"` — gated on `recorded_total > 1`, never on `winning_turn is None`, since a single-turn-mode source's
  `succeeded_turn` is always null by schema (not by omission); getting that gate backwards scores every
  single-turn source `inconclusive` forever. **Replayability and its seven reason strings**
  (`replay.check_replayable`/`compute_replay_status`) depend on the run *and its target's current*
  permission/terms/other-run-in-progress state, never the run's own fields alone — computed once per run in
  `api/main.py::run_summary` and reused verbatim by the single-replay endpoint's own 409s, so the two can never
  disagree. **No experience-store access, structurally**: `replay.py` and the new `run_replay_adaptive` import
  nothing from `kestrel.experience` at all (an AST-based test parses the source and checks for the actual import
  node, not a text search — a docstring that itself says "never imports kestrel.experience" would false-positive
  a substring check). The batch cap is `KESTREL_REPLAY_BATCH_MAX_RUNS` (default 20, `Settings.replay_batch_max_runs`,
  reported on `GET /api/config` as `replay.max_batch_runs`); a batch that stops partway through (a `RunInProgress`
  collision, or one entry's own `ReplayFailed`) is still a **200** with `complete: false` and a `stop_reason`,
  never a 409 — the precondition checks (permission, terms, the cap, a target-wide in-progress check with
  `excluding_run_id=-1`, since there is no "this run" for a batch request) only run *before* the first entry is
  claimed. `scripts/check_replay.py` is a standalone `httpx` + stdlib client (no `kestrel`/`ui` import): exit `1`
  ("still vulnerable") wins over everything regardless of completeness; exit `0` needs both a *completed* batch
  and every entry fixed; `argparse`'s own exit-2-on-bad-args must be remapped to this feature's `3`, or a missing
  `--target-id` would exit with the wrong code. **The graph lift** (`judge_node`/`send_node`/`evidence_node`/
  `decide_node` lifted out of `run_adaptive` to module-level `_judge_turn`/`_send_turn`/`_check_evidence`/
  `_decide_next`, shared with the new `run_replay_adaptive`) is mechanical and behaviour-preserving — proved by
  running the full offline suite before and after and diffing the pass/fail set, not by re-reading the diff.
  `attacker_node`/`record_node` are deliberately **not** shared (a model call vs. a list lookup); both the live
  and replay versions index `source_turns`/conversation state at `turns_used + 1 - 1`, and a replay's own
  `attacker_node` and `record_node` must use the *same* index for the message lookup and the provenance copy, or
  turn *N*'s message ships with turn *N±1*'s attacker-prompt version. **Schema v10** (`mode` CHECK widened to
  `'replay'`, plus `source_run_id`/`replay_outcome`) is a *second* rebuild of `runs`, by the same procedure v9
  used — but `RUNS_COLUMNS_SQL` is the *one* shared definition behind the fresh `CREATE TABLE`, the v9 rebuild and
  the v10 rebuild, so a database jumping straight from pre-v9 to v10 in one `_migrate` call gets the v10 shape
  directly from the v9-rebuild step (since that step's `CREATE TABLE runs_new` already uses the current,
  v10-shaped `RUNS_COLUMNS_SQL`) and the v10 rebuild step simply no-ops (its own guard checks for `source_run_id`
  in `PRAGMA table_info(runs)`, already present) — verified empirically, not just reasoned about, since getting
  this wrong would silently skip the `sqlite_sequence` fix below for that one migration path. **The
  `sqlite_sequence` fix repeats, because the hazard repeats**: any rebuild that drops and renames `runs` again
  loses its `sqlite_sequence` row the same way v9's first rebuild would have (if `runs` had never had one before);
  the fix is the same shape every time — read the old watermark before the drop, restore
  `max(old watermark, highest id actually copied)` in the same transaction as the rename — and `test_store_migration_v10.py`
  proves it the same way v9's test did: seed a database, delete its highest-numbered runs so the sequence sits
  above the highest surviving id, migrate, insert one more, assert the new id is above the old sequence. An
  interrupted replay (`close_interrupted_runs`) must also close with `replay_outcome = 'inconclusive'`, never
  left null — the fix is one `CASE WHEN mode = 'replay' THEN 'inconclusive' ELSE replay_outcome END`, a no-op for
  every non-replay row. **Events**: `run.start` gains `source_run_id`, `run.end` gains `replay_outcome` — both
  *omitted entirely* when not applicable (never `"replay_outcome": null`), unlike `verdict`/`succeeded_turn`,
  which the catalogue already marks `| null` and are always present; `run_finished(run)` has to read
  `getattr(run, "replay_outcome", None)` into the stashed outcome dict itself, or `_run_end`'s own `_present(...)`
  filter has nothing to omit. `replay.batch.start`/`.end` are unscoped (no single `run_id` for a whole batch,
  mirroring `events.connection_test`); a batch's own end line carries no `error` field for a `run_in_progress`
  collision (an expected stop, not a failure), but does carry one — the same root-cause class name its own
  crashed entry's `run.end` already logged, never the internal `ReplayFailed` wrapper's name — whenever
  `stop_reason` is `replay_failed` (code-review round 1, items 8–9). A third shape exists for a crash entirely
  outside the per-entry handling (`store.list_turns`, rebuilding a crashed entry's row): a second, outer `try`
  around the whole batch loop logs this same line with `complete=false`, `error=<root-cause class>`, and **no**
  `stop_reason` at all — that failure never resolves into a `BatchResult`, so the exception still propagates
  after the line is logged and the HTTP request itself fails with a 500 (round 2, item D1; deliberately kept
  behaviour, only the docs here and in `specs/010-structured-logging/contracts/log-records.md` and
  `specs/012-regression-replay/contracts/log-records-delta.md` were wrong about it). **UI**: the Replay button,
  its disabled reason/advisory, the
  outcome line and the comparison table must render ahead of `_render_finding`'s own failure-step early return
  (`app.py`, `if run.get("failure_step"): ... return`), or a run that failed to send would never show them at
  all, even disabled — placed-after-the-return is an easy, silent mistake since every *other* line in that
  function already assumes it survived the return. A Streamlit button rendered from both the "just-ran" result
  card and an "opened" run list entry in the same script pass needs a key namespaced by which card it is
  (`f"replay_button_{key_prefix}_{run['id']}"`), or a `DuplicateWidgetID` fires the moment both render at once.
  A pandas column that mixes `bool` and `str` values (a comparison table's "Hard evidence" row next to its
  "Verdict" row, built as one dict-of-rows-to-dataframe) fails Arrow serialisation inside `st.dataframe` with an
  opaque `ArrowTypeError`; every cell must be stringified first. **Test-building gotcha**: building an adaptive
  *source* run through the real API with real model doubles (to get authentic token/cost fields on its own log
  lines) makes it impractical to control exactly which turn it succeeds on (`ModelTransport`'s judge verdict is
  one flat attribute shared by every call in a test, not sequenceable per call without replacing the whole
  transport) — building the source directly via `store.claim_run`/`add_turn`/`finish_run` and reserving the real
  API/model doubles for the *replay* side (which does need authentic log lines) sidesteps this entirely. A test
  fixture that claims a second `in_progress` row on a target whose first one is still open hits the same
  `uq_runs_active` constraint `RunInProgress` is built on — a seed fixture needs every prior claim finished before
  claiming the next.
- 2026-11-21 — **OpenRouter ZDR guardrail blocks the HS-code target's own model (infra, not a Kestrel bug).**
  `targets/hs_code` defaults its conversational model to `openai/gpt-4o-mini` over OpenRouter
  (`CARGOLINT_CHAT_MODEL`, `agent/config.py`); as of this date the account's workspace guardrails (a Zero Data
  Retention policy, configurable at `openrouter.ai/workspaces/default/guardrails`) filter out the only endpoint
  for that model, so the target's own `/chat` 502s with `openai.NotFoundError`/`OpenAIModelNotFoundError`
  ("0 endpoints out of 1 requested are available matching your guardrail restrictions") before Kestrel's own
  attacker/judge calls are ever reached — every e2e test against the live target fails identically on the
  connection-test step (`{"ok": false, "step": "endpoint_error", "detail": "Status 502"}`), not just a given
  feature's own test. Confirmed external to this repo by running an untouched, pre-existing e2e file
  (`tests/e2e/test_us1_connection.py`) and seeing the same failure. Fix is account-side (relax the guardrail, or
  point `CARGOLINT_CHAT_MODEL` at a ZDR-compliant model) — don't chase this as a code regression; the offline
  suite (`tests/unit`, `tests/integration`) exercises everything the e2e layer does except the live model call.
  **Resolved 2026-11-23** (the owner could not relax the guardrail itself): the target's chat model default is
  now `openai/gpt-oss-120b` (`DEFAULT_CHAT_MODEL`, `targets/hs_code/agent/config.py`, read by both it and
  `app.py`), a ZDR, tool-capable endpoint that passed a tool call, a tool round trip and the `json_schema`
  structured output 4/4 times against real providers (Crusoe, AkashML, Google, BaseTen); `playwright.config.ts`
  pins it explicitly in the HS-code target's `webServer.env`, next to `HS_TARGET_API_KEY`/`HS_TARGET_CANARY`, so
  CI never silently drifts back. Gotcha confirmed probing candidates: **a model check for a tool-using agent
  must include a `tools` array** — `openai/gpt-4o-mini` still answers a plain, tool-less chat completion with a
  `200`, so that alone proves nothing; the guardrail specifically excludes its *tool-capable* endpoint
  (`'failed_routing_step': 'Filter by Guardrails'` only after `'Filter by Tool Compatibility'` has already
  narrowed the candidate pool to the one that then fails ZDR).
  **Recurred 2026-11-24** for the replacement model too: every live e2e fails at the connection-test step with
  `{"ok": false, "step": "endpoint_error", "detail": "Status 502"}`, and the target's own log shows
  `OpenAIModelNotFoundError: Error code: 404 ... 0 endpoints out of 20 requested are available matching your
  guardrail restrictions and data policy ... Model blocked by guardrail` for `openai/gpt-oss-120b`. Same
  account-side cause, same check: an untouched, pre-existing e2e (`tests/e2e/test_us1_connection.py`) fails the
  same way, so it is never a regression in the feature under test. Treat a 502 from `targets/hs_code` at the
  connection test as this until that check says otherwise; the offline suite covers everything the e2e does
  except the live model call.
- 2026-11-24 — **Behavioural evidence (013), part 1.** Deterministic proof is no longer canary-only: one
  `EvidenceChecker` (`src/kestrel/evidence/`), built per run by `build_checker(...)`, owns every check and runs
  them in the fixed order of FR-001 over each reply; **any** item ends the run succeeded with hard evidence and
  no judge call for that turn, and `evidence=None` keeps `EvidenceChecker.canary_only(...)` — today's behaviour
  exactly — for the *live* run functions only, so no existing caller or test changed; **both replay paths always
  build the full checker** from the source's copied tokens (FR-014, FR-035 — `evidence=` is a test seam there,
  never a canary-only fallback). Items are rows of `run_evidence` (kind, turn, location, OWASP
  class, non-secret detail, plus a pattern name and set version for unsafe output); the seven kinds and their
  labels/locations/classes live in one table (`evidence/model.py`), and `derived_items(run, stored)` is the one
  helper that gives a **pre-013** hard-evidence run its single canary item on every surface, so the summary, the
  run page and the report cannot disagree. The **override token** is two 6-char parts from a 31-symbol alphabet;
  the planted wording is a prompt file (`override_task.v1.md`) framed as the injected override, with at least one
  alphanumeric word between the parts, so the joined form appears in nothing Kestrel composes **even after
  normalisation** (case folded, every non-alphanumeric character dropped) — that normalised form is what both
  the echo-proofness test and the disarm check compare, and `note_sent` disarms on every message sent, a replay's
  re-sends included. Where the paragraph goes is a Kestrel-owned sidecar
  (`src/kestrel/attacks/data/insertion_points.json`, offset + sha256 of the seed's verbatim library text): direct
  seeds at the attacker-voice end, indirect seeds **interior**, inside the simulated injected content, wrapped in
  the seed's reviewed **quoting frame** (`frame_prefix`/`frame_suffix`, review round 1 item 7: a seed's own text is
  a meta-instruction *about* retrieved content, so an unframed paragraph at its sentence boundary still read in the
  user's voice). The run's exact filled task text is therefore frame + paragraph as **one string**
  (`InsertionPoint.frame`); the run starters pass `seed=` to `build_checker` so `planted_task_texts()` is that
  string *before* the retrieval provider is built (the provider captures the list eagerly), and `opening_message`
  records it for a checker built without its seed. A derived point (fixture library) carries no frame — the frame
  is reviewed per seed, never invented at run time — so only the shipped library exercises it offline
  (`test_override_placement.py`, one `test_evidence_store_isolation.py` run). A `PatternWrite` carries no document:
  `SpyExperienceStore.pattern_documents` is what a test inspects for pool text. Gotcha:
  the sidecar is keyed to the *shipped* library, but the offline suite drives the synthetic `fixture_library()`
  whose seeds share those ids with different text — so `insertion_point(family, id, text)` falls back to a
  derived point of the same shape when the fingerprint does not match, and only the unit test
  (`test_override_placement.py`) is strict; a strict runtime lookup would crash every offline run of an
  injection family. The **unsafe-output** set is twelve named patterns in four categories at set version 1, with
  the inert samples (3 positive + 3 negative per pattern) only in `tests/fixtures/unsafe_output_cases.json`; a
  unit test parses `contracts/detectors.md`'s own table and set version so the contract, the module and the
  fixture cannot drift. Gotchas while writing them: Python refuses an inline `(?i)` that is not at the start of
  the expression (use the `flags=` argument when the pattern is an alternation), and an attribute-value class that
  excludes *both* quote characters stops at the first inner quote of the other kind — the usual shape of an
  event-handler value whose code contains a quoted string — so such a value never matched until each quoting
  style got its own branch. **FR-063** strips the run's exact filled task text and scrubs its planted values at every
  experience-store and retrieval boundary (`writeback._winning_messages`, the judge progress notes the summary is
  built from, `retrieval.build_query`); the checker is built **before** the provider and the write-back so both
  receive this run's values, and `tests/support.py`'s `RepeatingStubAttacker`/`RepeatingStubJudge` (which echo the
  run's real parts, read back from the store) are what stop that test passing vacuously. Replay derives each
  turn's result from "any evidence item", never the canary flag (both branches), and copies the source's tokens
  with their armed state. Logging: four `run.start` fields (omitted when they do not apply), a new per-turn
  `evidence.check` line **before** the judge's `model.request`, and kinds/counts on `turn` and `run.end`; the
  `callback.ignored` field is `reason_kind`, not `reason`, because `tests/unit/test_events.py` enforces a
  deny-list of free-text-looking field names over the whole catalogue (the 013 contracts were corrected to
  match). Schema **v11** is additive — four new tables and two nullable `runs` columns, **no rebuild** — and
  creates every table of *both* parts, so part 2 needs no second bump. Pre-existing tests edited beyond
  SC-008's original list (and added to it): `tests/unit/test_prompt_registry.py` (the exact id set, the
  `version == "1"` pin and the two-line front-matter prefix, all three of which a new prompt id, two bumped
  attacker versions and the optional `framing` key change by construction), one assertion in
  `tests/unit/test_attacker_client.py` that pinned a bumped family's active reference as `@1` while reading it
  from the live registry — now compared against `prompt_registry.active_ref`, so no version literal can go stale
  again — and `tests/unit/test_experience_summary.py`, whose fallback-summary assertion pinned the old
  "canary hard evidence" suffix (now "; hard evidence": any deterministic proof, review round 1 item 13). The
  unsafe-output boundary after review rounds 2 and 3: a SQL statement must start its line (a *named* client
  prompt such as `mysql>` allowed, a bare `#`/`>`/`$` not) or be wrapped in inline-code backticks, so a
  destructive statement embedded after prose on the same line without backticks is a known recall cost (no
  upper-case-keywords rule, which would re-match a prose warning that quotes a statement); `eval` counts only when
  applied directly to the download's substitution; a shell or runtime given its own program inline (`-c`/`-e`)
  reads a piped download as data, judged within the piped command itself (never from a later command's flag on
  the line); a non-JavaScript `type` makes a script element a data block, and `data-type` is not `type`; a
  no-op `javascript:` URI is not a sink; and the tag context is an attribute-list grammar on one line, never
  a `<` comparison (a tag split across lines is a declared recall cost). Any example of a dangerous statement
  belongs in the fixture only — docs and commit messages describe the boundary behaviourally.
- 2026-11-25 — **Honest Spec-PR path (006 amendment, Phase 7).** `check_traceability.py` gained
  `spec_pr_rule_problems(pr_body, labels, issue_exists)`: the eleven-row order of
  `specs/006-human-approved-spec/contracts/pr-rules.md` over the **raw** description (no comment/markup strip —
  reversed in the spec's own review round 2 — a keyed line starts in column 1). Messages are plain prose, not
  tagged `[row N]`; tests classify a failure by a distinctive substring of its own message (`"conflicting
  declaration"`, `"(FR-015, FR-016)"`, `"is not an issue of this repository"`, …), so production text stays
  readable and the probe's row-tag convention never leaked into shipped code. `pr_state()`/`issue_exists_in_repo()` replace
  `PR_BODY`: both shell out to `gh` (`pr view --json body,labels`; `api repos/.../issues/<n>`) with the job's own
  token, live at evaluation time — `qa.yml`'s traceability job carries `PR_NUMBER`/`GH_TOKEN` and
  `permissions: {contents: read, pull-requests: read, issues: read}` instead of `PR_BODY`.
  **`scripts/qa_recheck.py`** (a non-required `.github/workflows/qa-recheck.yml`, `on.pull_request.types:
  [edited, labeled, unlabeled]`, **no concurrency group** — one would let an irrelevant event cancel a relevant
  recheck) re-runs only `qa.yml`'s `traceability` job on a body edit or a `refactor`/`bugfix` label change. Its
  step machine: `_find_run` (step 1) retries **only on a failed read**, never on a status that simply isn't
  `"completed"` yet — getting this wrong (retrying `get_latest_run` itself while "waiting") would call the wrong
  endpoint forever instead of handing off to step 2's `get_run`-based polling, since `next_action("queued", …)`
  also returns `"wait"` and both look identical to a naive retry loop. A re-run refusal is classified by
  **re-reading the run**, never by the POST's HTTP code (GitHub sends the same `403` whether another attempt is
  in progress or the refusal is final); every client call returns a value or raises `RecheckApiError` — `None`
  from `get_latest_run`/`get_job` means only a genuine empty result, never a failure in disguise, or a transient
  API blip reads as "nothing to do" and the recheck exits 0 with no signal. `already_fresh` never raises (a
  missing/unparsable timestamp means "not fresh", so the re-run request is sent, never silently skipped). The
  stale-result comment names the reason class **literally** (`"(reason: timeout|refused|error)"`), since a prose
  paraphrase alone doesn't satisfy "names the reason class" for a test (or a reader) checking for the word.
  Gotcha: `GITHUB_REPOSITORY` and `GITHUB_RUN_ID` are already-set default runner env vars — do **not** re-map
  them via a workflow step's own `env:` (only `GH_TOKEN`, `PR_NUMBER`, `HEAD_SHA` need it). Tests use a
  `_FakeClock` (`now`/`sleep` injected into `run_recheck`) so a 30-minute budget exhausts in milliseconds of real
  test time. T024 (create the `refactor`/`bugfix` labels) and T031 (the live throwaway-draft-PR check) are
  owner/live steps, not run from a worker session.
  **Review round 1 fixes.** The retry after a refused re-run must redo steps 3 **and** 4, not just resume
  polling: once the run completes again it has to re-fetch the `traceability` job (`get_job`, `filter=latest`)
  and redo `already_fresh` before any new POST — reusing the job id captured before the other attempt ran skips
  the freshness check and can re-run a stale attempt; the whole steps-3-4 block is now one `while True:` loop,
  re-entered on that path. `RecheckApiClient.request_rerun` classifies **only** a literal `(HTTP 403)` in `gh`'s
  stderr as `"refused"` — any other non-zero exit (a 5xx, a network error, 401/404) raises `RecheckApiError`
  instead, since the endpoint documents just `201`/`403` and a different failure must retry as `run_status =
  "error"`, not be misread as a final refusal. Every other real-client method now raises `RecheckApiError` on an
  undocumented 2xx shape too (a non-object body, a missing/null/non-list `workflow_runs` or `jobs`, a run or job
  missing its `status`/`id`/`created_at`) — `None` means only a genuinely empty, well-formed result. `_poll`'s
  signature is unchanged (`fetch, elapsed, budget_s, sleep, poll_interval_s, rerun_status, give_up`); a per-call
  failure notice is logged by wrapping each `fetch` closure in its own `try/except RecheckApiError: log; raise`
  instead of adding a parameter there. `already_fresh` treats a timezone-**naive** parsed timestamp the same as
  an unparsable one (`parsed.tzinfo is None` → `None`), since comparing a naive `datetime` to an aware one raises
  `TypeError` in the stdlib, not just a `ValueError` — the one case `datetime.fromisoformat` itself doesn't raise
  on. `check_traceability.py`'s `SPEC_PR_LINE_RE`/`REASON_LINE_RE` capture the whole rest of the line (`(.*)$`)
  and `.rstrip(" \t\r")` in Python instead of ending the pattern in `[ \t\r]*$`: the old non-greedy-then-
  optional-tail shape was quadratic on a long, space-padded line (measured ~6 s at 32,000 characters, ~35 s at
  65,000); the greedy `(.*)$` used instead is linear (~0 s at the same lengths). `parse_issue_lookup`'s
  `int(number)` is wrapped in its own `try/except ValueError`, since CPython refuses to convert a >4,300-digit
  string at all. Row 8's message cites `(FR-015, FR-016)`, matching the contract exactly (was `(FR-015)` only).
  **`scripts/qa_recheck.py`'s `get_recheck_run_created_at()` is read exactly once per `run_recheck()` call,
  before the steps-3-4 loop**, not on every pass through it: it is constant for the whole recheck run (its own
  `created_at`), and re-reading it inside the loop only widens the window in which the just-fetched `job` goes
  stale while that read's own retries sleep — a job id POSTed after such a window can belong to an attempt a
  concurrent recheck has already superseded (review round 2, finding 1).
- 2026-11-24 — **Graph typed state (refactor, no behaviour change).** `attack/graph.py` compiles its two graphs
  once at import (`LIVE_GRAPH`, `REPLAY_GRAPH`) from module-level node functions —
  `StateGraph(_State, context_schema=_LiveDeps)` / `StateGraph(_ReplayState, context_schema=_ReplayDeps)`. Every
  per-run value (store, run id, resolved target and secrets, clients, sender, checker, caps, deadline + clock,
  prompt references, a replay's recorded turns) is a field of a frozen dataclass context handed to
  `compiled.ainvoke(initial, config, context=deps)` and read by a node as `runtime.context`
  (`from langgraph.runtime import Runtime`); no node closes over a per-run value. The deps family is `repr=False`:
  `secrets` holds the auth values and `repr(runtime)` includes the context (001/FR-022). The conversation and a
  replay's `turn_results` are reducer-appended (`Annotated[list[...], _appended]`): a record node returns only
  its turn's delta and an empty delta is a no-op; `judge_requests` is a state field counted *before* the request
  is made (a `JudgeError` still counts, as the old one-item box did); the run's end is one frozen `Outcome`
  (`failure_step` defaults to None, which is what the old dict's `.get` gave). LangGraph 1.2.17 gotchas, each
  verified with a scratch probe under mypy: the `runtime` argument is injected by parameter **name** alone,
  whatever its annotation (`_internal/_runnable.py::KWARGS_CONFIG_KEYS`); a dataclass context instance passes
  through `_coerce_context` untouched (only a dict is coerced); and `Runtime[ContextT]` is **invariant**, so a
  node shared by both graphs must be generic over the context (`Runtime[_DepsT]`, `_DepsT` bound to the common
  `_Deps` base) or mypy rejects `add_node` for the second schema. The old hand-copied
  `conversation.append(("agent", state["pending_reply"]))` was itself one of the baseline mypy errors (22 → 21
  on `src`). `tests/unit/test_adaptive_graph_state.py` drives `LIVE_GRAPH` directly with a `_LiveDeps` of stubs
  (no `run_scope` needed: outside one the events helpers emit unkept lines and return). A test module that
  imports `TestOutcome` under its own name gets a pytest collection warning — alias it, as the other tests do.
