# Feature Specification: Regression Replay

**Feature Branch**: `012-regression-replay`

**Created**: 2026-11-19

**Status**: Draft

**Input**: User description: "Feature 012, regression replay for Kestrel. From a past run, re-send its recorded
attacker messages verbatim and in order to the same target, with no attacker model call. Score each new reply with
the canary check and the judge, as in a normal run. Store the replay as a new run with mode "replay", linked to its
source run id, with prompt versions recorded. Report one outcome against the source: fixed, still vulnerable, or
inconclusive, and show the source and replay verdicts side by side. A replay never writes shared patterns or target
memory. Add a batch replay of every succeeded run for a target, and a script for CI that exits non-zero if any
replay is still vulnerable. Expose replay through the API and a Replay button on the UI run page. Log replays
through the 010 events. No new required dependency. Mark regression replay as done in docs/roadmap.md in the
feature PR. Reviews are approved by @ilikeandroid."

## Clarifications

### Session 2026-11-19

- Q: What is the default for the configurable maximum number of replayable runs per batch (FR-031)? → A: 20, as a
  named, configurable positive-integer setting (`KESTREL_REPLAY_BATCH_MAX_RUNS`), parsed and validated the same way
  Kestrel's other positive-integer settings are, reported on the configuration endpoint alongside the other hard
  caps. A run produced by an A/B experiment (006/007) is an ordinary run of its target and counts toward this cap
  like any other replayable run; the batch's refusal message, given before anything is sent, names the replayable
  count, the configured cap, and the setting that raises it.
- Q: What exit status does the CI script (FR-036) use for a usage or API-level error, distinct from the three
  result-based codes (0 fixed/nothing-to-replay, 1 still vulnerable, 2 inconclusive)? → A: 3 — covering an
  unreachable API, an unknown target, and the batch refused for any precondition (including the batch-size cap).

## User Scenarios & Testing *(mandatory)*

Every other feature (001-011) gave Kestrel ways to *find* a weakness: an attack succeeds, the judge or a canary
confirms it, and the finding lands in the OWASP report. None of them gave Kestrel a way to *recheck* a weakness
after someone tries to fix it — today the only option is to pick the same family and hope Kestrel's attacker (or a
dice roll over the library) lands on something close to the original attack, which proves nothing about whether the
*specific* finding was fixed. Regression replay closes that loop: it re-sends a past attack's exact recorded
messages, with no attacker model in the loop, and reports whether the target is still vulnerable to that specific
attack or has been fixed.

### User Story 1 - Prove whether a specific finding was fixed (Priority: P1)

A user found a vulnerability last week, changed the target's system prompt or added a guardrail, and wants to know
whether *that exact attack* still works — not whether some new attack might also work, and not a result muddied by
the attacker model trying something slightly different this time. They open the finding's run, click **Replay**,
and Kestrel re-sends the same messages that attack used, in the same order, with no attacker model call, scores
each new reply the same way a live attack is scored (the canary check first, the judge second), and reports one of
three outcomes against the original run — **fixed**, **still vulnerable**, or **inconclusive** — with the original
and the new result shown side by side.

**Why this priority**: Without this, "did my fix work?" has no direct answer in Kestrel; a user is left re-running
fresh attacks and guessing whether a different result means the fix worked or the attacker just didn't try the same
thing twice. This is the smallest slice that delivers that answer, and every other story in this feature builds on
it.

**Independent Test**: Seed a store with a finished, succeeded run (single-turn or adaptive) against a stub target,
call the replay action on it, and verify: no attacker-model call is made; the target receives exactly the source
run's recorded message(s), verbatim and in the same order; a new run is stored, linked to the source; the outcome
is exactly one of fixed / still vulnerable / inconclusive, computed correctly for a target that now fails the
attack, one that still succeeds, and one that fails to answer at all; and the two runs' results are both readable
side by side.

**Acceptance Scenarios**:

1. **Given** a finished run whose verdict was succeeded, **When** the user replays it and the target no longer
   falls for any of the resent messages (every one answered, no canary, the judge failing every judged turn),
   **Then** Kestrel reports the outcome **fixed** and shows both runs' results side by side.
2. **Given** that same run, **When** the user replays it and the target still falls for it (a canary matches, or the
   judge says the attack succeeded, on any resent message), **Then** Kestrel reports **still vulnerable**, stops
   sending the remaining recorded messages (mirroring how a live adaptive attack stops at its first success), and
   shows both results side by side.
3. **Given** that same run, **When** the replay cannot be scored cleanly — the target fails to answer, no judge is
   configured and no canary matches, the judge itself errors or returns "unclear" on some turn, or the run's time
   limit is reached before every recorded message was sent and judged — **Then** Kestrel reports **inconclusive**
   rather than guessing at fixed or still vulnerable.
4. **Given** the replay is running, **When** it sends each message, **Then** no call is made to any attacker model,
   at any point, for any message.
5. **Given** a run that is still in progress, one whose verdict was failed or unclear, one that never sent a
   message successfully, or a replay run itself, **When** the user tries to replay it, **Then** Kestrel refuses
   before sending anything and states why (naming the original source run, in the replay-of-a-replay case).
