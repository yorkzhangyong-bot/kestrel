# Feature Specification: A/B Harness

**Feature Branch**: `007-ab-harness`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Feature 007: A/B harness. Goal: answer 'does X make attacks more effective?' with evidence, by running the same campaign under two configurations against one owned target and comparing outcomes."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a two-arm experiment and read the comparison (Priority: P1)

A red-teamer wants to know whether a change — a different attacker model, retrieval turned on, a larger token budget — actually makes attacks on their own agent more effective. They define a **campaign** (a target, which attack families, a mode, and how many repetitions), set up two **arms** that differ in exactly the thing they are testing, and start the **experiment**. Kestrel runs the campaign under arm A and arm B and shows a side-by-side comparison of the outcomes.

**Why this priority**: This is the feature — one controlled comparison answering "does X help?" with real runs. Without it, nothing else matters.

**Independent Test**: Define a campaign and two arms that differ in one field, start the experiment, and confirm a side-by-side result appears with each arm's outcomes and the difference between them.

**Acceptance Scenarios**:

1. **Given** an owned target, a chosen set of families, a mode, and a repetition count, and two arms that differ in at least one field, **When** the experiment is started, **Then** Kestrel runs the campaign under both arms and records each run against its arm.
2. **Given** two arms that are identical in every field, **When** the user tries to start the experiment, **Then** it is rejected with a message that the arms must differ.
3. **Given** a finished experiment, **When** the user opens its result, **Then** a side-by-side table shows arm A and arm B with the recorded diff between the arms and the difference in outcomes.

---

### User Story 2 - Trust the comparison (evidence separation and honest statistics) (Priority: P2)

