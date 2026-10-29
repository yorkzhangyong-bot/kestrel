# Feature Specification: Human-Approved Spec Workflow

**Feature Branch**: `006-human-approved-spec`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Feature 006: human-approved spec workflow. Goal: no feature implementation starts until a human has approved its specification on GitHub."

## Clarifications

### Session 2026-10-29

- Q: Should an implementation PR's reference to its merged spec PR be enforced by CI, or a reviewed convention? → A: Enforce in CI — the traceability job fails an implementation PR whose description lacks a `Spec-PR: #<n>` line.
- Q: Which files should the spec-mode check read when validating a feature's IDs and orphan references? → A: The whole feature directory (`spec.md`, `plan.md`, `tasks.md`, and any contracts).
- Q: What counts as a well-formed requirement identifier? → A: `FR-###` / `SC-###` with a zero-padded three-digit number (e.g. FR-001); gaps in the numbering are allowed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A human approves each spec before implementation (Priority: P1)

The repository owner wants assurance that no implementation work reaches `master` until they have reviewed and approved the feature's specification on GitHub. The author runs the Spec Kit flow, commits the spec artifacts on a feature branch, and opens a **spec-only** pull request (changes confined to `specs/` and `docs/`). The owner reviews the spec, requests changes or approves, and merges. Only after the spec PR is merged does the author move on to plan, tasks, and implementation.

**Why this priority**: This is the whole point of the feature — the approval gate that stops work from starting on an unapproved direction. Without it, nothing else matters.

**Independent Test**: Open a pull request that changes only `specs/` and `docs/`. Confirm the pipeline runs the lightweight spec path (not the full code gates) and that `master`'s protection blocks the merge until a code owner approves.

**Acceptance Scenarios**:

1. **Given** a feature branch whose changes are confined to `specs/` and `docs/`, **When** a pull request to `master` is opened, **Then** the pipeline runs the spec-mode requirement check and the spec review, and does not run the quality gate or the requirement-to-test traceability check.
2. **Given** a spec pull request with all checks green, **When** no code owner has submitted an approving review, **Then** branch protection blocks the merge.
3. **Given** a spec pull request with a code owner's approving review and green checks, **When** it is merged, **Then** that spec is the approved baseline for the feature and implementation may begin.

---

### User Story 2 - Spec-mode validation catches malformed or inconsistent requirement IDs (Priority: P2)

The author and owner want the spec's requirement identifiers to be clean before approval, so later traceability (requirement → test) rests on a sound baseline. On a spec-only PR the pipeline validates every `FR-nnn` and `SC-nnn` identifier.

**Why this priority**: A spec approved with duplicate or dangling IDs quietly breaks the downstream traceability gate; catching it at the spec stage is cheap, catching it later is not.

**Independent Test**: Run the spec-mode check on a spec with a duplicate `FR` ID and on one that references an undefined ID; both fail with a clear message. A clean spec passes.

**Acceptance Scenarios**:

1. **Given** a spec where two requirements are given the same identifier, **When** the spec-mode check runs, **Then** it fails and names the duplicated identifier.
2. **Given** a spec that references a requirement identifier which is defined nowhere, **When** the spec-mode check runs, **Then** it fails and names the orphan reference.
3. **Given** a spec with well-formed, unique identifiers and no orphan references, **When** the spec-mode check runs, **Then** it passes.

---

### User Story 3 - Implementation PRs cannot silently rewrite the approved spec (Priority: P2)

After a spec is approved, implementation pull requests must stay faithful to it. If an implementation PR (one that changes code) also edits a spec file, it must openly acknowledge the change; otherwise the approved spec could drift during implementation without anyone approving the drift.

**Why this priority**: The approval gate (US1) is only meaningful if the approved artifact cannot be edited unnoticed in a later code PR.

**Independent Test**: Open an implementation PR that changes a file under `src/` and a spec file with no acknowledgment; the traceability job fails. Add the acknowledgment line to the PR description; it passes. An implementation PR that changes code but no spec file is unaffected.

**Acceptance Scenarios**:

