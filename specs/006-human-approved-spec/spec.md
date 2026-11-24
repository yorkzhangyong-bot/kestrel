# Feature Specification: Human-Approved Spec Workflow

**Feature Branch**: `006-human-approved-spec`

**Created**: 2026-10-29

**Amended**: 2026-11-24 — an honest Spec-PR path for refactor and bug-fix pull requests (Clarifications, Session 2026-11-24; FR-009 amended; FR-015–FR-023 and SC-008–SC-010 added)

**Status**: Draft

**Input**: User description: "Feature 006: human-approved spec workflow. Goal: no feature implementation starts until a human has approved its specification on GitHub."

## Clarifications

### Session 2026-10-29

- Q: Should an implementation PR's reference to its merged spec PR be enforced by CI, or a reviewed convention? → A: Enforce in CI — the traceability job fails an implementation PR whose description lacks a `Spec-PR: #<n>` line.
- Q: Which files should the spec-mode check read when validating a feature's IDs and orphan references? → A: The whole feature directory (`spec.md`, `plan.md`, `tasks.md`, and any contracts).
- Q: What counts as a well-formed requirement identifier? → A: `FR-###` / `SC-###` with a zero-padded three-digit number (e.g. FR-001); gaps in the numbering are allowed.

### Session 2026-11-24

Answers taken from the owner's written requirement (the roadmap Housekeeping item) and from the gate's own history; no live question was needed.

- Q: How does a pull request that implements no specification — a behaviour-preserving refactor, or a fix for a bug in behaviour an approved spec already covers — pass the Spec-PR rule honestly? → A: (owner) The gate accepts `Spec-PR: none` only together with a reason line whose value is `refactor` or `bugfix: #<issue>` and a pull-request label that matches the reason; everything else stays fail-closed (FR-015, FR-016). Until now the only ways past the rule were to cite a number that is not the PR's spec or to merge with the check red: the graph refactor PR #49 was admin-merged that way, and every bug fix that touches `src/` or `ui/` would fail the same way (a tests-only fix never meets the rule).
- Q: Which pull requests does the Spec-PR rule cover? → A: Any pull request that changes `src/` or `ui/`, on any branch, whatever its name — the rule the gate has enforced since 2026-11-10 (commit df9a65f); a tests-only, scripts-only, docs-only or spec-only pull request needs no `Spec-PR:` line. FR-009, SC-007, the Edge Cases and the PR-rules contract still said `src/`, `tests/`, `ui/` or `scripts/`; they are corrected to what the gate enforces.

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
4. **Given** an implementation pull request that changes `src/` or `ui/` and whose description has no `Spec-PR:` line at all, **When** the traceability job runs, **Then** it fails for the missing spec-PR declaration (FR-009).

---

### User Story 4 - The cycle is documented and the protection is reproducible (Priority: P3)

A contributor needs to follow the workflow without tribal knowledge, and the owner needs to reproduce the exact GitHub branch-protection settings by hand (the platform does not let a repository set its own protection).

**Why this priority**: The enforcement works without docs, but adoption and correct manual setup depend on them.

**Independent Test**: A new contributor follows `README` and `docs/qa-pipeline.md` to run one full cycle; the owner applies `docs/branch-protection.md` in GitHub and observes the required behaviour.

**Acceptance Scenarios**:

1. **Given** the README and `docs/qa-pipeline.md`, **When** a contributor reads them, **Then** they can name each step of the cycle: specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge.
2. **Given** `docs/branch-protection.md`, **When** the owner applies the listed settings in GitHub, **Then** `master` requires a pull request, at least one code-owner approval, and the traceability, quality, and review checks.

---

### User Story 5 - A refactor or bug-fix pull request passes the Spec-PR rule honestly (Priority: P2)