The user needs the comparison to be trustworthy: confirmed successes (hard evidence) must not be mixed with suspected ones (a judge's opinion), and a difference must not look meaningful when the sample is too small to say so.

**Why this priority**: A misleading comparison is worse than none; the honesty rules (Principle II, small-sample caution) are what make the result worth acting on.

**Independent Test**: Run a small experiment and confirm each arm's success rate is split into confirmed and suspected, and that the comparison carries a significance indicator and a small-sample caveat rather than a bare percentage.

**Acceptance Scenarios**:

1. **Given** an arm's runs, **When** its result is shown, **Then** the success rate is reported twice — confirmed (a canary/hard-evidence match) and suspected (a judge verdict) — never as a single conflated number.
2. **Given** a comparison of two small samples, **When** the difference is shown, **Then** it carries a significance indicator (a confidence interval per rate and/or a two-proportion comparison) and a caveat that the sample is small.
3. **Given** per-arm results, **When** the report is read, **Then** it includes mean turns to success, mean tokens and estimated cost, a per-family breakdown, and a per-OWASP-category breakdown.

---

### User Story 3 - Control warming and order between arms (Priority: P2)

Because every run can write learned memory and patterns to the shared store (feature 004), arm A's runs could "warm" arm B and confound a retrieval-on-vs-off comparison. The user can run an arm **cold** — with write-back disabled — so it is not warmed by the other arm, and the experiment records the order the arms ran and which arm(s) wrote back.

**Why this priority**: Without warming control, the headline comparison (retrieval on vs off) is confounded; this makes the experiment a fair test.

**Independent Test**: Run a two-arm experiment with one arm set cold (write-back off), and confirm the experiment records the arm order and that the cold arm did not write back (so it was not warmed by the other arm).

**Acceptance Scenarios**:

1. **Given** an experiment option to disable write-back for a cold arm, **When** the experiment runs, **Then** that arm's runs do not write memory or patterns to the store.
2. **Given** a finished experiment, **When** its record is read, **Then** it states the order the arms ran and which arm(s) applied write-back (the warming applied).
3. **Given** the default (write-back enabled), **When** the experiment runs, **Then** each run writes back as an ordinary feature-002/003/004 run does.

---

### User Story 4 - Bounded and safe experiments (Priority: P2)

An experiment is many runs and real model spend, so it must be bounded and must never carry secrets. The user sets hard caps; when a cap is reached the experiment stops cleanly and still returns a usable partial comparison. Arms hold only model names and settings — never the target's credentials.

**Why this priority**: Unbounded spend or a leaked credential would make the feature unusable or unsafe (Principles VIII and IV).

**Independent Test**: Start an experiment with a low cap and confirm it stops within the wall-clock limit, reports partial results naming the cap that stopped it, and that no arm or output contains a target header or key.

**Acceptance Scenarios**:

1. **Given** a maximum run count, a maximum total token budget, and a wall-clock limit, **When** any cap is reached, **Then** the experiment stops cleanly, returns the partial results gathered, and records which cap stopped it.
2. **Given** an arm configuration, **When** it is created, stored, or shown, **Then** it contains only model names and settings — no target auth header value, key, or other secret.
3. **Given** a running experiment, **When** the user asks for its status, **Then** progress (runs completed vs planned, spend so far) is reported.

---

### User Story 5 - Read and share an OWASP-mapped report (Priority: P3)

The user wants to share the result. The experiment report names both arms' attacker models and versions, maps every result row to an OWASP class, and can be downloaded in the same formats as the feature 005 report.

**Why this priority**: Sharing and auditing matter, but the comparison (US1) and its honesty (US2) come first.

**Independent Test**: Open a finished experiment's report, confirm it names both attacker models and versions and maps each row to an OWASP class, and download it in the feature 005 formats.

**Acceptance Scenarios**:

1. **Given** a finished experiment, **When** the report is produced, **Then** it names both arms' attacker models and versions and their judge models (Principle III).
2. **Given** the per-category section, **When** it is read, **Then** every row is mapped to an OWASP LLM Top 10 class (Principle VI).
3. **Given** a finished experiment, **When** the user downloads the report, **Then** it is available in Markdown and HTML (the feature 005 formats).

---

### Edge Cases

- **Identical arms**: rejected before the experiment starts (the arms must differ in at least one field).
- **A cap hit mid-campaign**: the experiment stops cleanly at a run boundary and reports partial results, naming the cap; it does not leave a run half-finished or the target locked.
- **An arm's model is unavailable** (e.g. a blocked attacker model): the affected runs are recorded as failed-to-send (not silently dropped), and the arm result notes the shortfall rather than reporting a falsely low success rate.
- **Small or zero samples**: a comparison never shows a bare percentage difference without a significance indicator; a rate over zero runs is reported as "no data", not 0%.
- **Cost unknown for a model**: tokens are still reported; cost is marked unavailable for that model rather than guessed.
- **A single-turn arm vs an adaptive campaign mode**: the mode is a property of the campaign (shared by both arms); arms differ only in the listed arm fields, so both arms run the same mode.

## Clarifications

### Session 2026-10-29

- Q: At what level should the comparison compute its significance indicator? → A: Overall per arm — the confirmed (hard-evidence) success rate is the primary verdict (Principle II); per-family and per-OWASP are descriptive breakdowns only, with no per-cell significance test (per-cell N is too small to be meaningful).
- Q: Which significance method should the comparison use? → A: A Wilson score confidence interval for each arm's rate plus a two-proportion z-test for the difference, with a small-sample caveat below a fixed N (standard-library math, no new dependency).
- Q: How should the per-arm cost figure be computed? → A: A configured per-model price (per 1k tokens); cost = tokens × price. Tokens are always shown; cost is marked "unavailable" for any model whose price is not configured. No live billing lookup.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A campaign MUST consist of one target, a set of attack families (default: all families), a mode (single-turn or adaptive), and a repetition count N per family (default: 3).
- **FR-002**: An arm MUST be a named configuration of: attacker model, judge model, retrieval on/off (the feature-004 use-prior-experience switch), turn cap, and token budget.
- **FR-003**: An experiment MUST run exactly one campaign under exactly two arms (A and B); the two arms MUST differ in at least one field, and the experiment MUST record the diff between the arms.
- **FR-004**: Each run within an arm MUST be an ordinary run as defined by features 002/003/004 — stored, judged canary-first (hard evidence settles a run before any judge opinion), and, by default, writing back memory and patterns.
- **FR-005**: An experiment MUST support disabling write-back for a "cold" arm so that arm is not warmed by the other arm, and MUST record the order in which the arms ran and which arm(s) applied write-back.
- **FR-006**: For each arm, the result MUST report: success rate split into confirmed (hard evidence) and suspected (judge opinion) separately (Principle II); mean turns to success; mean tokens and estimated cost; a per-family breakdown; and a per-OWASP-category breakdown.
- **FR-007**: The comparison between the two arms MUST show the difference for each headline metric together with a significance indicator, computed at the overall-arm level (a Wilson confidence interval for each arm's success rate and a two-proportion z-test for the difference). The confirmed (hard-evidence) success rate is the primary comparison; the per-family and per-OWASP breakdowns are descriptive only and MUST NOT carry a per-cell significance test. The comparison MUST NOT present a bare percentage difference without a significance indicator when the sample is small.
- **FR-008**: An experiment MUST enforce hard caps — a maximum number of runs, a maximum total token budget, and a wall-clock limit — and when any cap is reached MUST stop cleanly, return the partial results gathered so far, and record which cap stopped it.
- **FR-009**: The experiment report MUST name both arms' attacker models and their versions, and the judge models used (Principle III).
- **FR-010**: The experiment report MUST map results to the OWASP LLM Top 10 in its per-category table (Principle VI).
- **FR-011**: An arm MUST carry only model names and settings — never a target auth header value, key, or any other secret (Principle IV); no secret may appear in an arm, an API payload, a report, or a log.
- **FR-012**: The system MUST provide operations to create an experiment, to get its status and progress while it runs, and to get its result when it finishes.
- **FR-013**: The screen MUST provide an Experiments view with an arm editor (both arms, with the fields of FR-002), live progress, and a side-by-side result table.
- **FR-014**: The experiment report MUST be downloadable in the same formats as the feature-005 report (Markdown and HTML) where applicable.
- **FR-015**: An experiment MUST run only against a single target the user is permitted to test (the target's existing permission gate applies, Principle VIII); a run that cannot proceed MUST be recorded, not silently dropped.
- **FR-016**: An experiment MUST be auditable: its stored record MUST retain the campaign, both arms and their diff, the per-run outcomes, the order and warming applied, and which cap (if any) stopped it.

### Key Entities

- **Campaign**: what is run — a target, the attack families (default all), the mode (single-turn or adaptive), and N repetitions per family (default 3). Shared by both arms of an experiment.
- **Arm**: a named configuration varied between A and B — attacker model, judge model, retrieval on/off, turn cap, token budget. Holds no secrets.
- **Experiment**: one campaign run under arm A and arm B, plus the warming option (cold-arm write-back), the hard caps, the run order, the status/progress, and the results. The unit a user creates, watches, and reads.
- **Run**: an ordinary attack run (features 002/003/004) tagged with its experiment and arm; stored, judged, and (unless the arm is cold) written back.
- **Arm result**: the per-arm aggregates — confirmed and suspected success rates, mean turns to success, mean tokens and estimated cost, per-family and per-OWASP-category breakdowns.
- **Comparison**: the per-metric difference between arms with its significance indicator (computed at the overall-arm level, confirmed rate primary) and small-sample caveat; per-family and per-OWASP differences are shown descriptively.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can define a campaign and two differing arms and start a two-arm experiment in a single action.
- **SC-002**: Every arm result reports success split into confirmed (hard evidence) and suspected (judge opinion); the two are never conflated into one success rate.
- **SC-003**: 100% of comparisons on a small sample carry a significance indicator and a small-sample caveat; zero comparisons present a bare percentage difference at small N.
- **SC-004**: When a cap is reached, the experiment stops within its wall-clock limit and still returns a usable partial comparison that names the cap that stopped it.
- **SC-005**: An experiment with a cold arm records that the arm did not write back, so it was not warmed by the other arm.
- **SC-006**: The experiment report names both attacker models and their versions, and every per-category row is mapped to an OWASP LLM Top 10 class.
- **SC-007**: No arm, API payload, report, or log contains a target auth value, key, or header.
- **SC-008**: The experiment report downloads in Markdown and HTML.
- **SC-009**: A two-arm experiment against the HS-code target (N=1, retrieval off vs on) completes end to end and produces a comparison.

## Assumptions

- **Significance note** (clarified 2026-10-29): the comparison uses a Wilson score confidence interval for each arm's success rate and a two-proportion z-test for the difference, with a small-sample caveat below a fixed sample threshold. The test is computed at the overall-arm level on the confirmed (hard-evidence) success rate as the primary verdict; per-family and per-OWASP breakdowns are descriptive only. Standard-library math, no new dependency.
- **Cost estimate** (clarified 2026-10-29): cost is estimated as tokens used × a configured per-model price (per 1k tokens); tokens are always reported, and cost is marked unavailable for any model whose price is not configured. No live billing lookup is performed.
- **Run order**: by default the experiment runs arm A's full campaign, then arm B's, recording the order; interleaving is not required. Warming between arms is governed by the cold-arm write-back option (FR-005).
- **Shared store**: runs use the existing single experience store (feature 004). For a clean retrieval-on-vs-off comparison, the user runs the write-back-sensitive arm cold; the experiment records the warming applied so a confounded run is visible, not hidden.
- **Reuse**: experiments reuse the existing run, judge, attacker, experience-store, and report-rendering capabilities (features 002–005); this feature adds the campaign/arm/experiment layer and the comparison, not new attack content.
- **Caps default**: the hard caps have sensible defaults (bounded runs, token budget, and wall-clock) that a user may lower; an experiment cannot be created without finite caps.

## Out of Scope

- More than two arms per experiment.
- Scheduling or recurring experiments.
- Cross-target experiments (an experiment runs against a single target).
- Statistical power planning or sample-size recommendation (the harness reports significance, it does not plan it).
- Any new attack content; experiments only run the existing attack library and loops.
