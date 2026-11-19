# Feature Specification: Retrieval Controls for the Experience Store

**Feature Branch**: `011-retrieval-controls`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "Feature 011, retrieval controls for Kestrel's experience store. Shared pattern retrieval
queries with the family goal plus the attacker's own recent messages only, never target replies. A configurable
distance floor drops far hits instead of always returning k. Deduplicate: skip retrieved hits near-identical to one
already selected, and on success write-back update the existing pattern's hit count instead of adding a
near-duplicate. Record the embedding model name in collection metadata and fail clearly at startup if it differs. Add
a recall@k fixture with known patterns and queries. Retrieval settings are logged in the 010 memory.retrieval event.
No new required dependency. Mark retrieval controls as done in docs/roadmap.md in the feature PR. Reviews are approved
by @ilikeandroid."

## Clarifications

### Session 2026-11-16

- Q: When the store's recorded embedding model name differs from the running model at start-up, how should Kestrel
  fail? → A: The feature-010 path for an unusable store: an ERROR `experience.unavailable` line whose reason kind is
  `embedding_model_mismatch`, carrying both model names (model names are not secrets) as fields and the remedy as
  its constant message; the store stays disabled for the session (no retrieval) and every run records loudly as
  not written back (`memory_written` false, Principle V) — exactly as for the other two unusable-store causes.
- Q: What are the shipped defaults for the distance floor and the near-identical threshold? → A: Both on by default,
  with numeric values pinned in planning from measurements on the shipped embedding model and confirmed by the
  single end-to-end run; each can be set or switched off with a documented value. Because the offline suite uses a
  deterministic embedding, the recall@k fixture and the floor and de-duplication tests run on an offline embedding
  that preserves lexical similarity (for example a hashed bag of words) with fixture-specific thresholds, so the
  behaviour is proved offline and the real-model numbers are only confirmed end to end.
- Q: Which existing patterns may a success be merged into (hit count raised instead of a new record)? → A: Same
  family only; library-seeded and success-derived patterns are both eligible; the nearest one within the threshold
  receives the hit; the write-back line reports which happened (merged into a named pattern, or added).
- Q: Does a pattern's hit count influence retrieval in this feature? → A: No — recorded on the pattern and logged
  only; ranking stays purely by distance.
- Q: How many of the attacker's own messages enter the retrieval query? → A: The last two attacker messages plus the
  family goal — a planning constant, not a setting; a test proves that no target reply, judge reason or progress
  text can reach the query.

### Session 2026-11-16 (spec review, round 1)

- Q: Where does the remedy for an unusable store reach the operator? → A: On the `experience.unavailable` line
  itself, as a mismatch-specific constant message (constant text is allowed on a line), with the recorded and
  running values as fields; the exception's own text still never reaches a line.
- Q: Does the write-back merge change any feature-004 statement? → A: Yes, on purpose: four 004 statements are
  amended (listed under Requirements), and the one existing test whose single-turn success replays its library
  seed is updated to assert the merge — the seed's hit count rises and no pattern is added — instead of a new
  pattern.
- Q: Are the shipped defaults confirmed? → A: The floor is pinned from measurements that include queries without
  the seed (turn 4 onwards), which moved it from 1.5 to 1.8 — every measured seedless query still admits at least
  one family seed at 1.8 while unrelated text stays dropped. 1.8 is a measured default, not a guarantee: the
  measurements use stand-ins for real attacker messages, so a real seedless query — especially in
  `indirect_injection` or `tool_exfiltration`, whose seeds sit farthest apart — may select nothing, which FR-003
  allows and which is visible on the `memory.retrieval` line as `pattern_count` 0 with a non-zero `dropped_floor`;
  the floor mainly drops near-unrelated text, and an operator retunes it from the logged distances and
  `dropped_floor`. The end-to-end run uses a turn cap of four and a time limit that fits four real turns, so a run
  reaching turn four yields one retrieval line from a seedless query that admits a pattern; a run can end before
  turn four for any stopping reason (success, an attacker or send failure, the token or time limit), so if no run
  has reached turn four after the second, up to two more are started — four at most — and the test fails if none
  reaches a seedless turn-four line. It also writes a neutral document, a near-identical variant (merged) and a
  paraphrase (added) on the real model at the shipped threshold.
- Q: What does "the selection holds k" mean with a greedy walk? → A: The selection is a nearest-first walk over a
  bounded candidate pool; it is short of k only when the pool is exhausted; "floor off equals feature 004" holds
  only when the near-identical threshold is off too.
- Q: Is the offline fixture robust? → A: Its vocabulary is collision-free under the test embedding's hash with
  dimension 256; the contract publishes every fixture distance with a margin of at least 0.1 from the fixture's
  floor and threshold, and the check asserts those margins.
- Q: Can target text reach the query indirectly? → A: Nothing the target writes enters the query directly — not a
  reply, not a judge note about it, not a memory summary built from such notes, not the purpose description — and
  the proof covers two runs on one target (so memory summaries exist) and a purpose-description marker. The one
  residual is accepted and named: an attacker message may itself echo a fragment of a reply, because the attacker
  model saw the reply; that text is the attacker's own.