A contributor opens a pull request that changes application code but implements no specification: a behaviour-preserving refactor, or a fix for a bug in behaviour that an approved spec already covers. There is no spec pull request to cite, so until now the only ways past the Spec-PR rule were to cite a number that is not the PR's spec, or to have the owner merge with the check red (as the graph refactor PR #49 was). Instead, the contributor declares `Spec-PR: none` in the description, states the reason on its own line — `Spec-PR-reason: refactor`, or `Spec-PR-reason: bugfix: #<issue>` naming the issue being fixed — and puts the matching label (`refactor` or `bugfix`) on the pull request. The traceability job accepts exactly that combination and nothing less; the owner still reviews and approves the merge, and judges whether the reason is truthful.

**Why this priority**: The gate is only credible if every truthful pull request has a way to pass it; a rule that forces admin-merges with a red check trains everyone to ignore the check.

**Independent Test**: Open a pull request that changes a file under `src/` with `Spec-PR: none`, the reason line `Spec-PR-reason: refactor` and the `refactor` label; the traceability job passes. Remove the label, or the reason line, or change the reason to `bugfix: #12` while the label stays `refactor`; it fails each time, and each failure message names the accepted forms.

**Acceptance Scenarios**:

1. **Given** a pull request that changes `src/` or `ui/` whose description has `Spec-PR: none` and `Spec-PR-reason: refactor`, **When** the pull request carries the `refactor` label and not the `bugfix` label, **Then** the Spec-PR rule passes.
2. **Given** a pull request that changes `src/` or `ui/` whose description has `Spec-PR: none` and `Spec-PR-reason: bugfix: #<issue>` with a numeric issue, **When** the pull request carries the `bugfix` label and not the `refactor` label, **Then** the Spec-PR rule passes without looking the issue up.
3. **Given** `Spec-PR: none` with no reason line, or a reason line whose matching label is missing, or the other reason's label, or a malformed reason (for example `refactoring`, `bugfix`, `bugfix: 12`, or `refactor` followed by more words), **When** the traceability job runs, **Then** it fails, says which condition failed, and names the accepted forms.
4. **Given** a description with both a `Spec-PR: #<n>` line and a `Spec-PR:` line whose value starts with `none`, or a reason line next to a `Spec-PR: #<n>` line, or two reason lines, or — on the honest path — a second `Spec-PR:` line of any value beside `Spec-PR: none` (another `none`, `none because …`, `TBD`), **When** the traceability job runs, **Then** it fails as a conflicting or malformed declaration.
5. **Given** a pull request on the honest path (`Spec-PR: none`) that also edits a spec file beside a `src/` change, **When** the description has no `spec-change:` line, **Then** the traceability job fails on the spec-change rule exactly as it would for any implementation pull request (FR-010, FR-011).
6. **Given** a pull request whose Spec-PR rule failed, **When** the contributor adds the missing label or edits the description to add the reason line without pushing a commit, **Then** the pipeline runs again and the rule is re-evaluated against the description and labels read live at that moment (FR-018) — and a manual re-run of the earlier, failed run judges that same current state.
7. **Given** a pull request whose description carries a `Spec-PR: #<n>` line and neither a `Spec-PR:` line whose value starts with `none` nor a `Spec-PR-reason:` line, **When** the traceability job runs, **Then** it passes exactly as before this change, whatever labels the pull request carries and whatever other `Spec-PR:` values sit beside it.

---

### Edge Cases

