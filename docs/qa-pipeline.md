# QA pipeline

The QA pipeline runs on every pull request to `master` ([.github/workflows/qa.yml](../.github/workflows/qa.yml)).
It is a set of gates: a PR should not merge until they pass. It changes no feature code — it only checks it.

## Gates

| Job | What it does | Fails when |
| --- | --- | --- |
| **classify** | Computes `spec_only` (true when the PR changes nothing under `src/`, `tests/`, `ui/`, `scripts/`) and exposes it to the other jobs; always succeeds, so the required jobs never skip (FR-006). | — (it only classifies). |
| **traceability** | On an **implementation PR**, [check_traceability.py](../scripts/check_traceability.py) checks every `FR-nnn`/`SC-nnn` in the feature spec is referenced under `tests/`, **and** enforces the implementation-PR rules (a `Spec-PR: #<n>` line; a `spec-change:` note when a spec file changes alongside `src/`). On a **spec-only PR** it runs [check_spec.py](../scripts/check_spec.py) instead (ids well-formed, unique, no orphan references across the feature dir; ids inside code spans are ignored). | A requirement id with no test; a missing `Spec-PR:` or required `spec-change:` line; or a malformed/duplicate/orphan id. |
| **quality** | On an implementation PR: `uv sync`, `ruff check src ui tests`, `mypy src`, `pytest … --cov=src` (≥85%), `gitleaks`, `pip-audit`. **On a spec-only PR it reports success without running these** (FR-005). | A lint or test failure; coverage **below 85%**; a secret; a **new** known-vulnerable dependency. (Never on a spec-only PR.) |
| **review** | Needs **quality**. The [Claude Code Action](https://github.com/anthropics/claude-code-action) (`anthropics/claude-code-action@v1`) reviews against [.github/review/checklist.md](../.github/review/checklist.md) on code PRs or [.github/review/spec-checklist.md](../.github/review/spec-checklist.md) on spec-only PRs, then posts one PR comment ending in `VERDICT: PASS`/`FAIL`; a follow-up step enforces the verdict. | The posted comment ends in `VERDICT: FAIL` (at least one **severe** finding). A review that cannot run does not block. |
| **notify** | Runs only if any job failed. Emails the failed job names and the first error lines (via `dawidd6/action-send-mail`). | — (best effort; never gates the PR). |

> Mutation testing was dropped from CI because its runtime exceeded 6 hours; run it locally with `uv run mutmut run` when needed.

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

## The human-approved spec workflow

No feature implementation reaches `master` until a human has approved its specification (feature 006). The cycle:

```text
specify -> clarify -> spec PR (specs/ + docs/ only) -> human approval -> merge
        -> plan / tasks / implement -> implementation PR (Spec-PR: #n) -> four gates -> human merge
```

- **Spec-only PR** — the Spec Kit artifacts under `specs/<nnn>-*/` are opened as a PR that touches no code
  directory. `classify` marks it spec-only; `traceability` runs the spec-mode check; `quality` reports success
  without running; `review` uses the spec checklist. A code owner must approve before it merges.
- **Implementation PR** — references its merged spec PR with a `Spec-PR: #<n>` line (enforced by `traceability`);
  and if it edits a spec file alongside a `src/` change it must carry a `spec-change: <reason>` line in the
  description. Both lines live in the PR description.
- **Human approval** is platform-enforced: [.github/CODEOWNERS](../.github/CODEOWNERS) assigns `specs/` (and the
  repo) to the reviewer `@ilikeandroid` — deliberately **not** the PR author `@yorkzhangyong-bot`, since GitHub
  does not count a PR author's own review. Branch protection (manual) requires a PR, a code-owner approval, and the
  `traceability`/`quality`/`review` checks; see [docs/branch-protection.md](branch-protection.md). The approval
  guarantee holds only once the owner has applied those settings.

## The review gate (Claude Code Action)

Gate 3 runs the official [Claude Code GitHub Action](https://github.com/anthropics/claude-code-action)
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
