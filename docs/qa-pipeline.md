# QA pipeline

The QA pipeline runs on every pull request to `master` ([.github/workflows/qa.yml](../.github/workflows/qa.yml)).
It is a set of gates: a PR should not merge until they pass. It changes no feature code — it only checks it.

## Gates

| Job | What it does | Fails when |
| --- | --- | --- |
| **classify** | Computes `spec_only` (true when the PR changes nothing under `src/`, `tests/`, `ui/`, `scripts/`) and exposes it to the other jobs; always succeeds, so the required jobs never skip (FR-006). | — (it only classifies). |
| **traceability** | On an **implementation PR**, [check_traceability.py](../scripts/check_traceability.py) checks every `FR-nnn`/`SC-nnn` in the feature spec is referenced under `tests/`, **and** enforces the implementation-PR rules: **any PR that changes `src/` or `ui/` must declare its spec provenance** — `Spec-PR: #<n>`, or the honest path below — regardless of branch name (`fix/*`, `chore/*`, `eval/*` are held to the same bar), plus a `spec-change:` note when a spec file changes alongside `src/`. The description and labels are read **live** from the platform (`gh pr view`) at evaluation time, never from the triggering event. A broken rule **fails the job** (the script's exit code is propagated, not masked by the `tee` log pipe). On a **spec-only PR** it runs [check_spec.py](../scripts/check_spec.py) instead (ids well-formed, unique, no orphan references across the feature dir; ids inside code spans are ignored). | A requirement id with no test; a missing or incomplete Spec-PR declaration or required `spec-change:` line; or a malformed/duplicate/orphan id. |
| **quality** | On an implementation PR: `uv sync`, `ruff check src ui tests`, `mypy src`, `pytest … --cov=src` (≥85%), `gitleaks`, `pip-audit`. **On a spec-only PR it reports success without running these** (FR-005). | A lint or test failure; coverage **below 85%**; a secret; a **new** known-vulnerable dependency. (Never on a spec-only PR.) |
| **review** | Needs **quality**. The [Claude Code Action](https://github.com/anthropics/claude-code-action) (`anthropics/claude-code-action@v1`) reviews against [.github/review/checklist.md](../.github/review/checklist.md) on code PRs or [.github/review/spec-checklist.md](../.github/review/spec-checklist.md) on spec-only PRs, then posts one PR comment ending in `VERDICT: PASS`/`FAIL`; a follow-up step enforces the verdict. | The posted comment ends in `VERDICT: FAIL` (at least one **severe** finding). A review that cannot run does not block. |
| **notify** | Runs only if any job failed. Emails the failed job names and the first error lines (via `dawidd6/action-send-mail`). | — (best effort; never gates the PR). |

> Mutation testing was dropped from CI because its runtime exceeded 6 hours; run it locally with `uv run mutmut run` when needed.

> **Feature-scoped traceability.** The gate is per-feature: it checks only the feature of the PR's branch, and a
> test reference counts for feature `<nnn>` only if it **names the feature** — a scoped token `<nnn>/FR-001` (or
> `<nnn>-FR-001`) anywhere, or a bare `FR-001` in a test file carrying a module-level `FEATURE = "<nnn>"` marker.
> This stops one feature's tests from accidentally "covering" another feature's same-numbered id. A requirement
> enforced outside unit tests (branch protection, `CODEOWNERS`, docs) can instead be justified in
> `specs/<nnn>-*/traceability.md` as a line `<nnn>/FR-00x: <justification>`. See
> [specs/006-human-approved-spec/traceability.md](../specs/006-human-approved-spec/traceability.md).

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
- **Implementation PR** — references its merged spec PR with a `Spec-PR: #<n>` line (enforced by `traceability`),
  or takes the honest path below; and if it edits a spec file alongside a `src/` change it must carry a
  `spec-change: <reason>` line in the description. These lines live in the PR description. A PR that changes only
  `tests/`, `scripts/`, `docs/` or `specs/` needs no `Spec-PR:` line at all — the rule is not evaluated for it.
- **Human approval** is platform-enforced: [.github/CODEOWNERS](../.github/CODEOWNERS) assigns `specs/` (and the
  repo) to the reviewer `@ilikeandroid` — deliberately **not** the PR author `@yorkzhangyong-bot`, since GitHub
  does not count a PR author's own review. Branch protection (manual) requires a PR, a code-owner approval, and the
  `traceability`/`quality`/`review` checks; see [docs/branch-protection.md](branch-protection.md). The approval
  guarantee holds only once the owner has applied those settings.

### The honest path for a refactor or bug-fix PR (FR-015–FR-024)

A PR that changes `src/` or `ui/` but implements no specification — a behaviour-preserving refactor, or a fix for
a bug in behaviour an approved spec already covers — has no spec PR to cite. Instead of forcing an admin-merge
with the check red, it declares, in its description:

```text
Spec-PR: none
Spec-PR-reason: refactor
```

or, naming the issue being fixed:

```text
Spec-PR: none
Spec-PR-reason: bugfix: #<issue>
```

and carries the matching pull-request label (`refactor` or `bugfix`, see
[docs/branch-protection.md](branch-protection.md#labels-the-honest-spec-pr-path-fr-021)) — **not** the other one.
`traceability` accepts exactly that combination:

- Exactly one `Spec-PR:` line, whose value is exactly `none`.
- Exactly one `Spec-PR-reason:` line, `refactor` or `bugfix: #<issue>` (digits only).
- The label named after the reason keyword, and not the other reason's label.
- For `bugfix: #<issue>`: a live lookup (`gh api repos/<repo>/issues/<n>`) finds that number as an issue of this
  repository, open or closed — a pull-request number, an issue transferred elsewhere, a deleted or non-existent
  issue, or a failed lookup all fail closed.

Anything else fails closed, naming the failed condition and the three accepted forms. The numbered form
(`Spec-PR: #<n>`) is unchanged: labels beside it are ignored, and its number is never looked up. Every keyed line
must start in column 1 of the raw description — an indented, bulleted, quoted or emphasised line, or one inside a
one-line `<!-- ... -->` comment, is ordinary text, not a declaration (a multi-line comment whose own line starts
in column 1 still counts, since the gate reads the raw description, not the rendered view).

**The live read and the recheck.** The description and labels are fetched live (`gh pr view`) each time
`traceability` runs, never from the event that triggered it, so a manual re-run and overlapping runs all judge
the same, current state. A label added through the GitHub UI after the PR was opened, or a description edited
afterwards, does not by itself re-run anything in `qa.yml` — a separate, non-required **QA Recheck** workflow
(`.github/workflows/qa-recheck.yml`) re-runs only the `traceability` job of the newest pipeline run for the
current commit, and only when the PR **body** actually changed or the `refactor`/`bugfix` label was **added or
removed**; a title or base-branch edit, or any other label, re-runs nothing. `quality` and `review` never re-run
for these events.

**If the recheck cannot refresh it** — a pull request from a fork (read-only token), GitHub's cap of 50 re-runs
per workflow run, a QA run that does not complete within its 30-minute bound, or a re-run still refused when that
bound runs out — `traceability` keeps its last attempt's result, which may be stale, and the recheck posts one
fixed-text PR comment saying so and how to refresh it. **Owner's merge rule:** after such a comment, do not merge
until a `traceability` attempt that started after it has passed — a push, a manual re-run, or a later automatic
recheck re-run all count, since each reads the live state; on a fork PR, which gets no comment, refresh
`traceability` with a push or a manual re-run after the last body or label change before merging, whatever the
recheck shows.

**Rollout note.** A pull request already open when this gate merges carries `qa.yml` runs from the previous
script (which read the event payload, with no honest path); its recheck re-runs that old `traceability` job,
which fails closed — such a PR needs one push to pick up the new gate.

## The review gate (Claude Code Action)

Gate 3 runs the official [Claude Code GitHub Action](https://github.com/anthropics/claude-code-action)
(`anthropics/claude-code-action@v1`) with **full access to the checked-out repository**: it reads
`.github/review/checklist.md` and the feature spec, may read any other file to gather evidence, and may run
`uv run pytest tests/unit -q`. It posts exactly one PR comment listing findings with a severity
(`severe`/`major`/`minor`/`possible`), each quoting the exact `file:line` evidence the Evidence rules require, and
ends with a line `VERDICT: PASS` or `VERDICT: FAIL`.

A follow-up step reads that comment (via the `gh` CLI with `GITHUB_TOKEN`) and is **fail-closed**: it fails the job
both when the latest verdict is `VERDICT: FAIL` (at least one severe finding) **and** when no `VERDICT: PASS` comment
was posted at all. A reviewer that cannot run — a missing or expired `ANTHROPIC_API_KEY`, an API error, an outage —
therefore blocks the merge instead of passing vacuously on an empty comment. The gate needs the `ANTHROPIC_API_KEY`
secret. **OpenRouter is no longer used for the review.**

### Temporary bypass: `SKIP_AI_REVIEW`

While the reviewer account's `ANTHROPIC_API_KEY` has no API credit, the review gate can be bypassed with a
repository **variable** (not a secret): set `SKIP_AI_REVIEW` to `true` under **Settings → Secrets and variables →
Actions → Variables**. When it is `true`, the `review` job skips the Claude Code Action and the verdict step and
reports success with the log line `AI review BYPASSED via SKIP_AI_REVIEW (temporary)`. When the variable is unset
(or any other value) behaviour is unchanged — fail-closed on a missing verdict. **Delete the variable to turn the
gate back on.** The bypass is deliberately temporary; it exists only because the reviewer has no credit.

The Claude Code Action also refuses to run on a pull request that edits a workflow file (it requires the workflow to
match the version on the default branch), so **workflow-editing PRs can never be reviewed by the action** — they are
merged by an administrator, or with `SKIP_AI_REVIEW` set. See [branch-protection.md](branch-protection.md).

The earlier standalone reviewer, [scripts/ai_review.py](../scripts/ai_review.py) — which called an OpenRouter model
over a redacted diff — is **deprecated** and no longer wired into CI; it and its redaction tests are kept for
reference.

Treat the AI review as a second pair of eyes, not an authority: confirm its findings before acting on them.

## Repository secrets

Set these four in **Settings → Secrets and variables → Actions** (`GITHUB_TOKEN` is provided automatically):

| Secret | Used by | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | review | Authenticates the Claude Code Action's review. Without it the review cannot run, so the gate **blocks** (fail-closed) unless the `SKIP_AI_REVIEW` variable is set. |
| `SMTP_USER` | notify | SMTP username / sender address for the failure email. |
| `SMTP_PASS` | notify | SMTP password or app password. |
| `NOTIFY_EMAIL` | notify | Recipient of the failure email. |

The notify job assumes Gmail SMTP (`smtp.gmail.com:465`, TLS). Point `server_address`/`server_port` in the
workflow at another provider if you are not using Gmail.
