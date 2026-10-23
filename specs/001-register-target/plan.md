# Implementation Plan: Register a Target Agent and Test the Connection

**Branch**: `001-register-target` (no git branch; work is on `master`) | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-register-target/spec.md`

## Summary

A single user registers an agent's HTTP endpoint in a Streamlit form and clicks "Test connection". Kestrel sends one fixed "Hello" through the configured request template and shows the reply as plain text, or names the step that failed. After ticking the permission checkbox, which accepts versioned terms of service, the user saves the target.

Streamlit only renders and calls a FastAPI API, and the API holds every rule:
- form validation and the hosting guard;
- the connection tester: no redirects, a 60-second deadline, a 1 MB cap, header values masked in replies;
- Fernet-encrypted header values in one SQLite file;
- in-memory form sessions that enforce one test at a time and saving only the settings that were tested.

The end-to-end tests drive the real screen with Streamlit's AppTest against a sacrificial HS-code target. That target is a small FastAPI app in `targets/hs_code/` running copied CargoLint classifier code with BM25-only retrieval.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**:
- Kestrel: FastAPI with uvicorn (API), Streamlit (screen), httpx (test requests and the screen's API calls), cryptography (Fernet).
- Sacrificial target, in its own project: FastAPI and uvicorn, plus what the copied CargoLint files need (langchain-core, langchain-openai, rank-bm25, lxml, python-dotenv), pinned to CargoLint's versions.

**Storage**: One SQLite file through the standard-library `sqlite3` module, with no ORM; default `data/kestrel.db` under the repo root, override with `KESTREL_DB_PATH` (a relative path resolves against the repo root). The encryption key comes from `KESTREL_SECRET_KEY`, or else a generated key file (default `~/.kestrel/secret.key`, override with `KESTREL_KEY_FILE`).

**Testing**: pytest.
- Unit tests for the pure modules.
- Integration tests through FastAPI's `TestClient`, with `httpx.MockTransport` standing in for targets.
- Screen tests through Streamlit's `AppTest` with a stubbed API client.
- End-to-end tests (marker `e2e`) start the sacrificial target and the API as subprocesses and drive the screen with `AppTest`.

**Target Platform**: The user's own machine (Windows, macOS or Linux) with `KESTREL_MODE=local`. A server with `KESTREL_MODE=hosted`, which is also the default when the variable is unset.

**Project Type**: Web application: a FastAPI backend and a Streamlit frontend in one uv project, plus a separate uv project for the sacrificial target.

**Performance Goals**: Every test ends within its 60-second deadline (SC-002). No throughput target, since there is one user.

**Constraints**:
- Timing: 60-second deadline per test, 10-second connect limit.
- Size: responses capped at 1 MB; replies shown up to 2,000 characters.
- One test in flight per form, and redirects never followed.
- Header values never logged or returned; URLs that carry credentials refused; logs never include a URL's query string.
- The API runs as one process, because form sessions live in memory.

**Scale/Scope**: One user and tens of targets; 3 user stories and 29 functional requirements.

No unknowns remain: the planning input and [research.md](./research.md) settle every choice.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the plan complies | Status |
|---|---|---|
| I. Scope is security, not quality | Builds only target registration and a connection test. A target holds endpoint settings only, so quality evaluations can reuse it later. | Pass |
| II. Hard evidence over opinion | No findings in this feature. | N/A |
| III. Every report states the attacker model | No reports in this feature. | N/A |
| IV. Secrets never leave the vault | Header values are Fernet-encrypted at rest and never returned by the API. URLs that carry credentials are refused, so keys can't end up stored unencrypted. Each test writes one log line with a fixed set of fields and no query string, validation errors never echo input, and values are masked in replies. Values go only to the target, with redirects off. SC-004 is tested with a known value ([research.md](./research.md) R9). | Pass |
| V. Learn from every run | A connection test is not a scan run (spec Assumptions); there is nothing to write back. | N/A |
| VI. OWASP mapping, fix-ready findings | No findings in this feature. | N/A |
| VII. Tests first, thin slices | Slice: Streamlit screen → FastAPI → connection tester → SQLite store, with the sacrificial HS-code target as the agent at the far end. Unit tests come before the code they cover; three end-to-end tests run against the sacrificial target through the real screen. | Pass |
| VIII. Only attack what you own | Layer 1: saving is refused without the checkbox, and the accepted terms version and date are stored per target for later scans to check. Layer 3: one fixed greeting per click, one test in flight per form, a 60-second deadline and a 1 MB cap. Layer 2 stays in phase two. | Pass |
| IX. Simple enough for a vibe coder | Paste a URL; the template and response path come prefilled; no YAML; one user, no login. Starting Kestrel locally takes two commands ([quickstart.md](./quickstart.md)); the core flow happens entirely in the screen. | Pass |
| X. Fixed stack, justified dependencies | Python 3.12, FastAPI, Streamlit, uv and pytest; SQLite ships with Python. Three new dependencies: **uvicorn** runs the FastAPI app, which has no server of its own. **httpx** sends test requests with streaming (for the 1 MB cap), timeouts and redirects off, and serves as the screen's API client. **cryptography** provides Fernet authenticated encryption for header values. The sacrificial target's libraries are needed to run the copied CargoLint classifier and stay in its own project. LangGraph and ChromaDB aren't needed yet. | Pass |

**Result**: pass, with no violations.

**Re-check after Phase 1 design**: pass. The data model, contracts and quickstart add no dependency or layer beyond this table.

## Project Structure

### Documentation (this feature)

```text
specs/001-register-target/
├── plan.md                  # This file
├── research.md              # Phase 0: decisions, rationale, alternatives
├── data-model.md            # Phase 1: SQLite schema, in-memory state, state transitions
├── quickstart.md            # Phase 1: how to run and validate the feature
├── contracts/
│   ├── kestrel-api.md       # Kestrel's HTTP API, used by the screen
│   ├── hs-code-target.md    # The sacrificial HS-code target's HTTP API
│   └── ui-form.md           # The Streamlit screen: widgets, behaviour, what the UI may do
├── checklists/
│   └── requirements.md
└── tasks.md                 # Phase 2, created by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml               # uv project "kestrel", Python 3.12; pytest marker e2e, excluded by default
uv.lock
.env.example                 # KESTREL_MODE, KESTREL_SECRET_KEY, KESTREL_KEY_FILE, KESTREL_DB_PATH, KESTREL_API_URL
src/kestrel/
├── settings.py              # reads the KESTREL_* variables; refuses to start on an invalid KESTREL_MODE
├── secrets.py               # key loading and creation, encrypt and decrypt, masking values in text
├── store.py                 # SQLite schema and target repository (sqlite3, no ORM)
├── connection/
│   ├── template.py          # placeholder rules, JSON-safe body filling, GET URL filling
│   ├── response_path.py     # evaluator for $, .field and [n]
│   ├── address_guard.py     # hosted-mode address check (FR-028)
│   ├── sessions.py          # form sessions: in-flight lock, fingerprint of the last successful test
│   └── tester.py            # one test: guard, send, name the outcome, mask, cut, log one line
└── api/
    ├── main.py              # FastAPI app, routes, error handlers that never echo input
    ├── schemas.py           # request and response models
    └── terms.md             # terms of service text and version number
