# Quickstart: Register a Target Agent and Test the Connection

How to run this feature and check that it works. Contracts: [kestrel-api.md](./contracts/kestrel-api.md), [hs-code-target.md](./contracts/hs-code-target.md), [ui-form.md](./contracts/ui-form.md).

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- An OpenRouter API key, needed only for the sacrificial HS-code target and the end-to-end tests.

## Set up

```bash
uv sync                                   # Kestrel
uv sync --project targets/hs_code         # sacrificial target, first time only
```

## Run Kestrel on your own machine

Kestrel treats an unset `KESTREL_MODE` as hosted and blocks localhost addresses. Set it to `local` when running on your own machine.

```bash
# terminal 1: the API (PowerShell: $env:KESTREL_MODE="local")
KESTREL_MODE=local uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000

# terminal 2: the screen
uv run streamlit run ui/app.py
```

On first start, the API logs where it created the encryption key file (default `~/.kestrel/secret.key`). Back that file up. If it's lost, saved auth header values can't be recovered and have to be re-entered; everything else is kept ([research.md](./research.md) R5). To supply the key yourself instead, set `KESTREL_SECRET_KEY`.

Saved targets live in `data/kestrel.db` under the repo root, whichever folder you start the API from.

## Run the sacrificial HS-code target (for manual checks)

```bash
# PowerShell: $env:HS_TARGET_API_KEY="test-key-123"; $env:OPENROUTER_API_KEY="sk-or-..."
HS_TARGET_API_KEY=test-key-123 OPENROUTER_API_KEY=sk-or-... \
  uv run --project targets/hs_code --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
```

## Manual checks

| # | Steps | Expected | Spec |
|---|---|---|---|
| 1 | New target. URL `http://127.0.0.1:8001/chat`, header `X-API-Key: test-key-123`, defaults unchanged. Click Test connection | "Connection works" and the reply as plain text | US1.1 |
| 2 | Tick the checkbox, open the terms expander, Save target | Form input kept while the terms are open; target listed with today's date and terms version | US2.1, US2.6, FR-029 |
| 3 | Restart the API | Target still listed | US2.5 |
| 4 | Response path `$.answer`, Test connection | "Response path not found…" | US1.2 |
| 5 | Header value `wrong`, Test connection | "The agent refused the request as unauthorized…"; the value appears nowhere | US1.4 |
| 6 | Successful test, untick the checkbox, Save | Saving is blocked | US2.2 |
| 7 | Successful test, change the URL, Save | Saving is blocked until a new test succeeds | US2.4 |
| 8 | Saved target: change only the name, Save | Saved without a test; header still stored | US3.2 |
| 9 | Saved target: change the URL | Checkbox cleared | US3.3 |
| 10 | Delete target, then Confirm delete | Target gone | US3.4 |
| 11 | Restart the API without `KESTREL_MODE`, test the saved target | "This address is on a local or private network…"; nothing reaches the target | FR-028, SC-007 |
| 12 | Stop the API, move the key file away, start it again, test a target that has a header | Start-up log reports the key mismatch; test shows "The stored auth headers can't be read…"; re-entering the value, testing and saving fixes it | R5 |
| 13 | Hostile reply (steps below) | The reply shows as plain text with the tags and links visible as characters; nothing is requested from port 8003 | SC-008, FR-007 |

### Hostile-reply check (13)

1. In an empty folder, save `reply.json`:

   ```json
   {"reply": "<img src=\"http://127.0.0.1:8003/leak.png\"> ![pixel](http://127.0.0.1:8003/pixel.png) [click](http://127.0.0.1:8003/)"}
   ```

2. In that folder run `python -m http.server 8002`, and in a second terminal run `python -m http.server 8003` (the "outside address").
3. In Kestrel: New target, method GET, URL `http://127.0.0.1:8002/reply.json?q={{prompt}}`, no headers, response path `$.reply`. Click Test connection.
4. Check that the reply appears as plain text, that the console of the 8003 server shows no request, and that the browser's Network tab shows nothing sent to port 8003.

## Automated tests

```bash
uv run pytest                    # unit and integration tests: offline, no keys, no cost
uv run pytest -m e2e             # end-to-end: needs OPENROUTER_API_KEY; starts the target and the API itself
uv run --project targets/hs_code --directory targets/hs_code pytest   # target smoke tests, no model calls
```

The end-to-end run drives the real screen through Streamlit's AppTest with three tests:
1. Registering the target shows its reply.
2. A wrong response path shows "Response path not found".
3. After a successful test, saving without the checkbox is blocked.

It then checks that the test header value appears nowhere in either process's output (SC-004). A run makes about six model calls and costs a fraction of a cent.