- Q: Can the end-to-end test pass vacuously? → A: No — it first asserts that at least one retrieval line exists.
- Q: Is the shipped default's model name derived correctly? → A: The shipped default delegates every call to the
  ONNX MiniLM function, whose model name is recorded; the end-to-end run asserts the two embed a neutral probe
  identically, so a silent change of the default model is caught.
- Q: Is the distance measure itself pinned? → A: Yes: the collection is created with an explicit `l2` space, the
  space is recorded beside the model name, and at start-up a different space fails exactly like a model mismatch
  (reason kind `space_mismatch`); feature-004 stores already use `l2` and are stamped on first open.

## User Scenarios & Testing *(mandatory)*

Feature 004 gave Kestrel an experience store: shared attack patterns (seeded from the library, added to by every
success) and per-target memory, retrieved before each attacker turn of a warm adaptive run and offered to the attacker
as hints. Reviewer feedback on that store named four gaps, and this feature closes them: the search text that selects
patterns is today built from the whole conversation, target replies included; retrieval always returns k patterns
however far they are; every success files a pattern even when a near-identical one exists; and the store never
records which embedding model built it. A fifth item makes retrieval quality measurable.

### User Story 1 - Hints come from the attacker's own words, never the target's (Priority: P1)

A red-teamer runs a warm adaptive attack. Before each attacker turn after the first, Kestrel searches the shared
patterns for background. Today that search text includes the target's replies, so what the target says steers which
patterns the attacker is shown — a long or oddly worded reply pulls in patterns about the reply, not about the
attack, and text the target controls reaches a retrieval path it should never touch. From now on the search is built
from the attack family's goal and the attacker's own recent messages only. Nothing the target writes enters the
query directly — not its replies, not the judge's reasons or progress notes written about them, not the memory
summaries built from those notes, not the purpose description — on any retrieval path. One residual is accepted
and named: an attacker message may itself echo a fragment of a reply, because the attacker model saw the reply;
that text is the attacker's own and stays in the query.

