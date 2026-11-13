# Feature Specification: Structured Logging and Tracing

**Feature Branch**: `010-structured-logging`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Feature 010, structured logging and tracing for Kestrel. Every run, turn, judge call
and model request emits a JSON log line with run id, turn, prompt versions, model slug, latency, tokens and cost; an
optional OpenTelemetry trace per run behind a flag; no new required dependency; a log viewer on the UI run page.
Reviews are approved by @ilikeandroid."

## Clarifications

### Session 2026-11-13

- Q: Where should a run's log lines be kept so the API can serve them to the run-page viewer? → A: In the run's
  own database — a per-run log table beside the run rows (the next additive schema step), deleted with the run;
  every line also goes to the log stream. At the per-run cap the first 1,000 lines are kept and one final
  `log.truncated` marker line records how many lines were dropped; the stream keeps everything.
- Q: Does Kestrel's whole log stream become JSON lines, or only the new run/turn/model/target events? → A: The
  whole stream, by default: every line Kestrel writes is a JSON object, the pre-existing lines becoming records
  with the same common fields; a setting switches to a plain-text format for local reading that renders the same
  fields, so nothing is lost by switching. Records are built from named fields, never by interpolating values into
  the message text. The pre-existing connection-test line keeps the target id and the outcome only.
- Q: When the tracing flag is on, where do the spans go? → A: To a collector over the standard OpenTelemetry
  protocol, configured by the standard `OTEL_EXPORTER_OTLP_*` environment variables with the service name
  defaulting to `kestrel`; the optional extra carries the SDK and that exporter. One root span per run carrying the
  run id, with child spans per turn, per model request and per target request. The flag on with the collector
  unreachable or the extra missing never fails, blocks or changes a run: exactly one warning line is logged and the
  flush at shutdown waits at most 5 seconds. OpenTelemetry only — LangSmith is out of scope. The recommender runs
  at report time and is logged, not traced.
- Q: Beyond the run, turn, model-request and target-request lines, are the roadmap's operational events in scope?
  → A: Yes, as log lines of the same shape (not spans): memory retrieval counts and the retrieved pattern ids,
  the write-back result, and an experiment's start, cap hit and end. The judge-call line carries the verdict and
  the hard-evidence flag; the target-call line carries the elapsed time and the HTTP status. Every record carries
  the run id, and every record of a run executed by an experiment carries the experiment id and the arm. A
  single-turn run emits no attacker model-request line (its message is the library seed).
- Q: How should the real OpenTelemetry adapter be verified offline given tracing is an optional extra? → A: The
  tracing packages are installed in the development environment only (never a runtime dependency) so the suite
  drives the real adapter with an in-process span collector; the "flag on, package missing" path is tested by
  making the import fail; and a test proves that no auth header value reaches a log line or a span attribute. The
  one-line Principle X justification for the optional extra and for the development-only packages goes in the
  plan.

### Session 2026-11-13 (spec review, round 1)

- Q: Can the API's own request handling, or an experiment's background task, become part of a run's trace? → A:
  No. Kestrel's tracer is private (the web framework's built-in telemetry stays off), the run's root span has no
  parent, only Kestrel's own spans exist, and an experiment of two runs yields two traces.
- Q: What is a run's scope, and where does the write-back line sit? → A: The scope runs from the claim of the run
  row to the end of the run's write-back; the write-back line is inside it and kept with the run, and the run-end
  line is the scope's last line, emitted after the write-back.
- Q: Which lines are kept in a run's log? → A: Exactly the records emitted inside the run's scope, run-start to
  run-end inclusive, plus the truncation marker. A line emitted for a run after its scope has closed — the
  recommender line at report time — goes to the stream only, is never kept and never disturbs the kept log.
- Q: What if the recorded prompt provenance differs from the version actually sent (an experiment arm pinning a
  non-active version; a single-turn run's judge)? → A: The provenance is corrected to record the version actually
  used, from the same source the log lines use, so FR-007's equality holds; this closes a feature-009 recording
  gap and is in scope because FR-007 depends on it.
- Q: What does a turn line carry beyond the turn's outcome? → A: Its duration, its token totals (prompt,
  completion, total), its cost, the attacker and judge model slugs, and the attacker and judge prompt references.
- Q: Does the log viewer appear for a run whose send failed? → A: Yes — for every opened run.
- Q: When is the retrieval line emitted and what does "warm" mean on it? → A: Whenever the run asks the experience
  store for background, with zero counts when nothing came back; `warm` means at least one pattern was retrieved.
