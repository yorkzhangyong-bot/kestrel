# Feature Specification: Learn From Every Run — Attack-Pattern Store and Per-Target Memory

**Feature Branch**: `004-attack-pattern-memory`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description:

> Feature 004: ChromaDB attack-pattern store and per-target memory.
>
> Context: this closes Principle V of the constitution (learn from every run). Features 001-003 can register a target, run single-turn and multi-turn adaptive attacks, and judge them, but nothing is written back, so every run starts from zero. This feature is defensive security tooling for a red-team platform the user owns. Specs describe behaviour and structure only; they contain no attack text.
>
> What to build: a local vector store (one collection, records typed pattern or memory, local default embeddings, versioned); idempotent start-up seeding of patterns from the attack library; per-target memory write-back after every run; memory safety constraints (summary only, internal id only, sanitised against self-injection); successful attacks also written as patterns; retrieval before each attacker turn behind a per-run "use prior experience" switch (patterns by semantic search, memory by exact target-id match); target understanding (optional purpose description plus accumulated memory) fed before the first turn; a per-target profile view; deletion also deletes a target's memory. One end-to-end test: two runs, the second run's attacker receives at least one memory record from the first.
>
> Out of scope: cross-target trait matching; memory consolidation or forgetting; pattern dedup/pruning; the OWASP report and risk score (005); the A/B harness and promptfoo baseline (006); syncing external pattern sources.

## Clarifications

### Session 2026-10-24