6. **Given** a replay has finished, **When** the user opens its own run page, **Then** it shows its own verdict,
   evidence and (for an adaptive source) turn-by-turn conversation exactly as any other run does, plus the outcome
   against its source and a link back to that source.
7. **Given** a replayable run's page, **When** the user clicks the **Replay** button, **Then** the page shows a
   line reading **"Outcome: "** followed by one of "fixed", "still vulnerable" or "inconclusive", and the
   comparison's two column headings naming the source and replay run ids.
8. **Given** a non-replayable run's page (in progress, not succeeded, itself a replay, or with no recorded
   message), **When** the user looks at it, **Then** the **Replay** button is visibly disabled and its reason is
   shown as readable text next to it.

---

### User Story 2 - Trust that checking a fix never teaches the attacker or clutters the findings (Priority: P1)

A replay's entire point is to hold everything constant except time: the same messages, the same target, so any
difference in outcome is attributable to whatever changed on the target's side. If a replay were allowed to feed its
own resent messages back into the shared library of learned attack patterns, or into the target's own memory of
what works against it, two problems would follow: the shared pattern pool would double-count a success Kestrel
already knows about, and a security-relevant recheck would quietly start acting like a fresh finding in the OWASP
report. A replay must leave no trace in either the learned-pattern pool, the target's memory, or the report's
findings.

**Why this priority**: This is as much a safety property as a feature: getting it wrong would silently corrupt the
signal every other feature (004, 005, 011) relies on — the shared pattern pool and the OWASP report. It stands
beside Story 1 because every replay and every batch replay must honor it from the first run, not as an
afterthought.

**Independent Test**: Run a single replay and a batch replay against an instrumented experience store that records
every call it receives, and confirm it receives none — no retrieval query, no pattern write, no memory write —
across every outcome (fixed, still vulnerable, inconclusive). Generate a target's OWASP report before and after a
replay whose source was already a finding, and confirm the finding count, the coverage rows and the recommendation
calls are identical.

**Acceptance Scenarios**:

1. **Given** a replay of any source (single-turn or adaptive, any outcome), **When** it runs, **Then** the
   experience store receives zero calls: no pattern query, no pattern write, no per-target memory write.
2. **Given** a target with at least one succeeded, non-replay run that is already a report finding, **When** that
   run is replayed and the target's OWASP report is generated again, **Then** the report's finding count, coverage
   rows and recommendation calls are unchanged — the replay appears nowhere in it.
3. **Given** a replay, **When** its run is stored, **Then** its "was memory written" status is recorded as "not
   attempted", never as "written" or "failed".

---

### User Story 3 - Check every past fix on a target in one action (Priority: P2)

A user who has been attacking a target for a while has accumulated several confirmed findings. After a round of
hardening, re-testing them one at a time is tedious and easy to under-cover. They want one action that replays
every one of that target's past findings and comes back with a tally: how many are now fixed, how many are still
vulnerable, how many came back inconclusive.

**Why this priority**: It turns Story 1 from a one-off check into a repeatable regression sweep, which is the
difference between "did I fix this one thing" and "did my round of fixes actually work" — valuable, but it is a
thin layer over Story 1 and depends on it being correct first.

**Independent Test**: Seed a target with several replayable runs (mixing single-turn and adaptive, and mixing
sources that will come back fixed, still vulnerable and inconclusive) plus at least one run that is not replayable
(in progress, failed, or itself a replay) and confirm a batch replay processes only the replayable ones, oldest
first, one at a time, and returns one entry per source plus accurate counts per outcome. Seed a target whose
replayable-run count exceeds the configured cap and confirm the whole batch is refused before anything is sent.

**Acceptance Scenarios**:

1. **Given** a target with several replayable runs, **When** the user starts a batch replay, **Then** Kestrel
   replays each one in turn, oldest first, one at a time, and never includes a run that is in progress, not
   succeeded, or itself a replay.
2. **Given** that batch finishes, **When** the user reads the result, **Then** it lists one entry per source run
   (naming the source and its new replay, the attack family, and both runs' verdicts and the computed outcome) and
   a count of how many came back fixed, how many still vulnerable, and how many inconclusive, and those counts sum
   to the number of entries.
3. **Given** a target whose number of replayable runs exceeds the configured maximum for one batch, **When** the
   user starts a batch replay, **Then** Kestrel refuses the whole batch before sending a single message, rather than
   silently replaying only some of them.
4. **Given** a target with zero replayable runs, **When** the user starts a batch replay, **Then** it completes
   immediately with zero entries and zero counts, rather than refusing or erroring.
5. **Given** a batch in progress, **When** a later entry's own claim collides with a genuinely concurrent run on
   the target, **Then** the batch stops, reports itself incomplete with the reason and every source run it never
   reached, and keeps every entry it had already completed — it is never discarded or reported as if the batch
   had simply refused outright.
6. **Given** a batch in progress, **When** one entry's own replay fails unexpectedly (not a collision — an
   unforeseen error), **Then** that entry's own run is recorded inconclusive, the batch stops there exactly as it
   does for a collision (incomplete, the reason, the unreached source runs), and the batch result itself is never
   an error response — the failure belongs to that one entry, not to the batch request.

