# Feature Specification: Register a Target Agent and Test the Connection

**Feature Branch**: `001-register-target` (no branch created; work is on `master`)

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description:

> Register a target agent and send it one prompt.
>
> Kestrel is a red-teaming lab for AI agents. This first feature lets a user register the HTTP endpoint of an agent they own and prove that Kestrel can talk to it. Nothing is attacked yet.
>
> User story: As a vibe coder who built an AI agent, I open Kestrel, fill in a form describing my agent's endpoint, click "Test connection", see the agent's reply to a harmless hello message, and save the target so it can be used in later scans.
>
> The registration form collects: a display name, the endpoint URL, the HTTP method, optional auth headers, a request body template that marks where the prompt goes, and a response path that tells Kestrel where the agent's reply text is in the JSON response. The user must tick a required checkbox stating "I own this agent or have written permission to test it" before saving.
>
> "Test connection" sends a single plain greeting to the endpoint using the form values, and shows either the parsed reply text or a clear error explaining which step failed: unreachable URL, authentication rejected, non-JSON response, or response path not found. The user cannot save a target until a test connection has succeeded.
>
> Saved targets appear in a list and can be selected, edited, and deleted. Auth header values are stored encrypted and are never shown back in full, never written to logs, and never included in any output.
>
> Acceptance: an end-to-end test registers the HS-code matching agent that is already in this repo, runs test connection, and sees its reply. A second test uses a wrong response path and sees the "response path not found" error. A third test tries to save without the permission checkbox and is blocked.
>
> Out of scope for this feature: attacks, judge, ChromaDB, reports, multiple users, login.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Test the connection to my agent (Priority: P1)

A vibe coder fills in the registration form with their agent's endpoint details and clicks "Test connection". Kestrel sends one harmless greeting to the agent and shows the agent's reply, or a clear message saying which step failed, so the user can fix the form and try again.

**Why this priority**: Proving that Kestrel can talk to the agent is the purpose of this feature and the base for every later scan. Without a working connection, nothing else can happen.

**Independent Test**: With the sacrificial HS-code target running, fill in the form with its details and click "Test connection"; the agent's reply appears. Change the response path to one that does not exist and test again; the "response path not found" message appears. Nothing needs to be saved.

**Acceptance Scenarios**:

1. **Given** the sacrificial HS-code target is running and the form holds its correct endpoint details and auth header, **When** the user clicks "Test connection", **Then** the agent's reply to the greeting is shown.
2. **Given** the form holds the sacrificial HS-code target's details but a response path that matches nothing in its reply, **When** the user clicks "Test connection", **Then** the "response path not found" message is shown and no reply text is shown.
3. **Given** the endpoint URL points to an address where nothing is listening, **When** the user clicks "Test connection", **Then** the "unreachable" message is shown.
4. **Given** an agent that requires an auth header and a form with a wrong header value, **When** the user clicks "Test connection", **Then** the "authentication rejected" message is shown, and the header value appears nowhere in it.
5. **Given** an endpoint that answers with something other than JSON, **When** the user clicks "Test connection", **Then** the "non-JSON response" message is shown.

---

### User Story 2 - Save my agent as a target (Priority: P2)

After a successful test, the user ticks "I own this agent or have written permission to test it" and saves. The target appears in the list of saved targets and is still there after Kestrel restarts, ready for later scans.

**Why this priority**: Saving turns a one-off check into a target that later scan features can use. It builds on Story 1, because only a tested target can be saved.

**Independent Test**: Test the sacrificial HS-code target successfully, tick the checkbox and save; the target appears in the list and is still listed after a restart. Repeat without ticking the checkbox; saving is blocked.

**Acceptance Scenarios**:

1. **Given** a successful test connection and the permission checkbox ticked, **When** the user saves, **Then** the target appears in the list of saved targets.
2. **Given** a successful test connection and the permission checkbox not ticked, **When** the user tries to save, **Then** saving is blocked and the user is told the checkbox is required.
3. **Given** no successful test connection for the current settings, **When** the user tries to save, **Then** saving is blocked and the user is told to run a successful test first.
4. **Given** a successful test, **When** the user changes the endpoint URL, HTTP method, auth headers, request body template or response path, **Then** saving is blocked until a new test succeeds.
5. **Given** a saved target, **When** Kestrel restarts, **Then** the target is still in the list.

---

### User Story 3 - Manage saved targets (Priority: P3)

The user picks a saved target from the list to see its details, test it again, edit it or delete it. Auth header values are never shown in full, and the user does not have to retype them to keep them.

**Why this priority**: Endpoints and keys change, and old targets need cleaning up. Users can still register and test agents without it.

