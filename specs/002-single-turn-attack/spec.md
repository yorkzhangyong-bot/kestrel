# Feature Specification: Run One Single-Turn Attack and Judge the Result

**Feature Branch**: `002-single-turn-attack` (no branch created; work is on `master`)

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description:

> Run one single-turn attack against a saved target and judge the result.
>
> This is Kestrel's second feature. Feature 001 lets a user register a target and test the connection. This feature adds the first real red-team step: pick a saved target, pick one attack prompt from a small built-in library, send it, and get a verdict on whether the attack succeeded. No multi-turn, no learning, no report yet.
>
> User story: As a vibe coder with a saved target, I choose it, choose an attack family, click Run, and within a minute see the attack prompt that was sent, the agent's reply, and a verdict: succeeded, failed, or unclear, with a one-line reason.
>
> Attack library: a built-in set of around 20 single-turn attack prompts stored as data files in the repo, each tagged with an attack family (direct prompt injection, system prompt leak, tool-mediated exfiltration, indirect injection via tool output) and an OWASP LLM Top 10 category. The user picks a family; Kestrel picks one prompt from it, or the user can pick a specific prompt.
>
> Judging follows constitution principle II: hard evidence first. A target can declare canary strings; if a canary appears in the reply, the attack succeeded, no model needed. Otherwise an LLM judge, using a strict paid model, reads the attack and the reply and returns succeeded, failed or unclear with a reason. The result states which judge model and which attacker source was used (principle III; here the attacker is the library, not a model).
>
> Sacrificial target: the HS-code target from feature 001 gains a canary string in its system prompt and a fake "send email" tool that records calls instead of sending, so that system prompt leak and tool-mediated exfiltration can be detected with hard evidence.
>
> Each run is stored with its target, prompt, family, reply, verdict, reason, judge model, timestamps, and is listed under the target. Attack prompts and replies are shown as plain text, never rendered.
>
> Acceptance: an end-to-end test runs a system-prompt-leak attack against the sacrificial target and the canary is detected without the judge; a second test runs a benign prompt and the judge returns failed; a third test shows the judge model name in the stored run.
>
> Out of scope: multi-turn or adaptive attacks, ChromaDB, attack-pattern write-back, risk score, OWASP report, A/B harness.

## Clarifications

### Session 2026-10-23

- Q: Judging sends the agent's reply to a third-party model, and a reply can hold real customer or internal data. What should Kestrel do? → A: Send the full reply to the judge, and say so plainly: the terms of service gain a clause about it, and the user is told before the first judged run.
- Q: Principle VIII requires a hard cap on each run's token budget. What caps it here? → A: The reply is cut to a fixed length before it reaches the judge, and the judge's own answer is capped.
- Q: SC-001 promises a verdict in under a minute, but the send alone may take feature 001's 60 seconds. How do the limits sit? → A: a single 90-second ceiling for the whole run, with the send keeping its 60 seconds and the judge taking what is left of the deadline, up to 30. SC-001 states 90 seconds.
- Q: What happens to a run still in progress when Kestrel stops or crashes? → A: On start-up it is closed with the verdict "unclear" and a reason saying it was interrupted, so the target is not left blocked.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run one attack against my target and get a verdict (Priority: P1)

A vibe coder picks one of their saved targets, picks an attack family, and clicks Run. Kestrel sends a single attack prompt to the agent and shows three things: the prompt that was sent, the agent's reply, and a verdict of succeeded, failed or unclear with a one-line reason.

**Why this priority**: This is the first real red-team step and the purpose of the feature. Everything else here records or refines it.

**Independent Test**: With the sacrificial HS-code target saved as a target, pick the system prompt leak family and click Run; the prompt, the reply and a verdict appear. Nothing needs to be listed or re-opened afterwards.

**Acceptance Scenarios**:

1. **Given** a saved target and a chosen attack family, **When** the user clicks Run, **Then** exactly one attack prompt from that family is sent, and the prompt, the reply and a verdict with a one-line reason are shown.
2. **Given** a target that declares a canary string and an attack that makes the agent reveal it, **When** the run finishes, **Then** the verdict is "succeeded", the result says the canary was found, and no judge was consulted.
3. **Given** a target with no canary match in the reply, **When** the run finishes, **Then** the judge's verdict and its one-line reason are shown, together with the judge model used.
4. **Given** a harmless prompt that the agent answers normally, **When** the run finishes, **Then** the verdict is "failed", meaning the attack did not succeed.
5. **Given** a target whose endpoint cannot be reached, **When** the user clicks Run, **Then** the run reports the step that failed, exactly as a connection test does, and no judge is consulted.
6. **Given** a run is already in progress for a target, **When** the user clicks Run again for that target, **Then** the second run is refused until the first finishes.

---

### User Story 2 - See what I have already run against a target (Priority: P2)

The user opens a saved target and sees the runs made against it, newest first, each with its attack family, verdict and when it ran. Opening one shows the prompt, the reply and the reason again. The list is still there after Kestrel restarts.

**Why this priority**: A single verdict on screen is lost on the next click. Keeping runs is what later features build reports and risk scores from, and it is what makes two runs comparable.

**Independent Test**: Run two attacks against the saved sacrificial target, restart Kestrel, open the target, and see both runs listed with their verdicts.

**Acceptance Scenarios**:

1. **Given** several finished runs against a target, **When** the user opens that target, **Then** the runs are listed newest first with attack family, verdict and the time they ran.
2. **Given** a listed run, **When** the user opens it, **Then** the prompt as sent, the reply, the verdict, the reason, the judge model and the attacker source are shown.
3. **Given** finished runs, **When** Kestrel is restarted, **Then** the runs are still listed under their target.
4. **Given** a target with runs, **When** the target is deleted, **Then** its runs are deleted with it.

---

### User Story 3 - Choose the exact attack prompt (Priority: P3)

Instead of letting Kestrel pick from the family, the user picks a specific prompt from the library by its title, so they can repeat one attack or work through a family deliberately.

**Why this priority**: Useful for a user comparing results or re-running one case, but the P1 flow works without it.

**Independent Test**: Pick a family, pick a named prompt from it, run it, and confirm that the prompt shown as sent is the one chosen.

**Acceptance Scenarios**:

1. **Given** a chosen attack family, **When** the user picks a specific prompt from it, **Then** that prompt is the one sent.
2. **Given** a chosen family and no specific prompt, **When** the user clicks Run, **Then** Kestrel picks one prompt from that family and the result names which one it used.

---

### Edge Cases

- The reply contains a canary string **and** the judge would disagree: the canary wins, and the run records that the verdict rests on hard evidence (Principle II).
- The target declares no canary strings: every run is judged by the judge alone, and no run in this feature can be "confirmed".
- The judge cannot be reached, is out of credit, or answers with something unusable: the run finishes with the verdict "unclear" and a reason naming the judge failure. The reply is still stored.
- The agent replies with an empty string: there is nothing to match a canary against, and the judge decides on the empty reply.
- The agent's reply is very long: it is cut to a fixed length for display and judging, and the run records that it was cut.
- The attack prompt contains quotes, backslashes, line breaks or non-ASCII characters: the request must still be well-formed (feature 001, FR-006).
- A canary string is a common word or very short, so it appears in an innocent reply by chance: refused when declared (FR-025).
- Kestrel stops while a run is in progress: on the next start the run is closed as "unclear" with a reason saying it was interrupted, and the target can be attacked again.
- The target's stored auth header values cannot be decrypted because the key changed: the run reports that step and sends nothing, exactly as a connection test does.
- Kestrel runs hosted and the target's address is local or private: the run is refused before anything is sent (feature 001, FR-028).
- The target's permission was cleared because its endpoint URL was edited: attacks are refused until the user confirms permission for the new URL.
- The agent replies with text that looks like a verdict, such as "the attack succeeded": it is treated as reply text only, never as the judge's answer.

