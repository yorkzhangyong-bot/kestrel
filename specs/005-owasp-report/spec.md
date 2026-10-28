# Feature Specification: OWASP-Mapped, Fix-Ready Report

**Feature Branch**: `005-owasp-report`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description:

> Feature 005: OWASP-mapped fix-ready report. A user who owns a registered target can generate a report that summarises every attack run against that target and tells them what to fix. Two formats (Markdown and HTML), downloadable from a new Report section in the Streamlit UI placed after Profile, and from an API endpoint. The Report section has a Generate report button, two download buttons, and a rendered preview. Contents, in order: a header (target name, purpose description, generation time, number of runs, attacker and judge models and token budget used — Principle III); an OWASP LLM Top 10 coverage table for the three classes Kestrel tests, each mapped to its attack family with run count and result ("not run yet" where no runs), plus an honest list of the seven classes not tested and why; a findings section with one finding per successful run (family, OWASP class, winning attacker message, the hard evidence or judge note that proved it, and a fix-ready recommendation); a section for failed and unclear runs, one line each; and a closing note on limitations, including that memory and learned patterns affect results. Recommendations are model-generated and marked as suggestions; hard evidence is quoted verbatim, never paraphrased. A target with no runs shows a clear empty state. Generating a report must never trigger a new attack or write to the experience store. Report content must not include target URLs, headers or secrets. Out of scope: per-run reports, PDF export, CSV export, scheduling, OWASP-first attack selection.

## Clarifications

### Session 2026-10-27

- Q: Which OWASP labels should the report use (the request labelled LLM06 "sensitive information disclosure")? → A: The code/OWASP 2025 labels — LLM01 Prompt Injection, LLM06 Excessive Agency, LLM07 System Prompt Leakage. "Sensitive Information Disclosure" is LLM02, one of the seven classes not tested.
- Q: Which model generates the fix-ready recommendations? → A: Reuse the configured judge model and key; without a judge key, findings omit recommendations with a clear note (FR-013).
- Q: How is recommendation generation bounded for cost? → A: One model call per successful run.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a report and read what happened (Priority: P1)

A vibe coder who has run some attacks against a saved target opens the new Report section (below Profile), clicks **Generate report**, and reads a rendered preview: a header, an OWASP coverage table, the findings, the failed/unclear runs, and a closing note on limitations. They download the report as Markdown or as HTML to keep or share. The report summarises every run against that target — it does not launch anything new.

**Why this priority**: This is the feature — turning the runs Kestrel already stored into one readable, shareable summary. It closes the loop from "I attacked my agent" to "here is what I found." Everything else refines what the report contains.

**Independent Test**: With a saved target that has several runs (including at least one success), generate a report and confirm the preview shows all five sections in order and that both the Markdown and HTML downloads contain the same content.

**Acceptance Scenarios**:

1. **Given** a target with runs, **When** the user clicks Generate report, **Then** a preview appears with, in order: the header, the OWASP coverage table, the findings, the failed/unclear runs, and the limitations note.
2. **Given** a generated report, **When** the user clicks the Markdown or the HTML download, **Then** a file in that format is downloaded with the same content as the preview.
3. **Given** a target with no runs, **When** the user opens the Report section, **Then** a clear empty state is shown ("No runs to report yet — attack this target first") and no report is generated.
4. **Given** the header, **When** the report is generated, **Then** it shows the target name, the purpose description (if set), the generation time, the number of runs, and the attacker and judge models and token budget recorded for this target's runs (Principle III).

---

### User Story 2 - Trust the findings and know what to fix (Priority: P2)