- Q: What does `judge_used` mean on a run-end line? → A: At least one judge request was made during the run.
- Q: May a trace context header reach the target? → A: No — it MUST NOT, and a test proves none does.
- Q: What is "the log stream", and how are the suite-wide criteria measured? → A: The stream is the output of
  Kestrel's own logger (the web server's lines are not part of it); the criteria are measured over the named runs
  the offline suite drives, and existing tests are neither deleted nor weakened — their assertions change only in
  the shape of the log lines they read.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Follow a run line by line (Priority: P1)

A red-teamer runs an attack and wants to know exactly what Kestrel did and what it cost: when the run started and
how it ended, each turn, each request to a model (the attacker, the judge, the recommender) with the model slug and
the prompt version that drove it, how long each step took, how many tokens it used and what those tokens cost, and
each request to the target with its latency and status. Every one of these events is one JSON line on Kestrel's
log stream, so the log can be read by eye, grepped, or fed to any log tool without parsing prose. A run that is
part of an experiment says which experiment and which arm it belongs to on every line.

**Why this priority**: Today a run leaves a single free-text log line and a database row. When a run is slow,
expensive or surprising there is nothing to read. Machine-readable, per-event lines with identifiers, timings,
tokens and cost are the foundation the viewer (US3) and the traces (US4) build on, and they make every later
question ("which model, which prompt version, how long, how much") answerable from the log alone.

**Independent Test**: Drive a single-turn run and an adaptive run against a stub target, with the real model
clients answering through a mocked transport, capture the log stream, parse every line as JSON, and check that the
expected events appear in order with the expected fields; repeat for a run inside a two-arm experiment and for a
report generation that calls the recommender.

**Acceptance Scenarios**:

1. **Given** a single-turn run against a stub target with a judge configured, **When** it finishes, **Then** the
   log stream carries, in this order, a run-start line, a target-request line, a judge model-request line, a turn
   line, a write-back line and a run-end line, each a complete JSON object on one line and each carrying the run
   id.
2. **Given** an adaptive run that uses N turns, **When** it finishes, **Then** there is exactly one turn line per
   turn carrying its turn number, duration, token totals, cost, the model slugs and prompt references in play, one
   attacker model-request line per attacker call, one judge model-request line per judge call, and one
   target-request line per message sent, every one carrying the run id and turn number.
3. **Given** any model-request line, **When** it is read, **Then** it names the request kind (attacker, judge or
   recommender), the model slug, the prompt id and version that was sent (for example `judge@1`), the latency in
   milliseconds, the outcome (the provider's status or the error kind), the number of attempts, the token counts
   the provider reported, and the estimated cost — or a null cost with the reason it could not be estimated; a
   judge line also carries the verdict it returned and the hard-evidence flag.
4. **Given** a run that belongs to an experiment, **When** any of its lines is read, **Then** the line carries the
   experiment id and the arm label as well as the run id.
5. **Given** a report generation that calls the recommender for a finding, **When** the call completes, **Then** a
   recommender model-request line on the stream carries the id of the run the finding belongs to and the
   recommender prompt version, and the run's kept log is unchanged.
6. **Given** a run-end line, **When** it is read, **Then** it carries the verdict, whether the evidence was hard,
   the stopping condition, whether at least one judge request was made, the turns and tokens used, whether the
   run was written back, the run's duration, and the run's total estimated cost (or a null total with the reason),
   and it is the last line of the run.
7. **Given** a run that asks the experience store for background, a finished run and an experiment that hits a
   cap, **When** their lines are read, **Then** a retrieval line carries the counts of patterns and memory records
   retrieved (zero when nothing came back) and the pattern ids, with `warm` true only when at least one pattern
   was retrieved; a write-back line inside the run says whether the run was written back; and the experiment's
   start, cap-hit and end lines carry the experiment id, the cap that stopped it, the runs completed and the
   tokens used.
8. **Given** an experiment arm that pins a prompt version other than the active one, **When** its run's lines and
   the provenance recorded on the run and its turns are read, **Then** both name the pinned version.

---

### User Story 2 - The log never leaks (Priority: P1)

An operator ships Kestrel's log stream to a shared log tool, or opens a run's log on the screen, and must be
certain that nothing sensitive went with it: no auth header value, no target URL, no target name, no attack
message, no reply from the target, no model-written free text about the reply. Log lines, trace attributes, the log
endpoint and the log viewer carry identifiers, counts, model slugs, prompt versions, timings, token counts and cost
only.

**Why this priority**: Secrets never leave the vault (Principle IV) and no attack text is committed or shown
outside the run record. A log is the easiest place for both to leak, because it is copied, shipped and read by
tools the user does not control. The guarantee has to be explicit and tested, not assumed.

**Independent Test**: Register a stub target whose auth header value, URL and display name are known strings,
drive a run whose attack message and target reply are known strings, with tracing on against an in-process span
collector, then inspect every log line, every span attribute, the log endpoint's response and the rendered viewer
and assert that none of the known strings appears.

**Acceptance Scenarios**:

1. **Given** a target with a known auth header value, URL and display name and a run with a known attack message
   and a known reply, **When** every log line, span attribute, log endpoint response and viewer rendering produced
   during and after the run is inspected, **Then** each of those strings appears zero times.
2. **Given** a judged turn, **When** its lines are read, **Then** they carry the verdict as a category and never
   the judge's free-text reason or progress note (which may quote the reply).
3. **Given** a connection test of an unsaved or saved target, **When** its line is read, **Then** it carries the
   step, status and duration (and the target id when the target is saved) and neither the URL nor the display name.
4. **Given** a model request that fails with an error, **When** its line is read, **Then** it carries the error
   kind and status only, never the error message text.
5. **Given** tracing is on, **When** a run's spans are collected in-process, **Then** no span attribute carries the
   auth header value, the URL, the display name, the attack message or the reply.

---

### User Story 3 - Read a run's log on the run page (Priority: P2)

A red-teamer opens a run on the screen and, under the finding, sees the run's log: every line Kestrel kept for that
run, in order, as a table (time, event, turn, model, prompt version, latency, tokens, cost) with the raw JSON
available. The screen reads the lines through the API only; it never opens a file or the database.

**Why this priority**: The primary user pastes a URL and reads a report; they will not tail a terminal. Showing the
run's own lines on its page makes the new information usable without any tooling. It depends on US1 (the lines
must exist and be kept) but US1 is valuable without it.