1. **Given** a pull request that changes both a file under `src/` and a spec file, **When** the PR description has no `spec-change:` line, **Then** the traceability job fails and explains why.
2. **Given** the same pull request with a `spec-change: <reason>` line in its description, **When** the traceability job runs, **Then** that check passes.
3. **Given** an implementation pull request that changes code but no spec file, **When** the traceability job runs, **Then** no spec-change acknowledgment is required.
4. **Given** an implementation pull request whose description has no `Spec-PR: #<n>` line, **When** the traceability job runs, **Then** it fails for the missing spec-PR reference.

---

### User Story 4 - The cycle is documented and the protection is reproducible (Priority: P3)

A contributor needs to follow the workflow without tribal knowledge, and the owner needs to reproduce the exact GitHub branch-protection settings by hand (the platform does not let a repository set its own protection).

**Why this priority**: The enforcement works without docs, but adoption and correct manual setup depend on them.

**Independent Test**: A new contributor follows `README` and `docs/qa-pipeline.md` to run one full cycle; the owner applies `docs/branch-protection.md` in GitHub and observes the required behaviour.

**Acceptance Scenarios**:

1. **Given** the README and `docs/qa-pipeline.md`, **When** a contributor reads them, **Then** they can name each step of the cycle: specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge.
2. **Given** `docs/branch-protection.md`, **When** the owner applies the listed settings in GitHub, **Then** `master` requires a pull request, at least one code-owner approval, and the traceability, quality, and review checks.

---

### Edge Cases

- **A required check that is skipped must still report success.** On a spec-only PR the quality gate does not do its work; but because it is a *required* status check, it must still report a successful result, or branch protection will wait forever on a check that never ran.
- **A spec-only PR that also touches non-code config** (for example a workflow file under `.github/`) is still classified spec-only: classification depends only on the absence of `src/`, `tests/`, `ui/`, and `scripts/` changes.
- **A docs-only PR** (no spec files, no code) takes the spec path; the spec-mode check has nothing to validate and passes.
- **An implementation PR that references no spec PR**: the traceability job fails it for the missing `Spec-PR: #<n>` line (FR-009), alongside the spec-change acknowledgment check (FR-010).
- **Bootstrap**: this workflow governs features from 006 onward; it is not applied retroactively to the already-merged features 001–005.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Spec Kit artifacts for a feature (`specs/<nnn>-*/spec.md`, `plan.md`, `tasks.md`, and any research or contracts files) MUST be delivered as a spec-only pull request before any `src/` or `tests/` changes for that feature.
- **FR-002**: The pipeline MUST classify a pull request as **spec-only** when it changes no files under `src/`, `tests/`, `ui/`, or `scripts/`.
- **FR-003**: On a spec-only pull request, the pipeline MUST run a spec-mode requirement check over the feature's directory (`spec.md`, `plan.md`, `tasks.md`, and any contracts) verifying that every `FR`/`SC` identifier is well-formed (the prefix followed by a zero-padded three-digit number, e.g. `FR-001`), is unique across the feature (no duplicate definitions), and that no referenced `FR`/`SC` identifier is undefined (no orphan references). Gaps in the numbering are allowed.
- **FR-004**: On a spec-only pull request, the pipeline MUST run a specification review against a documented spec review standard (`.github/review/spec-checklist.md`) covering ambiguity, missing or weak success criteria, untestable requirements, and conflicts with the constitution; a severe finding MUST block the merge.
- **FR-005**: On a spec-only pull request, the `quality` job reports success without running its heavy steps (lint, type check, tests, coverage, secret and dependency scans), and the full requirement-to-test traceability check is replaced by the spec-mode check.
- **FR-006**: Every required status check (traceability, quality, review) MUST report a result on every pull request — reporting success when it is intentionally skipped — so branch protection is never left waiting on a check that did not run.
- **FR-007**: The repository MUST designate the repository owner as the code owner for `specs/` via a `CODEOWNERS` file.
- **FR-008**: Merging to `master` MUST require a pull request, at least one approving review from a code owner, and passing required status checks for the traceability, quality, and review jobs.
- **FR-009**: An implementation pull request (one that changes files under `src/`, `tests/`, `ui/`, or `scripts/`) MUST reference the merged spec pull request for its feature with a `Spec-PR: #<n>` line in its description; the traceability job MUST fail an implementation pull request whose description lacks this line.
- **FR-010**: If a pull request changes a spec file in the same pull request as a `src/` change, the traceability job MUST fail unless the pull request description contains a `spec-change:` line.
- **FR-011**: As a specific case of FR-010, an implementation pull request MUST NOT modify a spec's `FR`/`SC` identifiers without a `spec-change:` note acknowledging the change.
- **FR-012**: The project documentation (README and `docs/qa-pipeline.md`) MUST describe the full cycle: specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge.
- **FR-013**: The repository MUST provide a branch-protection guide (`docs/branch-protection.md`) listing the exact GitHub settings to apply manually, because branch protection cannot be configured from within the repository.
- **FR-014**: The spec-mode requirement check MUST be implemented as a reusable tool (`scripts/check_spec.py`) with unit tests.

