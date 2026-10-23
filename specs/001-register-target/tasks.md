---

description: "Task list for feature 001: register a target agent and test the connection"
---

# Tasks: Register a Target Agent and Test the Connection

**Input**: Design documents from `specs/001-register-target/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Required. Constitution Principle VII asks for unit tests before implementation, and the spec names three end-to-end acceptance tests. In every phase, test tasks come first and must fail before the matching implementation task starts.

**Organization**: Tasks are grouped by user story, so each story can be built and checked on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: The user story the task belongs to (US1, US2, US3)
- Every task names the exact file it creates or changes

## Path Conventions

- `src/kestrel/`: API and all product logic (Python package)
- `ui/`: Streamlit screen; renders and calls the API, and never imports `kestrel`
- `targets/hs_code/`: sacrificial HS-code target, a separate uv project
- `tests/unit/`, `tests/integration/`, `tests/e2e/`: Kestrel's tests; `targets/hs_code/tests/`: the target's smoke tests

## Shared conventions

Tests and code written in different tasks rely on these names.

| Kind | Names |
|---|---|
| Widget keys in `ui/app.py` | `target_select`, `display_name`, `method`, `url`, `header_name_{i}`, `header_value_{i}`, `header_remove_{i}`, `add_header`, `body_template`, `response_path`, `test_button`, `permission`, `save_button`, `delete_button`, `delete_confirm`, `delete_cancel` |
| `st.session_state` keys | `config`, `form_id`, `headers`, `result`, `errors`, `loaded_target` |
| Fixtures in `tests/conftest.py` | `settings` (local mode, files under `tmp_path`), `hosted_settings`, `client` (FastAPI `TestClient`; accepts an `httpx.MockTransport` and a fake resolver), `all_logs` (every captured log line as one string) |
| Fixtures in `tests/e2e/conftest.py` | `hs_target`, `kestrel_api`, `ui`, plus the helper `assert_no_secret_in_logs()` |
| Environment | `KESTREL_MODE`, `KESTREL_SECRET_KEY`, `KESTREL_KEY_FILE`, `KESTREL_DB_PATH`, `KESTREL_API_URL`; for the target, `HS_TARGET_API_KEY` and `OPENROUTER_API_KEY` |
| Exact wording | Step messages from the table in [contracts/kestrel-api.md](./contracts/kestrel-api.md); widget labels from [contracts/ui-form.md](./contracts/ui-form.md) |

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the project and its tooling.

- [ ] T001 Create the uv project at the repo root: run `uv init --package --name kestrel --python 3.12`, then `uv add fastapi uvicorn httpx cryptography streamlit` and `uv add --dev pytest`. In `pyproject.toml`, set `requires-python = ">=3.12,<3.13"` and add `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `pythonpath = ["src", "ui"]`, `markers = ["e2e: starts the sacrificial target and the API; needs OPENROUTER_API_KEY"]` and `addopts = "-m 'not e2e' --import-mode=importlib"`. Confirm `uv run pytest` runs and collects nothing.
- [ ] T002 Create the package and test folders: `src/kestrel/__init__.py` (emptied of anything `uv init` generated), `src/kestrel/connection/__init__.py`, `src/kestrel/api/__init__.py`, and empty folders `tests/unit/`, `tests/integration/`, `tests/e2e/` (add a `.gitkeep` to each).
- [ ] T003 [P] Create `.gitignore` at the repo root with `/data/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`, `targets/hs_code/.venv/` and `targets/hs_code/.env`.
- [ ] T004 [P] Create `.env.example` at the repo root documenting `KESTREL_MODE` ("local" or "hosted"; unset means hosted), `KESTREL_SECRET_KEY` (optional Fernet key), `KESTREL_KEY_FILE` (default `~/.kestrel/secret.key`), `KESTREL_DB_PATH` (default `data/kestrel.db`) and `KESTREL_API_URL` (screen to API, default `http://127.0.0.1:8000`). Say that Kestrel reads real environment variables and doesn't load this file.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Settings, secrets, the API and screen skeletons, the sacrificial target and the end-to-end harness. All user stories need them.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Kestrel core

- [ ] T005 [P] Write `tests/unit/test_settings.py` for `kestrel.settings.load_settings(env)`. Cases:
  - `KESTREL_MODE` "local" and "hosted" are accepted; unset gives "hosted".
  - Any other value, such as "dev", raises `SettingsError` with a message naming `KESTREL_MODE`.
  - `KESTREL_DB_PATH` defaults to `data/kestrel.db`.
  - `KESTREL_KEY_FILE` defaults to `~/.kestrel/secret.key`, expanded.
  - `KESTREL_SECRET_KEY` is optional.

  Confirm the tests fail.
- [ ] T006 [P] Write `tests/unit/test_secrets.py` for `kestrel.secrets` (research R5). Cases for `load_or_create_key(settings, logger)`:
  - It uses `KESTREL_SECRET_KEY` when set (source "env"), and raises `SettingsError` for an invalid key.
  - It reads an existing key file (source "file").
  - It creates a missing file and its parent folders (source "generated"), logging a WARNING with the full path and "back this file up".
  - In hosted mode a generated or file key logs an extra warning about redeploys.

  Cases for `Vault` and `mask_values`:
  - `Vault.encrypt` and `Vault.decrypt` round-trip, and `decrypt` returns `None` for a token made with another key.
  - `mask_values(text, values)` replaces every value of 4 or more characters with `••••`, all occurrences, longest first.
  - Values of 1 to 3 characters are left alone.

  Confirm the tests fail.