**Independent Test**: Save a target with an auth header, select it, change its display name and save; then delete it after confirming. The header value never appears in full on screen.

**Acceptance Scenarios**:

1. **Given** a saved target with an auth header, **When** the user selects it, **Then** its details are shown with the header name and a fully masked value.
2. **Given** a saved target being edited, **When** the user changes only the display name and saves, **Then** the change is saved without a new test, and the stored header values are unchanged.
3. **Given** a saved target being edited, **When** the user changes the endpoint URL, **Then** the permission checkbox is cleared and must be ticked again, and a new successful test is needed before saving.
4. **Given** a saved target, **When** the user deletes it and confirms, **Then** the target and its stored auth header values are removed and it no longer appears in the list.
5. **Given** a saved target, **When** the user starts deleting it but cancels, **Then** nothing changes.

---

### Edge Cases

- A required field is empty, the URL is not a valid http or https address, or the prompt placeholder is missing or appears more than once: the form names the field at fault and nothing is sent.
- The agent does not answer within 30 seconds: the test stops and shows the "timed out" message.
- The endpoint answers with an error status other than an authentication refusal (for example 404 or 500): the "endpoint error" message is shown with the status code.
- The endpoint answers with a redirect: Kestrel does not follow it, so auth header values are never sent to another address, and shows the "endpoint error" message with the redirect location so the user can update the URL.
- The secure connection fails (for example, an untrusted certificate): shown as "unreachable", naming the certificate problem.
- The response path matches something other than text (a list, an object, a number or nothing): the "reply is not text" message is shown.
- The reply text is empty: the test counts as successful and shows "(empty reply)".
- The reply is very long: the first 2,000 characters are shown, with a note that it was shortened.
- The agent's reply or an error detail contains one of the target's auth header values: the value is masked before display.
- The user clicks "Test connection" again while a test is running: no second request is sent.
- A display name is already used by another saved target, ignoring letter case: saving is blocked with a message.
- Two targets share an endpoint URL but differ in other settings: allowed.
- Kestrel restarts while the user is filling in the form: unsaved input is lost; saved targets are kept.

## Requirements *(mandatory)*

### Functional Requirements

**Registration form**

- **FR-001**: Users MUST be able to enter a display name, an endpoint URL, an HTTP method (POST or GET; POST by default), zero or more auth headers (each a name and a value), a request body template and a response path.
- **FR-002**: The form MUST start with the request body template `{"message": "{{prompt}}"}` and the response path `$.reply`, both of which the user can change.
- **FR-003**: The prompt placeholder `{{prompt}}` MUST appear exactly once: in the request body template for POST, or in the URL's query for GET, which sends no body.
- **FR-004**: Before sending anything, the system MUST check the form and name the field at fault when a required field (display name, URL, response path) is empty, the URL is not a valid http or https address, an auth header name is not a valid header name, the placeholder rule in FR-003 is broken, or, for POST, the request body is not valid JSON once the placeholder is filled in.

**Test connection**

- **FR-005**: "Test connection" MUST send exactly one request to the endpoint, built from the current form values, with the prompt placeholder replaced by the greeting `Hello`.
- **FR-006**: Filling in the placeholder MUST produce a well-formed request even when the prompt contains quotes, backslashes, line breaks or non-ASCII characters, so that later features can send any attack text.
- **FR-007**: On success, the system MUST show the reply text found at the response path.
- **FR-008**: On failure, the system MUST show one message naming the step that failed:
  - **Unreachable**: no connection could be made to the URL.
  - **Timed out**: no response arrived within 30 seconds.
  - **Authentication rejected**: the endpoint refused the request as unauthorized or forbidden (status 401 or 403).
  - **Endpoint error**: any other error status, or a redirect, shown with its status code and, for a redirect, its location.
  - **Non-JSON response**: the endpoint answered successfully, but the body is not JSON.
  - **Response path not found**: the response path matches nothing in the response.
  - **Reply is not text**: the response path matches something other than text.
- **FR-009**: While a test is running, the user MUST NOT be able to start another test from the same form.
- **FR-010**: The system MUST NOT follow redirects.

**Saving**

- **FR-011**: The system MUST NOT save a target unless the checkbox "I own this agent or have written permission to test it" is ticked.
- **FR-012**: The system MUST NOT save a target unless the most recent test connection succeeded with exactly the connection settings being saved (endpoint URL, HTTP method, auth headers, request body template, response path). Changing only the display name MUST NOT require a new test.
- **FR-013**: Display names MUST be unique among saved targets, ignoring letter case.
- **FR-014**: Saved targets, including the permission confirmation and the date it was given, MUST persist across restarts of Kestrel.

**Managing saved targets**