- **A required check that is skipped must still report success.** On a spec-only PR the quality gate does not do its work; but because it is a *required* status check, it must still report a successful result, or branch protection will wait forever on a check that never ran.
- **A spec-only PR that also touches non-code config** (for example a workflow file under `.github/`) is still classified spec-only: classification depends only on the absence of `src/`, `tests/`, `ui/`, and `scripts/` changes.
- **A docs-only PR** (no spec files, no code) takes the spec path; the spec-mode check has nothing to validate and passes.
- **A pull request that changes `src/` or `ui/` and declares no spec provenance**: the traceability job fails it for the missing `Spec-PR:` line (FR-009) — `Spec-PR: #<n>`, or `Spec-PR: none` with a reason line and its label (FR-015) — alongside the spec-change acknowledgment check (FR-010). A pull request that changes only `tests/`, `scripts/`, `docs/` or `specs/` needs no `Spec-PR:` line, and a `Spec-PR:` declaration on such a pull request is not evaluated at all.
- **Both reason labels on one pull request**: `refactor` and `bugfix` together contradict each other; the honest path fails whichever reason the line gives (FR-016).
- **A reason label on a pull request that cites a spec PR**: a `refactor` or `bugfix` label beside `Spec-PR: #<n>` is not an error by itself — labels are consulted only when the declaration is `none` (FR-015). A *reason line* beside `Spec-PR: #<n>` is a conflict and fails (FR-016).
- **Two `Spec-PR: #<n>` lines, or an unrelated `Spec-PR:` value beside one**: unchanged — the numbered form is satisfied by the first numbered line, and a second number or a value such as `TBD` beside it has always been tolerated and still is; only a value starting with `none` or a reason line beside it is a conflict (FR-016). On the honest path the `Spec-PR:` line appears exactly once, with the value exactly `none` (FR-016).
- **The issue number**: `bugfix: #<issue>` is checked for form only (a `#` followed by digits), as `Spec-PR: #<n>` always has been; a closed, wrong or non-existent issue is for the reviewer to catch, not the gate (FR-015).
- **A label added, or the description edited, after the pull request was opened**: the pipeline runs again (FR-019), and every run — including a manual re-run of an older one — reads the description and labels live at evaluation time, never from the event that triggered it (FR-018); each run is the whole pipeline, so every required check reports on the latest run (FR-006).
- **Letter case**: like the existing `Spec-PR:` and `spec-change:` lines, the `none` value, the reason line's key and its keywords match regardless of case, and so do label names (GitHub label names are case-insensitive) (FR-017).
- **Extra words on a new-form line**: `Spec-PR: none because …` is not the `none` form — on the honest path the description carries exactly one `Spec-PR:` line and its value is exactly `none`, so that line, or any second `Spec-PR:` line beside `Spec-PR: none`, fails (FR-016); beside `Spec-PR: #<n>` a value starting with `none` is a conflict (FR-016). `Spec-PR-reason: refactor of the graph` is a malformed reason (FR-017). The numbered form keeps its existing grammar (text after the number has always been tolerated).
- **Line endings**: a description may arrive with Windows line endings (the platform's web form sends them); a trailing carriage return never makes a well-formed line malformed (FR-017).
- **Keyed lines inside an HTML comment or other markup**: the gate reads the raw description, exactly as today — a keyed line inside an HTML comment, a code block or any other markup counts like any other line (FR-017). A declaration the rendered view hides is the reviewer's to catch, as it has always been for the numbered form: the label is visible in the pull-request list, and the owner's approval is the control. The pull-request template keeps every example indented inside its comment, so a description built from it declares nothing by itself (FR-023).
- **A keyed line that does not start in column 1**: indented, bulleted (`- Spec-PR: none`), quoted or emphasised, it is ordinary text, not a declaration (FR-017).
- **A pull request created with its label** (`gh pr create --label refactor`): the platform fires `opened` and then `labeled`, so two runs start on the same commit; both read the live state, so both pass — unless the `opened` run reads before the label lands, in which case it fails, the notify job emails once, and the `labeled` run that follows is the newer, passing result (FR-018).
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
- **FR-009**: A pull request that changes files under `src/` or `ui/` — on any branch, whatever its name — MUST declare its spec provenance in its description with a `Spec-PR:` line of one of two forms: `Spec-PR: #<n>`, referencing the merged spec pull request for its feature, or `Spec-PR: none`, allowed only under the conditions of FR-015. The traceability job MUST fail such a pull request whose description carries no `Spec-PR: #<n>` line and no `Spec-PR:` line whose value starts with `none`, and one that carries both. A pull request that changes only `tests/`, `scripts/`, `docs/`, `specs/` or other non-application paths needs no `Spec-PR:` line. *(Amended 2026-11-24: the original text named `src/`, `tests/`, `ui/` or `scripts/`; the gate has enforced `src/` or `ui/` since 2026-11-10, and the `none` form is new.)*
- **FR-010**: If a pull request changes a spec file in the same pull request as a `src/` change, the traceability job MUST fail unless the pull request description contains a `spec-change:` line.
- **FR-011**: As a specific case of FR-010, an implementation pull request MUST NOT modify a spec's `FR`/`SC` identifiers without a `spec-change:` note acknowledging the change.
- **FR-012**: The project documentation (README and `docs/qa-pipeline.md`) MUST describe the full cycle: specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge.
- **FR-013**: The repository MUST provide a branch-protection guide (`docs/branch-protection.md`) listing the exact GitHub settings to apply manually, because branch protection cannot be configured from within the repository.
- **FR-014**: The spec-mode requirement check MUST be implemented as a reusable tool (`scripts/check_spec.py`) with unit tests.
- **FR-015**: The traceability job MUST accept `Spec-PR: none` on a pull request that changes `src/` or `ui/` only when all of the following hold: (a) the description carries exactly one `Spec-PR:` line in total and its value is exactly `none`; (b) it carries exactly one reason line, `Spec-PR-reason: <reason>`, whose value is exactly `refactor`, or `bugfix:` followed by optional spaces or tabs, `#` and one or more ASCII digits (`0`–`9`); (c) the pull request carries the label named after the reason keyword — `refactor` for `refactor`, `bugfix` for `bugfix: #<issue>` — and does not carry the other reason's label. The issue number is checked for form only; the job MUST NOT look it up.
- **FR-016**: In every other case the Spec-PR rule MUST fail (fail-closed). On the honest path the job MUST fail: a `Spec-PR:` line whose value starts with `none` but is not exactly `none` (`none because …`); a second `Spec-PR:` line of any value beside `Spec-PR: none` (another `none`, `TBD`, a number); `Spec-PR: none` with no reason line; two or more reason lines, identical or not; a malformed reason value; a reason line whose matching label is absent; the label of the other reason, alone or together with the matching one. On the numbered path the job MUST fail a `Spec-PR-reason:` line, or any `Spec-PR:` line whose value starts with `none`, beside `Spec-PR: #<n>` — a conflict; any other extra `Spec-PR:` value beside a numbered line keeps today's acceptance. The first failed condition, in the order of the PR-rules contract, is the one reported.
- **FR-017**: The new lines follow the grammar of the existing keyed lines: each is a whole line of the description that starts in column 1 — an indented, bulleted, quoted or emphasised line is ordinary text, not a keyed line; its key (`Spec-PR:`, `Spec-PR-reason:`) is followed by optional spaces or tabs and the value; and the key, the `none` value and the reason keywords match regardless of letter case. Unlike the numbered form, the `none` value and the reason value MUST be the whole remainder of their line (trailing spaces and a trailing carriage return aside), so extra words make the line malformed; the issue number is ASCII digits only. Label names are compared regardless of case. The gate reads the raw description, exactly as today: text inside an HTML comment or any other markup counts like any other line, for `Spec-PR:`, `Spec-PR-reason:` and `spec-change:` alike (a filter faithful to the platform's renderer would be a markdown parser, and other markup that hides text would count anyway). The `Spec-PR: #<n>` form and the `spec-change:` line keep their existing grammar unchanged.
- **FR-018**: The traceability job MUST read the pull request's description and labels live from the platform at evaluation time — never from the event that triggered the run — so a manual re-run of an earlier run and the overlapping runs of a pull request created with its label all judge the same, current state; when that read fails for any reason the job MUST treat the description as empty and the labels as none (fail closed). The read uses the job's own token, on a traceability job granted read permissions only. The Spec-PR rule itself MUST be evaluated as a pure function of the description text and the list of label names — unit-testable without GitHub, like the spec-change rule and the spec-mode check (FR-014).
- **FR-019**: The pipeline MUST run, and the traceability job re-evaluate the Spec-PR rule, when a pull request is opened, pushed to or reopened, when its title, description or base branch is edited (the platform's single "edited" event), and when a label is added or removed — so a declaration completed after opening counts without a new commit. Every required check reports on each such run (FR-006).
- **FR-020**: Every failure of the Spec-PR rule MUST say which condition failed and MUST name the accepted forms: `Spec-PR: #<n>`; `Spec-PR: none` with `Spec-PR-reason: refactor` and the `refactor` label; `Spec-PR: none` with `Spec-PR-reason: bugfix: #<issue>` and the `bugfix` label. Where a quoted example is the likely cause — a conflicting declaration, a second `Spec-PR:` line, a second reason line — the message MUST also say that every column-1 keyed line counts, also inside code blocks and HTML comments, so quoted examples must be indented.
- **FR-021**: The repository MUST provide the two labels `refactor` and `bugfix`, created by the owner by hand (labels, like branch protection, are not committed configuration), and `docs/branch-protection.md` MUST list them with their meaning next to the branch-protection settings.
- **FR-022**: A pull request on the honest path remains subject to every other rule unchanged: the spec-change rule (FR-010, FR-011) when it edits a spec file beside a `src/` change, the feature-scoped tests-traceability check (which depends on the branch's numeric prefix, not on the `Spec-PR:` line), the quality gate and the review; the spec-change rule itself is unchanged.
- **FR-023**: The project documentation MUST describe the honest path — `docs/qa-pipeline.md` (the accepted forms, the fail-closed cases, the live read and the re-run events), `docs/branch-protection.md` (the labels, FR-021), the project memory file `CLAUDE.md` (the Spec-PR rule a pull request must follow) and the pull-request template `.github/PULL_REQUEST_TEMPLATE.md` (both declaration forms with their labels, every example indented inside its HTML comment — a template example MUST never be a column-1 keyed line, since the gate reads the raw description, so the template itself declares nothing) — and the roadmap's Housekeeping item for this change moves to Done in the implementation pull request that ships the gate.

### Key Entities

- **Spec-only pull request**: A pull request whose changes touch no code directories (`src/`, `tests/`, `ui/`, `scripts/`) — in practice confined to `specs/` and `docs/`. It is the unit a human approves before implementation.
- **Implementation pull request**: A pull request that changes code to build a previously approved feature. When it changes `src/` or `ui/` it carries a Spec-PR declaration — the cited spec PR, or `none` with a reason and a label; a tests-only or scripts-only one needs no declaration — and it must acknowledge any spec edit it carries.
- **Spec-PR declaration**: The `Spec-PR:` line a pull request that changes `src/` or `ui/` must carry: `#<n>` cites the merged spec PR; `none` says the pull request implements no spec and is valid only with a reason line and its label.
- **Reason line and reason label**: `Spec-PR-reason: refactor` or `Spec-PR-reason: bugfix: #<issue>` in the description, paired with the pull-request label of the same name (`refactor`, `bugfix`). The label repeats the claim where the owner sees it — in the pull-request list, before the description is opened; the same author sets both, so the owner's approval, not the label, is the control.
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
- **SC-007**: 100% of pull requests that change `src/` or `ui/` whose description carries neither a `Spec-PR: #<n>` line nor a complete `Spec-PR: none` declaration (FR-015) are rejected by the traceability job. *(Amended 2026-11-24 with FR-009.)*
- **SC-008**: 100% of pull requests that change `src/` or `ui/` with `Spec-PR: none`, a valid reason line and the matching label pass the Spec-PR rule, and 100% of those with an incomplete, malformed or conflicting declaration (each case listed in FR-016) are rejected, with a failure message that names the accepted forms.
- **SC-009**: No pull request that the Spec-PR rule accepted before this change is rejected after it, with one deliberate exception: a description that also carries one of the new lines (a `Spec-PR:` value starting with `none`, or a `Spec-PR-reason:` line), which FR-016 rejects as a conflict. Every description with a `Spec-PR: #<n>` line and neither new line passes, whatever labels the pull request carries, and the rule's existing unit tests pass unchanged.
- **SC-010**: A label added or a description edited after opening re-evaluates the gate without a new commit, and a manual re-run of an earlier run judges the current state: the contributor sees a fresh, current check result on the same commit.

## Assumptions

- The single code owner is `@ilikeandroid` (the human reviewer account); `CODEOWNERS` assigns `specs/` (and, through branch protection, `master`) to that owner. The owner differs from the PR author `@yorkzhangyong-bot`, because GitHub does not count a PR author's own review toward a Code Owners requirement.
- A pull request that changes `src/` or `ui/` declares its spec provenance (FR-009) with a `Spec-PR:` line — `#<n>`, or `none` under FR-015 — in the pull request description, enforced by the traceability job, not only by human review.
- Branch protection and `CODEOWNERS` enforcement are GitHub platform features the owner applies manually (documented in `docs/branch-protection.md`); the repository cannot set them programmatically.
- The existing four-gate QA pipeline from feature 005 (traceability, quality, Claude Code review, notify) is the basis; this feature adds the spec-only path and the spec-change rule to it rather than replacing it.
- The `spec-change:` line lives in the pull request description (available to CI as the PR body), not in a commit message.
- This workflow governs features from 006 onward and is not applied retroactively to features 001–005.
- *(2026-11-24)* The reason line's key is `Spec-PR-reason:` — a key that cannot be mistaken for prose, unlike a bare `Reason:` — and the labels are named after the reason keywords, `refactor` and `bugfix`, rather than reusing the default `bug` issue label, so "matching" needs no mapping table.
- *(2026-11-24)* The honest path is not restricted by branch name, consistent with the Spec-PR rule firing on any branch: whether `refactor` is truthful for a given pull request is the owner's judgment at review, as it is for the number cited in `Spec-PR: #<n>`.
- *(2026-11-24)* The gate checks the issue number's form only: a lookup would prove that an issue exists, nothing about whether it describes the fix, and the `#<n>` form has never been verified either.
- *(2026-11-24)* Each description-edit, label-added or label-removed event runs the whole pipeline (quality and review included), because a partial run would let a skipped required job's success replace an earlier failure for the same commit. Cost and noise, accepted: a pull request created with its label fires `opened` and `labeled`, two runs on one commit (the `opened` run can read the state before the label lands, fail, and email once); once `SKIP_AI_REVIEW` is removed, every such event re-runs the paid AI review and a label toggle re-rolls its verdict. A verdict-only review on those events was considered and rejected (research §11: it could mark an unreviewed commit green), and no concurrency group is added until a need is shown.
- *(2026-11-24)* The implementation pull request for this change edits the workflow file (the pull-request event types; the traceability step's inputs), so the Claude review action refuses to review it; it merges by one of the two routes in `docs/branch-protection.md` — while `SKIP_AI_REVIEW=true` the review check passes and it merges normally after the owner's approval; otherwise an administrator merges with the review check red. It changes `scripts/`, `tests/` and `.github/` but no `src/` or `ui/`, so FR-009 does not require a `Spec-PR:` line of it; it carries `Spec-PR: #<this spec PR>` by convention.
- *(2026-11-24)* The live read uses the job's own token (`github.token`) on a traceability job limited to `contents: read` and `pull-requests: read`, and the `gh` CLI already on the runner — no new secret, no new dependency; the token is never printed, and a description value that a failure message echoes is printed as an escaped, truncated literal, so it cannot start a runner log line or a workflow command.
- *(2026-11-24)* The pull-request-opening skills (bug-to-pr, requirement-to-pr) live outside this repository; teaching them to write the declaration and pass the label is a follow-up for their owner, not part of this feature.

## Out of Scope

- GitHub Environments approval pauses (deployment-style manual approval gates).
- Automatic pull-request creation; authors open spec and implementation PRs by hand.
- Any change to the four existing merged features (001–005) to fit this workflow.
- Further reason keywords (`docs`, `chore`, `ci`, …): only `refactor` and `bugfix: #<issue>` are accepted; a new reason is a spec change.
- Verifying that the issue named by `bugfix: #<issue>` exists, is open, or describes the fix.
- Policing a `Spec-PR:` declaration on pull requests the rule does not cover (tests-only, scripts-only, docs-only, spec-only).
- Re-running only part of the pipeline on label or description events (considered and rejected in research §11).
