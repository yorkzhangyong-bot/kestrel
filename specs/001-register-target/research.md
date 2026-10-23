# Research: Register a Target Agent and Test the Connection

Phase 0 of [plan.md](./plan.md). Each entry gives the decision, why, and what else was considered.
"(planning input)" marks a decision that came from the `/speckit-plan` request; the entry adds the details.

## R1. Sending the test request

**Decision**: `httpx.AsyncClient`, one per test, with `follow_redirects=False`. The body is read as a stream. The connect limit is 10 seconds; a 60-second overall deadline (`asyncio.timeout`) covers the whole test. Headers sent: the user's headers, plus `Content-Type: application/json` for POST unless the user set one, plus `User-Agent: Kestrel/0.1 (connection test)`.

**Rationale**: Streaming lets the 1 MB cap stop reading early. httpx follows no redirects unless asked (FR-010). Async keeps the API responsive while a slow agent thinks. The same library also serves the UI's API client and FastAPI's `TestClient`.

**Alternatives**: `requests` (no async; a second HTTP library next to httpx), `aiohttp` (a second HTTP library), `urllib` (no async, no per-phase timeouts).

## R2. Naming the failure step

**Decision**: checks run in this order; the first match decides the outcome.

| # | Condition | Step | Detail shown (plain text) |
|---|---|---|---|
| 1 | Form invalid (FR-004) | none: 422 with field errors, nothing sent | |
| 2 | Hosted mode and a blocked address (FR-028, R8) | `address_not_allowed` | |
| 3 | A stored header value can't be decrypted (R5) | `credentials_unreadable` | |
| 4 | DNS failure, connection refused or reset, connect limit hit, TLS failure | `unreachable` | the error kind, e.g. "certificate verify failed" |
| 5 | 60-second deadline passes | `timed_out` | |
| 6 | Status 401 or 403 | `auth_rejected` | status code |
| 7 | Status 3xx | `endpoint_error` | status code and `Location` |
| 8 | Any other status outside 2xx | `endpoint_error` | status code |
| 9 | Body over 1 MB, by `Content-Length` or counted while streaming (planning input) | `endpoint_error` | "Response larger than 1 MB" |
| 10 | Body is not JSON | `non_json` | |
| 11 | Response path matches nothing | `path_not_found` | |
| 12 | Response path matches an object, list, number, boolean or null | `not_text` | the JSON type found |
| 13 | Text found | `success`; empty text is shown as "(empty reply)" | |

**Rationale**: This follows FR-008, plus the size rule. Checking the status before reading the body means an authentication refusal is never misreported as "non-JSON response". Steps 2 and 3 extend FR-008's list for FR-028 and for key loss.

## R3. Filling in the request

**Decision**: The placeholder is `{{prompt}}`. For POST it must appear exactly once in the body template and not in the URL. For GET it must appear exactly once in the URL's query string, and the body template is ignored. POST bodies are filled JSON-safely:
1. replace the placeholder with a unique sentinel;
2. parse the template as JSON (it must be valid, and the placeholder must sit inside a string value);
3. replace the sentinel inside string values with the prompt;
4. serialize with `json.dumps(..., ensure_ascii=False)`.

For GET, the prompt is percent-encoded into the query string.

**Rationale**: Parsing first guarantees a well-formed body whatever the prompt contains: quotes, backslashes, line breaks or non-ASCII text (FR-006). Later attack prompts depend on this.