### Key Entities

- **Spec-only pull request**: A pull request whose changes touch no code directories (`src/`, `tests/`, `ui/`, `scripts/`) — in practice confined to `specs/` and `docs/`. It is the unit a human approves before implementation.
- **Implementation pull request**: A pull request that changes code to build a previously approved feature; it references its spec PR and must acknowledge any spec edit it carries.
- **Requirement identifier**: An `FR-nnn` or `SC-nnn` token defined in a spec and referenced across the spec, plan, tasks, and (later) tests.
- **Spec review standard**: The checklist (`.github/review/spec-checklist.md`) the spec review applies — ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts.
- **Code owner**: The repository owner responsible, via `CODEOWNERS` and branch protection, for approving specs and all merges to `master`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a spec-only pull request the quality gate's substantive work (lint, type check, tests, coverage, secret and dependency scans) does not run; the PR's substantive checks are the spec-mode requirement check and the spec review.
- **SC-002**: 100% of specs containing a duplicate `FR`/`SC` identifier or an orphan reference are rejected by the spec-mode check.
- **SC-003**: 100% of pull requests that edit a spec file alongside code without a `spec-change:` note are rejected by the traceability job.
- **SC-004**: No change reaches `master` without a code owner's approving review and passing required checks (zero unapproved merges) — this guarantee holds once the owner has applied the settings in `docs/branch-protection.md`.
- **SC-005**: A contributor can execute the full cycle using only the README and `docs/qa-pipeline.md`, and the owner can reproduce the required branch protection using only `docs/branch-protection.md`.
- **SC-006**: The spec-mode check tool has unit tests covering well-formed identifiers, duplicate identifiers, orphan references, and a clean spec that passes unchanged.
- **SC-007**: 100% of implementation pull requests whose description lacks a `Spec-PR: #<n>` reference line are rejected by the traceability job.

## Assumptions

- The single code owner is `@ilikeandroid` (the human reviewer account); `CODEOWNERS` assigns `specs/` (and, through branch protection, `master`) to that owner. The owner differs from the PR author `@yorkzhangyong-bot`, because GitHub does not count a PR author's own review toward a Code Owners requirement.
- The implementation PR's spec-PR reference (FR-009) uses a `Spec-PR: #<n>` line in the pull request description and is enforced by the traceability job, not only by human review.
- Branch protection and `CODEOWNERS` enforcement are GitHub platform features the owner applies manually (documented in `docs/branch-protection.md`); the repository cannot set them programmatically.
- The existing four-gate QA pipeline from feature 005 (traceability, quality, Claude Code review, notify) is the basis; this feature adds the spec-only path and the spec-change rule to it rather than replacing it.
- The `spec-change:` line lives in the pull request description (available to CI as the PR body), not in a commit message.
- This workflow governs features from 006 onward and is not applied retroactively to features 001–005.

## Out of Scope

- GitHub Environments approval pauses (deployment-style manual approval gates).
- Automatic pull-request creation; authors open spec and implementation PRs by hand.
- Any change to the four existing merged features (001–005) to fit this workflow.