---

### User Story 4 - Gate a release on regression results (Priority: P2)

A team ships changes to the target behind CI. Before a change reaches production, they want an automated check that
fails the build if any previously confirmed attack still works against the candidate deployment — and they want
that check to fail the build, not pass it, if the result can't be determined cleanly, because a CI gate that
shrugs and passes on "couldn't tell" defeats its own purpose.

**Why this priority**: It is what makes regression replay actionable in a development workflow rather than a manual
button someone has to remember to click; it depends on Story 3's batch replay already working.

**Independent Test**: Run the CI script against a target with only-fixed replayable runs (or none at all) and
confirm it exits zero; against a target with at least one still-vulnerable replay and confirm it exits with the
"still vulnerable" code regardless of any inconclusive results also present; against a target with no
still-vulnerable result but at least one inconclusive one and confirm it exits with the distinct "inconclusive"
code; and against an unreachable API, an unknown target, and a target whose preconditions refuse the batch, and
confirm each exits with the distinct "usage/API error" code. Confirm the script never prints attack text, reply
text, the target's URL, or any header value, in any case.

**Acceptance Scenarios**:

1. **Given** a target whose batch replay comes back with every entry fixed, or with no replayable runs at all,
   **When** the CI script runs against it, **Then** it exits with status `0`.
2. **Given** a target whose batch replay comes back with at least one entry still vulnerable, **When** the CI
   script runs against it, **Then** it exits with a status reserved for "still vulnerable", whatever else the batch
   also contains.
3. **Given** a target whose batch replay comes back with no entry still vulnerable but at least one inconclusive,
   **When** the CI script runs against it, **Then** it exits with a distinct status reserved for "inconclusive" —
   never status `0`.
4. **Given** the API is unreachable, the named target does not exist, or the batch is refused for a precondition
   (permission, terms, an already-running run, or too many replayable runs for the cap), **When** the CI script
   runs, **Then** it exits with a distinct status reserved for that class of error, printing why.
5. **Given** any of the above, **When** the script's output is read, **Then** every line names the source and
   replay run ids, the attack family, the outcome, and whether each of the two runs' verdicts is hard evidence or
   a judge opinion, and the summary line states whether the batch was complete — never attack text, reply text,
   the target's URL, or a header value, in any line.
6. **Given** a target whose batch stopped early (a concurrent-run collision, or one replay's own unexpected
   failure) with no still-vulnerable entry among those completed, **When** the CI script runs against it,
   **Then** it exits with the same "could not conclude the target is fixed" status scenario 3 uses — an
   incomplete result is never treated as a pass.

---

### Edge Cases

- **The source run's target no longer exists**: the source run is gone too (deleting a target removes its runs), so
  the replay action reports "not found", exactly as opening a deleted run does today.
- **The target's canaries changed since the source ran**: the replay is scored against the canaries configured
  *now* — a canary added since the source ran can turn a reply that would once have been "unclear" into a confirmed
  success, and a canary removed since then can no longer match. This is intended: a replay checks the attack
  against the target as it stands today.
- **An adaptive source has more recorded messages than the current adaptive turn limit allows**: the replay sends
  up to that current limit and no further; because not every recorded message was sent and judged, the outcome is
  **inconclusive**, never guessed as fixed.
- **A multi-turn source's replayed early turns draw different replies than the original run did**: the later
  recorded messages were written to continue a conversation the *original* target produced, so they may no longer
  fit what today's target actually says; a clean "failed" verdict on every sent turn does not by itself prove the
  attack is fixed unless the source's own winning turn — the one its original run actually succeeded at — was
  itself sent and judged failed (FR-014). A **multi-message** source with no recorded winning turn (defensive;
  not reachable through normal operation) can never be scored fixed; it is always **inconclusive**. A
  single-message source has no such check at all, regardless of mode: a single-turn run never records a winning
  turn at all, while an adaptive run that succeeded on its very first turn does record one — either way, with
  only one message recorded, the check is skipped and that one message alone decides the outcome, exactly as
  before this rule existed.
- **No judge is configured when the replay runs** (it may have been configured when the source ran): the canary
  check still applies to every resent message; without a judge and without a canary match, the outcome is
  **inconclusive** (there is no way to call it fixed with certainty).
- **The judge configured at replay time differs from the one the source used**: expected and shown as-is — the
  side-by-side names each run's own judge model and judge prompt version, which may legitimately differ.
- **A recorded attacker message was masked when it was stored** (an adaptive run masks secret values before storing
  a turn): it is resent exactly as stored, masked value included; the replay never attempts to unmask or
  reconstruct it, even if the target's current auth header value has since changed.
- **Replaying a replay**: refused before anything is sent, naming the run's own source so the user can replay that
  one instead.
- **A batch replay's single entry collides with a genuinely concurrent run on the same target** (another browser
  tab, or the CI script and a user acting at the same moment), **or one entry's own replay fails with an
  unexpected error**: either way, the batch stops at that point rather than recording a guessed outcome for the
  entry in question, and reports itself incomplete — every entry finished so far (including, for the
  unexpected-error case, that entry itself, recorded inconclusive), which source runs were never reached, and
  why — never silently finishing short as if nothing were missing, and never answered as an error response of
  its own.
