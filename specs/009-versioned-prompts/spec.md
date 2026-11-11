# Feature Specification: Versioned Prompts

**Feature Branch**: `009-versioned-prompts`

**Created**: 2026-11-11

**Status**: Draft

**Input**: Give every prompt Kestrel sends to a model (the attacker prompt per family, the judge, the
recommender and the memory summariser) a tracked identity and semantic version, so every run turn and judge
verdict records which prompt version produced it, a prompt cannot change without a version bump, two versions can
be A/B tested with the existing experiment harness, and the active versions are visible — all with no change to
attack behaviour by default.

## Clarifications

### Session 2026-11-11

- Q: How is the "command-line" view of active prompt versions delivered, given Kestrel has no CLI today? → A: No
  standalone CLI — the active versions are exposed on the existing API (for example the config endpoint) and the
  command-line view is a `curl`/small-script request to it (carrying the `X-Kestrel-Token` in hosted mode).
- Q: Is a prompt's version and fingerprint taken over the authored template text or the fully rendered prompt? → A:
  The authored template text (the static text before runtime placeholders are filled); the rendered prompt varies
  per run and is never the thing versioned or hashed.
- Q: Which prompts may be a feature-007 prompt-version A/B arm subject? → A: Only the attacker and judge prompts (the
  ones whose version moves the 007 success metrics); a recommender or memory-summariser version arm is refused.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know which prompt produced a result (Priority: P1)

A red-teamer re-reads a run from last week and needs to know exactly which attacker and judge prompts produced it,
so a later result can be compared like for like. Every prompt Kestrel sends to a model is a registry entry with a
stable id, a semantic version and a content fingerprint; each run turn records the attacker prompt version that
drove it and each judge verdict records the judge prompt version that decided it. The prompts shipped today become
version 1.0.0 unchanged, so nothing about the attacks or verdicts shifts — only their provenance is now recorded.

**Why this priority**: Without recorded provenance, a change in results between two runs cannot be attributed —
was it the target, the attacker model, or a quietly edited prompt? Provenance is the foundation every other story
builds on, and it underpins Principle III (a result must name what produced it).

**Independent Test**: Run an attack and a judged verdict, then read the stored run turn and verdict and confirm
each carries a prompt id and version that exists in the registry; confirm the shipped prompts are recorded as
1.0.0 and that outcomes are identical to before the feature.

**Acceptance Scenarios**:

1. **Given** a completed run turn, **When** it is stored, **Then** it carries the id and version of the attacker
   prompt that produced it, and that id/version exists in the registry.
2. **Given** a judge verdict, **When** it is stored, **Then** it carries the id and version of the judge prompt
   that produced it, and that id/version exists in the registry.
3. **Given** the prompts shipped before this feature, **When** the registry is seeded, **Then** each is recorded
   at version 1.0.0 with its current text, and attack and verdict outcomes are unchanged.
4. **Given** a run turn or verdict created before the migration, **When** it is read, **Then** it shows a clear
   "not recorded" marker rather than a guessed version.

---

### User Story 2 - A prompt cannot change silently (Priority: P1)

A maintainer edits the judge prompt to sharpen it but forgets to bump its version. The test suite fails, pointing
at the prompt whose text no longer matches the fingerprint recorded for its version. Bumping the version (and
recording the new fingerprint) makes the suite pass. A prompt's text and its version can never drift apart.

**Why this priority**: The whole value of a version is that it names one exact text. If text can change under a
fixed version, every recorded provenance becomes a lie and the A/B harness compares mislabelled things. The guard
is what makes the version trustworthy.

**Independent Test**: Change a registered prompt's text without bumping its version and confirm the guard test
fails naming that prompt; bump the version and record the new fingerprint and confirm it passes.

**Acceptance Scenarios**:

1. **Given** a registered prompt whose text matches the fingerprint recorded for its version, **When** the guard
   runs, **Then** it passes.