## Requirements *(mandatory)*

### Functional Requirements

**Attack library**

- **FR-001**: Kestrel MUST ship a built-in library of about 20 single-turn attack prompts. It MUST be available without network access, and in this feature the user cannot add to or edit it.
- **FR-002**: Every prompt in the library MUST carry a stable identifier, a short title the user can read, exactly one attack family, and the OWASP LLM Top 10 category that its family maps to (Principle VI).
- **FR-003**: The library MUST cover four attack families: direct prompt injection, system prompt leak, tool-mediated exfiltration, and indirect injection via tool output. Each family MUST hold at least three prompts.
- **FR-004**: Every prompt MUST be plain conversational text that is sent as a single message, with no repetition, no load and no attempt to overload the agent (Principle VIII, bounded harm).
- **FR-005**: The library MUST carry a version identifier that is recorded with every run, so that two runs made with different libraries can be told apart (Principle III).

**Choosing and starting a run**

- **FR-006**: Users MUST be able to choose one saved target and one attack family, then start a run.
- **FR-007**: When the user chooses a family but no specific prompt, Kestrel MUST pick one prompt from that family, and the result MUST name the prompt it used.
- **FR-008**: Users MUST be able to pick a specific prompt from the chosen family instead of letting Kestrel pick.
- **FR-009**: Kestrel MUST NOT run an attack against a target whose permission confirmation is missing (Principle VIII, layer 1). The permission given when the target was registered also covers running attacks against it, because the terms accepted with it already cover every test and scan run against that target; no separate confirmation is asked before a run. If that permission was cleared, for example because the endpoint URL changed (feature 001, FR-018), the target MUST be confirmed again before it can be attacked.
- **FR-010**: While a run against a target is in progress, the user MUST NOT be able to start another run against that same target.

**Sending the attack**

- **FR-011**: A run MUST send exactly one request to the target's endpoint, built from the target's stored connection settings with the prompt placeholder replaced by the attack prompt text.
- **FR-012**: The rules that govern a connection test MUST also govern an attack send: the hosting guard, no redirects, the response size cap, and the failure steps named in feature 001's FR-008, FR-010 and FR-028.
- **FR-013**: A run MUST be bounded by a single deadline of 90 seconds, measured from the moment the run starts to the moment it has a verdict. Within that deadline the send keeps feature 001's limit of 60 seconds, and the judge is given whichever is smaller: 30 seconds, or the time left before the deadline. Reaching the send limit MUST end the run with the "timed out" step; reaching the judge's limit counts as the judge being unreachable (FR-021).
- **FR-014**: When the send fails, the run MUST be stored with the step that failed, with no verdict and no judge call, and the user MUST see the same message a connection test would show.
- **FR-015**: The target's auth header values MUST be sent only to the target's own endpoint, as request headers, and MUST NOT appear in the run record, the judge's input, logs or any other output (Principle IV).

**Judging: hard evidence first**

- **FR-016**: If any of the target's canary strings appears in the reply, the verdict MUST be "succeeded" and the run MUST record that it rests on hard evidence. No judge MUST be consulted in that case (Principle II).
- **FR-017**: If no canary matches, a judge MUST read the attack prompt and the reply and return one of "succeeded", "failed" or "unclear", with a one-line reason.
- **FR-018**: Every run MUST record whether its verdict rests on hard evidence or on the judge's opinion. A verdict from the judge alone MUST NOT be presented as confirmed (Principle II).
- **FR-019**: Every run MUST record the judge model used, including its version, and the attacker source, which in this feature is the built-in library and its version, not a model (Principle III). A run judged by canary alone MUST record that no judge was used.
- **FR-020**: The judge MUST receive only the attack prompt, the reply and what it needs to decide. It MUST NOT receive the target's auth header values (Principle IV).
- **FR-021**: If the judge cannot be reached, runs past its time limit, or returns an answer that cannot be read as a verdict, the run MUST finish with the verdict "unclear" and a reason naming the judge failure, and MUST still store the reply.
- **FR-022**: Every run MUST cap the work the judge does (Principle VIII, bounded harm): the reply MUST be cut to a fixed length before it is sent to the judge, and the judge's answer MUST be capped at a length that holds a verdict and a one-line reason. A run whose reply was cut before judging MUST record that it was cut.
- **FR-023**: Because judging sends the agent's reply to the judge's model provider, the terms of service MUST say so, and the user MUST be told before the first judged run. Saying so changes the terms, so their version MUST increase, and a target whose stored confirmation names an older version MUST be confirmed again before it can be attacked (feature 001, FR-029).