- **A finished run with a verdict of "succeeded" but that never actually sent a message** (not possible through
  normal operation, but refused defensively): not eligible for replay, same as an unanswered run.
- **Viewing a replay run from the target's run list**: it appears there like any other run, tagged with its mode
  and a link to its source, and opening it shows the full side-by-side, not just its own result.
- **A replay's own run is itself later a candidate for a future batch or single replay**: it never is — a batch
  never includes replay-mode runs, and a direct replay request against one is refused (see above).
- **The source run was itself produced by an A/B experiment (006/007)**: it is replayable exactly like any other
  succeeded run — no special case. The replay itself is never attributed to that (or any) experiment or arm; it is
  its own, plain run.

## Requirements *(mandatory)*

### Functional Requirements

**What a replay sends**

- **FR-001**: A replay MUST re-send the source run's recorded attacker message(s) verbatim — byte for byte as
  stored — and, for a source with more than one recorded message, in their original order. Nothing about the
  message text MUST be regenerated, edited, unmasked, or reconstructed; a value that was masked when it was stored
  MUST remain masked when it is resent.
- **FR-002**: A replay MUST NOT construct or call any attacker model, for any message it sends, regardless of
  whether the source run was single-turn or adaptive.
- **FR-003**: A replay MUST be sent to the source run's own target, using that target's current connection settings
  (URL, method, headers resolved from the vault, body template, response path) — never a different target, and
  never the settings as they were when the source ran if they have since changed.

**Which runs can be replayed**

- **FR-004**: Only a finished run whose mode is `single_turn` or `adaptive` (never `replay`), whose verdict is
  succeeded, and that has at least one recorded attacker message, MUST be eligible for replay. Kestrel MUST check
  eligibility before sending anything and refuse an ineligible run with exactly one of these reasons, word for
  word: a run still in progress — **"A run still in progress can't be replayed."**; a finished run that did not
  succeed, whether its verdict was failed, unclear, or it never reached a verdict because sending it failed —
  **"Only a succeeded run can be replayed."**; a succeeded run with no recorded attacker message (defensive; not
  reachable through normal operation) — **"This run has no recorded message to resend."**
- **FR-005**: A request to replay a run whose own mode is `replay` MUST be refused before anything is sent, with
  exactly this message, naming that run's own source run id (N) so the user can replay the original instead of a
  replay of it: **"This run is itself a replay of run #N."**