- [ ] T007 Implement `src/kestrel/settings.py` (frozen `Settings` dataclass with `mode`, `db_path`, `key_file`, `secret_key`; `load_settings(env=os.environ)`; `SettingsError`) to pass T005.
- [ ] T008 Implement `src/kestrel/secrets.py` (`load_or_create_key`, `Vault` built on `cryptography.fernet.Fernet`, `mask_values`) to pass T006. Write a generated key file with `os.chmod(path, 0o600)` where the OS supports it, and ignore the error on Windows.
- [ ] T009 Create `tests/conftest.py` with the fixtures `settings`, `hosted_settings`, `client` and `all_logs` from "Shared conventions". The `client` fixture builds `create_app(settings, transport=..., resolver=...)` from `kestrel.api.main`, so tests can pass an `httpx.MockTransport` and a fake resolver.
- [ ] T010 Write `tests/integration/test_api_base.py`. Cases:
  - `GET /api/config` returns `mode` and `defaults` exactly as in contracts/kestrel-api.md: `{"method": "POST", "body_template": "{\"message\": \"{{prompt}}\"}", "response_path": "$.reply"}`.
  - A request whose body misses a required field returns 422 in the shape `{"errors": [{"field": ..., "message": ...}]}`. Send `"headers": [{"name": "X", "value": "s3cret-value-123"}]` with no URL, and assert the response text doesn't contain `s3cret-value-123`.
  - `create_app()` with `KESTREL_MODE=dev` in the environment raises `SettingsError`.

  Confirm the tests fail.
- [ ] T011 Implement `src/kestrel/api/main.py` and `src/kestrel/api/schemas.py` to pass T010.
  - `create_app(settings=None, *, transport=None, resolver=None)` loads settings (`load_settings()` when `None`) and the key with `load_or_create_key`.
  - It configures the `kestrel` logger to write to stderr with `%(asctime)s %(levelname)s %(name)s %(message)s`.
  - It registers a `RequestValidationError` handler that returns only `{"errors": [{"field": "<dotted location without 'body'>", "message": "<text>"}]}` and never the input.
  - It serves `GET /api/config` with `mode` and `defaults`.
  - The API runs with `uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000`. Replace the API command in `specs/001-register-target/quickstart.md` with this one (a module-level `app` would create a key at import time).
- [ ] T012 [P] Write `tests/integration/test_ui_boundary.py`. It parses every `ui/*.py` with `ast` and fails if any file imports `kestrel` (plan, Structure Decision).
- [ ] T013 Create `ui/api_client.py` and a first `ui/app.py`.
  - `ui/api_client.py`: the base URL comes from `KESTREL_API_URL` (default `http://127.0.0.1:8000`). Add an `ApiError(status, body)` exception and `get_config()`.
  - `ui/app.py`: call `st.set_page_config(page_title="Kestrel")`, put the sidebar title "Kestrel", and fetch `/api/config` once per session into `st.session_state["config"]`.
  - Show the mode caption "Running locally" or "Running hosted: local and private addresses are blocked" (contracts/ui-form.md, row 11).
  - Import the client as `import api_client`; Streamlit puts the script's folder on `sys.path`. Never import `kestrel`.

### Sacrificial HS-code target (FR-024 to FR-027)

- [ ] T014 [P] Create `targets/hs_code/pyproject.toml` as its own uv project.
  - Name `hs-code-target`, `requires-python = ">=3.12,<3.13"`, and `[tool.uv] package = false`.
  - Dependencies: `fastapi`, `uvicorn`, `pydantic>=2.7,<3`, `langchain-core==1.6.10`, `langchain-openai==1.7.1`, `rank_bm25==0.2.2`, `lxml>=5`, `python-dotenv>=1`.
  - Dev group: `pytest`. Pytest settings: `testpaths = ["tests"]` and `pythonpath = ["."]`.

  Run `uv sync --project targets/hs_code`.
- [ ] T015 [P] Copy CargoLint files unchanged into `targets/hs_code/`, keeping their relative paths.
  - Take every file from commit `51ec448` with `git -C C:/ai/CargoLint show 51ec448:<path> > targets/hs_code/<path>`. CargoLint's working tree has uncommitted edits, so don't copy from disk.
  - Code: `agent/__init__.py`, `agent/config.py`, `agent/llm.py`, `agent/prompts.py`, `agent/routing.py`, `agent/schemas.py`, `rag/__init__.py`, `rag/nomenclature.py`, `rag/retriever.py`, `rag/rules.py`, `rag/translate.py`, `tools/__init__.py`, `tools/classify_hs6.py`, `tools/common.py`.
  - Data: `data/nomenclature_2026.jsonl`, `data/rules/firm_stop_words.json`, `data/rules/ics2_aliases.json`, `data/rules/ics2_stop_words.json`, `data/rules/ics2_unacceptable_terms.json`, `data/model_prices.json`, `data/SOURCES.md`.

  Then write `targets/hs_code/PROVENANCE.md` with:
  - the source repo and commit, and every copied file marked "unchanged";
  - the licences from `data/SOURCES.md`: CN 2026 under CC BY 4.0; the DG TAXUD and ICS2 documents reusable with acknowledgement;
  - what was deliberately left out, and why (research R11).

  Never import from `C:\ai\CargoLint`.
