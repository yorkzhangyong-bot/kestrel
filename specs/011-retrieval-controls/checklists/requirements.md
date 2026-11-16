# Specification Quality Checklist: Retrieval Controls for the Experience Store

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-16
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

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.
- Clarification session 2026-11-16 (five questions, batched to the coordinator and answered, recorded under
  Clarifications): the embedding-model mismatch takes the feature-010 unusable-store path (ERROR line, both model
  names, store disabled for the session, runs record loudly as not written back); both controls on by default with
  values pinned in planning and confirmed by the e2e, the offline proof on a lexical-similarity embedding with
  fixture-specific thresholds; merge targets are same-family only, library-seeded and success-derived both
  eligible, nearest within the threshold, outcome reported on the write-back line; the hit count is recorded and
  logged only; the query is the family goal plus the last two attacker messages, with a test proving no reply,
  judge reason or progress text can reach it. The three markers of the first draft (FR-006, FR-010, FR-012) are
  resolved by those answers.
- Deliberate concreteness kept because it *is* the requirement, not an implementation choice: the two feature-010
  event names the owner named (`memory.retrieval`, `memory.writeback`), the roadmap edit and its numbering, and
  "the store's own distance measure" as the unit of the floor and threshold (the owner asked for a distance floor;
  naming the unit makes FR-003, FR-004 and FR-012 testable without naming a library).
- Security framing carried from the constitution: FR-001/FR-002 and SC-001 make "no target text in the retrieval
  path" explicit and testable; FR-013/FR-017 and SC-007 keep the feature-010 deny-list and Principle IV intact;
  FR-016 and SC-008 keep the stack fixed (Principle X). No attack wording anywhere, the fixture included (FR-014).