For each run that succeeded, the report shows a finding the user can act on: which attack family and OWASP class it belongs to, the attacker message that worked, the proof it worked (hard evidence quoted exactly, or the judge's note when there was no hard evidence), and a concrete, suggestion-marked recommendation for the target's system prompt or tool configuration.

**Why this priority**: A list of runs is not actionable; a finding with proof and a suggested fix is. This is what makes the report "fix-ready" (Principle VI). It depends on Story 1's report but is the part a user acts on.

**Independent Test**: With a target that has a canary-confirmed success and a judge-only success, confirm each produces one finding whose evidence is quoted verbatim (canary case) or shown as the judge's note (judge case), and whose recommendation is clearly labelled a suggestion.

**Acceptance Scenarios**:

1. **Given** a successful run confirmed by a canary, **When** its finding is rendered, **Then** the hard evidence is quoted verbatim — byte-for-byte as stored — and never paraphrased.
2. **Given** a successful run decided by the judge (no canary), **When** its finding is rendered, **Then** it shows the judge's note and marks the result as suspected, not confirmed (Principle II).
3. **Given** any finding, **When** its recommendation is shown, **Then** the recommendation is generated from the run data and is clearly marked as a suggestion to review, not a guaranteed fix.
4. **Given** a finding, **When** it is rendered, **Then** it names the attack family, the OWASP class, and shows the winning attacker message.

---

### User Story 3 - See honest OWASP coverage (Priority: P2)

The report states plainly what Kestrel did and did not test. A coverage table lists the three OWASP LLM Top 10 classes Kestrel tests, each with the attack family it uses, the number of runs and the result, marking families with no runs as "not run yet". A short section lists the seven classes Kestrel does not test and why, so the report never implies more coverage than it has.

**Why this priority**: An honest report that admits its limits is more trustworthy and avoids a false sense of security. It is core to the report's value but secondary to having findings at all.

**Independent Test**: With a target that has runs in some families but not others, confirm the coverage table shows run counts and results for the families with runs, "not run yet" for the families without, and that the report lists the seven untested OWASP classes each with a reason.

**Acceptance Scenarios**:

1. **Given** a target with runs in some families, **When** the coverage table is rendered, **Then** each of the three tested OWASP classes shows its family or families, its run count, and a result; a class with no runs in any of its families shows "not run yet".
2. **Given** any report, **When** the coverage section is rendered, **Then** it lists the seven OWASP LLM Top 10 classes Kestrel does not test, each with a short reason it is out of scope.

---

### User Story 4 - Safe, read-only reporting (Priority: P3)

Generating a report is inert: it never starts an attack, never sends anything to the target, and never writes to the experience store; it only reads what is already stored. The report contains no target URL, no auth headers and no secrets. The same report is available from an API endpoint for automation.

**Why this priority**: These are the guarantees that make the report safe to generate anytime and safe to share. They matter once reports exist but do not change what a report says.

**Independent Test**: Generate a report and confirm no request reaches the target, nothing is written to the experience store, and a known secret value used as an auth header appears nowhere in either output; fetch the same report from the API endpoint in both formats.

**Acceptance Scenarios**:

1. **Given** report generation, **When** it runs, **Then** zero requests are sent to the target and zero records are written to the experience store.
2. **Given** a report, **When** it is produced in either format, **Then** it contains no target URL, no auth header names or values, and no secret.
3. **Given** the API report endpoint, **When** it is called for a target, **Then** it returns the report in Markdown and in HTML.
4. **Given** a downloaded HTML report, **When** it is opened in a browser, **Then** attacker messages and replies that contain HTML or scripts are shown as text and are never executed or loaded.

---

### Edge Cases

- **No runs**: a clear empty state, no model calls, no file generated.
- **Runs but no successes**: the findings section says plainly that no attack succeeded; the failed/unclear section still lists each run; coverage still shows counts and results.
- **No recommendation model configured**: findings still show the family, winning message and evidence, with a clear note that no recommendation is available because no model is configured (the judge is already optional this way).
- **A family with runs that all failed**: its coverage row shows the run count with a "held / no finding" result, not "not run yet".
- **Hostile run content**: attacker messages, replies and judge notes can contain HTML, scripts, links or markdown; the HTML report escapes them so they render as text, and the Markdown preview shows them as code, never executed or fetched (as in feature 002, SC-007).
- **A success with no stored winning message** (e.g. an older run): the finding shows the seed prompt as the attacker message and notes the detail is unavailable, rather than failing.
- **Target deleted while generating**: generation stops with a clear "target not found", producing no partial file.
- **Regenerating**: a new generation reflects the runs at that moment and carries a fresh generation time; nothing from a previous report is stored or reused.
- **Verbatim evidence vs. masking**: "verbatim" means byte-for-byte as Kestrel stored the evidence, which is already masked of auth header values (feature 002); the report never un-masks.

## Requirements *(mandatory)*

Feature 005 reads what features 002–004 stored. It reuses the saved target, its runs and conversation turns, the family→OWASP mapping from the attack library, and the masking already applied to stored replies and messages. It adds no attack behaviour and writes nothing to the experience store.

### Functional Requirements

**Generating and delivering the report**

- **FR-001**: Users MUST be able to generate a report for one saved target on demand, from a Report section in the screen placed after the Profile section, with a Generate report control, a Markdown download, an HTML download, and a rendered preview of the report.
- **FR-002**: The report MUST be produced in two formats — Markdown and HTML — with the same content, and MUST be available both through the screen's downloads and through an API endpoint that returns it for a given target.
- **FR-003**: Generating a report MUST read only the target and its stored runs and conversation turns; it MUST NOT start any run, send anything to the target, or write to the experience store.
- **FR-004**: A report MUST be generated on demand and MUST NOT require new persistent storage; nothing from a prior report is kept or reused.

**Header (Principle III)**

- **FR-005**: The report MUST begin with a header showing the target name, the purpose description (when set), the generation time, the number of runs, and the attacker and judge models, the token budget, and the total tokens used recorded for this target's runs.

**OWASP coverage**

- **FR-006**: The report MUST include a coverage table of the three OWASP LLM Top 10 classes Kestrel tests, taking the class for each attack family from the attack library's canonical mapping: **LLM01 Prompt Injection** (direct injection and indirect injection), **LLM06 Excessive Agency** (tool-mediated exfiltration), and **LLM07 System Prompt Leakage** (system-prompt leak). Each row MUST show the family or families, the run count, and a result.
- **FR-007**: A family with no runs MUST be shown as "not run yet"; a class whose families all have no runs MUST be shown as "not run yet".
- **FR-008**: The report MUST include an honest section listing the seven OWASP LLM Top 10 classes Kestrel does not test (LLM02, LLM03, LLM04, LLM05, LLM08, LLM09, LLM10), each with a short reason it is out of scope.

**Findings (Principle VI)**

- **FR-009**: The report MUST include one finding for each run whose verdict is "succeeded", and no finding for runs that failed, were unclear, or did not finish.
- **FR-010**: Each finding MUST show the attack family, the OWASP class, the winning attacker message (the attacker message(s) that achieved the success, or the seed prompt for a single-turn or turn-one success), and the proof.
- **FR-011**: When a success rests on hard evidence (a canary), the proof MUST quote that evidence verbatim — byte-for-byte as stored — and MUST NOT paraphrase it. When a success was decided by the judge, the finding MUST show the judge's note and mark the result as suspected, never confirmed (Principle II).
- **FR-012**: Each finding MUST include a recommendation for the target's system prompt or tool configuration, generated by the configured judge model — one model call per successful run — from the run data, and clearly marked as a suggestion to review rather than a guaranteed fix.
- **FR-013**: If no judge model is configured (no key), each finding MUST still show its family, winning message and evidence, with a clear note that no recommendation is available.

**Other runs and limitations**

- **FR-014**: The report MUST include a section listing each failed or unclear run in one line (its family, when it ran, its verdict, and how it ended).
- **FR-015**: The report MUST end with a note on limitations, stating at least that it covers only the attacks that were run, that judge verdicts are suspected rather than proven, that results depend on the attacker model and budget, and that warm runs' memory and learned patterns influence outcomes so results vary between runs.

**Safety and secrecy (Principle IV)**

- **FR-016**: The report MUST NOT contain the target's URL, auth header names or values, or any secret; the target's display name and purpose description MAY appear.
- **FR-017**: The HTML format MUST escape all run-derived content (attacker messages, replies, judge notes) so that HTML, scripts, links and images in it are shown as text and are never executed, rendered as markup, or loaded when the file is opened.
- **FR-018**: Recommendation generation MUST send the model only non-secret run data (the attack family, the winning message, the evidence/judge note); it MUST NOT send the target URL, headers or any secret.

**Empty state**

- **FR-019**: A target with no runs MUST show a clear empty state in the screen and from the API, with no model calls and no error, and MUST NOT produce a report file.

### Key Entities

- **Report**: an on-demand artifact for one target, with five parts in order — header, OWASP coverage, findings, failed/unclear runs, limitations — serialised to Markdown and to HTML. Not persisted.
- **Coverage row**: one tested OWASP class, the attack family or families Kestrel uses for it, the run count, and the result (including "not run yet").
- **Finding**: one successful run rendered for action — family, OWASP class, winning attacker message, verbatim hard evidence or the judge's note, and a suggestion-marked recommendation.
- **Recommendation**: model-generated, non-authoritative guidance for a target's system prompt or tool configuration, always labelled a suggestion.
- **Untested-class note**: one of the seven OWASP classes Kestrel does not test, with a short reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a target with runs, a report is generated with all five sections in order, and both the Markdown and HTML downloads carry the same content.
- **SC-002**: The findings section contains exactly one finding per "succeeded" run and zero findings for runs that failed, were unclear, or did not finish.
- **SC-003**: Every hard-evidence quote in a finding is byte-for-byte identical to what the run stored; across all tests, 0 hard-evidence quotes are paraphrased.
- **SC-004**: Every recommendation is labelled a suggestion; across all tests, 0 recommendations are presented as guaranteed fixes.
- **SC-005**: The coverage table lists exactly the three tested OWASP classes with per-class run counts and shows "not run yet" for every family with 0 runs; the report lists exactly the seven untested classes, each with a reason.
- **SC-006**: Across all report generations, the target URL, auth header names/values, and a known secret test value appear 0 times in the Markdown or the HTML output.
- **SC-007**: Generating a report makes 0 requests to the target and 0 writes to the experience store.
- **SC-008**: In a downloaded HTML report, run-derived content that contains HTML or a script is shown as text, and opening the file executes 0 scripts and loads 0 external resources.
- **SC-009**: A target with no runs produces a clear empty state with 0 model calls and no error, and no file.
- **SC-010**: When a target has runs, the header names the attacker and judge models and the token budget (Principle III); across all tests, 0 such reports omit them.
- **SC-011**: Recommendation generation makes at most one model call per successful run, and 0 model calls when a target has no successful runs or no model is configured.

## Assumptions

- Builds on features 001–004. The report reads saved targets, runs and conversation turns from the existing store, and the family→OWASP mapping from the attack library (feature 002). It adds no attack behaviour and no write to the experience store (feature 004). Reports are generated on demand and not persisted — no new storage, no scheduling.
- **OWASP labels follow the code, not the prompt.** The feature description labelled LLM06 "sensitive information disclosure"; per the OWASP LLM Top 10 (2025) and the attack library, **LLM06 is "Excessive Agency"** (the class Kestrel's tool-mediated-exfiltration family maps to), and "Sensitive Information Disclosure" is **LLM02**, one of the seven classes not tested. The three tested classes are therefore LLM01, LLM06 and LLM07, which leaves exactly seven untested — consistent with the description's "seven classes not tested". The report uses the library's canonical labels so it stays honest (confirmed in clarification).
- **Verbatim means as-stored (masked).** Stored replies and attacker messages are already masked of auth header values (feature 002). "Quoted verbatim" means byte-for-byte as stored; the report never un-masks, so FR-011 and FR-016 do not conflict.
- **Why the seven are out of scope** draws on the constitution: quality-adjacent classes such as LLM09 Misinformation are out of scope under Principle I (security, not quality); LLM10 Unbounded Consumption is out under Principle VIII (no DoS, bounded harm); others (LLM02, LLM03, LLM04, LLM05, LLM08) need target internals, training/supply-chain access, or downstream output handling that a black-box chat attacker cannot reach. Exact wording is pinned in planning.

- **Recommendations reuse the judge model** (confirmed in clarification): the configured judge model and key generate recommendations, one model call per successful run, each marked as a suggestion; without a judge key, recommendations are omitted with a clear note (FR-013). No new model setting is introduced.
- **The winning attacker message** in a finding is the attacker turn(s) up to and including the succeeded turn (the same span feature 004 stores as a success pattern), or the seed prompt for a single-turn or turn-one success.
- **The header** lists the distinct attacker and judge models recorded across the target's runs (usually one each), the configured per-run token budget, and the total tokens the runs used.