**Why this priority**: It is a safety property as much as a quality one: nothing the target writes enters the query
directly (the one residual, an attacker message echoing a reply fragment, is the attacker's own text). It also fixes
the query every other control in this feature is measured against, so it comes first.

**Independent Test**: Drive two warm adaptive runs against one stub target whose purpose description carries a known
marker, whose replies carry a second known marker, with a stub judge whose reason and progress notes carry a third
(so the second run's memory summaries, built from the first run's notes, carry it too), and record every search text
the store receives; assert every marker appears zero times, and that the family goal and the attacker's most recent
messages appear in every search text from the second turn on. Repeat for a run executed by an experiment arm with
retrieval on.

**Acceptance Scenarios**:

1. **Given** a warm adaptive run on its second or later turn, **When** patterns are retrieved, **Then** the search
   text consists of the attack family's goal and the attacker's own most recent messages of this run, in
   conversation order, within a fixed bound — and nothing else.
2. **Given** target replies and judge notes that carry known marker strings, **When** every search text of the run is
   inspected, **Then** each marker appears zero times.
3. **Given** the second turn of a run (the attacker's only message so far is the library seed), **When** patterns are
   retrieved, **Then** the search text is the family goal plus the seed message.
4. **Given** a run executed by an experiment arm with retrieval on, **When** patterns are retrieved, **Then** the same
   rule applies — the two retrieval paths cannot drift apart.
5. **Given** a cold run (prior experience off) or a single-turn run, **When** it executes, **Then** nothing is
   retrieved, exactly as in feature 004.

---

### User Story 2 - Only relevant, distinct patterns reach the attacker (Priority: P1)

Today retrieval returns the k nearest patterns of the family whatever their distance, and may return several
near-identical ones, because every success writes a new pattern and successes often repeat the same approach. The
red-teamer wants far hits kept out of the background and every hit in it distinct: a configurable distance floor
drops hits beyond it instead of padding the selection to k (with the shipped default that is mainly near-unrelated
text; the floor is a measured default an operator can retune, not a relevance guarantee), and a hit near-identical
to one already selected is skipped, so a duplicate never takes a slot from a distinct pattern.

**Why this priority**: Irrelevant and repeated hints waste the attacker's limited context and, with the shared pool
growing by one pattern per success, get worse over time. Together with Story 1 this is the retrieval behaviour the
feature exists to deliver.

**Independent Test**: Seed an offline store with patterns of one family at known distances from a query, set the
floor between the near and the far ones and the near-identical threshold so that two of the near ones count as
duplicates of each other; retrieve and assert the far one is absent, only one of the duplicate pair is present, a
third distinct near pattern still fills the selection, and the order is nearest first; switch each control off in
turn and assert it no longer acts (the far one returns; both of the pair return), and switch both off and assert
the feature-004 selection — the k nearest — returns.

**Acceptance Scenarios**:

1. **Given** patterns of the family at known distances and a floor set between them, **When** patterns are
   retrieved, **Then** only hits within the floor come back — fewer than k when fewer qualify, none when none do.
2. **Given** the floor switched off, **When** patterns are retrieved, **Then** no hit is dropped for its distance,
   and with the near-identical threshold also off up to k nearest hits come back, as in feature 004.
3. **Given** two near-identical patterns both within the floor and a third distinct one, **When** patterns are
   retrieved with k of 2, **Then** the nearer of the pair and the distinct one are selected and the other of the
   pair is skipped — the skipped duplicate does not use a slot.
4. **Given** any selection, **When** it is read, **Then** its hits are ordered nearest first, number at most k, all
   lie within the floor and no two lie within the near-identical threshold of each other.
5. **Given** the near-identical threshold switched off, **When** patterns are retrieved, **Then** no candidate is
   skipped.
6. **Given** a retrieval, **When** its log line is read, **Then** it carries the settings in effect (k, the floor,
   the threshold) and the outcome (candidates considered, dropped by the floor, skipped as duplicates, selected, and
   the selected pattern ids), and the counts add up.

---

### User Story 3 - A repeated success strengthens a pattern instead of cloning it (Priority: P2)

When a run succeeds, the attacker messages that won are written to the shared pool as a pattern. If a near-identical
pattern of the same family already exists, the write-back now increases that pattern's hit count instead of adding
a copy; a genuinely new approach is added with a hit count of one. The write-back log line says which happened, so
the pool grows with distinct approaches and records how often each one worked.

**Why this priority**: It keeps the shared pool from filling with copies (which Story 2 would otherwise have to
skip on every retrieval) and records a signal — how many times an approach succeeded — that later features can
rank on. It depends on the same near-identical measure as Story 2 but is independently valuable.

**Independent Test**: Write back several successful runs into an offline store: two whose winning messages are
near-identical to each other, one that replays a library-seeded pattern, one that is unlike every pattern, and one
near-identical to a pattern of a different family; assert the pool's pattern count, each pattern's hit count and
each write-back line's outcome.

**Acceptance Scenarios**:

1. **Given** a success whose winning messages are near-identical to an existing pattern of the same family, **When**
   it is written back, **Then** no new pattern record is created, the existing pattern's hit count rises by one,
   and the write-back line says the success was merged, naming the pattern and its new hit count.
2. **Given** a success unlike every existing pattern of its family, **When** it is written back, **Then** one new
   pattern is added with a hit count of one, and the line says it was added.
3. **Given** a success near-identical only to a pattern of a different family, **When** it is written back, **Then**
   a new pattern is added in the run's own family — de-duplication is scoped to the family.
4. **Given** a success that replays a library-seeded pattern of its family, **When** it is written back, **Then**
   that library pattern's hit count rises and no copy is added.
5. **Given** a run that did not succeed, **When** it is written back, **Then** no pattern is added or updated and its
   memory record is written exactly as before.
6. **Given** de-duplication switched off, **When** a success is written back, **Then** a new pattern is added, as in
   feature 004.

---

### User Story 4 - The store knows which embedding model built it (Priority: P2)

Patterns are found by comparing embeddings, and embeddings from different models are not comparable: a store built
by one model and searched by another returns nonsense without any error. Nor are distances comparable across
distance measures: the same vectors under another measure would move every floor and threshold. The store now
records the name of the embedding model that produced its vectors and the distance measure its index uses, and is
created with that measure pinned; whenever Kestrel opens the store at start-up it compares both with what is in use
and fails clearly on a mismatch, naming both values. A store created by feature 004, which recorded neither, keeps
working: it already uses the same measure and is stamped with the running model's name and the measure the first
time it is opened.

**Why this priority**: A silent mismatch would make every warm run worse while looking healthy. The check is small,
runs once at start-up, and protects the data the other stories rely on.

**Independent Test**: Create an offline store under one model name and confirm the name and the distance measure are
recorded; reopen it under the same name and confirm nothing is reported; reopen it under a different name and confirm
the named failure that states both names and the remedy; open a store whose index uses a different distance measure
and confirm the same kind of failure naming both measures; open a store that carries a store version but no model
name and confirm it opens cleanly and is stamped with both.

**Acceptance Scenarios**:

1. **Given** a fresh store, **When** it is created, **Then** its index uses the pinned distance measure and its
   collection metadata records the embedding model's name and that measure beside the store version.
2. **Given** a store recorded under the running model's name and measure, **When** Kestrel starts, **Then** the
   store opens with no message.
3. **Given** a store recorded under a different model's name, **When** Kestrel starts, **Then** it fails clearly at
   start-up with a named failure whose constant message states the remedy and whose fields carry the recorded name
   and the running model's name — never a cryptic error later in a run — and the store stays disabled for the
   session: runs proceed without retrieval and each one records loudly as not written back, as for every other
   unusable store.
4. **Given** a store whose index uses a different distance measure, **When** Kestrel starts, **Then** it fails in
   the same way, with its own reason kind, the recorded and expected measures as fields and the remedy as the
   message.
5. **Given** a store created by feature 004 (store version present, no model name and no recorded measure),
   **When** Kestrel starts, **Then** the store opens without failure (its index already uses the pinned measure), is
   stamped with the running model's name and the measure, and the next start compares against that stamp.

---

### User Story 5 - Retrieval quality is measurable (Priority: P3)

A maintainer changes something that affects retrieval — the thresholds, the query rule, the embedding model — and
wants to know whether the right patterns still come back. A labelled fixture of known patterns and queries, written
as neutral placeholders and never as attack wording, states which patterns each query should retrieve, which queries
have no relevant pattern, and which patterns are near-duplicates of each other; a check seeds a fresh store from it
and reports recall@k with the retrieval controls on.

**Why this priority**: Without a yardstick the thresholds of Stories 2 and 3 are guesses and regressions go
unnoticed. It is tooling for maintainers, so it comes after the behaviour it measures.

**Independent Test**: Seed a fresh offline store from the fixture, run every labelled query with the fixture's k and
settings, and assert recall@k meets the fixture's stated minimum, that the "no relevant pattern" queries return
nothing and that each near-duplicate pair yields one hit.

**Acceptance Scenarios**:

1. **Given** the fixture seeded into a fresh store, **When** each labelled query is retrieved with the fixture's
   settings, **Then** recall@k is at or above the fixture's stated minimum.
2. **Given** a query the fixture labels as having no relevant pattern, **When** it is retrieved with the floor on,
   **Then** zero hits come back.
3. **Given** a pair the fixture labels as near-duplicates, **When** a query close to both is retrieved, **Then**
   exactly one of the pair is selected.
4. **Given** the fixture file, **When** it is read, **Then** it contains neutral placeholder texts only — no attack
   wording.

---

### Edge Cases

- **Second turn**: the attacker's only message so far is the library seed, so the search text is the family goal plus
  the seed; the seed's own library pattern is a legitimate (and usually the nearest) hit, as in feature 004.
- **Long attacker messages**: the window bounds how many messages enter the search text, not their length; an
  embedding model that reads only the first part of a long text does so for the query as it already does for the
  patterns.
- **Fewer than k qualifying patterns, or none**: the selection is shorter, down to empty; the retrieval line is still
  emitted with zero selected and `warm` false (`010/FR-016` unchanged), and the hints block simply has no patterns
  section.
- **A floor so tight that nothing qualifies**: zero hits, the line's dropped-by-floor count equals its candidate
  count, and the run continues — a retrieval that finds nothing never fails a run.
- **Every candidate within the floor is a near-duplicate of the first**: one hit is selected; the line's skipped
  count equals the candidates within the floor minus one.
- **A hit at exactly the floor, or two hits at exactly the threshold**: a hit at the floor is within it; two hits at
  the threshold are near-identical.
- **Invalid settings**: a negative floor or threshold, or a value that is neither a number nor the documented "off"
  value, refuses to start, as every other invalid setting does; the floor and threshold are independent — either may
  be off while the other is on.
- **Settings for another embedding model**: the defaults are tuned for the embedding model Kestrel ships with; an
  operator who changes the model (and rebuilds the store) must retune them, which the settings documentation says.
- **A success near-identical to several existing patterns**: the nearest one receives the hit.
- **A pattern with no recorded hit count** (written before this feature): it counts as one; a merge makes it two.
- **The near-duplicate look-up fails during write-back**: the write-back fails loudly as a whole, exactly as any
  write-back failure does today (`004/FR-010`); nothing is retried silently.
- **The store cannot be read during retrieval**: retrieval stays best-effort — the turn proceeds without hints and
  the existing warning line is emitted (`004` edge case, `010` `memory.retrieval_failed`).
- **The embedding model name mismatches at start-up**: the failure is named and carries both names as fields; the
  store is disabled for the session, so no pattern or memory is written to it and every run records loudly as not
  written back; the remedy (rebuild the store, or restore the previous model) is the failure line's own constant
  message, so it reaches the operator on the line and not only in a traceback. Existing records are never
  re-embedded by this feature.
- **The index's distance measure differs from the pinned one** (a collection created outside Kestrel, or by a
  future version with another measure): the same failure shape with its own reason kind, both measures as fields
  and the remedy (rebuild the store) as the message; a feature-004 store never trips it, because it already uses the
  pinned measure.
- **A store with the model name but a different store version**: the existing version warning is unchanged; the
  model name check is independent of it.
- **Experiments**: a cold arm is untouched; a warm arm retrieves with the controls in effect, so "retrieval on vs
  off" keeps its meaning — "on" is retrieval as this feature now defines it.
- **Memory records**: untouched by every control here — they are selected by exact target id, never by distance,
  and are never de-duplicated.

## Requirements *(mandatory)*

Feature 011 refines feature 004's pattern retrieval and success write-back, and extends feature 010's retrieval and
write-back log lines. It amends five feature-004 statements, on purpose: the search text of `004/FR-016` ("the
family's goal combined with the conversation so far") becomes the family's goal combined with the attacker's own
recent messages (FR-001); the closing clause of `004/FR-009` ("every success is written; no de-duplication") and
`004/SC-003` ("every successful run produces exactly one new pattern record") become "every success is recorded,
as exactly one new pattern or one merge into a near-identical same-family pattern" (FR-006, FR-008, SC-004); the
feature-004 edge case "many near-identical successes — patterns may repeat" no longer holds, because they merge;
and — owner-approved after an independent review found that a reused numeric run id could silently overwrite a
surviving pattern, because `runs.id` was not `AUTOINCREMENT` — the `pattern:run:<run_id>` id and the "deterministic
ids make seeding and write-back idempotent via upsert" claim
(`004/contracts/experience-store.md:21,31`, `004/data-model.md:52`, `004/quickstart.md:32`) become: an added pattern
gets a unique `pattern:run:<uuid>` id (the run id kept only as `origin_run_id` metadata, FR-006); seeding stays
idempotent through its own deterministic `pattern:lib:<prompt_id>` ids, and write-back's safety against repeats now
comes from running exactly once per run plus de-duplication's merge, never from an upsert on a derived id. Where
behaviour is unchanged — memory retrieval by exact target id and its recency cap, the warm/cold switch,
the hints block, the memory record written after every run, loud write-back failure, the profile, deletion, the
permission and terms gates and the three hard caps — this spec says so rather than restating it.

### Functional Requirements

**The retrieval query**

- **FR-001**: The search text that selects shared patterns (the retrieval query) MUST be built from exactly two
  sources: the current attack family's goal, and the attacker's own messages of the current run — the last two, in
  conversation order (a planning constant, not a setting). Nothing else MUST enter it: not a target reply, not a
  judge reason, not a judge progress note, not the target's purpose description, not a memory summary. On the first
  retrieval of a run (its second turn) the attacker's only message is the library seed, so the query is the goal
  plus the seed.
- **FR-002**: One query rule MUST govern every retrieval path — a run started from the API and a run executed by an
  experiment arm — so the two cannot drift apart; and a test MUST prove that known markers placed in the target's
  replies, in the judge's reasons and progress notes and in the target's purpose description appear zero times in
  any query the store receives — across two warm runs on one target, so that the second run's memory summaries,
  built from the first run's judge notes, are in the store — while the family goal and the attacker's messages do
  appear.

**The distance floor**

- **FR-003**: Retrieval MUST apply a configurable distance floor: a candidate whose distance from the query, in the
  store's own distance measure, exceeds the floor MUST be dropped, so that the selection holds fewer than k hits —
  possibly none — when fewer qualify; the selection MUST NOT be padded with far hits. With the floor switched off
  and the near-identical threshold (FR-004) also off, up to k nearest hits come back, as in feature 004.

**De-duplication at retrieval**

- **FR-004**: Retrieval MUST apply a configurable near-identical threshold: candidates are considered nearest first,
  and a candidate whose distance to any already selected hit is at or below the threshold MUST be skipped. A skipped
  candidate MUST NOT count toward k: the selection MUST consider candidates beyond the first k (over a bounded
  candidate pool pinned in planning) so that duplicates do not starve it of distinct hits that qualify. With the
  threshold switched off, no candidate is skipped.
- **FR-005**: The selection handed to the attacker MUST be ordered nearest first, hold at most k hits, every hit
  within the floor, and no two hits within the threshold of each other. The hints block that carries them, and its
  hints-not-commands framing (`004/FR-019`), are unchanged.

**Write-back de-duplication and hit counts**

- **FR-006**: When a run succeeds, before its winning messages are written as a new shared pattern, the write-back
  MUST look for the nearest existing pattern of the same family — never another family's. When that pattern lies
  within the near-identical threshold (the same threshold retrieval uses), the write-back MUST increase its hit
  count by one, record the run as its latest hit, and MUST NOT add a new record; otherwise it MUST add a new pattern
  with a hit count of one. Library-seeded and success-derived patterns are both eligible to receive the hit, and the
  nearest one within the threshold receives it. The write-back line MUST report which happened: merged into a named
  pattern, or added (FR-013).
- **FR-007**: Every pattern MUST carry a hit count — one for a library-seeded pattern and for a success-derived
  pattern when it is added; a pattern written before this feature counts as one. The hit count is recorded and
  logged; it MUST NOT change the retrieval ranking in this feature, which is by distance only.
- **FR-008**: A run that did not succeed MUST neither add nor update a pattern (`004/FR-009`), and the memory record
  of every run MUST be written exactly as before (`004/FR-006`). With de-duplication switched off, every success adds
  a pattern, as in feature 004.

**The embedding model name**

- **FR-009**: The store MUST create its collection with an explicitly pinned distance measure (the squared
  Euclidean measure the store uses today) and MUST record, in the collection's own metadata beside the store
  version, the name of the embedding model that produced its vectors and the distance measure its index uses,
  written when the collection is created.
- **FR-010**: Whenever Kestrel opens the store at start-up it MUST compare the recorded model name with the name of
  the embedding model in use, and the index's actual distance measure with the pinned one. On a mismatch of either
  it MUST fail clearly, at start-up, with a named failure that states the recorded value, the running value and the
  remedy — never a silent degrade and never a cryptic error on a later write-back — and no pattern or memory MUST be
  written to the mismatched store. The failure takes the feature-010 path for an unusable store: an ERROR
  `experience.unavailable` line whose reason kind is `embedding_model_mismatch` or `space_mismatch`, whose fields
  carry the recorded and the running value (model names and measure names are not secrets), and whose constant
  message is mismatch-specific text that states the remedy (rebuild the store directory, or run Kestrel with the
  model that built it); the store stays disabled for the session, so nothing is retrieved and every run records
  loudly as not written back (`memory_written` false, Principle V) — exactly as for the other two unusable-store
  causes. A store recorded under the running model's name and the pinned measure MUST open without any message.
- **FR-011**: A store created by feature 004 (store version present, no model name, no recorded measure) MUST keep
  working: its index already uses the pinned measure, so on its first open Kestrel MUST stamp it with the running
  model's name and the measure and MUST NOT treat the missing keys as a mismatch; from then on FR-010 applies. A
  stamp MUST never overwrite a recorded model name (a store that carries a name but lacks the measure keeps its
  name, so FR-010 still catches a model mismatch on it), and only a store whose index uses the pinned measure is
  stamped — any other index fails FR-010 unstamped. Existing records are kept as they are — nothing is re-embedded.

**Settings**

- **FR-012**: The distance floor and the near-identical threshold MUST be settings beside the existing retrieval
  bounds (k and the memory cap), each with a default and a documented way to switch it off; an invalid value — a
  negative number, or a value that is neither a number nor the off value — MUST refuse to start, as every other
  invalid setting does. Both controls are on by default: the default values are expressed in the store's own
  distance measure for the embedding model Kestrel ships with, pinned in planning from measurements on that model
  that include queries with and without the seed (a floor of 1.8 and a threshold of 0.15; the planning record
  states the measurements), and confirmed by the end-to-end run (FR-018); the settings documentation states both
  values, the off value, and that a different embedding model needs retuned values.

**Logging (feature 010 lines)**

- **FR-013**: Every retrieval line (`memory.retrieval`) MUST additionally carry the settings in effect — k, the
  floor and the threshold, the latter two null when off — and the outcome: the number of candidates considered,
  dropped by the floor, skipped as near-duplicates and selected (which equals the existing pattern count), the
  selected pattern ids (already carried), the distance of each selected hit and the number of attacker messages in
  the query; the counts MUST add up (candidates equals dropped plus skipped plus selected). The write-back line
  (`memory.writeback`) MUST additionally say, for a success, whether the pattern was added or merged, the id of the
  pattern added or merged into, its resulting hit count and its distance to the nearest existing pattern (null when
  the family had no pattern or de-duplication is off). The new fields MUST be added to the field catalogue and to
  feature 010's log-records contract.
  Feature 010's deny-list (`010/FR-009`) is unchanged: no query text, reply text, pattern text or message text
  reaches any line — identifiers, counts, distances and settings only.

**Quality fixture**

- **FR-014**: A recall@k fixture MUST exist: a labelled set of neutral, behaviour-level placeholder pattern texts
  (never attack wording) and queries, where each query names the pattern ids expected among its top k, some queries
  are labelled as having no relevant pattern, and some pattern pairs are labelled as near-duplicates; the fixture
  states its k, its floor and threshold, and its minimum recall@k. An offline check MUST seed a fresh store from the
  fixture, run every query with the retrieval controls on, and assert recall@k at or above the stated minimum, zero
  hits for every "no relevant pattern" query and exactly one hit per near-duplicate pair. The check, like the floor
  and de-duplication tests of FR-003 to FR-006, runs on a deterministic offline embedding that preserves lexical
  similarity — near-identical texts embed near each other and unrelated texts far apart (for example a hashed bag
  of words) — with the thresholds the fixture and the tests state, so the behaviour is proved offline while the
  shipped model's numbers are confirmed only by the end-to-end run.

**Compatibility and bounds**

- **FR-015**: Everything this feature does not name MUST be unchanged: memory retrieval by exact target id and its
  recency cap; the warm/cold switch and a cold run's attacker input; single-turn runs, which retrieve nothing; the
  hints block; the memory record and the loud write-back failure; the profile; deletion; the permission and terms
  gates, the three hard caps and the token budget (Principle VIII). A feature-007 experiment's "retrieval on vs off"
  arms keep their meaning: "on" is retrieval with these controls in effect, "off" is unchanged.
- **FR-016**: The feature MUST add no new required dependency (Principle X): the floor and the de-duplication use the
  store's own distance measure and the standard library only.
- **FR-017**: No auth header value, API key, target URL or target display name MUST reach the store, its collection
  metadata, the retrieval query or any log line (`004/FR-012` and `010/FR-009` unchanged).

**Tests (Principle VII)**

- **FR-018**: There MUST be one end-to-end test against the owned HS-code sacrificial target, started and stopped by
  the test itself: two warm adaptive runs on one target under a turn cap of four and a time limit that lets four
  real turns complete, where — after first asserting that at least one retrieval line exists, so the test cannot
  pass vacuously — the retrieval lines of every run (the first run is warm on the library seeds too) carry the
  shipped settings and the counts and select at least one pattern within the floor, including at least one line
  whose query no longer contains the seed (turn four); a run can end before turn four for any stopping reason —
  success, an attacker or send failure, the token or time limit — so if no run has reached turn four after the
  second, the test starts up to two more (four at most) and fails if no run reaches a seedless turn-four line;
  where, on the same store with the real model, a neutral
  document, a near-identical variant of it and a paraphrase of it are written back at the shipped threshold and the
  variant is merged (hit count two) while the paraphrase is added; where the store the runs used carries the
  embedding model's name and the pinned measure; and where the shipped default embedding and the model it is
  recorded under are checked to embed a neutral probe identically. Every other requirement and criterion MUST be
  verifiable offline, with a deterministic embedding (the lexical one of FR-014 wherever distances matter) and a
  temporary store that is never the repository's own.

**Roadmap**

- **FR-019**: The feature's implementation pull request MUST move "Retrieval controls" into the roadmap's Done
  section as feature 011 and renumber the planned items — regression replay 012, behavioural evidence expansion 013,
  community prompt feed 014 — including the cross-reference to regression replay inside the community-feed item.
  This edit is part of the implementation pull request, not of the spec-only pull request.

### Key Entities

- **Retrieval query**: the search text that selects shared patterns for one attacker turn — the family goal plus the
  attacker's own most recent messages of the run, bounded by a window; never a target reply, judge reason, judge
  progress note, purpose description or memory summary.
- **Retrieval settings**: k (the existing bound), the distance floor, the near-identical threshold (each of the last
  two may be off), and the attacker-message window; expressed in the store's own distance measure.
- **Candidate and selection**: a candidate is a pattern of the current family returned by the store for a query,
  with its distance; the selection is the ordered subset handed to the attacker — nearest first, at most k, within
  the floor, pairwise distinct.
- **Pattern record (extended)**: as in feature 004, plus a hit count (one when added; raised by each merged success)
  and the run that last hit it.
- **Collection metadata (extended)**: the store version (feature 004) plus the embedding model name and the pinned
  distance measure; a feature-004 store gains both on first open.
- **Recall@k fixture**: labelled placeholder patterns and queries with expected ids, "no relevant pattern" queries,
  near-duplicate pairs, the k and settings to run with, and the minimum recall@k.
- **Retrieval line and write-back line (extended)**: the feature-010 lines with the settings and outcome fields of
  FR-013.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across every retrieval of the offline suite's warm runs — two runs on one target started from the API,
  and a run executed by an experiment arm — the known reply marker, the known judge markers (also present in the
  target's memory summaries on the second run) and the known purpose-description marker appear 0 times in the query
  the store receives, and the family goal and the attacker's own messages appear in 100% of the queries from the
  second turn on.
- **SC-002**: With a floor set between known near and known far patterns, 100% of selected hits lie within the floor
  and the far patterns are selected 0 times; with both the floor and the threshold off, the selection is the k
  nearest, exactly as before.
- **SC-003**: Across every retrieval the suite drives, 0 pairs of selected hits lie within the threshold of each
  other, and the selection — a nearest-first walk over the bounded candidate pool — is short of k only when the pool
  is exhausted, every candidate having been examined (dropped, skipped or selected).
- **SC-004**: After N successful runs (N ≥ 2) whose winning messages are near-identical to one another, the family
  holds exactly 1 pattern derived from them with a hit count of N and 0 copies; N successes each unlike every
  existing pattern add exactly N patterns, each with a hit count of 1.
- **SC-005**: The recall@k fixture scores a recall@k of 1.0 offline (every expected id among the top k of every
  labelled query), 0 hits for every "no relevant pattern" query, and exactly 1 hit per near-duplicate pair.
- **SC-006**: 100% of stores opened by this version carry the embedding model name and the distance measure after
  one open, and 100% of collections this version creates use the pinned measure; a store recorded under a different
  model name, or whose index uses a different measure, is reported at start-up 100% of the time with the named
  reason, both values as fields and the remedy as the message, and 0 patterns or memory records are written to it;
  a feature-004 store opens with 0 failures and is stamped.
- **SC-007**: 100% of retrieval lines carry the settings and the four counts, and on every line the candidate count
  equals dropped plus skipped plus selected; across the known-marker runs, the reply marker, the judge markers, the
  attacker's message text and any pattern text appear 0 times on any log line.
- **SC-008**: Kestrel's required dependencies are unchanged, and the whole offline suite passes with the
  deterministic embedding and temporary stores — 0 tests touch the repository's own store directory.
- **SC-009**: Existing tests keep their intent, and exactly 1 existing expectation changes, on purpose and named: the
  feature-004 deletion test's single-turn success replays its library seed and now merges into it (the seed's hit
  count rises to 2, 0 patterns are added, shared patterns still survive deletion) instead of adding a pattern; a cold
  run's attacker input and a single-turn run are identical to before the feature; the same stub-driven run uses the
  same number of turns and tokens before and after the feature.
- **SC-010**: One end-to-end test passes against the HS-code target: two warm adaptive runs under a turn cap of 4
  (up to 2 more, 4 at most, only while no run has reached turn 4), at least 1 retrieval line present, every
  retrieval line of every run carrying the shipped settings and counts with at least 1 pattern selected — at least
  1 of them from a query without the seed, on turn 4, or the test fails — the three real-model
  write-backs giving added, merged (hit count 2) and added, the model name and the measure recorded in the store
  those runs used, and the shipped default embedding and its recorded model agreeing on a neutral probe.
- **SC-011**: In the implementation pull request the roadmap lists "Retrieval controls" under Done as 011 and the
  three planned items as 012, 013 and 014, with 0 stale references to their former numbers.

## Assumptions

- Builds on features 004 (the store, retrieval, write-back, hints), 007 (experiment arms with retrieval on or off),
  009 (the family label is the goal text used in the query today, since the goal sentences moved into the prompt
  files) and 010 (the retrieval and write-back lines, the field catalogue, the deny-list, the start-up failure
  events). All are reused unchanged except where this spec adds to them.
- Distances are the store's own distance measure between embeddings (the squared Euclidean measure, pinned at
  creation and recorded); the floor and the threshold are numbers in that measure, both on by default. Their
  default values — a floor of 1.8 and a threshold of 0.15 — are planning constants measured on the embedding model
  Kestrel ships with, including queries that no longer contain the seed (turn four onwards), and confirmed by the
  end-to-end run (the real model): 1.8 is the smallest round value at which every measured seedless query still
  admits at least one family seed, while unrelated text stays dropped; 0.15 merges whitespace, spelling and
  one-word variants and keeps a paraphrase distinct. The floor is a measured default, not a guarantee: the
  measurements use stand-ins for real attacker messages, so a real seedless query — especially in
  `indirect_injection` or `tool_exfiltration` — may select nothing, which FR-003 allows and which shows on the
  retrieval line as `pattern_count` 0 with `dropped_floor`; 1.8 mainly drops near-unrelated text, and operators
  retune from the logged distances and `dropped_floor`. The offline tests and the fixture always state the values they
  need, because a deterministic test embedding has its own distance scale, and they use an offline embedding that
  preserves lexical similarity so that "near-identical" and "far" are meaningful offline.
- The attacker-message window is a planning constant, not a setting: the last two attacker messages keeps parity
  with today's two-turn window while removing the replies.
- Accepted limitation: the attacker model sees the target's replies, so an attacker message may echo a fragment of
  one; that fragment is then the attacker's own text and may enter the query. The guarantee is that no target text
  enters the query directly — not a reply, a judge note, a memory summary or the purpose description.
- The near-identical threshold is one number shared by retrieval de-duplication and write-back de-duplication:
  "near-identical" means the same thing on both paths.
- The hit count is recorded and logged only; it does not change ranking or appear in the profile in this feature. It
  is the groundwork a later feature (the community prompt feed, 014 after renumbering) can tier and prune on.
- The seed's own library pattern remains a legitimate hit on the second turn (feature 004 behaviour).
- A store's embedding model name is derived from the embedding function in use, the same way for the shipped default
  and for the deterministic test embedding, so the start-up check is exercised offline.
- Extending the retrieval and write-back lines edits feature 010's log-records contract; the implementation pull
  request therefore carries the `spec-change:` note the traceability gate requires for a spec file edited alongside
  code.
- Hard caps, the permission box and the token budget (Principle VIII) are unchanged; retrieval adds no model call and
  no target request, as before.
- One end-to-end scenario against the owned HS-code target is the only test that needs a model key; every other
  requirement and criterion is verified offline.

## Out of Scope

- Re-embedding an existing store when the embedding model changes (a migration); this feature detects the mismatch
  and names the remedy.
- Pruning, forgetting or expiring patterns; ranking or tiering by hit count; showing hit counts in the profile or
  the report.
- De-duplicating memory records, or applying the floor to memory (memory is selected by exact target id).
- Per-arm retrieval settings in experiments; the arms keep their on/off switch.
- Changing the hints block, the attacker prompt, the judge, scoring or the report.
- The community prompt feed and regression replay (roadmap items, renumbered by FR-019).