- [ ] T016 Write `targets/hs_code/tests/test_app.py` (needs T014 and T015). Cases:
  - `import tools.classify_hs6` works. This catches lazily imported modules that weren't copied.
  - Starting `app` without `HS_TARGET_API_KEY` fails.
  - `GET /health` returns 200 `{"status": "ok"}` without a key.
  - `POST /chat` without `X-API-Key`, or with a wrong one, returns 401 `{"detail": "unauthorized"}`, and the model client factory is never called.
  - With a fake model client, it returns 200 and a non-empty `reply` for both "Stainless steel vacuum flask, 500 ml" and "Hello".
  - When the fake client raises, it returns 502 `{"detail": "model call failed"}`.

  Build the fake from CargoLint's `tests/fakes.py` at commit `51ec448` (and the pieces of its `tests/conftest.py` the fake needs). Copy it into `targets/hs_code/tests/fakes.py` and list it in `PROVENANCE.md`. Confirm the tests fail.
- [ ] T017 Implement `targets/hs_code/kb.py` with `build_kb()` (research R11). It returns an object with:
  - `index`: `NomenclatureIndex.from_jsonl("data/nomenclature_2026.jsonl")`;
  - `retriever`: `HybridRetriever(bm25=BM25Index(docs), vectors=NullVectorSearch(), chunks=index)`;
  - `bti=None`, `bti_vectors=None`, `shippers=[]`.

  Build the BM25 `docs` from the index's chunks, using the same `(id, text)` pairs that CargoLint's `rag/loader.py` writes to `store/bm25.pkl`. Read `C:/ai/CargoLint/rag/loader.py` for reference only; don't copy it. `NullVectorSearch.embed_queries(queries)` returns `[[0.0] for _ in queries]`, and `search_by_vector(...)` and `search(...)` return `[]`.
