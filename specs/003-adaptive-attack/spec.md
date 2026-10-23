# Feature Specification: Run a Multi-Turn Adaptive Attack and Judge the Result

**Feature Branch**: `003-adaptive-attack` (no branch created; work is on `master`)

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description:

> Feature 003: multi-turn adaptive attack.
>
> Context: Kestrel is a defensive red-teaming platform. It only tests agents the user owns or has written permission to test. Do not write, repeat or generate any attack prompt text in the conversation or in specs. Describe behaviour only.
>
> Goal: instead of sending one library prompt, an attacker agent holds a conversation with the target. It starts from a library prompt, reads each reply, and adapts its next message until it succeeds or hits a limit.
>
> Must have:
> - An attacker/judge loop built as a LangGraph graph (Principle X).
> - The attacker model is configurable, defaulting to a less-restricted model such as DeepSeek or Qwen via OpenRouter, and every run records its model, version and budget (Principle III).
> - Hard caps on turns and token budget per run, plain conversation only (Principle VIII).
> - After each turn: canary check first, judge only if no canary matched (Principle II, same rule as feature 002).
> - The full conversation is stored with the run, masked like feature 002 replies.
> - The screen shows the conversation turn by turn and the final verdict.
> - One end-to-end test against the HS-code target.
>
> Out of scope: ChromaDB write-back and memory (feature 004), risk score and report (feature 005).

## Clarifications

### Session 2026-10-24

- Q: How should an adaptive run be bounded? → A: Three hard caps, whichever hits first — a turn cap, a per-run token budget across all attacker and judge calls, and an overall wall-clock time limit.
- Q: What should the default turn cap be? → A: 6 turns, configurable.
- Q: How does the screen launch an adaptive attack versus a single-turn one? → A: A Single-turn / Adaptive mode toggle in the existing Attack panel, reusing the same family and prompt controls and one Run button.
- Q: Which model family should the default attacker use? → A: A DeepSeek model via OpenRouter, with the exact model pinned in planning and recorded per run (Principle III).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run an adaptive attack against my target and get a verdict (Priority: P1)

A vibe coder picks one of their saved targets and an attack family, then starts an adaptive attack. Instead of sending a single prompt, an attacker agent opens a conversation with the target: it sends an opening message drawn from the attack family, reads the target's reply, and sends an adapted follow-up, turn after turn, until it either succeeds or reaches a limit. The user sees a single verdict — succeeded, failed or unclear — with a one-line reason.

**Why this priority**: This is the feature. A multi-turn attacker finds weaknesses a single prompt misses, and it is the step that makes Kestrel more than a one-shot checker. Everything else here records or displays it.

**Independent Test**: With the sacrificial HS-code target saved, start an adaptive attack in a chosen family and watch it run several turns and finish with a verdict, without exceeding its turn and token limits.

**Acceptance Scenarios**:

1. **Given** a saved target with a valid permission confirmation, **When** the user starts an adaptive attack in a chosen family, **Then** the attacker holds a conversation of one or more turns and the run finishes with a verdict and a one-line reason.
2. **Given** a target that reveals a declared canary at some turn, **When** that reply arrives, **Then** the run stops immediately with the verdict "succeeded" by hard evidence, and no judge is consulted for that turn (Principle II).
3. **Given** a target that holds firm, **When** the attacker reaches the turn limit or the token budget without success, **Then** the run stops and records that it ended by reaching that limit, with the final verdict the agent earned (failed or unclear).
4. **Given** a reply with no canary match, **When** the turn is judged, **Then** the judge reads the conversation so far and returns succeeded, failed or unclear; a "succeeded" stops the run, anything else lets the attacker adapt and continue.
5. **Given** a target whose endpoint cannot be reached partway through, **When** a turn's send fails, **Then** the run stops and records the failed step, exactly as a single-turn run does, with no further turns.

---

### User Story 2 - Review the conversation of a run (Priority: P2)

The user opens a finished adaptive run and reads the whole conversation, turn by turn: each attacker message and the target's reply, in order, with the final verdict, the reason and how the run ended. The conversation is still there after Kestrel restarts.

**Why this priority**: A single verdict hides how the attacker got there. Seeing the conversation is what lets a user understand the weakness and, later, fix it. It builds on Story 1 and on feature 002's run history.