- **FR-006**: Before claiming a replay's run row, Kestrel MUST check the same preconditions a normal run checks on
  the same target, refusing with the exact same wording a normal run already uses: the permission box is
  confirmed (**"Tick the permission box and save the target before attacking it."**), the current terms of
  service are accepted (**"The terms of service have changed; read them and tick the box again."**), and no other
  run (of any mode) is already in progress on that target (**"A run against this target is already in
  progress."**).

**Scoring a replay**

- **FR-007**: Each reply a replay receives MUST be scored exactly as a live run scores a reply: the canary check
  first (a match is hard evidence of success, decided without the judge), and the judge only when no canary
  matched.
- **FR-008**: A replay of a single-turn source MUST be judged the same way a single-turn run is judged — the attack
  message and its reply alone. A replay of an adaptive source MUST be judged per resent turn the same way the
  adaptive loop judges a turn — with the conversation built from the replay's own messages and replies so far
  (never the source run's original replies).
- **FR-009**: A replay MUST use the judge currently configured (its current model and its active prompt), not
  whatever judge configuration was in effect when the source ran.
- **FR-010**: A replay of an adaptive source MUST stop sending further recorded messages as soon as one succeeds (a
  canary match or a judge success) — mirroring a live adaptive run's own stop-at-first-success behavior — and MUST
  record which of the source's recorded messages were never sent as a result.
- **FR-011**: A replay's turn count MUST never exceed the adaptive turn limit currently configured, even when the
  source run recorded more messages than that; when the current limit is reached before every recorded message was
  sent, the remaining ones MUST be left unsent and the replay MUST NOT be reported as fixed.

**The outcome**

- **FR-012**: Every finished replay MUST be assigned exactly one outcome against its source: **fixed**, **still
  vulnerable**, or **inconclusive**. The outcome MUST be recorded on the replay's own run and MUST be one of these
  three values.
- **FR-013**: The outcome MUST be **still vulnerable** when any resent message succeeded (a canary matched, or the
  judge returned a success verdict, on any turn the replay sent).
- **FR-014**: The outcome MUST be **fixed** only when every one of the source's recorded messages was sent and
  scored, none succeeded, and the judge returned a failure verdict on every turn it judged (no canary match and no
  judge error, no "unclear" verdict, and no message left unsent). For a source with **more than one** recorded
  message, "fixed" additionally requires that the source's own **winning turn** — the turn its own run succeeded
  at (`runs.succeeded_turn`) — was itself sent and judged **failed** by the judge, never inferred from a canary
  miss alone: the source's later recorded messages were written for replies the *original* target gave, so a
  replay's earlier turns can draw different replies from today's target and leave the later ones no longer
  fitting the conversation that produced them, and an all-"failed" judge run proves nothing about the actual
  attack if the one turn that mattered was never genuinely re-tested. A multi-message source with no recorded
  winning turn MUST be **inconclusive**, never fixed (fail closed; FR-015). A single-message source is unaffected
  by this addition, since its one message is always its own winning turn. A multi-turn replay re-tests the
  source's recorded messages, not a fresh adaptive attack: "fixed" for such a source means that recorded sequence,
  including its own winning message, no longer succeeds today — not that the target would resist a new adaptive
  attack built from scratch.
- **FR-015**: The outcome MUST be **inconclusive** in every other case — including, but not limited to: a message
  that failed to send; no judge configured and no canary match; a judge error or an "unclear" judge verdict on any
  turn; the run's time limit reached, or the current adaptive turn or token limit reached, before every recorded
  message was sent and scored; or any unexpected failure that interrupts the replay.
- **FR-016**: The user-visible labels for the three outcomes MUST be exactly "fixed", "still vulnerable", and
  "inconclusive".

**Comparing the replay to its source**

- **FR-017**: For a finished replay, Kestrel MUST be able to show the source run and the replay side by side,
  naming for each: its overall verdict, whether that verdict is hard evidence (a canary) or a judge opinion, the
  judge model and judge prompt version behind it (when a judge was used), and — for a source with more than one
  recorded message — the per-message verdict, with any message the replay never sent shown with the exact marker
  **"not sent"**. The comparison's two columns MUST be headed by each run's own identity — **"Source (run #N)"**
  and **"Replay (run #M)"** (N, M = each run's own id) — and its rows MUST be labelled, in order, **"Verdict"**,
  **"Hard evidence"**, **"Judge model"**, **"Judge prompt"**, then one row per recorded message labelled **"Turn
  k"** (k = the message's position, 1-based; exact labels — the agentic QA platform generates Playwright tests
  from this spec, so these strings MUST be stable).
- **FR-018**: The side-by-side comparison MUST need no attack text or reply text beyond what a run's own page
  already shows; it MUST NOT require or display anything new in that regard.
- **FR-019**: Opening a replay run on its own MUST show its own result exactly as any other finished run's result is
   shown (its verdict, evidence, and — for an adaptive source — its turn-by-turn conversation), plus its recorded
   outcome against its source and a reference back to the source run.

**Recording a replay**

- **FR-020**: A replay MUST be stored as its own run, distinguishable from a normal run by its mode, and linked to
  the run it replayed.
- **FR-021**: A replay's run MUST carry the attack identity it is testing — the attack family, OWASP category, and
  the seed attack's id, title and text — copied from its source run, never recomputed or re-picked.
- **FR-022**: A replay's run MUST record no attacker model (it used none) and MUST record the judge model and
  judge-prompt-version provenance behind its own verdict exactly as a normal run does — on the run for a single-turn
  replay, and on the run and on each judged resent message for an adaptive replay — using the judge configuration
  active at replay time, never the source's.
- **FR-023**: A replay of an adaptive source MUST record each sent message as its own turn, the same way an
  adaptive run's conversation is recorded today, and the attacker-prompt-version provenance of each resent message
  MUST be copied from the source's matching turn (it names what produced that text; nothing produced it anew).
- **FR-024**: A replay's "was memory written" status MUST always be recorded as "not attempted" — never as
  succeeded or failed, since a replay never attempts a write-back (see FR-026).

**Leaving no trace in memory or the report**

- **FR-025**: A replay MUST NOT query the shared pattern pool or a target's memory for any kind of background or
  hint, under any outcome.
- **FR-026**: A replay MUST NOT write to the shared pattern pool or a target's memory, under any outcome — not a
  new pattern, not a raised hit count on an existing one, not a memory record.
- **FR-027**: A target's report of findings MUST exclude every replay run from its findings, its per-category
  counts, and its fix-recommendation generation; a replay MUST NOT create or imply a duplicate finding for a source
  that is already reported. The same exclusion MUST apply to the run page's own headline summary counts (how many
  of the target's runs are confirmed and how many are suspected): a replay run MUST NOT be counted there either —
  replays are re-checks, not findings, wherever a finding is tallied.

**Batch replay**

- **FR-028**: Kestrel MUST offer one action that replays every currently-replayable run of one target, and MUST
  never include a run whose mode is already `replay` in that set.
- **FR-029**: A batch replay MUST process its runs one at a time, oldest first (by when each source run started),
  never more than one in progress on the target at once. Its own preconditions (permission, terms, the cap, and
  that no other run is already in progress when it starts) MUST be checked once, before the first message of the
  batch is sent, and refused as a whole on failure. The batch MUST instead **stop partway through**, without
  being refused as a whole and without guessing an outcome for the entry in question, in either of two cases: a
  later entry's own claim is refused because a genuinely concurrent run started on the target after the batch
  began; or one entry's own replay fails with an unexpected error (recorded inconclusive on that entry's own run,
  the same way a single replay's own unexpected failure always is, logged by class and never by message — FR-015).
  In both cases the batch's result MUST say it is incomplete, why, and which source runs it never reached, and
  MUST NOT be reported as an error response of its own — the failure belongs to the one entry, never to the
  batch request as a whole.
- **FR-030**: A batch replay MUST result in exactly one entry per source run it actually processed, each naming
  the source run, the replay it produced, the attack family, both runs' verdicts, whether each of those verdicts
  is hard evidence or a judge opinion, and the computed outcome, plus a count of entries per outcome; the counts
  MUST always sum to the number of entries. The result MUST also state whether the batch completed — every
  replayable run at the moment it started was processed — or stopped early (FR-029), and, when it stopped early,
  which source runs were never reached.
- **FR-031**: A batch replay MUST be bounded by a configurable maximum number of replayable runs per batch
  (default 20; a run produced by an A/B experiment counts toward it like any other replayable run); when a target
  has more replayable runs than that maximum, Kestrel MUST refuse the entire batch before sending any message,
  rather than silently replaying only some of them, and the refusal MUST state the replayable count, the
  configured cap, and that the cap is configurable.
- **FR-032**: A batch replay's per-run turn count MUST still never exceed the adaptive turn limit currently
  configured, and each run within it MUST still honor the same per-run time limit a single replay or a normal run
  honors.
- **FR-033**: A target with zero currently-replayable runs MUST produce a batch result with zero entries and zero
  counts, not a refusal and not an error.

**A script for continuous integration**

- **FR-034**: Kestrel MUST provide a script, runnable in a CI pipeline, that calls the running Kestrel API the same
  way the UI does (the same API address and access-token settings) to batch-replay one named target and report the
  result.
- **FR-035**: The script MUST print one line per replay entry — naming the source and replay run ids, the attack
  family, the outcome, and each run's own evidence kind, source and replay named separately (canary or judge; or,
  for the one entry whose own replay crashed, that it has none) — and one summary line naming the outcome counts
  and the batch's completeness, and MUST NOT print attack text, reply text, the target's URL, or any header value
  under any circumstance.
- **FR-036**: The script MUST exit with status `1`, reserved for "at least one entry is still vulnerable",
  whenever that is true — whether or not the batch completed (FR-029/FR-030) — taking priority over everything
  else. Short of that, the script MUST exit with status `0` only when the batch **completed** and every entry is
  fixed, or the target had nothing replayable; with status `2` in every other case short of status `1` —
  reserved for "could not conclude the target is fixed" — which MUST include a batch that stopped early
  (`complete` is false) even when every entry completed so far was fixed, exactly as it includes a completed
  batch with at least one inconclusive entry: an incomplete result is "could not tell", never "passed" (a CI
  gate built on this script MUST NOT pass when the result could not be determined). The script MUST exit `3` for
  a usage problem or an API-level failure (the API unreachable, an unknown target, or the batch refused for a
  precondition, including the batch-size cap of FR-031).
- **FR-037**: The script's exit-status meanings MUST be documented in its own `--help` output and in the feature's
  quickstart guide.

**Exposure through the API and the UI**

- **FR-038**: Kestrel MUST expose: an action to replay one named run, an action to batch-replay one named target,
  and, on a run's own detail, its replay-specific fields (its source run, its outcome, and the data needed for the
  side-by-side) when that run is a replay. Both actions MUST stay synchronous — the request completes only once
  every message has been sent and scored (or the action refused) — the same way starting a normal run does today,
  with no separate poll-for-progress step.