- [ ] T018 Implement `targets/hs_code/app.py` to pass T016.
  - Refuse to start without `HS_TARGET_API_KEY`.
  - Serve `GET /health`.
  - `POST /chat` first compares `X-API-Key` with `hmac.compare_digest`, then builds the KB once (lazily, then cached).
  - It runs `classify_lines([LineText(line_no=1, text_en=message)], ClassifyContext(hybrid=True, precedents=False), kb, client, workers=1)`, getting the client from a module-level `get_model_client()` (default: CargoLint's `agent.llm.get_client()`).
  - The reply follows [contracts/hs-code-target.md](./contracts/hs-code-target.md): up to three lines `N. <code> <kb.index.subheading_text(code)> (confidence 0.82)`, or `No HS-6 suggestion for "<message>": the description is too vague to classify.`
  - Return 502 `{"detail": "model call failed"}` when the client raises or the line's status is failed.

### End-to-end harness

- [ ] T019 Create `tests/e2e/conftest.py` (needs T011, T013, T018). Mark every test in the folder `e2e`, and skip with a clear reason when `OPENROUTER_API_KEY` is unset. Start each server with its own interpreter rather than through `uv run`, so stopping it doesn't leave a child server running on Windows.
  - **`hs_target`** (session fixture):
    - Run the interpreter printed by `uv run --project targets/hs_code python -c "import sys; print(sys.executable)"` with `-m uvicorn app:app --host 127.0.0.1 --port <free port>` and cwd `targets/hs_code`.
    - Set `HS_TARGET_API_KEY` to a fresh random value of at least 24 characters; that's the known value for SC-004.
    - Send output to a temp log file, and wait up to 300 s for `GET /health`.
  - **`kestrel_api`** (session fixture): run `sys.executable -m uvicorn --factory kestrel.api.main:create_app` on a free port. Set `KESTREL_MODE=local`, and point `KESTREL_DB_PATH` and `KESTREL_KEY_FILE` at a temp folder. Log to a temp file and wait for `GET /api/config`.
  - **`ui`**: set `KESTREL_API_URL` and return `AppTest.from_file(<repo root>/ui/app.py, default_timeout=120)`.
  - **`assert_no_secret_in_logs()`**: asserts the target's key appears 0 times in both log files (SC-004).
  - Stop both processes at the end of the session.

**Checkpoint**: The API answers `/api/config`, the screen renders, the sacrificial target answers `/chat` with a key, and `uv run pytest` is green.

---

## Phase 3: User Story 1 - Test the connection to my agent (Priority: P1) 🎯 MVP

**Goal**: The user fills in the form, clicks Test connection, and sees the agent's reply as plain text or a message naming the step that failed.

**Independent Test**: With the sacrificial target running, fill in the form and test; the reply appears. With response path `$.answer`, "Response path not found" appears. Nothing needs to be saved.

### Tests for User Story 1 ⚠️

> Write these first and make sure they fail before T028.

- [ ] T020 [P] [US1] Write `tests/unit/test_template.py` for `kestrel.connection.template` (FR-003, FR-004, FR-006).
  - **Errors on the body template** (`TemplateError` with `field` `settings.body_template`): POST with 0 or 2 placeholders; the placeholder outside a JSON string, as in `{"m": {{prompt}}}`; a template that isn't valid JSON.
  - **Errors on the URL** (`TemplateError` with `field` `settings.url`): POST with the placeholder in the URL; GET with it 0 or 2 times, or outside the query string. GET ignores the body template.
  - **POST filling**: `build_request("POST", url, '{"message": "{{prompt}}"}', prompt)` gives valid JSON whose `message` equals the prompt. Try prompts containing `"`, `\`, a line break, `{{`, `}}` and `漢字 ü`, plus a placeholder inside a longer string such as `"Q: {{prompt}}"`.
  - **GET filling**: `build_request("GET", "http://h/chat?q={{prompt}}", ...)` percent-encodes the prompt and returns no body.
- [ ] T021 [P] [US1] Write `tests/unit/test_response_path.py` for `kestrel.connection.response_path` (research R4).
  - `parse` accepts `$`, `$.reply`, `$.choices[0].message.content` and `$.a.b[2][0]`.
  - `parse` rejects `reply`, `$.`, `$..a`, `$.a[`, `$.a[-1]` and `$.a[x]` with `PathSyntaxError`.
  - `extract(doc, path)` returns the matched value, and raises `PathNotFound` for a missing field, an index out of range, or a step into a string or number.
- [ ] T022 [P] [US1] Write `tests/unit/test_address_guard.py` for `kestrel.connection.address_guard.is_allowed(url, mode, resolver)` (FR-028, research R8).
  - Local mode allows everything without resolving.
  - Hosted mode refuses `localhost`, `api.localhost`, `127.0.0.1`, `[::1]`, `10.1.2.3`, `172.16.0.1`, `192.168.1.1`, `169.254.169.254`, `100.100.100.200`, `0.0.0.0`, `224.0.0.1`, `[::ffff:127.0.0.1]` and `[fd00:ec2::254]`.
  - Hosted mode refuses a name the fake resolver maps to `10.0.0.5`, including when it also returns a public address.
  - Hosted mode allows a name that resolves only to `93.184.216.34`.
  - A resolver error counts as allowed; the tester then reports `unreachable`.
- [ ] T023 [P] [US1] Write `tests/unit/test_sessions.py` for `kestrel.connection.sessions.FormSessions` (FR-009, FR-012, research R7).
  - `start(form_id)` returns False while that form has a test in flight, and True for another form.
  - `finish(form_id, fingerprint)` releases the form and records the fingerprint; `finish(form_id, None)` clears an earlier one.
  - `fingerprint(settings)` is the same when header names differ only in order or case. It changes when the URL, method, a header value, the body template or the response path changes. It's a hex HMAC that contains no header value.
  - Sessions unused for 60 minutes are dropped; use a fake clock.
- [ ] T024 [P] [US1] Write `tests/unit/test_tester.py` for `kestrel.connection.tester.run_test(...)`, using `httpx.MockTransport` (FR-005, FR-007, FR-008, FR-010, FR-023, research R1, R2, R9). Each case in research R2 must give the right `step`, the exact `message` from contracts/kestrel-api.md, and the right `detail`:
  - **Replies**: success with reply text; an empty reply gives `reply_text == ""` and `ok`.
  - **Status codes**: 401 and 403 give `auth_rejected`. 302 with `Location` gives `endpoint_error` with the location in `detail`, and no second request is sent. 500 gives `endpoint_error`.
  - **Size cap**: a body over 1,048,576 bytes, signalled by `Content-Length` or found while streaming without one, gives `endpoint_error` with "Response larger than 1 MB".
  - **Body and path**: non-JSON gives `non_json`; a missing path gives `path_not_found`; a list, number or null gives `not_text` with "Found: list" (or the type found).
  - **Network**: a closed local port with the real transport gives `unreachable`. A handler that sleeps past a 0.5-second test deadline gives `timed_out`.
  - **Hosting guard**: hosted mode with a private address gives `address_not_allowed`, and nothing is sent.
  - **The request**: exactly one per run, carrying `Hello`, the user's headers and `User-Agent: Kestrel/0.1 (connection test)`.
  - **Output**: a reply over 2,000 characters is cut, with `reply_truncated` set. A header value echoed in the reply or detail comes back as `••••`.
  - **Logging**: one INFO line on logger `kestrel.connection` with target name, configured URL, method, step, status and duration. The log text never contains the header value or the reply.
- [ ] T025 [P] [US1] Write `tests/integration/test_api_connection_tests.py` for `POST /api/connection-tests` (contracts/kestrel-api.md).
  - A success and two failure steps return 200 with the result shape.
  - Invalid forms return 422 naming `settings.url`, `settings.body_template`, `settings.response_path` or `settings.headers.0.name`, and never the submitted values.
  - A header with `value: null` and no `target_id` gives 422.
  - After `app.state.sessions.start(form_id)`, a request with that `form_id` gets 409 `test_in_progress`.
  - `hosted_settings`, with a fake resolver returning `10.0.0.5`, gives `address_not_allowed`.
  - `all_logs` contains the header value 0 times (SC-004).
- [ ] T026 [P] [US1] Write `tests/integration/test_ui_connection.py` with `AppTest` and a stubbed `api_client` (import `api_client`, which `pythonpath` makes possible, and monkeypatch its functions). Cases:
  - The form shows the defaults from `/api/config` (FR-002).
  - `add_header` adds a row that can be filled in.
  - Clicking `test_button` sends the form values with a `form_id`.
  - A success shows `st.success` containing "Connection works", with the reply in a code element.
  - A reply containing `**bold**`, `<img src=x onerror=alert(1)>`, `[link](http://evil)` and `![x](http://evil/x.png)` appears only inside the code element and in no markdown element (SC-008).
  - An empty reply shows "(empty reply)", and a cut reply shows the caption.
  - A failure shows `st.error` with the message and the detail in a code element.
- [ ] T027 [US1] Write `tests/e2e/test_us1_connection.py` (marker `e2e`; uses the T019 fixtures).
  - **Spec acceptance test 1 (US1.1)**: fill in `url` with the sacrificial target's URL, add the header `X-API-Key` with its key, and leave the defaults unchanged. Click `test_button` and assert a success box and a non-empty reply in the code element.
  - **Acceptance test 2 (US1.2)**: set `response_path` to `$.answer` and test again. Assert the error box starts with "Response path not found" and no reply code element is shown.
  - End each test with `assert_no_secret_in_logs()`.

### Implementation for User Story 1

- [ ] T028 [P] [US1] Implement `src/kestrel/connection/template.py` to pass T020 (research R3): `PLACEHOLDER = "{{prompt}}"`, `TemplateError(field, message)`, `validate(method, url, body_template)`, `build_request(method, url, body_template, prompt)`.
- [ ] T029 [P] [US1] Implement `src/kestrel/connection/response_path.py` to pass T021: `parse`, `extract`, `PathSyntaxError` and `PathNotFound`.
- [ ] T030 [P] [US1] Implement `src/kestrel/connection/address_guard.py` to pass T022.
  - Provide `is_allowed(url, mode, resolver=default_resolver)`; `default_resolver` uses `socket.getaddrinfo` over all address families.
  - Check addresses with `ipaddress`: `is_loopback`, `is_private`, `is_link_local`, `is_unspecified`, `is_reserved` and `is_multicast`.
  - Also block `100.64.0.0/10`, and unwrap `ipv4_mapped` IPv6 addresses before checking.
- [ ] T031 [US1] Implement `ResolvedSettings` and `async run_test(settings, *, mode, display_name, transport=None, resolver=..., deadline_s=60.0, connect_timeout_s=10.0, max_bytes=1_048_576, max_reply_chars=2000)` in `src/kestrel/connection/tester.py` to pass T024 (research R1, R2, R9).
  - Use `httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=httpx.Timeout(deadline_s, connect=connect_timeout_s))` inside `asyncio.timeout(deadline_s)`.
  - Stream the body with the 1 MB cap, and classify the outcome in research R2's order.
  - Mask with `mask_values`, cut the reply to 2,000 characters, and log one line on `kestrel.connection` with only the fields listed in research R9.
- [ ] T032 [US1] Implement `FormSessions` in `src/kestrel/connection/sessions.py` to pass T023: `start`, `finish`, `last_success`, `fingerprint`, a per-process random HMAC key, and a 60-minute expiry. Needs T031 for `ResolvedSettings`.
- [ ] T033 [US1] Add `POST /api/connection-tests` to `src/kestrel/api/main.py`, with `HeaderIn`, `ConnectionSettingsIn`, `ConnectionTestRequest` and `ConnectionTestResult` in `src/kestrel/api/schemas.py`. Pass T025.
  - **Validation (422 in the contract format)**: URL and response path required; URL must be `http` or `https`; header names must be HTTP tokens and not `Host`, `Content-Length`, `Transfer-Encoding` or `Connection`; `template.validate` and `response_path.parse` must pass; `value: null` without a `target_id` is refused.
  - **Run**: take the `FormSessions` lock (409 `test_in_progress` if taken), then run the test with the app's transport, resolver and mode.
  - **After**: record the fingerprint on success or clear it on failure, then release the lock.
- [ ] T034 [US1] Add `test_connection(payload)` to `ui/api_client.py` with a 90-second timeout. Add the US1 parts of `ui/app.py`: contracts/ui-form.md rows 2 to 6 and the Connection test panel, using the widget keys from "Shared conventions". Pass T026.
  - **Form**: the display name, method and URL fields.
  - **Header rows**: a name input, a `type="password"` value input, Remove, and Add header.
  - **Template and path**: both prefilled from `/api/config`.
  - **`test_button`**: disabled while a test runs; keep a UUID4 `form_id` in `st.session_state`.
  - **Results**: `st.success` and `st.error` carry only Kestrel's wording; `reply_text` and `detail` go through `st.code(text, language=None)`. Show "(empty reply)" and the truncation caption.
  - **Validation errors**: show 422 field errors under the matching field.
- [ ] T035 [US1] Run `uv run pytest` (all unit and integration tests green), then `uv run pytest -m e2e tests/e2e/test_us1_connection.py` with `OPENROUTER_API_KEY` set (T027 green).

**Checkpoint**: User Story 1 works on its own and is the MVP: register, test, read the reply or the failing step.

---

## Phase 4: User Story 2 - Save my agent as a target (Priority: P2)

**Goal**: After a successful test and with the permission box ticked, the user saves the target; it survives restarts.

**Independent Test**: Test the sacrificial target, tick the box, save, and see it listed, also after a restart. With the box unticked, saving is blocked.

**Depends on**: User Story 1, because only a tested target can be saved (`FormSessions` and `POST /api/connection-tests`).

### Tests for User Story 2 ⚠️

- [ ] T036 [P] [US2] Write `tests/unit/test_store.py` for `kestrel.store.TargetStore(db_path, vault)` (data-model.md). Cases:
  - `create_target(...)` round-trips through `list_targets()` and `get_target(id)`.
  - Header values are stored as Fernet tokens: read the raw `target_headers.value_encrypted` column and assert it differs from the value. They come back decrypted only through `resolve_headers(id)`.
  - `name_key` makes "HS Agent" and "hs agent" collide with `NameTaken`, and also "Ärger" and "ärger".
  - The method check rejects "PUT".
  - The unique index rejects two headers named `X-Key` and `x-key` on one target.
  - Reopening the same file keeps the data (FR-014).
  - `PRAGMA foreign_keys` and `PRAGMA secure_delete` are on, and `meta` holds `schema_version = 1`.
- [ ] T037 [P] [US2] Write `tests/integration/test_api_save.py` for `POST /api/targets` and `GET /api/targets` (contracts/kestrel-api.md). Cases:
  - **Success**: after a successful test with the same `form_id`, saving returns 201 with headers as `{"name", "has_value": true, "readable": true}` and no values.
  - **409 `not_tested`**: when the form never tested, when its most recent test failed, and when the settings changed after the test. A different display name alone still saves (FR-012).
  - **422**: field `permission_confirmed` when it's false (FR-011); field `terms_version` when it's not the current version (FR-029).
  - **409 `name_taken`**: field `name`, for a name that differs only in case (FR-013).
  - **Listing**: `GET /api/targets` lists the target with `permission_confirmed_at` and `terms_version`, also from a new app instance on the same database (FR-014).
  - **Config**: `GET /api/config` includes `terms.version` and `terms.text`.
  - **Secrets**: the saved header value appears 0 times in `all_logs` and in every response body (SC-004).
- [ ] T038 [P] [US2] Write `tests/integration/test_ui_save.py` with `AppTest` and a stubbed `api_client`. Cases:
  - The `permission` checkbox label is exactly "I own this agent or have written permission to test it".
  - The expander "Terms of service (version 1)" shows the terms text, and opening it keeps the typed form values (US2.6).
  - `save_button` sends `permission_confirmed` and `terms_version`.
  - Errors are shown for 409 `not_tested`, 409 `name_taken` and 422 `permission_confirmed`.
  - After a save, the saved-targets table shows name, URL, method, permission date and terms version; the typed header values are gone from `st.session_state`; and a new `form_id` is in use.
- [ ] T039 [US2] Write `tests/e2e/test_us2_save.py` (marker `e2e`).
  - **Spec acceptance test 3 (US2.2)**: test the sacrificial target successfully, leave `permission` unticked and click `save_button`. Assert saving is blocked and the table has no row.
  - **US2.1**: tick `permission`, save, and assert the target is listed.
  - End with `assert_no_secret_in_logs()`.

### Implementation for User Story 2

- [ ] T040 [US2] Implement `src/kestrel/store.py` to pass T036, with `sqlite3` only (no ORM).
  - **Schema**: create it on open, with these constraints quoted from data-model.md.
    - `targets`:
      - `id` INTEGER PRIMARY KEY;
      - `name` TEXT NOT NULL, "Trimmed, 1 to 100 characters";
      - `name_key` TEXT NOT NULL UNIQUE, "`name.casefold()`; makes display names unique ignoring letter case (FR-013)";
      - `url` TEXT NOT NULL, "`http` or `https`; for GET, contains `{{prompt}}` exactly once in the query string (FR-003)";
      - `method` TEXT NOT NULL, "`CHECK (method IN ('POST', 'GET'))`";
      - `body_template` TEXT NOT NULL, "POST: valid JSON with `{{prompt}}` exactly once inside a string value. GET: stored but not sent";
      - `response_path` TEXT NOT NULL, "Syntax in research R4";
      - `permission_confirmed_at` TEXT NOT NULL, "ISO-8601 UTC. Set on first save, and again when a save changes the URL or accepts a newer terms version";
      - `terms_version` TEXT NOT NULL, "Version of the terms accepted with the permission (FR-029)";
      - `created_at` and `updated_at` TEXT NOT NULL, "ISO-8601 UTC".
    - `target_headers`:
      - `id` INTEGER PRIMARY KEY;
      - `target_id` INTEGER NOT NULL, "`REFERENCES targets(id) ON DELETE CASCADE`";
      - `position` INTEGER NOT NULL, "Order shown in the form";
      - `name` TEXT NOT NULL, "HTTP token characters only. `Host`, `Content-Length`, `Transfer-Encoding` and `Connection` are not allowed";
      - `value_encrypted` TEXT NOT NULL, "Fernet token. Never returned by the API (FR-020, FR-021)";
      - "Unique index on `(target_id, lower(name))`".
    - `meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)`, holding `schema_version = 1`.
  - **Connections**: open one per call, with `PRAGMA foreign_keys=ON` and `PRAGMA secure_delete=ON`.
  - **Interface**: `create_target`, `list_targets`, `get_target`, `resolve_headers` (decrypted values for the tester) and the `NameTaken` exception.
- [ ] T041 [P] [US2] Write `src/kestrel/api/terms.md`. The first line is `version: 1`, followed by a short plain-language text. It says the user owns the agent or has written permission to test it, that the user is responsible for every test and scan run against it, and that Kestrel only sends plain conversational messages within fixed limits (FR-029).
- [ ] T042 [US2] Extend `src/kestrel/api/main.py` and `src/kestrel/api/schemas.py`. Pass T037.
  - **Config**: load `terms.md` (version and text) into `GET /api/config`.
  - **Store**: open `TargetStore` at start-up, creating the folder of `db_path`.
  - **Endpoints**: add `GET /api/targets` and `POST /api/targets`, with `SaveTargetRequest`, `TargetSummary`, `TargetDetail` and `HeaderOut`.
  - **Save rules** (contracts/kestrel-api.md):
    - the same form validation as T033;
    - the display name trimmed to 1 to 100 characters;
    - `permission_confirmed` must be true, and `terms_version` must equal the current version;
    - the form session's last successful fingerprint must match the submitted settings, otherwise 409 `not_tested`;
    - `NameTaken` becomes 409 `name_taken` with field `name`.
  - **Permission date**: set `permission_confirmed_at` to the current UTC time.
- [ ] T043 [US2] Add `save_target(payload)` and `list_targets()` to `ui/api_client.py`, and the US2 parts of `ui/app.py`: contracts/ui-form.md rows 7 to 9 and the Saved targets table. Pass T038.
  - **Permission**: the `permission` checkbox.
  - **Terms**: `st.expander("Terms of service (version N)")`, showing the text from `/api/config` with `st.text`.
  - **Saving**: `save_button`, with errors shown at the matching field.
  - **Table**: `st.dataframe` of saved targets.
  - **After a save**: clear the typed header values and start a new `form_id`.
- [ ] T044 [US2] Run `uv run pytest` and `uv run pytest -m e2e tests/e2e/test_us2_save.py` (T039 green).

**Checkpoint**: User Stories 1 and 2 work: test, tick, save, restart, still listed.

---

## Phase 5: User Story 3 - Manage saved targets (Priority: P3)

**Goal**: The user selects a saved target to view, re-test, edit or delete it. Header values are never shown and never have to be retyped.

**Independent Test**: Save a target with a header, select it, rename it and save without a test, then delete it after confirming. The header value never appears.

**Depends on**: User Story 2 (saved targets).

### Tests for User Story 3 ⚠️

- [ ] T045 [P] [US3] Write `tests/unit/test_store_edit.py` for `TargetStore`. Cases:
  - In `update_target`, a header `value` of `None` keeps the stored encrypted value, a new string replaces it, and an omitted header is removed (FR-017).
  - `update_target` renews `permission_confirmed_at` when the URL or the terms version changes, and keeps it otherwise (FR-018).
  - `delete_target` removes the target and its `target_headers` rows (FR-019).
  - With a `Vault` on a different key, `get_target` reports the header as `readable=False`, and `resolve_headers` reports it as unreadable instead of raising.
- [ ] T046 [P] [US3] Write `tests/integration/test_api_manage.py` for `GET`, `PUT` and `DELETE /api/targets/{id}`, and for `target_id` in tests (contracts/kestrel-api.md). Cases:
  - `GET /api/targets/{id}` returns headers as names with `has_value` and `readable`, and no values (FR-021).
  - A `PUT` with only a new name saves without a test (FR-012).
  - A `PUT` with changed settings and no matching successful test gives 409 `not_tested`.
  - A test with `target_id` and `value: null` sends the stored value (check it in the MockTransport handler), and a later `PUT` with `value: null` keeps it (FR-016, FR-017).
  - A `PUT` with a new URL renews `permission_confirmed_at` (FR-018).
  - `DELETE` gives 204, and the next `GET` gives 404 (FR-019).
  - An unknown id gives 404 on `GET`, `PUT`, `DELETE` and as a `target_id`.
  - **Key loss (research R5)**: restart the app with another key file and the same database.
    - Start-up logs an error that the key doesn't match.
    - `GET` shows `readable: false`.
    - A test of the target returns `credentials_unreadable`, and the MockTransport receives no request.
    - Re-entering the value, testing and saving makes it readable again.
- [ ] T047 [P] [US3] Write `tests/integration/test_ui_manage.py` with `AppTest` and a stubbed `api_client`. Cases:
  - Selecting a saved target in `target_select` loads its fields. Each stored header shows an empty value input with the placeholder "Stored · leave empty to keep" and is sent as `value: null` (US3.1, FR-017).
  - Changing `url` clears `permission` (US3.3, FR-018).
  - A name-only change saves (US3.2).
  - `delete_button` shows `delete_confirm` and `delete_cancel`. Cancel changes nothing (US3.5). Confirm calls delete, refreshes the table and starts a new `form_id` (US3.4).

### Implementation for User Story 3

- [ ] T048 [US3] Add `update_target` and `delete_target` to `src/kestrel/store.py`, and have `get_target` and `resolve_headers` report unreadable headers instead of raising. Pass T045.
- [ ] T049 [US3] Extend `src/kestrel/api/main.py`. Pass T046.
  - **`GET /api/targets/{id}`**.
  - **`PUT /api/targets/{id}`**: no test is needed when the resolved connection settings equal the stored ones; otherwise the `not_tested` rule applies. Renew `permission_confirmed_at` on a URL or terms-version change.
  - **`DELETE /api/targets/{id}`**.
  - **`POST /api/connection-tests`**: resolve `target_id` and `value: null` headers from the store. Return `credentials_unreadable` without sending when a needed value can't be decrypted.
  - **Start-up**: try to decrypt one stored header value, and log an ERROR that the key doesn't match if that fails (research R5).
- [ ] T050 [US3] Add `get_target`, `update_target` and `delete_target` to `ui/api_client.py`, and the US3 parts of `ui/app.py`: contracts/ui-form.md rows 1, 4 and 10. Pass T047.
  - **`target_select`**: "New target", then saved targets as "name · URL".
  - **Loading a target**: stored headers become empty password inputs with the placeholder "Stored · leave empty to keep".
  - **Permission**: clear `permission` when the URL differs from the loaded one.
  - **Saving**: save edits with `update_target`.
  - **Delete**: the two-step delete.
  - **`form_id`**: start a new one whenever the selection changes, and after a save or delete.
- [ ] T051 [US3] Run `uv run pytest` (all green), then the full `uv run pytest -m e2e tests/e2e/`.

**Checkpoint**: All three user stories work on their own.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, a full manual check, and a last secret-hygiene pass.

- [ ] T052 [P] Write `README.md` at the repo root. Cover:
  - what Kestrel is, in one paragraph from the constitution;
  - how to run it locally: the two commands from quickstart.md, with `KESTREL_MODE=local`;
  - where the key file lives and why to back it up;
  - how to run the tests;
  - a link to `specs/001-register-target/quickstart.md`.
- [ ] T053 [P] Write `targets/hs_code/README.md`: what the sacrificial target is for, how to start it, its environment variables and how to register it in Kestrel (from contracts/hs-code-target.md), with a link to `PROVENANCE.md`.
- [ ] T054 Go through the 12 manual checks in `specs/001-register-target/quickstart.md` against a running API, screen and sacrificial target. Fix any difference, in the code or in quickstart.md.
- [ ] T055 Review secret hygiene in `src/kestrel/**/*.py`, `ui/app.py` and `ui/api_client.py`. Check every logging call, `print`, `st.markdown`, `st.write` and exception message that could carry a header value or target text against the rules in research R9, and fix any that break them.
- [ ] T056 Run everything a last time: `uv run pytest`, `uv run pytest -m e2e`, and `uv run --project targets/hs_code --directory targets/hs_code pytest` for `targets/hs_code/tests/`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: needs Setup, and blocks all user stories. Two tracks can run side by side: the Kestrel core (T005 to T013) and the sacrificial target (T014 to T018). The end-to-end harness (T019) needs both.
- **User Story 1 (Phase 3)**: needs Foundational.
- **User Story 2 (Phase 4)**: needs User Story 1, because saving requires a successful test.
- **User Story 3 (Phase 5)**: needs User Story 2, because it manages saved targets.
- **Polish (Phase 6)**: needs the stories you intend to ship.

### Within each phase

- Test tasks first; confirm they fail.
- Then pure modules (template, response path, guard), then the tester and sessions, then API routes, then the screen.
- Close the phase with its "Run" task (T035, T044, T051).

### Task-level dependencies worth knowing

- T009 (fixtures) comes before T010; T011 needs T007 and T008.
- T016 needs T014 and T015; T018 needs T016 and T017.
- T019 needs T011, T013 and T018.
- T032 needs T031 (`ResolvedSettings`); T033 needs T028 to T032.
- T042 needs T040 and T041; T049 needs T048.

### Parallel Opportunities

- Phase 1: T003 and T004.
- Phase 2: T005, T006, T012, T014 and T015 at the start; the target track (T014 to T018) alongside the core track (T007 to T013).
- Phase 3: all seven test tasks (T020 to T026), then T028, T029 and T030.
- Phase 4: T036, T037 and T038, then T041 alongside T040.
- Phase 5: T045, T046 and T047.
- Phase 6: T052 and T053.

---

## Parallel Example: User Story 1

```bash
# All US1 test files at once (each a different file):
Task: "Write tests/unit/test_template.py"            # T020
Task: "Write tests/unit/test_response_path.py"       # T021
Task: "Write tests/unit/test_address_guard.py"       # T022
Task: "Write tests/unit/test_sessions.py"            # T023
Task: "Write tests/unit/test_tester.py"              # T024
Task: "Write tests/integration/test_api_connection_tests.py"   # T025
Task: "Write tests/integration/test_ui_connection.py"          # T026

# Then the three pure modules at once:
Task: "Implement src/kestrel/connection/template.py"       # T028
Task: "Implement src/kestrel/connection/response_path.py"  # T029
Task: "Implement src/kestrel/connection/address_guard.py"  # T030
```

## Parallel Example: User Story 2

```bash
Task: "Write tests/unit/test_store.py"               # T036
Task: "Write tests/integration/test_api_save.py"     # T037
Task: "Write tests/integration/test_ui_save.py"      # T038
# then
Task: "Implement src/kestrel/store.py"               # T040
Task: "Write src/kestrel/api/terms.md"               # T041
```

## Parallel Example: User Story 3

```bash
Task: "Write tests/unit/test_store_edit.py"          # T045
Task: "Write tests/integration/test_api_manage.py"   # T046
Task: "Write tests/integration/test_ui_manage.py"    # T047
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1: Setup.
2. Phase 2: Foundational (both tracks and the harness).
3. Phase 3: User Story 1.
4. **Stop and validate**: run T035, then demo testing the sacrificial target from the screen.

### Incremental delivery

1. Setup and Foundational give you a running API, screen and sacrificial target.
2. Add User Story 1, the MVP: test any agent and read the reply or the failing step.
3. Add User Story 2: save tested targets behind the permission tick and terms.
4. Add User Story 3: view, re-test, edit and delete saved targets.
5. Each step keeps earlier stories working; the phase's "Run" task proves it.

---

## Notes

- [P] tasks touch different files and don't depend on unfinished tasks.
- The [Story] label maps each task to its user story for traceability.
- Commit after each task or logical group; stop at any checkpoint to validate.
- `uv run pytest -m e2e` needs `OPENROUTER_API_KEY` and spends a fraction of a cent per run; a plain `uv run pytest` is offline and free.
- Never import from `C:\ai\CargoLint`. The target uses only the copies made in T015.