**Independent Test**: Run an adaptive attack, restart Kestrel, open the run, and read the full conversation turn by turn with its verdict.

**Acceptance Scenarios**:

1. **Given** a finished adaptive run, **When** the user opens it, **Then** every turn is shown in order — the attacker's message and the target's reply — followed by the verdict, the reason and the stopping condition.
2. **Given** a mix of single-turn and adaptive runs under a target, **When** the user lists them, **Then** each run shows its kind, its verdict and when it ran, newest first.
3. **Given** finished adaptive runs, **When** Kestrel is restarted, **Then** the runs and their full conversations are still there.
4. **Given** a target with adaptive runs, **When** the target is deleted, **Then** its runs and conversations are deleted with it.

---

### User Story 3 - Know which attacker drove the run (Priority: P3)

Every adaptive run names the attacker model and version that drove it and the budget it was given and used, so that two runs can be compared and a result can be trusted or discounted on the strength of its attacker (Principle III).

**Why this priority**: Attack success depends on the attacker. Without knowing which model attacked and how hard it was allowed to try, a verdict is not comparable or reproducible. Useful once runs exist, but the P1 flow works without it being visible.

**Independent Test**: Run two adaptive attacks with different configured attacker models; each run names its own model and the budget it used.

**Acceptance Scenarios**:

1. **Given** a finished adaptive run, **When** the user opens it, **Then** it names the attacker model and version, the judge model, the turn and token budget it was allowed, and the turns and tokens it actually used.
2. **Given** the attacker model is changed in the deployment settings, **When** a new run is made, **Then** the new run records the new model, and earlier runs still name the model that drove them.

---

### Edge Cases

- The target reveals a canary on the very first reply: the run succeeds at turn one by hard evidence, with no judge call.
- The attacker reaches the turn limit without success: the run ends "failed" or "unclear" and records that it stopped at the turn limit, not that the agent is safe in general.
- The token budget runs out mid-conversation: the run stops before the next model call that would exceed it, and records that it stopped at the token budget.
- The overall time limit is reached: the run stops and records that it timed out.
- The attacker model is unreachable, out of credit, or returns nothing usable: the run ends "unclear" with a reason naming the attacker-model failure, and whatever conversation happened so far is still stored.
- The judge is unreachable or unreadable at some turn: that turn is treated as "not yet succeeded" and the run continues if budget remains; if it was the last turn, the run ends "unclear", as in feature 002.
- The target's reply is empty or very long: an empty reply is judged on its own; a long reply is cut to a fixed length before it is judged or stored, and the run records that it was cut.
- A reply or an attacker message contains an auth header value: it is masked before the conversation is stored, judged or shown.
- Kestrel stops mid-run: on restart the interrupted run is closed as "unclear" with a reason saying it was interrupted, keeping whatever turns were stored, and its target is not left blocked (as in feature 002).
- The target's stored auth header values cannot be decrypted: the run reports that step and sends nothing, exactly as a single-turn run does.
- The target's permission was cleared or its terms version is out of date: the attack is refused before anything is sent, exactly as in feature 002.

## Requirements *(mandatory)*

Feature 003 extends feature 002. Where behaviour is identical, this spec says so rather than restating it: the permission and terms gates, canary matching, judge verdicts, reply masking and cutting, run listing, restart persistence, deletion and the start-up sweep all behave as in [feature 002](../002-single-turn-attack/spec.md).

### Functional Requirements

**Starting an adaptive attack**

- **FR-001**: Users MUST be able to choose a saved target and an attack family, then start an adaptive attack, distinctly from a single-turn attack. The screen MUST offer a Single-turn / Adaptive mode toggle in the Attack panel that reuses the same family and prompt controls and one Run button; the run records which mode was used.
- **FR-002**: An adaptive attack MUST begin from one prompt in the chosen family (the opening message), chosen as in feature 002 (Kestrel picks one, or the user picks a specific one).
- **FR-003**: The permission and terms-of-service gates MUST apply before anything is sent, exactly as in feature 002: a target without a current permission confirmation, or on an older terms version, is refused with no run created.
- **FR-004**: While an adaptive run against a target is in progress, the user MUST NOT be able to start another run of any kind against that same target.