ui/
├── app.py                   # Streamlit screen: renders and calls the API, imports nothing from kestrel
└── api_client.py            # httpx calls to the Kestrel API
targets/hs_code/             # sacrificial HS-code target, its own uv project
├── pyproject.toml
├── PROVENANCE.md            # each copied CargoLint file, source commit 51ec448, licences, what was left out
├── app.py                   # FastAPI: POST /chat, GET /health, X-API-Key check
├── kb.py                    # light knowledge base: nomenclature index, BM25, no-op vector search
├── agent/  rag/  tools/     # copied CargoLint code, unchanged
├── data/                    # copied CargoLint data: nomenclature, rules, model prices, SOURCES.md
└── tests/                   # smoke tests: imports, auth check, reply shape (fake model client)
tests/
├── unit/                    # template, response_path, address_guard, secrets, store, sessions, tester
├── integration/             # API with MockTransport targets, secret scan of logs, ui/ import rule, screen via AppTest
└── e2e/                     # sacrificial target and API as subprocesses, screen via AppTest (marker e2e)
```

**Structure Decision**:
- **Kestrel**: one uv project. API and logic live in the `src/kestrel` package. The Streamlit screen lives in a top-level `ui/` folder that may not import `kestrel`, which makes "Streamlit only renders and calls the API" testable: an integration test fails if `ui/` imports anything from `kestrel`.
- **Sacrificial target**: a separate uv project, so CargoLint's libraries never enter Kestrel's environment. The end-to-end tests start it as a subprocess, the same way they would treat any user's agent.
- **Git**: `/data/` (Kestrel's database) and `targets/hs_code/.env` are git-ignored; `targets/hs_code/data/` is committed.

## Alignment with the mockup and the architecture diagram

**Followed**: the sidebar order in [docs/ui-mockup.html](../../docs/ui-mockup.html), which is Target picker, method and URL, auth headers, request template and response path, Test connection, then the permission checkbox. Its defaults are kept too: POST, `{"message": "{{prompt}}"}` and `$.reply`. The design also follows the Streamlit UI → FastAPI → target adapter → target path in [docs/architecture.html](../../docs/architecture.html).

**Deviations**:

| Source | Deviation | Why |
|---|---|---|
| Mockup | Adds a display-name field | FR-001; the mockup has none |
| Mockup | Auth headers become rows (a name plus a masked value field, with add and remove) instead of one text area | A text area can't keep stored values hidden while editing (FR-021) or keep a value the user didn't retype (FR-017) |
| Mockup | Adds Save target and a two-step Delete | Stories 2 and 3; the mockup has neither. Two steps instead of a pop-up dialog so AppTest can drive it |
| Mockup | Adds a "Terms of service" expander under the checkbox | FR-029; the mockup only has an asterisk. An expander keeps the form input (scenario 2.6) |
| Mockup | Test results and a saved-targets table go in the main area | The mockup's main area is the scan run view, which is out of scope; FR-015 needs names and URLs visible |
| Mockup | Adds a mode caption, e.g. "Running hosted: local and private addresses are blocked" | Explains FR-028 refusals |
| Mockup | Not built: attack families, max turns, budget cap, Launch attack run, the "rate limit 2 req/s" status line and the run view | Out of scope: attacks, judge and reports |
| Diagram | FastAPI handles targets, connection tests and encrypted headers only; no runs and no general rate limiting | Only one test in flight per form (FR-009) is needed now |
| Diagram | The connection tester is the first piece of the target adapter: one HTTP request and one log line, with no tool-call tracing | Tool calls only matter once attacks exist |
| Diagram | Adds a SQLite file for targets | Planning input; ChromaDB is for the attack store and isn't used here |
| Diagram | The HS-code agent becomes the sacrificial target in `targets/hs_code/`, with BM25-only retrieval and no fake email tool | Research R11; the fake email tool and canary tokens come with attack features |
| Diagram | Not built: attacker, judge, jailbreak classifier, ChromaDB, report, DVLA and AIGoat | Out of scope |

## Complexity Tracking

No constitution violations, so nothing to justify.
