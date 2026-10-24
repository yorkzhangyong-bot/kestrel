# Kestrel

Kestrel is a hosted red-teaming platform for tool-using AI agents. A user registers an agent endpoint (a URL plus optional headers), Kestrel runs adaptive attacks against it, judges the outcomes with hard evidence where possible, and produces a report mapped to the OWASP LLM Top 10 with a risk score. It's built for people who made an agent with Cursor, Claude Code or Lovable and haven't done any security testing.

**Status**: features 001–003 are done. You can register an agent, run a single-turn attack from the built-in library, or run a multi-turn adaptive attack driven by an attacker model, and read the judged result and the full conversation. The ChromaDB attack-pattern store and per-target memory (004), the OWASP report with risk score (005) and the A/B harness (006) come next. The project's rules are in the [constitution](.specify/memory/constitution.md).

> The built-in attack-prompt library (`src/kestrel/attacks/data/library.json`) is not yet populated; until it is, the attack routes report that no library is available and the end-to-end attack tests skip. See `specs/002-single-turn-attack/tasks.md` (T013).

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

## Running an attack

Once a target is saved, declare any **canary strings** you have placed in your agent (for example a secret marker in its system prompt). If a canary turns up in a reply, the attack is **confirmed** by hard evidence, with no model involved. Otherwise a **judge** model reads the attack and the reply and returns succeeded, failed or unclear — always marked "suspected", never confirmed.

The judge is optional:

- Set `KESTREL_JUDGE_API_KEY`, or reuse `OPENROUTER_API_KEY`, to turn it on. Pick the model with `KESTREL_JUDGE_MODEL` (default `google/gemini-3.8-flash`).
- Without a key, canary evidence still decides runs and judged runs end "unclear" rather than failing.
- Each judged run sends the attack and the (capped) reply to the model provider, so a run costs a fraction of a cent. The terms of service say this, and the judge never receives your auth header values.

### Single-turn or adaptive

The Attack panel offers two modes. **Single-turn** sends one library prompt (feature 002). **Adaptive** (feature 003) runs a short conversation: an attacker model opens from a library prompt, reads each reply and the judge's note, and adapts its next message until it succeeds or hits a cap.

- The attacker is a separate model, configured like the judge: `KESTREL_ATTACKER_MODEL` (default `deepseek/deepseek-v3.2`, a capable, inexpensive, comparatively unrestricted model), with `KESTREL_ATTACKER_API_KEY` falling back to `OPENROUTER_API_KEY`. Without an attacker key, adaptive mode is disabled; single-turn still works.
- Every adaptive run is bounded by three caps, whichever is reached first: turns (`KESTREL_ADAPTIVE_MAX_TURNS`, default 6), a token budget across all attacker and judge calls (`KESTREL_ADAPTIVE_TOKEN_BUDGET`, default 40000), and a wall-clock limit (`KESTREL_ADAPTIVE_TIME_LIMIT_S`, default 300). The run records which cap it hit, so a cutoff is never mistaken for the agent being safe. An adaptive run costs more than a single-turn one — up to a few cents — because it makes several model calls.
- Each run names the attacker model and the budget it used (Principle III). The full conversation is stored, masked, and shown turn by turn.
- **Terms version 3**: because an adaptive run also sends replies to the attacker model's provider, the terms now disclose this, and any target saved before this release must have its permission box ticked again before it can be attacked.

## Your encryption key

Kestrel encrypts auth header values with a key. On first start, the API creates `~/.kestrel/secret.key` and logs where it is. **Back that file up.** Without it, saved header values can't be read, and you'll have to type them in again; everything else about your targets is kept.

To manage the key yourself, set `KESTREL_SECRET_KEY` instead. Do that on a server, where a generated file may not survive a redeploy.

## Tests

```bash
uv run pytest                    # unit and integration tests: offline, no keys, no cost
uv run pytest -m e2e             # end-to-end tests against the sacrificial HS-code target
uv run --directory targets/hs_code pytest   # the target's own smoke tests
```

The end-to-end tests need `OPENROUTER_API_KEY`, because the [sacrificial HS-code target](targets/hs_code/README.md), the judge (feature 002) and the attacker model (feature 003) all make real model calls through OpenRouter. A run costs a fraction of a cent. Without the key, the tests are skipped.

## More

- [Quickstart and manual checks](specs/001-register-target/quickstart.md)
- [Feature 001 spec, plan and tasks](specs/001-register-target/)
- [Feature 002 spec, plan and tasks](specs/002-single-turn-attack/)
- [Feature 003 spec, plan and tasks](specs/003-adaptive-attack/)