- **FR-039**: A target's run listing MUST show a replay run's mode with the exact label **"replay"** (never
  folded into a generic "single-turn"/"adaptive" label), in a listing that carries a **"Source"** column naming
  the source run for a replay row and left blank for every other row.
- **FR-040**: The UI's run page MUST offer a button labelled exactly **"Replay"**, rendered for **every** run
  shown on the run page, not just every *finished* one — a run still in progress shows the button disabled with
  the "in progress" reason as its caption (FR-004), and one that ended at a failure step shows it too, alongside
  the page's own error display for that step — never omitted because a run's result, or lack of one yet, renders
  through a different path. A run that is not currently eligible for replay MUST make that visibly clear — the
  button shown **disabled, with the reason as its visible caption** — rather than silently doing nothing when
  clicked, using exactly one of the seven reason strings FR-004 to FR-006 define (the "not succeeded" reason
  covering a failed, an unclear, or a failed-to-send verdict alike; the "another run in progress" reason covering
  a different, concurrent run on the same target, distinct from this run's own "in progress" case).
  A source whose recorded turns exceed the currently configured adaptive turn limit MUST still show an
  **enabled** button (it is still eligible; FR-004) alongside this exact advisory caption: **"This source
  recorded more turns than the current adaptive limit; the replay can end at best still vulnerable or
  inconclusive."** — the replay still runs, sending only up to the current limit, exactly as FR-011 and the Edge
  Cases describe.
- **FR-041**: After a replay finishes, the run page MUST show a line reading exactly **"Outcome: "** followed by
  the outcome's label (FR-016) — for example "Outcome: fixed" — and the side-by-side comparison required by
  FR-017; opening a replay run from the target's run list MUST show the same outcome line and comparison, with a
  link back to the source run labelled exactly **"Replay of run #N"** (N = the source run's id). For a replay
  whose source has **more than one** recorded message, the page MUST also show, directly under the outcome line
  (both right after the replay runs and whenever the replay run is later opened), exactly this caption: **"A
  multi-turn replay re-tests the recorded messages, not an adaptive attack."** — never shown for a replay of a
  single-message source. The API decides whether the caption applies and the comparison carries the caption text
  (or null); the UI only displays what it is given (FR-042).
- **FR-042**: The UI MUST reach every replay capability only through the API — no replay-specific logic MUST live
  in the screen itself. In particular, whether a run is currently replayable, its blocked reason when it is not
  (FR-004 to FR-006), and its advisory when it is replayable but may end inconclusively (FR-040) MUST all be
  computed by the API — from the run's own fields, its target's current permission and terms state, and the
  currently configured adaptive turn limit, never from the run's own fields alone — and the UI MUST only display
  the values the API returns, never re-derive any of them.

**Logging**

- **FR-043**: A single replay MUST be logged as its own run through the existing structured-event mechanism: a
  start event naming its mode as replay and naming the source run it is replaying, one event per message it sends,
  the same per-request and per-judge-call events a normal run emits, and an end event carrying the computed
  outcome alongside the fields a normal run's end event already carries.
- **FR-044**: A batch replay MUST be logged with its own start event (naming the target and how many runs it will
  process) and end event (naming how many finished with each outcome).
- **FR-045**: No log line produced by a replay or a batch replay MUST ever carry attack text, reply text, a judge's
  reason or progress note, the target's URL, the target's display name, or a header value — the same rule every
  other run's log lines already follow.

**Hard rules and bounds**

- **FR-046**: No attack-prompt text MUST appear in this feature's own code, tests, fixtures, or commits; tests MUST
  use neutral placeholder messages, exactly as every other feature's tests do.
- **FR-047**: No auth header value, API key, or the target's URL or display name MUST ever reach the judge during a
  replay — the judge receives only the attack text and the reply, or the per-turn conversation, exactly as it does
  for a normal run.
- **FR-048**: This feature MUST add no new required dependency to the project.
- **FR-049**: Everything this feature does not name MUST be unchanged: a normal (non-replay) run's behavior,
  scoring, storage and logging; the shared pattern pool and per-target memory for every non-replay run; the OWASP
  report for every non-replay run; the three hard caps, the permission gate and the terms gate (Principle VIII).

**Documentation and process**

- **FR-050**: The feature's implementation pull request (never the spec-only pull request) MUST mark regression
  replay as done in the project's roadmap document.

### Key Entities

- **Source run**: a past, finished, non-replay run with a succeeded verdict and at least one recorded attacker
  message — the thing a replay re-tests.
- **Replay run**: a run whose mode marks it as a replay, linked to its source, carrying the source's attack identity
  (family, OWASP category, seed prompt), no attacker model, and its own verdict, evidence, judge provenance and
  (for an adaptive source) its own turn-by-turn conversation, produced by resending the source's recorded messages.
- **Outcome**: the one headline result of a finished replay against its source — fixed, still vulnerable, or
  inconclusive.
- **Comparison**: the source run and its replay shown side by side — each one's overall verdict, evidence kind,
  judge model and judge prompt version, and (for a multi-message source) each message's own verdict, with an unsent
  message marked as such.
- **Batch replay**: one action that replays every currently-replayable run of a target, oldest first, yielding one
  entry per source plus a count of entries per outcome, bounded by a configurable maximum entries per batch.
- **Replayable run**: a finished, non-replay run with a succeeded verdict and at least one recorded attacker
  message — the set a single replay accepts and a batch replay draws from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every replay the offline test suite drives, across both single-turn and adaptive sources, the
  target receives exactly the source's recorded message(s), verbatim and in original order, and 0 attacker-model
  calls are made.
- **SC-002**: Across a test matrix covering a target that now fails every resent message, one that still falls for
  at least one, one that fails to answer, one with no judge configured, one that hits the current turn limit
  before finishing, one whose **first** resent message comes back an unclear verdict or a judge error while every
  later one is cleanly judged failed, and a multi-message source whose own winning turn is either never reached or
  reached but not judged failed, every replay is assigned exactly one of fixed / still vulnerable / inconclusive,
  and each matches the rule in FR-013 to FR-015 100% of the time — the unresolved-early-turn case and the
  winning-turn case both scoring **inconclusive**, never fixed: neither an unresolved early turn nor an unproven
  winning turn is ever hidden behind other turns' clean failures.
- **SC-003**: Across every replay and batch replay the offline test suite drives, the experience store records 0
  calls of any kind (query or write), under every outcome.
- **SC-004**: Generating a target's OWASP report before and after replaying one of its existing findings yields an
  identical finding count, coverage rows and recommendation-call count.
- **SC-005**: A request to replay a run that is in progress, not succeeded, has no recorded message, or is itself a
  replay is refused before any message is sent, 100% of the time, naming the reason (and, for a replay of a
  replay, the original source run id).
- **SC-006**: A batch replay of a target with N replayable runs, run to completion, produces exactly N comparison
  entries, oldest source first, with outcome counts that sum to N, and reports itself complete; a target whose
  replayable-run count exceeds the configured cap has its whole batch refused before any message is sent, 100%
  of the time; a batch that stops early — because a later entry's claim collides with a concurrent run, or
  because one entry's own replay fails unexpectedly (`replay_failed`) — reports itself incomplete, naming every
  source run it never reached, and is never scored as if it had finished.
- **SC-007**: The CI script exits `0` only on a **completed** all-fixed or nothing-to-replay result, a code
  reserved for "still vulnerable" whenever at least one entry is (completed or not), a distinct code reserved for
  "could not conclude the target is fixed" both when no entry is still vulnerable but at least one is
  inconclusive and when the batch itself did not complete, and a further distinct non-zero code for a usage or
  API-level failure — each case verified directly, including an incomplete, all-fixed-so-far batch never scoring
  as `0`, and the "still vulnerable" code confirmed to win over every other case.
- **SC-008**: 0 lines logged by a replay or a batch replay, across the offline test suite, carry attack text, reply
  text, a judge reason or progress note, the target's URL, the target's display name, or a header value.
- **SC-009**: Kestrel's required dependencies are unchanged after this feature ships.
- **SC-010**: One end-to-end scenario passes against the owned HS-code target: a real run is sent, and — because
  a live model's own verdict on the day is not guaranteed to be "succeeded" — the test's own temporary database
  row is then promoted to "succeeded" directly (a documented, test-only step; never through any code path a real
  user action can reach) so it is replayable; replaying it through the real API gives a result with the right
  *structure* — a new run linked to the source, one of the three outcome labels, the judge prompt version
  recorded, zero attacker-model calls, zero experience-store writes, and the side-by-side readable afterward. The
  scenario does not assert which of the three outcomes the live model's reply to the replay produces, since that
  depends on the model's behaviour on the day, not on Kestrel.

## Assumptions

- Builds on 001/002 (single-turn runs and canaries), 003 (the adaptive loop, reused to drive a replay's own
  turn-by-turn sending and judging), 004/011 (the experience store and its retrieval path, which a replay must
  never call), 005 (the OWASP report, which a replay must never appear in), 009 (prompt-version provenance,
  recorded on a replay exactly as on a normal run) and 010 (the structured-event mechanism, reused for a replay's
  own lines). All are reused unchanged except where this spec narrows them (FR-025 to FR-027).
- "Current settings" means: the target's connection settings and canaries as configured right now, the judge
  currently configured, and the adaptive turn/token/time limits currently configured. It does not mean the
  attacker configuration, since a replay never involves an attacker model.
- A replay's own hard caps (turn count, token budget, time limit) follow the same currently-configured limits a
  live run follows, additionally bounded by how many messages the source run actually recorded — whichever is
  smaller.
- The batch-replay cap (FR-031, default 20) is its own configurable setting
  (`KESTREL_REPLAY_BATCH_MAX_RUNS`), validated the same way Kestrel's other positive-integer settings are and
  reported on the configuration endpoint beside the other hard caps (Clarifications, 2026-11-19).
- FR-025/FR-026 are a deliberate, named deviation from Principle V ("a run that does not write back is a bug"):
  a regression replay must not change the memory or shared patterns it would otherwise learn from, because that
  would double-count a success the pool already holds and bias later attacks on unrelated targets with a
  re-check of old material, not a new one — the owner's own requirement states this directly. The deviation is
  total (every replay, every outcome), not a silent gap (`memory_written` is always "not attempted", never a
  failure), and is recorded as such in the implementation plan's Complexity Tracking, the same way the 007 A/B
  harness recorded its own cold-arm write-back skip.
- A masked value inside a replayed message is resent exactly as stored; the replay process is never given the
  means to unmask it, matching Principle IV (secrets never leave the vault).
- Nothing about how a *normal* run is scored, stored, logged, or written back changes; this feature only adds a
  new kind of run and the actions that create one.
- A multi-turn replay re-tests its source's recorded messages, not a fresh adaptive attack: "fixed" for a
  multi-turn source means that recorded sequence, including its own winning turn, no longer succeeds against
  today's target — it does not mean the target would resist a new adaptive attack built from scratch (FR-014).

## Out of Scope

- Editing, tweaking, or regenerating any part of a replayed message; a replay is always byte-for-byte verbatim, or
  it is not a replay (it would be a new attack).
- Replaying a source's messages against a target other than the one it originally attacked, or against a canary
  set other than the target's current one.
- Any new attacker-model-driven run derived from a past finding; that is simply a new run, already covered by
  existing features.
- Scheduling or automatically triggering a replay or batch replay on a timer; the CI script is invoked explicitly
  by a pipeline, not by a scheduler Kestrel itself runs.
- A new section, chart, or summary in the OWASP report for regression results; replay results are deliberately
  excluded from that report (FR-027), not given a new place inside it.
- Any change to the shared pattern pool's or a target's memory's existing behavior for non-replay runs.
- A UI control for editing the batch-replay cap or the CI script's exit-status numbers; both are configuration, not
  a form field.
