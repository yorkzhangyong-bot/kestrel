# Contract: Sacrificial HS-code target

A small FastAPI app in `targets/hs_code/` that wraps copied CargoLint classifier code ([research.md](../research.md) R11). It's test support only: Kestrel never offers it to users. The end-to-end tests start and stop it themselves (FR-027).

## Start-up

```bash
uv run --project targets/hs_code --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
```

| Variable | Required | Meaning |
|---|---|---|
| `HS_TARGET_API_KEY` | yes | The only accepted `X-API-Key` value. Start-up stops if it's missing, so the target never runs open (FR-026) |
| `OPENROUTER_API_KEY` | for replies | CargoLint's model key. Without it, `/chat` answers 502 |
| `CARGOLINT_CHAT_MODEL` | no | CargoLint's model setting; default `openai/gpt-4o-mini` |

## Endpoints

### `GET /health`

No authentication. 200 `{"status": "ok"}`. Tests use it to wait for start-up.

### `POST /chat`

| Request part | Value |
|---|---|
| Header `X-API-Key` | Must equal `HS_TARGET_API_KEY` |
| Body | `{"message": "<text>"}` |

| Status | Body | When |
|---|---|---|
| 200 | `{"reply": "<non-empty text>"}` | The classifier ran |
| 401 | `{"detail": "unauthorized"}` | Header missing or wrong. Checked before anything else, and no model call is made |
| 422 | FastAPI validation error | Body missing or `message` not a string |
| 502 | `{"detail": "model call failed"}` | The model provider failed or isn't configured |

Example replies:

```text
No HS-6 suggestion for "Hello": the description is too vague to classify.
```

```text
HS-6 suggestions for "Stainless steel vacuum flask, 500 ml":
1. 9617.00 Vacuum flasks and other vacuum vessels (confidence 0.82)
2. 7323.93 Table, kitchen or other household articles of stainless steel (confidence 0.31)
```

## Registering it in Kestrel

It works with the form defaults unchanged (FR-025):

| Field | Value |
|---|---|
| Endpoint URL | `http://127.0.0.1:8001/chat` |
| Method | POST |
| Auth header | `X-API-Key`: the value of `HS_TARGET_API_KEY` |
| Request body template | `{"message": "{{prompt}}"}` |
| Response path | `$.reply` |
