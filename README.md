# Kestrel

Kestrel is an autonomous red-teaming agent for tool-using AI agents. You register a target (any HTTP chat endpoint you own), pick an attack family, and Kestrel's attacker agent plans and runs a multi-turn attack against it: it sends messages, inspects the replies and any tool activity for hard evidence, judges each turn, and adapts its next move. Across runs it builds a memory of what worked on each target and reuses successful attack patterns. You don't chat with Kestrel; you configure it and watch the attacker's conversation with your target unfold turn by turn in the Streamlit UI. Built for vibe coders who ship agents with tools but have no security testing in place.

**Status**: features 001–005 are done. You can register an agent, run a single-turn attack from the built-in library, or run a multi-turn adaptive attack driven by an attacker model, and read the judged result and the full conversation. Kestrel learns from every run: a local ChromaDB store keeps attack patterns and per-target memory, and a warm run primes the attacker with what worked before. And it writes a report (005): an OWASP-mapped, fix-ready summary of a target's runs, with model-generated fix suggestions, in Markdown or HTML. The A/B harness (006) comes next. Every pull request runs a four-gate QA pipeline — traceability, quality (ruff, mypy, tests with coverage, gitleaks, pip-audit), a Claude Code review, and a failure notifier — described in [the QA pipeline docs](docs/qa-pipeline.md). The project's rules are in the [constitution](.specify/memory/constitution.md).

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

- The attacker is a separate model, configured like the judge: `KESTREL_ATTACKER_MODEL` (default `deepseek/deepseek-v4.1-flash`, a current, inexpensive, comparatively unrestricted DeepSeek model), with `KESTREL_ATTACKER_API_KEY` falling back to `OPENROUTER_API_KEY`. Without an attacker key, adaptive mode is disabled; single-turn still works. If an adaptive run reports the attacker answered with status 404, your OpenRouter account likely has a guardrail blocking that model — allow it, or point `KESTREL_ATTACKER_MODEL` at a model your account permits.
- Every adaptive run is bounded by three caps, whichever is reached first: turns (`KESTREL_ADAPTIVE_MAX_TURNS`, default 6), a token budget across all attacker and judge calls (`KESTREL_ADAPTIVE_TOKEN_BUDGET`, default 40000), and a wall-clock limit (`KESTREL_ADAPTIVE_TIME_LIMIT_S`, default 300). The run records which cap it hit, so a cutoff is never mistaken for the agent being safe. An adaptive run costs more than a single-turn one — up to a few cents — because it makes several model calls.
- Each run names the attacker model and the budget it used (Principle III). The full conversation is stored, masked, and shown turn by turn.
- **Terms version 3**: because an adaptive run also sends replies to the attacker model's provider, the terms now disclose this, and any target saved before this release must have its permission box ticked again before it can be attacked.

### Learning from every run

Every finished run is recorded in a local ChromaDB store next to the database (`data/chroma/`), so Kestrel stops starting from zero (feature 004):

- After each run Kestrel writes one **memory** record for that target — a one-line summary and safe metadata, never the reply text, the URL, or an auth value. A successful attack also becomes a shared, anonymised **pattern**. The attack library is seeded into the store at start-up.
- The Attack panel has a **Use prior experience** toggle (on by default). A warm run retrieves patterns similar to the current family, plus this target's own memory, and gives them to the attacker as hints; a cold run behaves exactly like feature 003. You can also give a target a one-line **purpose description** (no sensitive info) to orient the attacker from the first turn.
- A per-target **Profile** summarises what Kestrel has learned. Deleting a target also deletes its memory; the shared patterns stay.
- Tune it with `KESTREL_CHROMA_PATH` (default `data/chroma`), `KESTREL_EXPERIENCE_PATTERN_K` (default 5) and `KESTREL_EXPERIENCE_MEMORY_CAP` (default 10). Embeddings run locally through ChromaDB's built-in model — no embedding API, no cost.

## The report

The **Report** panel (after a target's Profile) turns a target's runs into an OWASP-mapped, fix-ready report you can read inline and download as Markdown or HTML (feature 005):

- A header names the target, its purpose, the attacker and judge models, and the token budget used. An **OWASP coverage** table maps Kestrel's attack families to their OWASP LLM Top 10 classes (LLM01 prompt injection, LLM06 excessive agency, LLM07 system prompt leakage) with run counts and results, and the report lists the seven classes it does not test, each with a reason.
- Each successful run becomes a **finding**: the winning attacker message, the hard evidence quoted verbatim (a canary match) or the judge's note marked "suspected", and a model-generated **fix suggestion**. Suggestions use the judge model and are cached per run, so regenerating a report does not call the model again.
- Generating a report is read-only: it starts no attack, sends nothing to the target, and writes nothing to the experience store (it only reads the memory and pattern counts for the limitations note). No URL, header or auth value ever appears in the output.

It is served by `GET /api/targets/{id}/report?format=md|html`, which reads the target's stored runs and turns. The only new dependency is `markdown-it-py` (the HTML is derived from the Markdown with raw HTML escaped), and the database moves to schema v5 — a `report_recommendations` cache; existing databases migrate automatically.

## Your encryption key

Kestrel encrypts auth header values with a key. On first start, the API creates `~/.kestrel/secret.key` and logs where it is. **Back that file up.** Without it, saved header values can't be read, and you'll have to type them in again; everything else about your targets is kept.

To manage the key yourself, set `KESTREL_SECRET_KEY` instead. Do that on a server, where a generated file may not survive a redeploy.

## Tests

```bash
uv run pytest                    # unit and integration tests: offline, no keys, no cost
uv run pytest -m e2e             # end-to-end tests against the sacrificial HS-code target
uv run --directory targets/hs_code pytest   # the target's own smoke tests
```

The end-to-end tests need `OPENROUTER_API_KEY`, because the [sacrificial HS-code target](targets/hs_code/README.md), the judge (feature 002) and the attacker model (feature 003) all make real model calls through OpenRouter. The first end-to-end run also downloads ChromaDB's default local embedding model (~80 MB) once, so it needs network that one time; afterwards it is cached and the offline `uv run pytest` never downloads it. A run costs a fraction of a cent. Without the key, the tests are skipped.

## More

- [Technical design](docs/technical-design.md)
- [QA pipeline](docs/qa-pipeline.md)
- [Quickstart and manual checks](specs/001-register-target/quickstart.md)
- [Feature 001 spec, plan and tasks](specs/001-register-target/)
- [Feature 002 spec, plan and tasks](specs/002-single-turn-attack/)
- [Feature 003 spec, plan and tasks](specs/003-adaptive-attack/)
- [Feature 004 spec, plan and tasks](specs/004-attack-pattern-memory/)
- [Feature 005 spec, plan and tasks](specs/005-owasp-report/)

## License

Kestrel is released under the MIT License. See [LICENSE](LICENSE).

**Third-party content**: the built-in attack-prompt library includes prompts from [Agentic Prompt-Injection Boundary Pairs](https://github.com/3nesdeniz/agentic-prompt-injection-boundary-pairs), licensed CC-BY-4.0.