**Independent Test**: Record a run's lines, request them through the log endpoint and confirm they come back in
order and in full; render the run page with those lines and confirm the viewer shows them; request the log of an
unknown run and of a run with no kept lines and confirm the explicit responses.

**Acceptance Scenarios**:

1. **Given** a finished run with kept lines — including a run whose send failed — **When** the operator opens the
   run on the run page, **Then** a log viewer lists its lines in recording order with the time, event, turn, model,
   prompt version, latency, tokens and cost of each, and the raw JSON of each line can be shown.
2. **Given** a run that predates this feature (no kept lines), **When** it is opened, **Then** the viewer states
   that no log lines were recorded for it, rather than showing an empty table or an error.
3. **Given** an unknown run id, **When** its log is requested, **Then** the API answers "not found".
4. **Given** hosted mode, **When** the log is requested without the API token, **Then** the request is refused like
   every other request.
5. **Given** a run that is still in progress (an experiment's run in the background), **When** its log is requested,
   **Then** the lines kept so far are returned.
6. **Given** a run whose kept log was truncated at the cap, **When** it is opened, **Then** the viewer shows the
   kept lines and the final marker line with the number of dropped lines.
7. **Given** a report generated after a run (normal or truncated at the cap), **When** the run's log is requested,
   **Then** it is exactly what it was before the report — the recommender's line went to the stream only.

---

### User Story 4 - Trace a run, optionally (Priority: P2)

An operator who already runs a tracing collector turns on a flag and gets one trace per run: a root span for the
run carrying the run id, and child spans for each turn, each model request and each target request, carrying the
same identifiers, timings, tokens and cost as the log lines. Without the flag nothing changes. With the flag but
without the optional tracing package installed, Kestrel says so once and runs exactly as before.

**Why this priority**: Traces answer "where did the time go in this run" at a glance and plug into tooling teams
already have. They are optional because the primary user has no collector; the log lines (US1) carry the same
facts for everyone.

**Independent Test**: With the flag off, run and confirm no tracing component is loaded and no span is produced;
with the flag on and the package available, run and confirm exactly one trace with the expected span tree and
attributes using an in-process span collector; with the flag on and the package unavailable, confirm one warning
and an unchanged run; with the flag on and the collector unreachable, confirm an unchanged run, one warning and a
bounded shutdown.

**Acceptance Scenarios**:

1. **Given** the tracing flag is off (the default), **When** a run executes, **Then** Kestrel's tracing code loads
   no tracing package and no span is produced.
2. **Given** the flag is on and the optional tracing package is installed, **When** a run executes — started from
   the API or by an experiment — **Then** exactly one trace is produced for it: a root span for the run that has
   no parent and carries the run id, child spans for each turn, each model request and each target request, no
   other span, and attributes limited to the same fields the log lines carry; two runs of one experiment yield
   two traces.
3. **Given** the flag is on and the optional package is not installed, **When** Kestrel starts, **Then** exactly one
   warning line says tracing is unavailable, and every run proceeds without tracing with no error and no change of
   outcome.
4. **Given** the flag is on and the collector cannot be reached or refuses the spans, **When** a run executes and
   Kestrel later shuts down, **Then** the run completes unchanged, the delivery failure is reported as exactly one
   warning, and the shutdown flush waits at most 5 seconds.
5. **Given** the flag is on and no collector address is configured, **When** a run executes, **Then** spans go to
   the standard default collector address and the service is named `kestrel` unless the standard service-name
   variable says otherwise.
6. **Given** the flag is on, **When** the run sends messages to the target, **Then** no trace context header
   reaches the target.

---

### User Story 5 - Logging can never harm a run (Priority: P1)

A maintainer changes nothing about attacks, judging or scoring by turning logging on, keeping run logs, or tracing:
a run reaches the same verdict, with the same evidence, in the same number of turns and tokens, whether or not a
log line could be kept or a span could be delivered. A failure inside logging or tracing is reported once as a
warning and never stops, fails, blocks or slows a run materially.

**Why this priority**: Observability that can break the thing it observes is worse than none. Runs are bounded by
hard caps (Principle VIII) and judged on hard evidence (Principle II); the new machinery must not touch either.

**Independent Test**: Drive the same stub run with the log sink working, with the log sink failing, and with a
failing trace exporter, and compare verdict, hard evidence, stopping condition, turns and tokens used; check that
no model call and no target request is made by logging or tracing; check the per-run line cap.

**Acceptance Scenarios**:

1. **Given** a log sink that fails on every write, **When** a run executes, **Then** the run completes with the
   same verdict, evidence, stopping condition, turns and tokens as with a working sink, and one warning names the
   sink failure.
2. **Given** a trace exporter that fails on every delivery, **When** a run executes, **Then** the same holds.
3. **Given** any run, **When** logging and tracing are on, **Then** they add no model call and no target request,
   and no token they account for is counted against the run's token budget.
4. **Given** a run that would keep more lines than the per-run cap, **When** the cap is reached, **Then** further
   lines still reach the log stream, the kept log ends with one marker line recording the dropped count, and the
   run continues.

### Edge Cases

- A single-turn run makes no attacker model request: its turn line names the attack library seed (by prompt id) as
  the message source and carries no attacker model slug or attacker prompt reference, and no attacker model-request
  line is invented for it.
- The judge is not configured (single-turn or adaptive): no judge model-request line is emitted, the run-start
  line carries no judge prompt reference, the turn line carries no judge fields, the run and its turns record
  null judge provenance, and the run-end line's `judge_used` is false because no judge request was made —
  whatever the run's stored flags say.
- A turn is decided by a canary match: no judge call is made, so there is no judge line; the turn line carries the
  canary match and the hard-evidence flag and a null judge prompt reference, and the turn's recorded judge
  provenance is null. On a judge line the hard-evidence flag is always false, because the judge
  is consulted only when no canary matched — the flag is carried so a judge line can never be read as a confirmed
  finding (Principle II).
- The attacker model fails or returns nothing usable: a model-request line carries the error kind and no tokens,
  and the run-end line carries the attacker-failed stopping condition.
- A transient provider error is retried inside one logical request: one model-request line carries the attempt
  count, the final status and the tokens summed over every attempt, so a retry cannot hide spend.
- The provider reports no token usage: the token fields are null, the cost is null with the reason, and the run's
  budget accounting is unchanged (it keeps treating an absent count as zero).
- No price is configured for the model: the cost is null with the reason, never zero; the run-end total is null
  with the reason if any request of the run lacked a price.
- A run predates this feature: the viewer says no lines were recorded; nothing is guessed or back-filled.
- The per-run cap on kept lines is reached: the first 1,000 lines are kept, the stream keeps everything, one final
  `log.truncated` marker line records the dropped count when the run ends, and the run is unaffected.
- The tracing flag is on but the optional package is missing: exactly one warning at start-up, then runs behave as
  with the flag off.
- The collector is unreachable or refuses the spans: exactly one warning; spans are dropped; the run is unaffected;
  shutdown waits at most 5 seconds for delivery.
- A line or span fails to format or to be kept: the failure is logged once as a warning and swallowed.
- A connection test is not a run: its line carries no run id, and no URL or display name either — the target id
  (when saved), the step, the status and the duration only.
- The recommender runs at report time, outside any run's scope: its line carries the id of the finding's run, goes
  to the stream only, is not kept in the run's log and does not disturb the kept log or its marker; it is not part
  of the run's trace.
- An experiment's run is linked to its experiment only after it finishes today, but every line emitted during the
  run must already carry the experiment id and arm label.
- An experiment arm pins a prompt version that is not the active one: the lines and the recorded provenance both
  name the pinned version (the recording is corrected; the pinned text is what the model received).
- Retrieval is asked but nothing comes back (an empty or cold store): the retrieval line is still emitted with zero
  counts and `warm` false; a run with prior experience switched off asks for nothing and emits no retrieval line.
- A start-up failure (the attack library, the experience store, its seeding): a named event with the failure's
  class, never its message text.
- A target is deleted: its runs' kept lines go with the runs.
- The plain-text format is selected: the same fields are rendered, so switching formats loses nothing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every run MUST emit a run-start line when its row is claimed and a run-end line as the last line of
  its scope — after the run's write-back has completed. The run-start line MUST carry the run id, target id, mode,
  attack family, the library prompt id of the seed, the attacker source, the attacker and judge model slugs in
  play, the attacker and judge prompt versions in play, the run's hard caps (turn budget, token budget, time limit)
  and whether prior experience is used. The run-end line MUST carry the verdict, whether the evidence is hard, the
  stopping condition, whether at least one judge request was made (`judge_used`), the turns used, the tokens used,
  whether the run was written back, the duration in milliseconds and the run's total estimated cost (or null with
  the reason).
