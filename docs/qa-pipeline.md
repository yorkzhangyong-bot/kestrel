# QA pipeline

The QA pipeline runs on every pull request to `master` ([.github/workflows/qa.yml](../.github/workflows/qa.yml)).
It is a set of gates: a PR should not merge until they pass. It changes no feature code — it only checks it.

## Gates

| Job | What it does | Fails when |
| --- | --- | --- |
| **traceability** | [scripts/check_traceability.py](../scripts/check_traceability.py) reads the feature's `specs/<nnn>-*/spec.md` (feature inferred from the branch prefix, e.g. `005`), collects every `FR-nnn`/`SC-nnn`, and checks each is referenced somewhere under `tests/`. | Any requirement id has no test that mentions it. |
| **quality** | `uv sync`, then `ruff check src ui tests`, `mypy src`, `pytest tests/unit tests/integration` with coverage on `src`, plus `gitleaks` and `pip-audit`. | A lint or test failure; line coverage **below 85%**; a secret in the diff/history; a **new** known-vulnerable dependency. |
| **mutation** | Needs **quality**. Runs `mutmut` on the `src/*.py` files changed in the PR (using coverage so only covering tests run per mutant) and computes the kill score. | Mutation score **below 70%**. Skips (and passes) when the PR changes no `src` files. |
| **review** | Needs **mutation**. The [Claude Code Action](https://github.com/anthropics/claude-code-action) (`anthropics/claude-code-action@v1`) reviews the PR against the checklist and feature spec with full-repo access (it may read any file and run `uv run pytest tests/unit -q`), then posts one PR comment ending in `VERDICT: PASS`/`FAIL`; a follow-up step enforces the verdict. | The posted comment ends in `VERDICT: FAIL` (at least one **severe** finding). A review that cannot run does not block. |
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
model, and no experience-store writes outside the attack flow. The Evidence rules require every finding to quote
its exact `file:line` and to end the comment with the `VERDICT:` line the gate reads.

## The review gate (Claude Code Action)

Gate 4 runs the official [Claude Code GitHub Action](https://github.com/anthropics/claude-code-action)
(`anthropics/claude-code-action@v1`) with **full access to the checked-out repository**: it reads
`.github/review/checklist.md` and the feature spec, may read any other file to gather evidence, and may run
`uv run pytest tests/unit -q`. It posts exactly one PR comment listing findings with a severity
(`severe`/`major`/`minor`/`possible`), each quoting the exact `file:line` evidence the Evidence rules require, and
ends with a line `VERDICT: PASS` or `VERDICT: FAIL`.

A follow-up step reads that comment (via the `gh` CLI with `GITHUB_TOKEN`) and fails the job only when it contains
`VERDICT: FAIL` — at least one severe finding — so the gate blocks on severe only; a review that cannot run does
not block. The gate needs the `ANTHROPIC_API_KEY` secret. **OpenRouter is no longer used for the review.**

The earlier standalone reviewer, [scripts/ai_review.py](../scripts/ai_review.py) — which called an OpenRouter model
over a redacted diff — is **deprecated** and no longer wired into CI; it and its redaction tests are kept for
reference.

Treat the AI review as a second pair of eyes, not an authority: confirm its findings before acting on them.

## Repository secrets

Set these four in **Settings → Secrets and variables → Actions** (`GITHUB_TOKEN` is provided automatically):

| Secret | Used by | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | review | Authenticates the Claude Code Action's review. Without it the review cannot run and the gate does not block. |
| `SMTP_USER` | notify | SMTP username / sender address for the failure email. |
| `SMTP_PASS` | notify | SMTP password or app password. |
| `NOTIFY_EMAIL` | notify | Recipient of the failure email. |

The notify job assumes Gmail SMTP (`smtp.gmail.com:465`, TLS). Point `server_address`/`server_port` in the
workflow at another provider if you are not using Gmail.