**Alternatives**: Plain string replacement with an escaped prompt (breaks when the placeholder isn't inside a string); a template engine such as Jinja (new dependency, far more power than needed).

## R4. Response paths

**Decision**: Kestrel has its own small evaluator for `$` (the whole response), `.name` (a field) and `[n]` (a list position from 0), for example `$.choices[0].message.content`. A field name is any run of characters except `.`, `[` and `]`.
- A syntax error is a form error (FR-004).
- A missing field, an index out of range, or stepping into a value that isn't an object or list gives `path_not_found`.
- A match that isn't a string gives `not_text`.

**Rationale**: It's about 40 lines with no dependency. Full JSONPath (filters, wildcards) adds syntax users could trip over and nothing this feature needs.

**Alternatives**: `jsonpath-ng` or `jsonpath-python` (new dependency, larger syntax).

## R5. Encrypting header values and losing the key (planning input)

**Decision**:
- **Encryption**: header values are encrypted with Fernet from the `cryptography` package (AES with an HMAC, so tampering is detected).
- **Key source**: the key comes from `KESTREL_SECRET_KEY`. If that's unset, Kestrel reads the file named by `KESTREL_KEY_FILE` (default `~/.kestrel/secret.key`). If the file doesn't exist, Kestrel creates one on first start, with owner-only permissions where the OS supports them. It then logs a warning with the full path and "back this file up".
- **Hosted warning**: in hosted mode, a generated key file gets an extra warning, because a redeploy may lose it.
- **Bad key**: an invalid `KESTREL_SECRET_KEY` stops start-up with a clear message.
- **Location**: the key file lives outside the repo and apart from the database. A copied or accidentally committed database file is then unreadable on its own.

**If the key is lost**: the header values can't be recovered, but nothing else is affected, because names, URLs, templates, paths and permission records are not encrypted.
- At start-up Kestrel tries to decrypt one stored value and logs an error if it fails.
- Targets stay listed, and their headers show as unreadable.
- Testing such a target stops at `credentials_unreadable` without sending anything.
- The user re-enters the values (edit, type, test, save), which encrypts them with the current key.
- Restoring the old key makes the old values readable again.

**Alternatives**: AES-GCM through the low-level `cryptography` API (more code for the same protection); the OS keyring (platform quirks, new dependency); refusing to start without the variable (contradicts the planning input).

## R6. Storage (planning input)

**Decision**: one SQLite file through the standard-library `sqlite3` module, with no ORM. By default it's `data/kestrel.db` under the repo root (the folder holding `pyproject.toml`). A relative `KESTREL_DB_PATH` is resolved against the repo root too, so the API opens the same database whichever folder it starts in.
- **Connections**: a new connection per request.
- **Settings**: `PRAGMA foreign_keys=ON` and `PRAGMA secure_delete=ON` (deleted rows are overwritten).
- **Schema**: created at start-up as version 1 and recorded in a `meta` table; no migration tool yet.
- **Unique names**: display names are unique through a `name_key` column holding `name.casefold()` under a UNIQUE constraint. SQLite's `NOCASE` only folds ASCII letters.

Details are in [data-model.md](./data-model.md).

**Rationale**: No server process and no ORM, and one user needs nothing more.

**Alternatives**: SQLAlchemy or SQLModel (excluded by the planning input and not needed); a JSON file (no transactions or uniqueness).

## R7. "One test at a time" and "save only what was tested"

**Decision**: The UI creates a random `form_id` for each form instance and sends it with every test and save. For each `form_id`, the API keeps in memory:
- whether a test is running;
- if the most recent test succeeded, an HMAC fingerprint of its connection settings (cleared when a test fails).

The fingerprint covers URL, method, header names and values, body template and response path. The HMAC key is random and lives only in the running process.

These rules follow:
- A second test while one is running gets 409 (FR-009).
- Saving a new target, or an edit that changes connection settings, needs the fingerprint to match the submitted settings, with kept header values resolved; otherwise 409 (FR-012).
- An edit that changes only the display name needs no test.
- Sessions expire after an hour without use.
- The API must run as one process, which is uvicorn's default.

**Rationale**:
- **Server-side lock**: Streamlit restarts the script when a widget is used during a run, so disabling the button can't stop a second request on its own. The server has to refuse it.
- **Most recent test**: keeping the last result per form gives FR-012's "most recent test" exactly.
- **HMAC**: header values never sit in anything that could end up in a log.

**Alternatives**: Signed test tokens (can't express "the most recent test failed"); storing test results in SQLite (state only one form ever needs, kept across restarts for no reason).

## R8. Blocking internal addresses when hosted (planning input: `KESTREL_MODE`)

**Decision**: `KESTREL_MODE` is `local` or `hosted`. Unset means `hosted`; any other value stops start-up.

In hosted mode, before anything is sent, Kestrel:
1. refuses the host names `localhost` and `*.localhost`;
2. resolves the host (all A and AAAA records);
3. refuses if any address is one of these:
   - loopback or unspecified;
   - private;
   - link-local, which covers the `169.254.169.254` cloud metadata address;
   - reserved or multicast;
   - in `100.64.0.0/10`, the shared space some cloud metadata services use, which Python doesn't count as private;
   - an IPv4-mapped IPv6 form of any of the above.

The resolver can be swapped out in tests.

**Accepted risk, to fix before public launch**: the HTTP client resolves the name again when it connects. An attacker who controls DNS could switch the address between the check and the connection (DNS rebinding). Redirects are already off. Closing the gap means connecting to the checked address directly. SC-007 covers addresses as they resolve at check time, and the spec's Assumptions record this risk.

**Alternatives**: Always blocking (breaks local agents and the end-to-end tests); an allowlist of public hosts (unworkable for arbitrary agents).

## R9. Keeping secrets out of every output (FR-020 to FR-023, Principle IV)

**Decision**:
- **API responses**: the API never returns header values, only `name`, `has_value` and `readable`.
- **URLs**: a URL with a user name or password before the host, or with a query parameter named like a credential, is refused on `settings.url` with the message "put credentials in an auth header, not the URL" (FR-004). A name counts when, ignoring case and treating `-` as `_`, it equals `key`, `token`, `secret`, `password`, `auth`, `api_key`, `apikey`, `access_token`, `code`, `sig` or `signature`, or ends with `_` followed by one of them. So `client_secret`, `x-api-key` and Azure Functions' `code` count; `keyword` and `oauth` don't. The suffix rule also catches names like `country_code`; that's accepted, and the error message tells the user what to do. Secrets inside the URL path can't be recognised; the spec records this as an accepted limitation.
- **Logging**: each test writes one log line with a fixed set of fields: target name, the URL's scheme, host, port and path (never its query string), method, step, status code and duration in milliseconds (planning input). The line never contains reply text, header values, request bodies or the prompt.
- **Validation errors**: a custom handler reduces them to field names and messages. FastAPI's default handler echoes the submitted input.
- **Masking**: before a reply or detail is returned, every stored or submitted header value is replaced with `••••`. FR-004 rejects values shorter than 4 characters, so every value is long enough to mask without garbling normal text; `mask_values` still skips anything shorter, as a guard.
- **UI rendering**: the UI shows target text only with `st.code(text, language=None)` or `st.text`. It never uses `st.markdown` or `st.write`, which render markdown, links and images (FR-007, SC-008). `st.error` and `st.success` carry only Kestrel's own wording.

**Rationale**: Each item closes a specific leak path.

## R10. The Streamlit screen and how it's tested

**Decision**:
- **Sidebar**: the form, in the mockup's order, plus the additions listed in [plan.md](./plan.md).
- **Main area**: the test result and a saved-targets table.
- **Terms**: shown in an expander.
- **Delete**: a two-step button.
- **No rules in the UI**: it reads defaults, terms and mode from `GET /api/config`.
- **Tests**: UI tests use Streamlit's `AppTest` (`streamlit.testing.v1`). End-to-end runs give each script run a timeout above the 60-second deadline; AppTest's default is 3 seconds.

**Rationale**: AppTest drives the real script without a browser. Expanders and buttons are easy to drive; pop-up dialogs are not.

**Alternatives**: Browser tests with Playwright (heavier, new dependency); API-only end-to-end tests (they skip the UI layer Principle VII asks for).

## R11. The sacrificial HS-code target (planning input: own FastAPI app, copied files)

**Decision**:
- **Copied unchanged** from CargoLint at commit `51ec448`:
  - code (about 2,500 lines): `agent/{__init__,config,llm,prompts,routing,schemas}.py`, `rag/{__init__,nomenclature,retriever,rules,translate}.py`, `tools/{__init__,classify_hs6,common}.py`;
  - data: `data/nomenclature_2026.jsonl` (5.2 MB, EU Combined Nomenclature 2026, CC BY 4.0), `data/rules/` (four JSON files, about 100 KB), `data/model_prices.json`, and `data/SOURCES.md` for the licences.
  - `PROVENANCE.md` lists every copied file with its source path and the commit.
- **Not copied**: `rag/loader.py` (it pulls in TARIC, PGP and BTI code), `rag/embeddings.py`, `rag/bti.py`, the Chroma indexes (134 MB and 1.8 GB), CargoLint's UI and the rest of its agent.
- **Written for the target**:
  - `kb.py` builds the three things `classify_lines` reads: the nomenclature index (loaded from the copied JSONL), a BM25 index over its chunks, and a no-op vector search. The no-op search returns one dummy vector per query and no hits, so CargoLint's `HybridRetriever` runs only its BM25 leg. Setting `bti_vectors = None` turns the precedent leg off.
  - `app.py` serves `POST /chat`. It requires an `X-API-Key` header equal to `HS_TARGET_API_KEY` and returns 401 otherwise. It runs `classify_lines` on one line, using the message as the English text, and returns a reply listing up to three HS-6 suggestions or saying none were found.
- **Model calls**: these go through CargoLint's own client (OpenRouter, `OPENROUTER_API_KEY`, default model `openai/gpt-4o-mini`). That's about two model calls per message, well under the 60-second limit, costing a fraction of a cent.
- **Dependencies**: the target has its own `pyproject.toml`, pinned to CargoLint's versions where CargoLint pins them: fastapi, uvicorn, pydantic, langchain-core, langchain-openai, rank-bm25, lxml, python-dotenv.

**Rationale**:
- **Unchanged code**: the classifier runs as CargoLint wrote it.
- **No vector leg**: dropping it avoids a 134 MB index build, embedding costs and the chromadb dependency. Retrieval quality doesn't matter for a target that exists to be attacked.
- **Separate project**: these libraries stay out of Kestrel's environment.

**Alternatives**:
- **Full-fidelity retrieval**: copy `rag/embeddings.py` and build a Chroma index on first start. That costs about 5 minutes, an embedding fee and the chromadb dependency; it's worth it later only if attacks need realistic retrieval.
- **Importing from `C:\ai\CargoLint`**: ruled out by the planning input.

**Risk**: A copied file may import another module inside a function, which the import trace above can't see. The target's smoke test catches this before any end-to-end run: it imports `tools.classify_hs6` and handles one message with a fake model client.

## R12. Test layers

**Decision**:
- **Unit tests**: cover `template`, `response_path`, `address_guard` (with a fake resolver), `secrets` (masking, key loading and creation), `store` (temporary file), `sessions` and `tester`.
  - For the tester, `httpx.MockTransport` covers every step in R2.
  - A closed local port gives `unreachable`.
  - A slow handler with a shortened deadline gives `timed_out`.
- **Integration tests**:
  - The API runs through `TestClient` with an injected transport.
  - A known header value is used in a test and a save, and all captured log output must contain it 0 times (SC-004).
  - Validation errors must not echo input.
  - `ui/` must import nothing from `kestrel`.
  - The UI runs through `AppTest` with a stubbed API client. It checks the defaults, the plain-text reply (SC-008), that a URL change clears the checkbox, and the two-step delete.
- **End-to-end tests** (marker `e2e`, skipped when `OPENROUTER_API_KEY` is missing):
  - The sacrificial target and the API start as subprocesses on free ports. The API gets `KESTREL_MODE=local` and a temporary database and key.
  - `AppTest` drives `ui/app.py` through three tests: (1) register the target and see its reply; (2) a wrong path shows "Response path not found"; (3) after a successful test, saving with the box unticked is blocked.
  - Both processes' output is then scanned for the test header value (SC-004).
- **Default run**: a plain `pytest` run skips `e2e`; `pytest -m e2e` runs them.