- **FR-002**: Every turn MUST emit one turn line carrying the turn number, the source of the attacker message (the
  library seed's prompt id, or the attacker prompt id and version that generated it), the turn's duration in
  milliseconds, the turn's prompt, completion and total token counts (null when nothing was reported), the turn's
  estimated cost (or null with the reason), the attacker and judge model slugs and the attacker prompt reference
  in play (each absent when no such request can occur in the turn), the judge prompt reference of the judge
  request made on the turn (null when none was made — a canary-decided turn; absent when no judge is
  configured), the length in characters of the
  message and of the reply, whether the reply was truncated, whether a canary matched, the hard-evidence flag, and
  the turn's verdict category if it was judged. A single-turn run emits exactly one turn line.
- **FR-003**: Every request to a model — an attacker generation, a judge verdict, a recommender call — MUST emit one
  model-request line carrying the request kind, the model slug, the prompt id and version sent (`id@version`), the
  latency in milliseconds measured over the whole logical request including retries, the outcome (the provider's
  status code, or the error kind when the request failed), the number of attempts, the prompt, completion and total
  token counts the provider reported (null when it reported none), and the estimated cost (or null with the reason).
  A judge line additionally carries the verdict category it returned and the hard-evidence flag (always false on a
  judge line, because the judge is consulted only when no canary matched). A recommender line carries the id of the
  run whose finding it advises on; it is emitted outside that run's scope, so it reaches the stream only (FR-010).
  A single-turn run makes no attacker request and emits no attacker line.
- **FR-004**: Every request to the target MUST emit one target-request line carrying the elapsed time in
  milliseconds, the outcome (the HTTP status code when one was received, otherwise the failure step name), the
  reply length in characters and whether the reply was truncated — and nothing about the URL, headers, request body
  or reply text.
- **FR-005**: A run's scope MUST run from the claim of its row to the end of its write-back. Every record emitted
  inside the scope MUST carry the run id, the target id, the mode and the family; records about a turn MUST carry
  the turn number; every record of a run executed by an experiment MUST carry the experiment id and the arm label.
  Every record MUST carry a UTC timestamp, a level and an event name.
- **FR-006**: The log stream is the output of Kestrel's own logger (the web server's lines are not part of it).
  Every line on it MUST be exactly one JSON object per line (JSON Lines), including the lines that predate this
  feature, which become records with the same common fields: a record's message is constant text and every value
  (a count, a path, an exception type, an id) travels as a field; no exception text is embedded. The event names
  and field names MUST be stable and documented. One setting MUST switch the stream to a plain-text format that
  renders the same fields, for local reading; JSON is the default.