2. **Given** a registered prompt whose text was changed without a version bump, **When** the guard runs, **Then**
   it fails and identifies the prompt whose text no longer matches its recorded fingerprint.
3. **Given** the same prompt id at the same version, **When** two texts are presented for it, **Then** this is
   rejected — one id at one version identifies exactly one text.

---

### User Story 3 - See the active prompt versions (Priority: P2)

An operator opening the screen, or querying the API from the command line (`curl` or a small script), can see
which version of each prompt is currently active — attacker families, judge, recommender and memory summariser —
without digging through files. The display shows ids and versions, never a prompt's raw text.

**Why this priority**: Visibility turns provenance from a buried database column into something an operator can
act on — confirming which version is live before a run and spotting an unexpected version. It depends on the
registry (US1) but is not needed to record provenance, so it sits below the P1 foundation.

**Independent Test**: Open the UI and query the API (for example the config endpoint) from the command line, and
confirm both show each prompt's id and active version, with no prompt text shown.

**Acceptance Scenarios**:

1. **Given** the registry is seeded, **When** the operator opens the screen, **Then** the active version of each
   prompt is shown with its id.
2. **Given** the registry is seeded, **When** the operator queries the API from the command line (`curl` or a
   script), **Then** the active version of each prompt is listed.
3. **Given** either surface, **When** the active versions are shown, **Then** no prompt's raw text appears.

---

### User Story 4 - A/B test two versions of a prompt (Priority: P2)

An experimenter wants to know whether a new judge or attacker prompt is actually better. They set up a two-arm
experiment that differs only in the version of one named prompt, and the existing harness runs it and reports the
comparison with the same honest statistics — confirmed and suspected success kept separate, a Wilson interval and
a two-proportion note — with the arm difference recording the prompt id and both versions.

**Why this priority**: This is the payoff of versioning: an evidence-based way to decide whether a prompt change
helps. It reuses the feature 007 harness and the P1 registry, so it is valuable but builds on the foundation.

**Independent Test**: Configure a two-arm experiment that differs only by the version of one prompt, run it, and
confirm the comparison is produced by the existing statistics and that the recorded arm diff names the prompt id
and both versions.

**Acceptance Scenarios**:

1. **Given** two arms that differ only in the version of one named prompt, **When** the experiment runs, **Then**
   it completes and the recorded diff names that prompt id and both versions.
2. **Given** a finished prompt-version experiment, **When** the comparison is read, **Then** confirmed and
   suspected success are reported separately with the existing Wilson interval and two-proportion note.
3. **Given** an arm that names a prompt id and version absent from the registry, **When** the experiment is
   started, **Then** it is refused before any model is called.

---

### User Story 5 - Judge accuracy per prompt version (Priority: P2)

Someone improving the judge runs the judge evaluation and reads its accuracy broken down by judge prompt version,
so they can see whether a new judge prompt scores better on the golden set than the previous one.

**Why this priority**: It closes the loop on judge-prompt changes with an accuracy number per version, complementing
the live A/B harness with an offline golden-set view. It is valuable but narrower than the general provenance and
guard, so P2.

**Independent Test**: Run the judge evaluation across rows produced under more than one judge prompt version and
confirm the report presents results grouped by judge prompt version.

**Acceptance Scenarios**:

1. **Given** the judge evaluation, **When** it reports, **Then** its results are grouped by judge prompt version.
2. **Given** a single judge prompt version in use, **When** the evaluation reports, **Then** it still names that
   version alongside the results.

### Edge Cases

- A prompt's text is edited but its version left unchanged — the guard must fail and name the prompt, never pass
  silently.
- Run turns and verdicts created before the migration have no version — they must carry a clear "not recorded"
  marker, not a guessed or back-dated version (the honesty rule from feature 002).
- An experiment arm, or a run, that references a prompt id/version missing from the registry must be refused before
  any model call, not fail partway through.
