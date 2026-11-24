# Specification Quality Checklist: Human-Approved Spec Workflow

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-29
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- This is a governance/CI feature, so its domain is inherently GitHub pull requests, branch protection, and a
  CI pipeline. Named deliverables that the feature request specified (`CODEOWNERS`, `.github/review/spec-checklist.md`,
  `docs/branch-protection.md`, `scripts/check_spec.py`) are treated as required artifacts, not premature technology
  choices; the requirements still describe *what* each must do and *why*, leaving the *how* to the plan.
- No `[NEEDS CLARIFICATION]` markers: the feature request was precise, and the few open mechanics (how an
  implementation PR references its spec PR; the skipped-but-reported required check) are resolved with documented
  assumptions and an edge case rather than questions.

## Re-validation 2026-11-24 (the honest Spec-PR path amendment)

Re-run over the amended spec (FR-009 and SC-007 amended; FR-015–FR-023, SC-008–SC-010, User Story 5, edge cases,
assumptions and out-of-scope items added). Every item above still passes:

- **Content quality**: the amendment names the `Spec-PR:` / `Spec-PR-reason:` lines, two label names and the
  pull-request events the pipeline reacts to. As with the original (Notes above), these are the feature's
  user-facing interface in a governance/CI domain — what a contributor writes and what the platform reports — not
  technology choices; the *how* (patterns, environment variables, job wiring) stays in plan.md and contracts/.
- **Requirement completeness**: no `[NEEDS CLARIFICATION]` marker; FR-015 and FR-016 enumerate the accept and
  fail-closed cases so each is one unit-test row; SC-008–SC-010 are counts or observable outcomes; the Session
  2026-11-24 clarifications record the owner's requirement and the FR-009 scope correction; the remaining choices
  (the key name, the label names, the re-run cost, no issue lookup, branch independence, the admin-merge of the
  workflow edit) are stated defaults in Assumptions for the owner's review on the spec PR.
- **Feature readiness**: User Story 5 has seven acceptance scenarios covering the accept, fail-closed, conflict,
  spec-change, re-run and unchanged-form paths; tasks.md's "Added 2026-11-24" coverage table maps every new id to
  a task; the ids no unit test can cover are justified in traceability.md.

Review round 1 (2026-11-24, FAIL: 0 severe, 6 medium, 7 minor) fixed in place: AS4/AS7 and SC-009 now agree with
FR-016 on conflicts; FR-015/FR-016 decide stray and malformed `Spec-PR:` lines one way (exactly one line, exactly
`none`, on the honest path); FR-017 adds column 1 and ASCII digits; FR-018 is a live read of the
description and labels; FR-023 adds the pull-request template; the live-verification vehicle is a throwaway draft
PR that touches `src/`; cost, noise and the two merge routes are stated in Assumptions. Every checklist item above
still passes.

Review round 2 (2026-11-24, FAIL: 0 severe, 3 medium, 7 minor) fixed in place: the round-1 HTML-comment stripping is
reversed — the gate reads the raw description, exactly as today (FR-017, SC-009 back to one exception, FR-022
unchanged); the draft-PR live check restores `specs/` to master's version first, uses only non-existent numbers and
must be mergeable; the optional verdict-only review is dropped; `pr_state`'s failure path is tested; the traceability
job is limited to read permissions; the rollout order is stated once. Every checklist item above still passes.

Owner review of spec PR #50 (2026-11-24), two changes applied in place: (1) the pipeline re-runs only on relevant
events — a body change, or the `refactor`/`bugfix` label added or removed — and only its traceability job, through a
separate recheck workflow (FR-019, SC-010, the Assumptions, research §11 with the documentation cited); (2) a
`bugfix: #<issue>` number must be an existing issue of this repository, looked up live and fail-closed (new FR-024;
FR-015, FR-018, SC-008, the Assumptions, research §12). Both recorded as owner decisions in the Clarifications session,
superseding the earlier decisions without deleting them. Every checklist item above still passes.

Review of the owner changes, round 1 (2026-11-24, FAIL: 1 severe, 1 medium, 6 minor) fixed in place: the recheck has
no concurrency group (an irrelevant event can no longer cancel a relevant recheck; a refused-in-progress re-run is
retried within the bound; a one-action label swap step added to the live check); the stale-result cases (fork,
50-re-run cap, timeout, refusal) and their consequence are stated with a fixed-text comment and the owner's merge
rule; the owner's words are kept verbatim with the design decisions marked for confirmation; 410 Gone for a deleted
issue; a run awaiting approval counts as no run; `branches: [master]`, `timeout-minutes: 35` and the rollout note.
Every checklist item above still passes.

Review of the owner changes, round 2 (2026-11-24, FAIL: 0 severe, 1 medium, 5 minor) fixed in place: a re-run
refusal is classified by re-reading the run, never by the POST's HTTP status code (GitHub's job re-run endpoint
documents only `201` and `403`, and sends the same `403` for an in-progress attempt and a final refusal — a
20,000-scenario simulation showed the old by-code classifier posting 6,285 false-alarm stale-result comments
against 169, genuine, for the fixed one); the recheck's step machine ships as a tested script,
`scripts/qa_recheck.py` (T034), with a pre-POST freshness skip (`already_fresh`, avoiding a wasted re-run when the
latest attempt already postdates this recheck) and comment-hygiene safeguards (no `VERDICT:` substring, a per-call
timeout, one comment retry); the owner's merge rule now covers a pull request from a fork directly and accepts any
`traceability` attempt — the recheck's own automatic re-run included — that started after the stale-result comment
and passed; the two-relevant-events edge case names an unambiguous example (`refactor` swapped for `bugfix`,
distinct from the unrelated-label swap that demonstrates an irrelevant event cancelling nothing). Every checklist
item above still passes.

Review of the owner changes, round 3 (2026-11-24, FAIL: 0 severe, 1 medium, 4 minor) fixed in place: every
`scripts/qa_recheck.py` client call now returns a value or raises `RecheckApiError` after its own timeout, so a
transient failure is retried within the budget rather than read as "no run" or left to crash silently (a review
simulation found 747/4,688 of 20,000 interleavings, at 1%/5% failure rates, ending stale with no comment under the
naive reading; 0 at both rates once fixed); a run with no `traceability` job reaches the comment at once;
`already_fresh` never raises on a missing or unparsable timestamp, returning `False` (send the re-run request, never
skip it); the script's entry point catches any other exception and still attempts the comment before exit 1; T034
moved under "Tests (write first, must fail)" ahead of T033, which now makes it pass; the plan's constitution
re-check names both recheck permissions; the recheck job sets up Python before running the script, as the
traceability job does; quickstart's overlap step no longer states the refusal as certain. Every checklist item
above still passes.