- **FR-007**: The prompt versions on a line MUST be the versions actually sent to the model — the active version
  from the prompt registry, or the version an experiment arm pinned — written as `id@version`, and wherever
  provenance is recorded on the run or its turns (non-null) the line MUST equal it. Judge provenance is recorded
  only when a judge request was made: an adaptive run with no judge records null judge provenance and its
  run-start line carries no judge prompt reference; a canary-decided turn records null judge provenance and its
  turn line carries a null judge prompt reference. Where the recording today departs from what was sent (an arm
  that pins a non-active version is recorded as the active one; a single-turn run records no judge version), the
  provenance MUST be corrected to record the version actually used, taken from the same source the lines use.
- **FR-008**: The estimated cost of a model request MUST be computed from the provider-reported total tokens and
  the price configured for that model slug in the existing per-model price table, with the same arithmetic the
  experiment harness uses; when no price is configured for the model, or the provider reported no usage, the cost
  MUST be null with a one-line reason, never zero. A run's total MUST be the sum over its requests, or null with
  the reason if any request's cost is null.
- **FR-009**: No log line, no trace attribute, no response of the log endpoint and no rendering of the log viewer
  MUST ever contain an auth header value, an API key or token, the target URL, the target display name, the attack
  message text, the target's reply text, the judge's free-text reason or progress note, or a provider or exception
  message text. Lines carry identifiers, counts, lengths, category values, model slugs, prompt versions, timings,
  token counts and cost only. This applies to every line Kestrel emits, including the pre-existing connection-test
  line, which keeps the target id (when saved), the step, the status and the duration only. A test MUST prove that
  no auth header value reaches a log line or a span attribute.
