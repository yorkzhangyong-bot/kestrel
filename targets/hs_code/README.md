# Sacrificial HS-code target

A small FastAPI app that Kestrel's end-to-end tests attack. It wraps the HS-6 classifier from CargoLint, using files copied unchanged and listed in [PROVENANCE.md](PROVENANCE.md). It's test support only: Kestrel never offers it to users, and later features will add deliberately vulnerable parts, such as a fake email tool and canary tokens.

Retrieval is keyword-only (BM25) instead of CargoLint's vector search, so its HS-6 suggestions are rough. That's fine for a target whose job is to be attacked.

## Start it

From the repo root:

```bash
uv sync --project targets/hs_code     # first time only

# PowerShell: $env:HS_TARGET_API_KEY="test-key-123"; $env:OPENROUTER_API_KEY="sk-or-..."
HS_TARGET_API_KEY=test-key-123 OPENROUTER_API_KEY=sk-or-... \
  uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001
```

| Variable | Required | Meaning |
|---|---|---|
| `HS_TARGET_API_KEY` | yes | The only accepted `X-API-Key` value. The app won't start without it. |
| `OPENROUTER_API_KEY` | for replies | The model key CargoLint uses. Without it, `/chat` answers 502. |
| `CARGOLINT_CHAT_MODEL` | no | The model, `openai/gpt-4o-mini` by default. |

`GET /health` needs no key. `POST /chat` takes `{"message": "..."}` with the `X-API-Key` header and answers `{"reply": "..."}`. The full contract is in [specs/001-register-target/contracts/hs-code-target.md](../../specs/001-register-target/contracts/hs-code-target.md).

## Register it in Kestrel

The form's defaults already match:

| Field | Value |
|---|---|
| Endpoint URL | `http://127.0.0.1:8001/chat` |
| Method | POST |
| Auth header | `X-API-Key`, with the value of `HS_TARGET_API_KEY` |
| Request body template | `{"message": "{{prompt}}"}` |
| Response path | `$.reply` |

## Tests

```bash
uv run --directory targets/hs_code pytest
```

These smoke tests make no model calls: CargoLint's own `FakeRawClient` stands in for the model.