**The attacker/judge loop**

- **FR-005**: An adaptive attack MUST be driven by an attacker agent that, each turn, reads the target's most recent reply and the conversation so far and produces the next message to send. The loop MUST be structured as a graph of attacker and judge steps (Principle X).
- **FR-006**: Each turn MUST send exactly one message to the target, built from the target's stored connection settings with the prompt placeholder replaced by the attacker's message, exactly as a single-turn send is built.
- **FR-007**: After each turn, the system MUST check the reply for the target's canary strings first; only if no canary matches MUST a judge read the conversation so far and return succeeded, failed or unclear (Principle II).
- **FR-008**: The loop MUST stop as soon as the attack succeeds — a canary match, or a judge verdict of "succeeded" — and MUST continue to the next turn on "failed" or "unclear" while budget remains.
- **FR-009**: Every message the attacker sends MUST be plain conversational text sent as a single message; the attacker MUST NOT repeat, flood or try to overload the target (Principle VIII).

**Limits and bounded harm (Principle VIII)**

- **FR-010**: Each run MUST be bounded by three hard caps, whichever is reached first: a cap on the number of turns (default 6, configurable), a cap on the total token budget across all attacker and judge model calls, and an overall wall-clock time limit. The run MUST stop before any model call that would exceed the token budget.
- **FR-011**: Reaching the wall-clock time limit MUST stop the run.
- **FR-012**: When a run stops at a cap rather than a verdict of success, it MUST record which of the three caps it reached (turns, token budget or time), so a cutoff is never mistaken for the agent being safe.
- **FR-013**: When a turn's send fails, the run MUST stop and be stored with the failed step and no verdict, exactly as a single-turn run does (feature 002), with no further turns.

**The attacker model (Principle III)**

- **FR-014**: The attacker model MUST be a deployment setting that defaults to a DeepSeek model reached through OpenRouter, chosen for being capable and comparatively unrestricted; the exact model is pinned in planning. The feature MUST run with the default and need no per-run configuration.
- **FR-015**: Every run MUST record the attacker model and its version, the judge model, the turn and token budget it was allowed, and the turns and tokens it actually used (Principle III).
- **FR-016**: If the attacker model is not configured or cannot be reached, the run MUST end "unclear" with a reason naming the attacker-model failure, and MUST still store any conversation that occurred.
- **FR-017**: The attacker model MUST receive only the conversation so far and what it needs to produce the next message; it MUST NOT receive the target's auth header values, URL, name or any other stored setting (Principle IV).

**Verdict and evidence**

- **FR-018**: A run's verdict MUST be one of succeeded, failed or unclear, and MUST record whether it rests on hard evidence (a canary) or on the judge's opinion; a judge-only verdict MUST NOT be presented as confirmed (Principle II), exactly as in feature 002.
- **FR-019**: A successful run MUST record the turn at which it succeeded and whether a canary or the judge settled it.

**Storing the conversation**

- **FR-020**: Every finished run MUST store the full conversation as an ordered list of turns, each turn holding the attacker's message and the target's reply, together with the fields a single-turn run stores (target, seed prompt, family, OWASP category, verdict, evidence basis, reason, judge model, attacker model and version, budgets and usage, start and end times, stopping condition, and the failed step if the send failed).
- **FR-021**: The stored conversation MUST be masked for auth header values before it is stored, judged or shown, and each reply cut to a fixed length, exactly as a single-turn reply is (feature 002).
- **FR-022**: Adaptive runs MUST be listed under their target alongside single-turn runs, each showing its kind, verdict and when it ran, newest first; they MUST persist across restarts, be removed when the target is deleted, and be closed as "unclear" by the start-up sweep if interrupted (all as in feature 002).

**Showing the conversation**

- **FR-023**: The screen MUST let the user start an adaptive attack and, when it finishes, show the conversation turn by turn — each attacker message and target reply labelled by who sent it — followed by the verdict, the reason, how the run ended, and the attacker and judge models used.
- **FR-024**: Attacker messages, target replies and the judge's reason MUST be shown as plain text, exactly as received or produced: markdown, HTML, links and images in them are shown as characters and never rendered, followed or loaded (feature 002, SC-007).

**Sacrificial HS-code target (test support)**