- **FR-015**: Saved targets MUST appear in a list showing each target's display name and endpoint URL.
- **FR-016**: Users MUST be able to select a saved target to view it, test it again, edit it or delete it.
- **FR-017**: When a target is edited, its stored auth header values MUST be kept unless the user replaces or removes them.
- **FR-018**: If the endpoint URL changes during an edit, the permission checkbox MUST be cleared and ticked again before saving, because the permission applies to a specific endpoint.
- **FR-019**: Deleting a target MUST ask for confirmation, then permanently remove the target and its stored auth header values.

**Auth header values**

- **FR-020**: Auth header values MUST be stored encrypted.
- **FR-021**: Once entered, auth header values MUST only ever be shown fully masked; header names stay visible.
- **FR-022**: Auth header values MUST NOT appear in logs, error messages, the target list, exports or any other output, and MUST be sent only to the target's own endpoint, as request headers.
- **FR-023**: If an auth header value appears in a reply or error detail that is about to be displayed, the system MUST mask it first.

**Sacrificial HS-code target (test support)**

- **FR-024**: This repo MUST include a sacrificial HS-code target for the end-to-end tests: a local agent endpoint that passes each message to the CargoLint HS-code matching agent and returns the agent's reply. It uses CargoLint as it is, without changes to the CargoLint repo.
- **FR-025**: The sacrificial target MUST accept the request shape of the form defaults (a JSON body whose `message` field holds the prompt) and return its reply at `$.reply`, so it can be registered without changing the defaults.
- **FR-026**: The sacrificial target MUST require an auth header with a known test value and refuse requests without it, or with a wrong value, as unauthorized (status 401). The end-to-end tests then also cover auth headers and the "authentication rejected" message.
- **FR-027**: The end-to-end tests MUST start the sacrificial target themselves and stop it afterwards, with no manual steps beyond CargoLint's one-time setup.

### Key Entities

- **Target**: An agent endpoint the user registered. Holds a unique display name, the endpoint URL, the HTTP method, its auth headers, the request body template, the response path, and the permission confirmation with the date it was given.
- **Auth header**: A name and a secret value belonging to one target. The value is stored encrypted and never shown in full.
- **Connection test result**: The outcome of one test: either the reply text, or the step that failed and its message. It is shown to the user and not stored.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user who knows their agent's endpoint, request format and reply field can test and save it in under 3 minutes on the first attempt.
- **SC-002**: Every test connection ends with a reply or a failure message; none waits longer than the 30-second time limit.
- **SC-003**: For each failure step in FR-008, a deliberately caused failure is reported under that step, with no misclassifications.
- **SC-004**: Across all acceptance tests, a known test value used as an auth header value appears 0 times in logs, error messages, the target list or any other output.
- **SC-005**: Every attempt to save without the permission checkbox ticked, or without a successful test of the current connection settings, is blocked, with no exceptions.
- **SC-006**: Three end-to-end tests pass against the sacrificial HS-code target: its reply is shown; a wrong response path shows "response path not found"; after a successful test, saving without the permission checkbox is blocked.

## Assumptions

- Single user, no login (constitution Principle IX). Multiple users and login are out of scope.
- Also out of scope for this feature: attacks, the judge, the attack-pattern store and reports.
- A test connection is not a scan. It produces no findings and writes nothing to the attack-pattern store; the write-back rule in Principle V applies to scan runs.
- For now Kestrel runs as a single-user tool on the user's own machine, so endpoints on localhost or a private network are allowed. Before Kestrel is reachable from the internet, requests to private and internal addresses must be restricted; otherwise anyone could use Kestrel to reach the server's own network.
- Endpoints take a JSON request and return a JSON response. Streaming replies and other formats are out of scope.
- Only POST and GET are offered; other methods can be added later.
- Credentials belong in auth headers. Anything typed into the URL or the request body template is not treated as a secret.
- The greeting is the fixed text "Hello", and a test times out after 30 seconds.
- Auth header values are fully masked when shown; revealing part of a value is not offered.
- Response paths use the notation of the form default: `$` for the whole response, dots for fields and `[n]` for list positions, for example `$.choices[0].message.content`.
- Dependency: the HS-code matching agent is CargoLint, a separate repo (`C:\ai\CargoLint`) that runs as an interactive app with no HTTP endpoint. The sacrificial HS-code target in this repo (FR-024 to FR-027) wraps it. Running the target needs CargoLint's one-time setup on the same machine: its knowledge base and its model-provider API key.
- End-to-end tests against the sacrificial target make real model calls through CargoLint, so they need network access and cost a small amount per run.
- In this feature the sacrificial target behaves like CargoLint itself. The fake email tool and canary tokens come with later attack features.