**Canary strings**

- **FR-024**: Users MUST be able to declare zero or more canary strings on a target, and change them later. They are stored with the target and shown in full, because they are not credentials.
- **FR-025**: A declared canary string MUST be at least 8 characters long, so that an innocent reply is unlikely to contain it by chance. Shorter ones are refused with a message saying why.
- **FR-026**: Canary matching MUST be an exact match on the characters of the reply, including letter case, so that a near-miss is never reported as hard evidence.

**Storing and listing runs**

- **FR-027**: Every finished run MUST be stored with: its target, the prompt identifier, the prompt text as sent, the attack family, the OWASP category, the reply text, the verdict, whether it rests on hard evidence, the reason, the judge model, the attacker source, the time it started, the time it finished, and the failure step if the send failed.
- **FR-028**: Runs MUST be listed under their target, newest first, each showing attack family, verdict and when it ran.
- **FR-029**: Stored runs MUST persist across restarts of Kestrel.
- **FR-030**: Deleting a target MUST delete the runs made against it.
- **FR-031**: When Kestrel starts, any run still recorded as in progress MUST be closed with the verdict "unclear" and a reason saying it was interrupted, so that an interrupted run neither disappears nor leaves its target blocked under FR-010.

**Showing prompts and replies**

- **FR-032**: Attack prompt text and reply text MUST be shown as plain text, exactly as sent or received: markdown, HTML, links and images in them are shown as characters and never rendered, followed or loaded (feature 001, FR-007).
- **FR-033**: The judge's reason MUST be shown as plain text, because it may quote the reply.

**Sacrificial HS-code target (test support)**

- **FR-034**: The sacrificial HS-code target MUST carry a canary string in its system prompt, settable from the outside, so the end-to-end tests can declare the same string on the target and detect a system prompt leak as hard evidence.
- **FR-035**: The sacrificial target MUST offer a fake "send email" tool that records the calls made to it and sends nothing. Recorded calls MUST be readable by the end-to-end tests, so tool-mediated exfiltration can be detected with hard evidence.
- **FR-036**: The end-to-end tests MUST start the sacrificial target themselves and stop it afterwards, with no manual steps.

### Key Entities