- Q: Default state of the "use prior experience" switch? → A: ON (warm) by default; cold is an explicit opt-out, used mainly by the later A/B harness (006).
- Q: What does "fail loudly" mean when write-back fails? → A: the attack run's own record (verdict, turns, evidence) is still saved normally; the run is flagged as not written back (`memory_written = false`), the screen shows a visible warning on that run, and an error is logged. The attack result is never discarded because of a write-back failure.
- Q: Is the target purpose description fed to the attacker in a cold run? → A: Yes, when set. The switch controls only retrieved patterns and memory, not the user-typed description. Cold is feature-003 behaviour plus the description when one is set.
- Q: How much of a target's memory is supplied when warm? → A: Bounded and most-recent-first, capped at 10 records, with any successful record for the current attack family kept in the selection even if older. The exact cap may be tuned in planning; the spec fixes "bounded, recent-first, successes of the same family preserved".
- Q: What does warm pattern retrieval search against? → A: Semantic similarity to the current attack family's goal combined with the conversation so far, so the hints adapt as the conversation evolves.
- Q: Is pattern retrieval scoped by family? → A: Current family only — only patterns tagged with the attack family being run are retrieved.
- Q: What represents a success-derived pattern for future similarity search? → A: The attacker message(s) that led to the success (Kestrel's own text, the approach that worked), not the target's reply and not merely the seed prompt.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Learn from every run (Priority: P1)

A vibe coder runs attacks against their targets, as in features 002 and 003. From now on, every finished run — single-turn or adaptive, succeeded, failed or unclear — is remembered: the platform writes one short record of what happened for that target, and when an attack succeeds it also files an anonymised pattern that any future attack can draw on. The attack library is loaded into this shared store once, at start-up, so there is prior knowledge to build on from day one. Nothing the user does is required; the learning happens automatically, and if a run ever fails to be recorded that failure is made loud, because a run that does not write back is a bug (Principle V).

**Why this priority**: This closes Principle V and is the foundation the rest of the feature stands on. Without write-back there is nothing to retrieve, nothing to profile, and nothing to forget. On its own it already delivers value: the platform stops starting from zero and begins accumulating a per-target and shared record.

**Independent Test**: With the sacrificial HS-code target saved, run one attack of any kind and confirm the store then holds exactly one new memory record for that target with safe metadata only, plus one new pattern record if and only if the run succeeded; restart and confirm start-up seeding adds no duplicate patterns.

**Acceptance Scenarios**:

1. **Given** a finished run of any kind and any outcome, **When** the run ends, **Then** exactly one memory record is written for that run's target, carrying a one-line summary and the run's metadata.
2. **Given** a run that succeeded, **When** it is recorded, **Then** one new shared pattern record is also written, tagged with family, OWASP category and the origin run; **and given** a run that did not succeed, **Then** no pattern record is written.
3. **Given** the store already seeded from the attack library, **When** the system starts again, **Then** no duplicate pattern records are created.
4. **Given** the store cannot be written at the end of a run, **When** the write-back is attempted, **Then** the failure is surfaced and logged rather than swallowed.

---

### User Story 2 - Reuse prior experience to attack smarter (Priority: P2)

Before starting an attack, the user chooses whether it should use prior experience. When it is on, the attacker is primed, before each turn, with a few of the most relevant shared patterns and with everything the platform has learned about this particular target, offered as hints it may use or ignore. When it is off, the attack behaves exactly as in feature 003, starting cold. The choice is recorded on the run, so a warm run and a cold run can always be told apart later.

**Why this priority**: This is the payoff of learning: later runs benefit from earlier ones, and against the same target the attacker stops repeating what already failed. It depends on Story 1's write-back, so it follows it, but it is what makes the feature worth having.

**Independent Test**: Run two attacks against the same target with "use prior experience" on; confirm the second run's attacker is given at least one memory record produced by the first run, and that with the switch off no patterns or memory are retrieved.

**Acceptance Scenarios**:

1. **Given** the switch is off, **When** an attack runs, **Then** no patterns or memory are retrieved and no retrieved hints are added — the attacker's input matches feature 003, plus the purpose description if one is set.
2. **Given** the switch is on and the target has earlier memory, **When** each attacker turn is prepared, **Then** the attacker receives up to a bounded number of semantically similar shared patterns and this target's own memory, as hints.
3. **Given** the switch is on, **When** patterns are retrieved, **Then** they are selected by semantic similarity, while memory is selected by exact match on the internal target id, not by semantic similarity.
4. **Given** two targets each with their own memory, **When** one is attacked, **Then** only that target's memory is offered to the attacker; the other target's memory never appears.
5. **Given** retrieved hints, **When** they reach the attacker, **Then** they are presented as suggestions, not commands, and do not override the plain-conversation rule or the turn, token and time caps of feature 003.

---

### User Story 3 - Tell the attacker what a target is for (Priority: P2)

At registration the user can add a single optional line describing what the target is for — clearly marked as not a place for sensitive information. That description, together with whatever the platform has already learned about the target, is given to the attacker as background before the first turn, without using up a conversation turn or sending anything to the target. An attacker that knows a target is, say, a customs-classification assistant can aim its probing better from the start.

**Why this priority**: Context before the first turn makes early turns count instead of being spent discovering what the target is. It is valuable but secondary to recording and reuse, and it is small and self-contained.

**Independent Test**: Register a target with a one-line purpose description, run an attack, and confirm the description is supplied to the attacker as background before the first turn and is shown back in the target's profile, while never being treated as a secret field.

**Acceptance Scenarios**:

1. **Given** the registration form, **When** the user fills in the optional purpose description, **Then** it is saved with the target, shown when editing, and clearly marked as not for sensitive information.
2. **Given** a target with a purpose description, **When** an attack starts, **Then** the attacker is given the description as background before the first turn, consuming no conversation turn and sending nothing to the target.
3. **Given** a target with no purpose description, **When** an attack starts, **Then** nothing about a description is added and the attack proceeds normally.

---

### User Story 4 - See what Kestrel has learned about a target (Priority: P3)

The user opens a target and sees a profile: how many times it has been attacked, broken down by attack family and verdict, with the most recent one-line summaries of what happened. It is a plain, readable picture of the target's history, built only from the safe records the platform stored.

**Why this priority**: It turns the accumulated memory into something a person can read and act on. It is useful once memory exists but is not needed for attacks to improve, so it comes after write-back and retrieval.

**Independent Test**: After several runs against a target, open its profile and see counts by family and verdict and recent summaries, with no auth header value or other secret anywhere on the view.

**Acceptance Scenarios**:

1. **Given** a target with several recorded runs, **When** the user opens its profile, **Then** they see how many runs it has, grouped by family and verdict, with recent one-line summaries.
2. **Given** a target with no recorded runs yet, **When** the user opens its profile, **Then** they see an empty-state message rather than an error.
3. **Given** any target profile, **When** it is shown, **Then** it contains only summaries and non-secret metadata and never an auth header value.

---

### User Story 5 - Forget a target when it is deleted (Priority: P3)

When the user deletes a target, everything the platform learned specifically about that target is deleted with it — its memory records go, just as its runs and conversations already do. The shared, anonymised patterns stay, because they carry no target identity and represent general knowledge the platform keeps.

**Why this priority**: Deletion must mean deletion for anything tied to a target (Principle IV spirit and basic hygiene), but it only matters once memory exists, so it is grouped with the other follow-on stories.

**Independent Test**: Create a target, run attacks so it has memory and contributes a pattern, delete the target, and confirm its memory records are gone while the shared patterns remain.

**Acceptance Scenarios**:

1. **Given** a target with memory records, **When** the target is deleted, **Then** all of that target's memory records are removed from the store.
2. **Given** a success earlier contributed a shared pattern, **When** the origin target is deleted, **Then** that pattern remains, because it holds no target identity.
3. **Given** a target is deleted, **When** another target is later attacked warm, **Then** none of the deleted target's memory can be retrieved.

---

### Edge Cases

- **First run against a target**: there is no memory yet; warm retrieval returns only shared patterns (or nothing, if the library seeded none), and the run still writes its first memory record at the end.
- **No judge notes to summarise**: a run settled by a canary with no judge call, or run with no judge configured, has no progress notes; the summary falls back to a fixed description built from the run's own metadata (family, verdict, evidence basis, stopping condition).
- **Store unreadable during retrieval**: retrieval is best-effort — if the store cannot be read, the run logs it and continues without hints (it does not fail the run), because hints are optional; write-back, by contrast, is mandatory and fails loudly.
- **Store unwritable at write-back**: the run's own outcome is still stored as in features 002–003; the run is flagged `memory_written = false`, the screen shows a visible warning on that run, and an error is logged. The attack result is never discarded (a bug condition under Principle V).
- **Very long concatenated judge notes**: the one-line summary is truncated to a fixed maximum length before it is stored.
- **A target that emits instruction-like text**: the stored summary is sanitised to a fixed, bounded, single-line format, so nothing from the target can act as an instruction when the summary is later fed to the attacker (no self-injection).
- **Many near-identical successes**: every success is written as a pattern; no de-duplication or pruning happens in this feature, so patterns may repeat.
- **Store/schema version differs from the running code**: the store records its own version; reconciling an older store (migration) is out of scope here, as with the SQLite schema — the version is recorded now so a later feature can detect and handle a mismatch.
- **Empty or missing attack library at seeding**: seeding writes zero patterns and is not an error.
- **Purpose description used for a secret despite the warning**: the field is the user's responsibility and is treated as non-secret (it is shown in the profile and given to the attacker); the "no sensitive info" label is the safeguard, unlike auth header values which are encrypted and never leave the vault.

## Requirements *(mandatory)*

Feature 004 extends features 002 and 003. Where behaviour is identical — the permission and terms gates, canary matching, the judge and its per-turn progress notes, reply masking and cutting, run storage and listing, the start-up sweep, deletion of a target's runs, and the sacrificial target — this spec says so rather than restating it. It also **closes the Principle V deferral** that features 002–003 carried: from this feature on, every run writes back.

### Functional Requirements

**The store**

- **FR-001**: The system MUST keep a local vector store persisted under the data directory alongside the SQLite database (for example `data/chroma/`), using the stack's built-in local default embeddings with no external embedding service (Principle X).
- **FR-002**: The store MUST use a single collection whose records are distinguished by a `type` metadata field valued either `pattern` or `memory`.
- **FR-003**: The store MUST record its own schema/store version so that a later version change can be detected.
- **FR-004**: At start-up the system MUST idempotently seed `pattern` records from the attack library; running start-up again MUST NOT create duplicate patterns.
- **FR-005**: Every `pattern` record's metadata MUST carry the attack family, the OWASP category and a source reference, and MUST NOT contain any target URL, display name, or auth header name or value (Principle IV).

**Write-back after every run (Principle V)**

- **FR-006**: After every finished run — single-turn or adaptive, and whatever the outcome — the system MUST write exactly one `memory` record for that run's target.
- **FR-007**: A `memory` record MUST contain a one-line situation summary plus metadata: the internal target id, the attack family, the OWASP category, the verdict, whether hard evidence was found, the turns used, the stopping condition, and the attacker model (Principles III, V, VI).
- **FR-008**: The situation summary MUST be built only by concatenating the run's own per-turn judge progress notes into one line, making no additional model calls; when a run has no judge notes, the summary MUST fall back to a fixed description derived from the run's metadata.
- **FR-009**: A run that succeeds MUST also be written as one new `pattern` record tagged with the family, the OWASP category and the origin run id. The pattern's searchable content MUST be the attacker message(s) that led to the success — Kestrel's own text, the approach that worked — never the target's reply text. Runs that do not succeed MUST NOT create a pattern record. Every success MUST be written; no de-duplication or pruning happens in this feature.
- **FR-010**: When a run's write-back cannot be completed, the system MUST fail loudly — because a run that does not write back is a bug (Principle V). Specifically: the run's own outcome record (verdict, turns, evidence — feature 002/003) MUST still be saved normally; the run MUST be flagged as not written back (`memory_written = false`); the screen MUST show a visible warning on that run; and an error MUST be logged. The attack result MUST NOT be discarded because of a write-back failure, and write-back MUST NOT be retried silently.

**Memory safety (Principle IV and no self-injection)**

- **FR-011**: A `memory` record MUST store only the one-line summary of what happened; it MUST NOT store the target's raw reply text.
- **FR-012**: A `memory` or `pattern` record MUST identify a target only by its internal id; it MUST NOT contain the target's URL, display name, auth header names or values, or any other secret (Principle IV).
- **FR-013**: The situation summary MUST be sanitised into a fixed, length-bounded, single-line format so that instruction-like content cannot be carried from a target, through memory, into an attacker's prompt (no self-injection).

**Retrieval and the warm/cold switch**

- **FR-014**: Each run MUST carry a "use prior experience" setting, chosen per run and recorded on the run so warm and cold runs can be told apart afterwards. The setting MUST default to on (warm); cold is an explicit opt-out.
- **FR-015**: When the setting is off (cold), the system MUST skip all retrieval of patterns and memory. A cold run MUST behave as in feature 003, except that the target's purpose description, when one is set, is still given to the attacker (FR-021) — the switch governs only retrieved patterns and memory, not the user-typed description.
- **FR-016**: When the setting is on (warm), before each attacker turn the system MUST retrieve up to a bounded number of `pattern` records by semantic similarity and the current target's `memory` records by exact internal-target-id match, and MUST supply both to the attacker. Pattern retrieval MUST search against the current attack family's goal combined with the conversation so far, and MUST be limited to patterns tagged with the current family. The memory selection MUST be bounded and most-recent-first (default cap 10 records, tunable in planning), and MUST always keep any successful memory record for the current attack family even if it is older than the recency cut-off.
- **FR-017**: `pattern` records MUST be retrieved by semantic similarity; `memory` records MUST be retrieved by exact internal-target-id match and MUST NOT be retrieved by semantic similarity.
- **FR-018**: Retrieved memory MUST be limited to the current target; one target's memory MUST NOT be offered when attacking a different target.
- **FR-019**: Retrieved patterns and memory MUST be presented to the attacker as hints, not commands; the attacker MUST be free to ignore them, and they MUST NOT override the plain-conversation rule or the turn, token and time caps of feature 003 (Principle VIII).

**Target understanding**

- **FR-020**: The target registration flow MUST offer an optional one-line purpose description, clearly marked as not for sensitive information, stored with the target, shown when editing, and treated as a non-secret field (not encrypted, unlike auth header values).
- **FR-021**: Before the first attacker turn, the system MUST give the attacker, as background, the target's purpose description (when set) regardless of the warm/cold setting, and — only when the run is warm — the target's accumulated memory, without consuming a conversation turn and without sending anything to the target.

**Profile view**

- **FR-022**: The screen MUST provide a per-target profile that summarises that target's memory records — at least a count of runs grouped by attack family and by verdict, with the most recent one-line summaries.
- **FR-023**: The profile MUST show only summaries and non-secret metadata and MUST never show an auth header value (Principle IV).

**Deletion**

- **FR-024**: Deleting a target MUST delete all of that target's `memory` records from the store, in addition to deleting its runs and conversations as in feature 003.
- **FR-025**: Shared `pattern` records MUST survive target deletion, because they carry no target identity and represent shared knowledge.

**Tests (Principle VII)**

- **FR-026**: There MUST be one end-to-end test against the sacrificial HS-code target: two runs with "use prior experience" on, where the second run's attacker is given at least one `memory` record produced by the first run.
- **FR-027**: The end-to-end test MUST start and stop the sacrificial target itself with no manual steps, reusing it unchanged (as in feature 003).

### Key Entities

- **Attack-pattern store**: the local vector store. One collection, records typed `pattern` or `memory`, local default embeddings, with its own recorded version. Lives under the data directory next to the SQLite database.
- **Pattern record**: anonymised, shared attack knowledge — attack family, OWASP category, a source reference, and, when derived from a success, the origin run id. Holds no target identity. Its searchable content is the library prompt (for seeded patterns) or the attacker message(s) that succeeded (for success-derived patterns) — never any target reply. Seeded from the attack library and added to by successful runs. Retrieved by semantic similarity, scoped to the current attack family.
- **Memory record**: what happened in one run against one target — the internal target id, a one-line sanitised summary, attack family, OWASP category, verdict, whether hard evidence was found, turns used, stopping condition, and attacker model. Retrieved by exact target-id match. Deleted with its target.
- **Target purpose description**: an optional, one-line, user-provided, non-secret description of what a target is for, captured at registration.
- **Use-prior-experience setting**: a per-run choice — warm (retrieve and hint) or cold (feature-003 behaviour) — defaulting to warm, with cold an explicit opt-out, recorded on the run.
- **Write-back status**: a per-run flag (`memory_written`) recording whether the run's memory record was stored; `false` keeps the attack result, drives a visible warning on the run, and marks a Principle V bug condition.
- **Target profile**: a per-target summary derived only from that target's memory records.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After any run (single-turn or adaptive, any outcome), exactly one new memory record exists for that run's target; across all acceptance tests, 0 runs produce zero or more than one.
- **SC-002**: Running start-up seeding any number of times yields the same number of library-derived pattern records; repeated start-ups add 0 duplicates.
- **SC-003**: Every successful run produces exactly one new pattern record and every non-successful run produces 0; across all acceptance tests there are 0 exceptions.
- **SC-004**: A known test value used as an auth header value, together with the target's URL and display name, appears 0 times across all stored pattern and memory records.
- **SC-005**: With the switch on, a second run against a target is given at least one memory record produced by an earlier run against that same target; with the switch off, it is given 0 patterns and 0 memory records.
- **SC-006**: Memory retrieved while attacking one target includes 0 records belonging to any other target, across all acceptance tests.
- **SC-007**: With the switch off and no purpose description set, the attacker's input is identical to feature 003 — 0 retrieved hints are added.
- **SC-008**: A target's raw reply text appears 0 times in any memory record; only the one-line summary is stored.
- **SC-009**: Every stored summary conforms to the fixed single-line, length-bounded format; across all acceptance tests 0 summaries exceed the maximum length or contain disallowed control characters.
- **SC-010**: Deleting a target removes 100% of that target's memory records and leaves 100% of shared pattern records intact.
- **SC-011**: Across fault-injection tests where the store cannot be written, 0 write-back failures are silent — each one keeps the attack's own record, flags the run `memory_written = false`, shows a visible warning on the run, and logs an error.
- **SC-012**: One end-to-end test passes against the sacrificial HS-code target: two warm runs, the second run's attacker receiving at least one memory record from the first.
- **SC-013**: A user can open a target's profile and see its run counts by family and verdict and recent summaries, with 0 secrets shown.
- **SC-014**: Warm pattern retrieval returns 0 patterns tagged with a family other than the run's attack family, across all acceptance tests.

## Assumptions

- Builds on features 001–003. Target registration and connection testing (001); single-turn attacks, canary matching, the judge, reply masking and cutting, run storage, the permission and terms gates, the start-up sweep and the sacrificial target (002); the adaptive attacker/judge loop, per-turn judge progress notes, conversation storage, and the attacker model and its recording (003) are all reused unchanged except where this spec adds to them.
- This feature **closes the deliberate Principle V deferral** carried by features 002–003. The run record already holds the family, OWASP category, verdict, evidence basis, stopping condition, attacker model and conversation that write-back needs.
- ChromaDB and its built-in local default embeddings are already in the fixed stack (Principle X), so no new dependency justification is needed; the store runs fully locally and offline, with no embedding API calls and no cost.
- Out of scope, as stated: cross-target trait matching; memory consolidation or forgetting; pattern de-duplication or pruning; the OWASP report and risk score (005); the A/B harness and promptfoo baseline (006); syncing external pattern sources. Handling a store whose recorded version differs from the running code (migration) is also out of scope; the version is recorded now so a later feature can act on it.
- Retrieval is bounded: a small, fixed number of patterns (pinned in planning) and a bounded amount of this target's memory — most-recent-first, default cap 10 records, always keeping any successful record for the current family even if older. Hints are best-effort; a retrieval failure never fails a run, whereas a write-back failure always fails loudly (FR-010).
- The "use prior experience" switch is surfaced per run (like the single-turn/adaptive mode toggle of feature 003), defaults to on (warm) with cold an explicit opt-out, and is recorded on the run so the later A/B harness (006) can compare warm against cold.
- The target purpose description is independent of the warm/cold switch: it is given to the attacker whenever it is set. A cold run is therefore feature-003 behaviour plus the description when one is set, and identical to feature 003 when none is.