- **FR-010**: Every record emitted inside a run's scope — from its run-start line to its run-end line inclusive —
  MUST be kept with the run, in emission order, in the run's own database so that it can be served later; a record
  emitted for a run after its scope has closed (the recommender line at report time) MUST reach the stream only and
  MUST NOT be kept or alter the kept log. Kept lines live as long as the run (they are deleted with it) and are
  bounded by a fixed per-run cap of 1,000 lines — when the cap is reached, the first 1,000 lines are kept, later
  lines still reach the stream, one final `log.truncated` marker line recording the dropped count is kept when the
  run ends, and the run continues.
- **FR-011**: The API MUST serve a run's kept lines in order through a run-scoped read endpoint that answers "not
  found" for an unknown run, an empty list for a run with no kept lines, and the lines kept so far for a run in
  progress; the endpoint is subject to the same hosted-mode token as every other endpoint and returns no field
  outside the FR-009 allow-list.
- **FR-012**: The run page MUST show a log viewer for every opened run — including a run whose send failed — that
  lists its kept lines in order with the time, event, turn, model, prompt version, latency, tokens and cost of each
  and offers the raw JSON of each line; a run with no kept lines MUST show an explicit "no log lines were recorded"
  state, and a truncated log MUST show its marker line. The viewer MUST obtain the lines through the API only.
- **FR-013**: Tracing MUST be off by default and MUST be turned on by one setting. When on, every run MUST produce
  exactly one trace of its own: a root span for the run that has no parent and carries the run id, child spans for
  each turn, each model request and each target request, and no other span — the web framework's built-in request
  spans stay off, so neither an API request nor an experiment's background task can become part of a run's trace.
  Span attributes are limited to the fields the corresponding log lines carry (FR-009 applies). Spans MUST be
  delivered to a collector over the standard OpenTelemetry protocol, configured by the standard
  `OTEL_EXPORTER_OTLP_*` environment variables (none of which Kestrel overrides), with the service name defaulting
  to `kestrel` unless the standard service-name variable is set. Kestrel MUST NOT add a trace context header to any
  request sent to the target. The recommender, which runs at report time, is logged and not traced.
- **FR-014**: Tracing MUST NOT add a required dependency: the tracing packages are an optional extra, installed in
  the development environment only for the test suite. With the flag off, Kestrel's own tracing code MUST NOT
  import any tracing package, and the tracing module MUST have no module-level import of one (the fixed stack's
  own, transitive use of the tracing library is unaffected and is not what this measures). With the flag on and the
  packages absent, Kestrel MUST log exactly one warning at start-up and run without tracing.
- **FR-015**: A failure inside logging or tracing — formatting a line, keeping a line, creating or delivering a
  span, a collector that is unreachable or that refuses the spans — MUST be caught, reported as exactly one
  warning per failure cause, and MUST never fail, stop, block or change the outcome of a run; logging and tracing
  MUST add no model call and no target request and MUST NOT count toward a run's token budget. Span delivery MUST
  NOT block the run, and the flush of undelivered spans at shutdown MUST wait at most 5 seconds whatever the
  collector does.