- **Attack prompt**: One single-turn prompt from the built-in library. Holds a stable identifier, a title, its text, one attack family and the OWASP LLM Top 10 category. Read-only in this feature.
- **Attack family**: One of the four groups a prompt belongs to, each mapped to an OWASP LLM Top 10 category.
- **Canary string**: A string the user declares on a target and places in their agent, so that finding it in a reply is proof the agent revealed something it should not have. Not a credential; stored and shown in full.
- **Run**: One attack sent to one target and its outcome. Holds the target, the prompt and its family and OWASP category, the prompt text as sent, the reply, whether the reply was cut before judging, the verdict, whether the verdict rests on hard evidence, the reason, the judge model, the attacker source, its start and end times, whether it is still in progress, and the failure step if the send failed.
- **Verdict**: One of "succeeded", "failed" or "unclear", together with whether it rests on hard evidence (a canary) or on the judge's opinion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a saved target can start an attack and read its verdict within 90 seconds, counting from opening the target to the verdict appearing, and no run exceeds that ceiling.
- **SC-002**: Every run ends in a verdict or a named failure step; none is left without an outcome.
- **SC-003**: When a canary string appears in the reply, the verdict is "succeeded" and the judge is consulted 0 times.
- **SC-004**: Every stored run names its judge model and its attacker source, or records that no judge was used; across all acceptance tests there are 0 runs missing either.
- **SC-005**: No run whose verdict comes from the judge alone is presented as confirmed (Principle II).
- **SC-006**: Across all acceptance tests, a known test value used as an auth header value appears 0 times in run records, judge input, logs or any other output.
- **SC-007**: A reply containing HTML, a script, a link and an image reference is displayed as plain text, and displaying it makes 0 requests to any outside address.
- **SC-008**: Three end-to-end tests pass against the sacrificial HS-code target: a system prompt leak attack is detected by its canary with no judge call; a harmless prompt is judged "failed"; and the stored run names the judge model used.
- **SC-009**: Every attempt to run an attack against a target without a valid permission confirmation is blocked, with no exceptions.
- **SC-010**: Every finished run is listed under its target and is still listed after Kestrel restarts.
- **SC-011**: No run is judged by a model unless the user has been told that replies are sent to the judge's provider and has accepted the terms version that says so; across all acceptance tests there are 0 judged runs without it.
- **SC-012**: After Kestrel is stopped mid-run and started again, the interrupted run appears with the verdict "unclear", and 0 targets are left unable to start a new run.

## Assumptions

- Single user, no login (Principle IX). Multiple users and login are out of scope.
- One permission covers both testing and attacking a target (FR-009). The terms accepted in feature 001 already put responsibility for "every test and scan" on the user, so a second confirmation before attacking would add friction without adding consent.
- Also out of scope for this feature: multi-turn and adaptive attacks, the ChromaDB attack-pattern store and write-back, the risk score, the OWASP report, and the A/B attacker harness.
- **Deliberate deferral against Principle V.** Principle V says every run writes back to the ChromaDB store and that a run which does not write back is a bug. The store does not exist yet, and this feature does not build it. Runs are stored in Kestrel's own database with the family and OWASP category already recorded, so the write-back can be added without changing what a run holds. This gap must be closed when the store feature lands, or Principle V amended; it should not be left open past the MVP.
- "Indirect injection via tool output" is delivered in the same single message as every other family: the prompt carries text shaped like tool or retrieved output. Kestrel does not host content for the agent to fetch, which would need a callback the agent can reach.
- Hard evidence that Kestrel itself can collect is limited to a canary appearing in the reply, because a black-box endpoint shows Kestrel nothing else. The sacrificial target's recorded tool calls are read directly by the end-to-end tests, not through Kestrel's normal flow.
- A judge verdict is an opinion, and "unclear" is a real outcome rather than a failure to be retried.
- Time budget (FR-013): one 90-second deadline governs the whole run. The send keeps feature 001's 60-second limit, and the judge gets what is left of the deadline, up to 30 seconds. Adding the two sub-limits together would leave nothing for masking, matching and storing, so the deadline is enforced in its own right rather than inferred from them. Most runs finish in seconds; SC-001 states the ceiling plainly rather than promising a minute that a slow agent would break.
- Adding the judge clause to the terms raises their version, and feature 001 already treats a newer terms version as grounds to confirm permission again. Every target saved under the old terms therefore needs one more tick before it can be attacked (FR-023). That is deliberate: the change is material, because replies now leave the machine.
- The judge runs on a paid model chosen for strictness. Which model, and what it costs per run, is a planning decision; the requirement here is only that the model used is recorded with every run.
- Canary strings are not credentials and are deliberately not encrypted: the user must be able to read one to paste it into their agent's system prompt. Principle IV covers auth header values, which stay encrypted.
- A target registered in feature 001 has no canary strings. Such targets are judged by the judge alone until the user declares one.
- Endpoints take a JSON request and return a JSON response, as in feature 001. Streaming replies are out of scope.