- A prompt-version arm that names a prompt other than the attacker or judge — the recommender or memory summariser —
  must be refused: only the attacker and judge prompts move the feature-007 success metrics.
- Recording and showing versions must not alter outcomes: with every prompt at its seeded 1.0.0 version, attacks
  and verdicts behave exactly as before.
- The no-attack-text rule bites on the attack library fixtures (feature 002's per-family injection payloads), which
  the registry does not ingest; the attacker prompt *templates* in `attack/attacker.py` are operational prompts and
  are versioned in the registry with full text, like the judge, recommender and summariser prompts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every prompt Kestrel sends to a model — the attacker prompt per family, the judge prompt, the
  recommender (fix-advice) prompt and the memory-summariser prompt — MUST be a registry entry carrying a stable
  id, a semantic version, its authored template text (the static text as authored, before any runtime placeholders
  are filled), and a content fingerprint computed over that template text.
- **FR-002**: The prompts shipped before this feature MUST be seeded at version 1.0.0 with their existing text, so
  default attack, judge, recommendation and memory behaviour is unchanged.
- **FR-003**: Each completed run turn MUST record the id and version of the attacker prompt that produced it, and
  each judge verdict MUST record the id and version of the judge prompt that produced it.
- **FR-004**: A database schema migration (to version 7) MUST add this prompt-version provenance to run turns and
  judge verdicts; rows created before the migration MUST carry a clear "not recorded" marker rather than a guessed
  version.
- **FR-005**: A prompt id at a given version MUST identify exactly one text: presenting two different texts for the
  same id and version MUST be rejected or detectably fail.
- **FR-006**: The test suite MUST fail when a registered prompt's authored template text no longer matches the
  content fingerprint recorded for its id and version — i.e., changing a prompt without bumping its version MUST be
  caught and the offending prompt identified.
- **FR-007**: The active version of each registered prompt MUST be exposed on the existing API (for example the
  config endpoint) and shown in the UI, as id and version without the prompt's raw text; the command-line view is a
  request to that API (`curl` or a small script), which in hosted mode carries the `X-Kestrel-Token` (Principle IV).
- **FR-008**: The feature 007 experiment harness MUST support a prompt-version arm, in which two arms may differ
  only by the version of one named prompt — the attacker or the judge prompt (the prompts whose version moves the
  007 success metrics); an arm naming a recommender or memory-summariser prompt version MUST be refused. The
  experiment MUST record, in the arm diff, that prompt's id and the version each arm used, and the existing
  comparison statistics (confirmed and suspected success kept separate, Wilson interval, two-proportion note) MUST
  apply unchanged.
- **FR-009**: A run or experiment arm that names a prompt id or version absent from the registry MUST be refused
  before any model is called.
- **FR-010**: The judge evaluation in the test suite MUST report its results broken down by judge prompt version.
- **FR-011**: The no-attack-text hard rule covers the **attack library fixtures** (feature 002's per-family
  injection payloads), which the registry does not ingest and which stay sourced exactly as today — never committed,
  save for the single documented exception. The four model-facing prompt *templates* — the attacker prompt template
  per family (already in `attack/attacker.py`), the judge, the recommender and the memory-summariser prompts — are
  Kestrel's own operational prompts, not attack payloads, and MUST live in the registry with their full text,
  versioned and committed alongside one another.
- **FR-012**: Prompt ids, versions and fingerprints are not secrets, but the new provenance, displays and any
  export MUST continue to exclude target auth values, the target URL and the target name (Principle IV).
- **FR-013**: With every prompt at its seeded 1.0.0 version, recording and displaying prompt versions MUST NOT
  change any attack, judge, recommendation or scoring behaviour — by default this feature is observability only.

### Key Entities

- **Versioned prompt (registry entry)**: one of Kestrel's model-facing prompts, identified by a stable id, carrying
  a semantic version, its authored template text (the static text before runtime substitution), and a content
  fingerprint over that template text; one id at one version is exactly one text, and one version per id is active.
- **Prompt provenance**: the prompt id and version recorded on a stored run turn (the attacker prompt) and on a
  stored judge verdict (the judge prompt), added by the version-7 migration; rows predating the migration are
  marked "not recorded".
- **Content fingerprint**: the recorded hash of a prompt's authored template text for an id and version, used to
  detect a template change that was not accompanied by a version bump, and safe to show because it reveals no text.
- **Prompt-version experiment arm**: a feature 007 arm that differs from the other only by the version of one named
  prompt (the attacker or judge prompt); the experiment's recorded arm diff names that prompt id and both versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every run turn and every judge verdict created after the migration carries a prompt id and version
  that exists in the registry — no new run turn or verdict is missing its provenance.
- **SC-002**: Changing any registered prompt's text without bumping its version makes the guard test fail and name
  the prompt; bumping the version and recording the new fingerprint makes it pass.
- **SC-003**: With all prompts at their seeded 1.0.0 version, results on the judge golden set and the end-to-end
  HS-code run are unchanged from before the feature — no behaviour drift by default.
- **SC-004**: The active version of each prompt is visible in the UI and on the API (so a `curl`/script command-line
  check lists them), and no prompt's raw text is shown on either.
- **SC-005**: An experiment comparing two versions of one prompt produces the existing comparison — confirmed and
  suspected success separate, with the Wilson interval and two-proportion note — and the recorded arm diff names the
  prompt id and both versions.
- **SC-006**: The judge evaluation output is grouped by judge prompt version.
- **SC-007**: No attack-library fixture text, and no target auth value, URL or name, appears in the recorded
  provenance, the API responses, the UI, or any commit introduced by this feature; the four prompt templates
  carry their full text in the registry exactly as Kestrel's other committed prompts do.

## Assumptions

- The feature reuses the adopted stack (Principle X): a content fingerprint and semantic-version handling need no
  new runtime dependency, and SQLite schema versioning already exists — this is the version-7 step on top of the
  current schema.
- "Current prompts" are the judge, recommender, memory-summariser and attacker (per-family) prompts as shipped
  through feature 008; seeding them at 1.0.0 preserves today's behaviour because their text is unchanged.
- The attacker prompt templates already live in `attack/attacker.py` with full text; this feature moves them, with
  the judge, recommender and memory-summariser prompts, into the registry with full text and a version. The attack
  library fixtures (feature 002 payloads) are unaffected and remain governed by the no-attack-text rule.
- Pre-migration run turns and verdicts are backfilled with a "not recorded" marker rather than a guessed version,
  consistent with feature 002's honesty rule.
- Kestrel has no standalone CLI today; the "command-line view" is a request to the existing API (`curl` or a small
  script), so this feature adds no new interactive surface — the API exposes the active versions and the UI reads
  them the same way.
- Canary hard evidence (Principle II) is unaffected; this feature records and compares provenance and does not
  change how a verdict is decided.
- **Footnote (plan finding):** the memory summariser composes its writeback summary deterministically (no model
  call), so no summariser prompt exists to version — the registry covers three model-facing prompt kinds (attacker
  per family, judge, recommender); `FR-001`'s mention of a memory-summariser prompt is vacuous and no behaviour is lost.

## Out of Scope

- Editing prompts or bumping versions through the UI or the command line, and any in-app prompt-authoring workflow —
  versions are bumped at the source, as prompts are maintained today.
- Per-use provenance for the recommender and memory-summariser prompts beyond recording and showing their active
  version — only run turns (attacker) and verdicts (judge) record per-use provenance.
- Extending the OWASP report headers to prompt versions; the report already states the attacker model and version
  (Principle III), and prompt-version display in this feature is the UI and CLI.
- Rolling back, or re-running, historical runs under a chosen prompt version.
- Changing any prompt's intent, the attacker or judge models, or the attack library.