- **FR-016**: Beyond the lines of FR-001 to FR-004, Kestrel MUST emit operational lines of the same shape for: the
  attacker's background retrieval, emitted whenever the run asks the experience store for background (counts of
  patterns and memory records retrieved — zero when nothing came back — the pattern ids, and `warm`, true only
  when at least one pattern was retrieved; a run with prior experience switched off asks for nothing and emits no
  retrieval line); the write-back result after a run (written or failed), emitted inside the run's scope; and an
  experiment's start, cap hit (which cap, runs completed, tokens used) and end (status and reason). These are
  lines, not spans.
- **FR-017**: With logging on and tracing off (the shipped default), every attack, judge, recommendation, scoring
  and experiment behaviour MUST be unchanged — this feature is observability only, and the existing hard caps and
  permission gate are untouched. The one recording change is the provenance correction of FR-007, which changes
  what is recorded about a run, never what the run does.

### Key Entities

- **Log line (event record)**: one JSON object on the log stream describing one event — a run start or end, a
  turn, a model request, a target request, a connection test, or an operational event — with the common fields
  (timestamp, level, event name, run id, target id, mode, family, turn, experiment id and arm when applicable) and
  the event's own fields as named members; never any text from the FR-009 deny-list.
- **Run scope**: the span of time from the claim of a run's row to the end of its write-back; every record emitted
  inside it carries the run's identifiers and is kept; the run-end line closes it.
- **Model-request record**: the fields of a model request — kind, model slug, prompt `id@version`, latency, outcome,
  attempts, prompt/completion/total tokens, estimated cost and its reason when null, and the verdict category plus
  the hard-evidence flag for a judge call.
- **Turn record**: the turn's number, message source, duration, token totals, cost, the model slugs and prompt
  references in play, message and reply lengths, canary and hard-evidence flags and verdict category.
- **Run log**: the ordered set of records kept for one run — exactly those emitted inside its scope, at most the
  first 1,000 plus one `log.truncated` marker carrying the dropped count; lives and dies with the run; never
  touched by a record emitted after the scope closed.
- **Cost estimate**: tokens / 1,000 × the configured price for the model slug; null with a reason when the price or
  the usage is missing; summed to a run total that is null when any part is.
- **Trace**: one per run when tracing is on — a parentless root span for the run carrying the run id and child
  spans per turn, model request and target request, nothing else, with attributes drawn from the same allow-listed
  fields; delivered to the collector the standard variables name, under the service name `kestrel` by default.
- **Tracing flag**: the single setting that turns tracing on; off by default.
- **Log viewer**: the run page's table and raw view of a run's kept lines, fed by the log endpoint.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Each run the offline suite drives for this feature — the stub single-turn run, the stub adaptive run
  of N turns, the two runs of the two-arm experiment and the redaction runs — produces a run-start line, one turn
  line per turn, one model-request line per model request made, one target-request line per target request made,
  a write-back line and a run-end line, in order, and every line on the stream during those runs parses as a JSON
  object.
- **SC-002**: Across every log line, trace attribute, log endpoint response and viewer rendering produced by the
  redaction runs (a single-turn and an adaptive run against a stub target with a known auth header value, URL and
  display name and a known attack message and reply, tracing on), the known strings each appear zero times; on
  the end-to-end run against the owned HS-code target, the target's real key appears zero times in the API's log
  output and in the run's served lines.
- **SC-003**: A run's log is one click away from the opened run on the run page, lists every kept line in order with
  its time, event, turn, model, prompt version, latency, tokens and cost, and a run without kept lines shows the
  explicit "no log lines were recorded" state.
- **SC-004**: With the tracing flag on and the packages installed, every run — started from the API or by an
  experiment of two runs — produces exactly one trace of its own whose parentless root span carries the run id,
  whose child spans cover 100% of its turns, model requests and target requests, and which contains no other
  span; with the flag on and the packages absent, exactly one warning is logged per process start and every run
  completes; with the flag on and the collector unreachable or refusing, every run completes, exactly one warning
  is logged and shutdown waits at most 5 seconds; with the flag off, Kestrel's own tracing code imports no tracing
  package.
- **SC-005**: Verdict, hard evidence, stopping condition, turns used and tokens used are identical for the same
  stub-driven run with a working log sink, a failing log sink and a failing trace exporter; after the feature no
  existing test is deleted or weakened, and existing assertions change only in the shape of the log lines they
  read.
- **SC-006**: For every model request with a configured price, the line's cost equals total tokens / 1,000 × price
  (within 1e-9); for every request without a price or without reported usage, the cost is null with a reason and
  never zero.
- **SC-007**: Kestrel's required dependencies are unchanged, and the offline suite passes once in the test-suite
  mode that blocks the tracing exporter's import (a test-configuration switch; the tests that need the real
  exporter are skipped in that mode) — every feature except tracing works without the optional extra.
