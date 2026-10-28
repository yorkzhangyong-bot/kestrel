# QA pipeline

The QA pipeline runs on every pull request to `master` ([.github/workflows/qa.yml](../.github/workflows/qa.yml)).
It is a set of gates: a PR should not merge until they pass. It changes no feature code — it only checks it.

## Gates

| Job | What it does | Fails when |
| --- | --- | --- |
| **traceability** | [scripts/check_traceability.py](../scripts/check_traceability.py) reads the feature's `specs/<nnn>-*/spec.md` (feature inferred from the branch prefix, e.g. `005`), collects every `FR-nnn`/`SC-nnn`, and checks each is referenced somewhere under `tests/`. | Any requirement id has no test that mentions it. |
| **quality** | `uv sync`, then `ruff check src ui tests`, `mypy src`, `pytest tests/unit tests/integration` with coverage on `src`, plus `gitleaks` and `pip-audit`. | A lint or test failure; line coverage **below 85%**; a secret in the diff/history; a **new** known-vulnerable dependency. |
| **mutation** | Needs **quality**. Runs `mutmut` on the `src/*.py` files changed in the PR (using coverage so only covering tests run per mutant) and computes the kill score. | Mutation score **below 70%**. Skips (and passes) when the PR changes no `src` files. |
| **review** | Needs **traceability** and **quality**. [scripts/ai_review.py](../scripts/ai_review.py) sends the review checklist, the feature spec, and the PR diff to an OpenRouter model, then posts the findings as a PR comment. | A finding is graded **severe**. A model that cannot be reached posts an "unavailable" comment and does **not** block (exit 0). |
| **notify** | Runs only if any job failed. Emails the failed job names and the first error lines (via `dawidd6/action-send-mail`). | — (best effort; never gates the PR). |

Two deliberate, documented exceptions keep the quality gate meaningful on a codebase that predates it, without
touching feature code:

- **`mypy src` is advisory** (`continue-on-error`). It runs over all of `src` and reports type issues, but does not
  block yet, because there is pre-existing type debt in the core modules (store, experience store, attack graph,
  API, address guard). New code should type-check cleanly; tighten this to blocking once the backlog is cleared.
- **`pip-audit` allowlists known advisories.** The `chromadb` advisories currently have no fix version and
  `chromadb` is a stack-pinned dependency (Principle X), so their IDs are passed to `--ignore-vuln`. The gate still
  fails on any **new** vulnerability. Remove the ignores when `chromadb` ships a fix.

The review standard the AI reviewer applies is [.github/review/checklist.md](../.github/review/checklist.md): the
constitution principles, ten checks (requirement fidelity, real APIs, dependency provenance, secrets, input/output
handling, authorization, error handling, failure-path tests, non-weakened CI, architecture fit), and three
project rules treated as severe — no raw HTML in the report renderer, no target name/URL/auth header sent to any
model, and no experience-store writes outside the attack flow. The reviewer switches to a stricter bar when the
diff touches `src/kestrel/attack`, `src/kestrel/secrets.py`, or `src/kestrel/report/render.py`.

## The review model and its limits

The reviewer calls OpenAI's `openai/gpt-5.4-mini` via OpenRouter. The review is deliberately advisory — a second
pair of eyes, not a gate on its own:

- The PR diff is truncated (~60k characters) to bound cost and latency. On a very large PR the reviewer sees only
  the first part of the diff.
- On any error or HTTP 429 the script retries twice with backoff. If it still cannot run, it posts a comment
  saying the review was unavailable and exits 0 — an unreachable model never blocks a merge.
- Only a **severe** finding fails the job. `major`/`minor` findings are informational and appear in the PR comment.
- The model prompt contains only the checklist, the feature spec, and the diff. Environment variables and files
  outside the diff and the spec are never sent.
- Before they are sent, the diff and the spec are **redacted**: OpenAI/OpenRouter keys (`sk-…`, `sk-or-…`), GitHub
  tokens (`ghp_`/`gho_`/`github_pat_`), AWS keys (`AKIA…`), `Authorization: Bearer` tokens, any `api_key`/`token`/
  `password`/`secret` value assigned with `=` or `:`, and `user:password@` URLs all become `[REDACTED]`. Diff hunks
  for `.env` and `.env.*` files are dropped entirely.

Treat the AI review as a second pair of eyes, not an authority: confirm its findings before acting on them.

## Repository secrets

Set these four in **Settings → Secrets and variables → Actions** (`GITHUB_TOKEN` is provided automatically):

| Secret | Used by | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | review | Authenticates the OpenRouter call for the AI review. Without it, the review posts "unavailable" and passes. |
| `SMTP_USER` | notify | SMTP username / sender address for the failure email. |
| `SMTP_PASS` | notify | SMTP password or app password. |
| `NOTIFY_EMAIL` | notify | Recipient of the failure email. |

The notify job assumes Gmail SMTP (`smtp.gmail.com:465`, TLS). Point `server_address`/`server_port` in the
workflow at another provider if you are not using Gmail.
