# Kestrel

Kestrel is a hosted red-teaming platform for tool-using AI agents. A user registers an agent endpoint (a URL plus optional headers), Kestrel runs adaptive attacks against it, judges the outcomes with hard evidence where possible, and produces a report mapped to the OWASP LLM Top 10 with a risk score. It's built for people who made an agent with Cursor, Claude Code or Lovable and haven't done any security testing.

**Status**: feature 001 is done. You can register an agent, test the connection, and save, edit and delete targets. Attacks, judging and reports come in later features. The project's rules are in the [constitution](.specify/memory/constitution.md).

## Run it on your own machine

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# terminal 1: the API (PowerShell: $env:KESTREL_MODE="local")
KESTREL_MODE=local uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000

# terminal 2: the screen, at http://localhost:8501
uv run streamlit run ui/app.py
```

`KESTREL_MODE=local` matters. Without it, Kestrel assumes it runs on a server and refuses agents on `localhost` or a private network.

Saved targets live in `data/kestrel.db` under the repo root. Other settings are listed in [.env.example](.env.example).

## Your encryption key

Kestrel encrypts auth header values with a key. On first start, the API creates `~/.kestrel/secret.key` and logs where it is. **Back that file up.** Without it, saved header values can't be read, and you'll have to type them in again; everything else about your targets is kept.

To manage the key yourself, set `KESTREL_SECRET_KEY` instead. Do that on a server, where a generated file may not survive a redeploy.

## Tests

```bash
uv run pytest                    # unit and integration tests: offline, no keys, no cost
uv run pytest -m e2e             # end-to-end tests against the sacrificial HS-code target
uv run --directory targets/hs_code pytest   # the target's own smoke tests
```

The end-to-end tests need `OPENROUTER_API_KEY`, because the [sacrificial HS-code target](targets/hs_code/README.md) makes real model calls. A run costs a fraction of a cent. Without the key, the tests are skipped.

## More

- [Quickstart and manual checks](specs/001-register-target/quickstart.md)
- [Feature 001 spec, plan and tasks](specs/001-register-target/)