- **SC-008**: 100% of the records emitted inside the scope of the two runs of the suite's two-arm experiment carry
  the experiment id and arm label.
- **SC-009**: No run keeps more than 1,000 lines plus one marker; a run that reaches the cap keeps its first 1,000
  lines and one final `log.truncated` line whose dropped count equals the number of lines not kept, and still
  finishes normally.

## Assumptions

- The structured lines are produced by the standard logging facilities already in the stack and serialised as JSON
  with the standard library; no new runtime dependency is needed for logging (Principle X). The tracing packages
  are an optional extra; the test suite exercises the real tracing adapter with an in-process span collector, so
  the extra is installed in the development environment only, with the Principle X justification in the plan.
- The log stream is the output of Kestrel's own logger, written to the process's standard error stream as today;
  the web server's own lines on that stream are not part of it. Every line on the stream is JSON (the plain-text
  format is a setting for local reading that renders the same fields); shipping, rotating and retaining the stream
  is the operator's concern and out of scope.
- A run's kept lines live in the same database as the run, in a per-run log table deleted with the run; this is
  the next additive schema step after the current version. A run that predates the step simply has no kept lines.
- Traces go to a collector over the standard OpenTelemetry protocol at the endpoint the standard
  `OTEL_EXPORTER_OTLP_*` variables name (the standard default address when none is set), under the service name
  `kestrel` by default; the optional extra carries the SDK and that exporter. Kestrel's tracer is private — the web
  framework's built-in telemetry stays off — so only Kestrel's spans exist. LangSmith is out of scope.
- The operational lines of FR-016 (retrieval counts and pattern ids, write-back result, experiment start, cap hit
  and end) are in scope as lines of the same shape, not as spans.
- The cost arithmetic reuses the experiment harness's price table (one blended price per 1,000 tokens per model
  slug) and its "unavailable (no configured price for ...)" wording; prompt and completion token counts are the
  provider's reported usage, and the run's existing budget accounting is not changed by this feature.
- Prompt versions come from the feature-009 registry, which records provenance on runs and turns; three prompt
  kinds exist (attacker per family, judge, recommender) — the memory summariser is deterministic and makes no model
  request, so it emits no model-request line. The recording of that provenance is corrected where it departs from
  the version actually sent (FR-007); the registry itself is unchanged.
- A single-turn run makes no attacker model request (its message is the library seed), so attacker lines occur in
  adaptive runs; both modes emit run, turn, target-request, write-back and judge lines.
- Latency of a model request is measured over the whole logical request, retries included; attempts are counted;
  tokens are summed over attempts, matching the existing budget accounting.
- The run's scope is opened by the code that starts the run and ends after its write-back, so the experiment id
  and arm label are bound before the run starts (the experiment engine knows them when it launches each run), even
  though the run–experiment link row is written after the run today.
- Tracing uses one trace per run with the spans named in FR-013; the recommender runs at report time outside any
  run and is logged, not traced. Trace context is not propagated to the target.
- The existing connection-test log line changes shape (JSON; target id when saved, step, status and duration only)
  as a consequence of FR-006 and FR-009; no other feature-001 behaviour changes.
- Hard caps, the permission box and the token budget (Principle VIII) are unchanged; a line or span never counts
  toward a budget.
- One end-to-end scenario against the owned HS-code target is the only test that needs a model key; every other
  requirement and criterion is verified offline with stub targets, the real model clients over a mocked transport,
  sinks and span collectors.
- **Footnote (plan finding):** two libraries of the fixed stack, ChromaDB and FastAPI, already depend on the
  OpenTelemetry API and SDK, and importing ChromaDB loads the SDK whatever Kestrel's flag says. The optional extra
  therefore genuinely adds only the OTLP/HTTP exporter, "no tracing package imported with the flag off" (FR-014,
  SC-004) measures Kestrel's own tracing code, and the "package missing" path is exercised in tests by making the
  exporter import fail.

## Out of Scope

- Metrics (counters, histograms), dashboards, alerting, and any log-shipping or rotation of the log stream.
- Tracing of API request handling or of the screen; only runs are traced. LangSmith or any vendor-specific tracing —
  OpenTelemetry only.
- A live tail: the viewer shows the lines kept so far when the run page is rendered or refreshed.
- Changing what is logged by the sacrificial HS-code target (test support only).
- Retention policies for kept lines beyond the run's own lifetime, and exporting a run's log in other formats.
- Logging the content of prompts, messages, replies or reasons anywhere — excluded by design, not deferred.