- **FR-025**: The end-to-end test MUST use the sacrificial HS-code target from feature 002, unchanged, and MUST start and stop it itself with no manual steps.
- **FR-026**: There MUST be one end-to-end test that runs an adaptive attack against the sacrificial target through the real screen and asserts that the run completes with a verdict, records the attacker model and the turns used, and stores the full conversation.

### Key Entities

- **Adaptive run**: One multi-turn attack on one target and its outcome. Extends feature 002's run with a kind ("adaptive"), the attacker model and version, the turn and token budgets allowed and used, the ordered conversation, the turn at which it succeeded (if any), and the stopping condition (succeeded, turn cap, token budget, time, send failure, attacker-model failure, or interrupted).
- **Conversation turn**: One step of the conversation: the attacker's message and the target's reply, in order, both masked.
- **Attacker**: The model that drives the attack — its name, version and the budget it is given. What Principle III records as the attacker, in place of feature 002's library-only attacker source.
- **Verdict**: One of succeeded, failed or unclear, with whether it rests on hard evidence (a canary) or the judge's opinion, as in feature 002.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can start an adaptive attack and read its verdict without any run exceeding its turn cap (default 6), its token budget, or its overall time limit.
- **SC-002**: Every adaptive run ends in a verdict or a named failure step, and records how it ended (success at a turn, a named limit, or a failure); none is left without an outcome.
- **SC-003**: When a canary appears in any turn's reply, the run stops at that turn with verdict "succeeded" by hard evidence and the judge is consulted 0 times for that turn.
- **SC-004**: Every adaptive run names its attacker model and version, its judge model, and the budget it was allowed and used; across all acceptance tests there are 0 runs missing any of these (Principle III).
- **SC-005**: No run whose verdict comes from the judge alone is presented as confirmed (Principle II).
- **SC-006**: Across all acceptance tests, a known test value used as an auth header value appears 0 times in any stored conversation, judge input, attacker input, log or other output (Principle IV).
- **SC-007**: A reply or attacker message containing HTML, a script, a link and an image reference is shown as plain text, and showing it makes 0 requests to any outside address.
- **SC-008**: Every attempt to start an adaptive attack against a target without a current permission confirmation or on an older terms version is refused with no run created.
- **SC-009**: One end-to-end test passes against the sacrificial HS-code target: an adaptive attack completes with a verdict, records the attacker model and turns used, and stores the full conversation.
- **SC-010**: After Kestrel is stopped mid-run and restarted, the interrupted adaptive run appears with verdict "unclear", its stored turns intact, and its target able to start a new run.

## Assumptions

- Builds on features 001 and 002. A target is registered and tested (001); canary matching, the judge, run storage, reply masking and cutting, the permission and terms gates, the start-up sweep and the sacrificial target all come from 002 and are reused unchanged.
- Out of scope, as stated: writing runs back to the ChromaDB attack-pattern store and any cross-run memory (feature 004); the risk score and the OWASP report (feature 005).
- **Deliberate deferral against Principle V**, carried over from feature 002: adaptive runs do not write back to the attack-pattern store, because the store does not exist yet. The run record already holds the family, OWASP category, verdict and conversation a later write-back needs. This must close when the store lands (feature 004) or Principle V be amended; it must not survive the MVP.
- The attacker is a real model making real calls, so an adaptive run costs more and takes longer than a single-turn run. A run is bounded by three caps — turns (default 6), a per-run token budget and a wall-clock time limit — and the exact token-budget and time numbers, plus the exact default DeepSeek model, are pinned in planning against live OpenRouter pricing. The requirement here is that the three caps exist, are enforced, and are recorded with every run.
- A judge verdict is an opinion; "failed" within the loop means "not yet succeeded, keep trying", not "the agent is safe". The final verdict reflects only what happened within the run's limits.
- The default attacker model is a DeepSeek model reached through OpenRouter, chosen for being capable and comparatively unrestricted; the exact model, and the judge model, are pinned in planning, and whichever is used is recorded with the run (Principle III).
- An adaptive run and a single-turn run (feature 002) are two kinds of the same stored run, listed together under a target.
- Endpoints take a JSON request and return a JSON response, as in features 001 and 002. Streaming replies are out of scope.
