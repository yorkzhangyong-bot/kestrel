# Traceability — 013 Behavioural Evidence (part 1)

Part 1 of this feature ships as its own pull request (FR-062). Every part-1 id carries a `013/FR-###`/`013/SC-###`
token or a bare id in a test file marked `FEATURE = "013"`; the ids a test cannot carry, and every part-2 id, are
justified below in the form `scripts/check_traceability.py` reads. T068 rewrites this file for the whole feature
with the last pull request.

## Part 1 — covered by tests

| id | Covered by |
|----|------------|
| FR-001, FR-002, FR-005, FR-006 | `tests/integration/test_evidence_detectors.py` (the fixed order, any item ends the run with no judge call, a canary and a detector match as two items); `tests/integration/test_evidence_part1_replay.py` (the canary as an item through the checker) |
| FR-003, FR-038 | `tests/unit/test_store_evidence.py` (items stored with the run, listed in the order found, one query per target); `tests/integration/test_evidence_api_ui.py` (every item field on the summary and the detail) |
| FR-004, FR-039 | `tests/unit/test_evidence_model.py` (the seven kinds, labels, locations and classes; the exact evidence line); `tests/integration/test_evidence_api_ui.py` (the headline, the Evidence section, the notices) |
| FR-007 | `tests/unit/test_evidence_model.py` (no detail the model builds carries the run's own token parts or a URL); `tests/integration/test_evidence_detectors.py` (an excerpt carrying a token part is scrubbed before it is stored) |
| FR-008, FR-009, FR-012, FR-013, FR-051, SC-001 | `tests/unit/test_override_detector.py` (the token, the joined-form check, the normalised disarm check, 1,000 opening messages never carry the joined form); `tests/integration/test_evidence_detectors.py` (confirmed without the judge, the parts apart confirm nothing, the joined form in no sent message, a disarmed run records no item and the exact notice) |
| FR-010, FR-011, FR-064, SC-014 | `tests/unit/test_override_placement.py` (the sidecar: every shipped seed, fingerprints, direct at the attacker-voice end with no frame, indirect interior with its quoting frame present, the paragraph inside the frame's quoted span, the joined form absent from the framed message after normalisation, the run's task text is the framed text as one string, the runtime lookup returns the reviewed point, the `framing: override` field); `tests/integration/test_evidence_detectors.py` (a family that carries no task sends today's message); `tests/integration/test_evidence_store_isolation.py` (a shipped indirect seed's framed text is stripped whole) |
| FR-014, FR-017, FR-018, FR-065, SC-002, SC-003 | `tests/unit/test_unsafe_output.py` (the fixture's coverage rule, 100% positive / 0% negative per named pattern, one match per category, the echo rule, the contract's own table and set version); `tests/integration/test_evidence_detectors.py` (confirmed under LLM05 with the pattern name and set version, benign shapes record nothing, a Kestrel-sent message is never scanned) |
| FR-015, FR-016, FR-059 | `tests/unit/test_unsafe_output.py` (the contract, the module and the fixture cannot drift; the inert note) |
| FR-034 | `tests/unit/test_store_evidence.py` (the status written at claim time, the one in-run update, never nulled by the sweep) |
| FR-035, FR-036, FR-037, SC-009 | `tests/integration/test_evidence_part1_replay.py` (the token copy with its armed state, any item scores still vulnerable on both paths, a pre-feature source, both experiment arms alike); `tests/integration/test_evidence_replay_detectors.py` (the real detectors on both replay paths, the re-sent disarming message, an inherited disarm applying from its own turn) |
| FR-040, FR-042, FR-043, SC-004, SC-008 | `tests/integration/test_evidence_api_ui.py` (the run-list column, today's text for a run without items, the config block, nothing derived in the screen) |
| FR-044, FR-045 | `tests/unit/test_report_findings.py`, `tests/unit/test_report_coverage.py` (items per finding, confirmed only under a class an item carries, held otherwise, the LLM05 row, six untested classes) |
| FR-047, FR-048, SC-007 | `tests/unit/test_events_evidence.py` (the catalogue, the four `run.start` fields omitted when absent, `evidence.check`, the `turn`/`run.end` fields); `tests/integration/test_evidence_redaction.py` (0 lines carry a token, a detail, reply or attack text) |
| FR-050, SC-012 | `tests/integration/test_evidence_detectors.py` (a confirmed run makes no model request at all; a judged run makes the one it made before) |
| FR-057 | `tests/unit/test_store_migration_v11.py` (additive, no rebuild, every row readable) |
| FR-061 | `tests/integration/test_evidence_store_isolation.py` (a family that plants nothing writes exactly what it did before); `tests/unit/test_retrieval_query_scrub.py` (the query without planted values is unchanged) |
| FR-063, SC-013 | `tests/unit/test_strip_planted_tasks.py` (a framed task stripped whole, the bare paragraph alone would leave the frame); `tests/unit/test_retrieval_query_scrub.py`; `tests/integration/test_evidence_store_isolation.py` (repeating attacker and judge doubles, confirmed on turn 3; the shipped indirect seed's frame never reaches the pool or a query) |
| FR-021, FR-027, FR-030, FR-068 | `tests/unit/test_settings_evidence.py` (the three settings and the start-up validation of the base URL; the listener and the per-run check themselves are part 2) |
| SC-010 | `tests/e2e/test_us013_detectors.py` (part 1's live scenario; part 2 adds its own) |

## Reviewed properties (SC-014) — for the implementation pull request's reviewer

SC-014 keeps two wording properties out of the tests on purpose: a test asserts their structure, never their
meaning, and the meaning is reviewed here by a person.

- **The override framing** — `src/kestrel/prompts/override_task.v1.md` must read as the injected override itself:
  an instruction that claims to supersede the agent's own operating instructions and, on that claimed authority,
  requires the joined token (FR-064). Asserted structurally: the file's `framing: override` front-matter field and
  at least one alphanumeric word between the two parts (`tests/unit/test_override_placement.py`,
  `tests/unit/test_override_detector.py`). Reviewed: that the wording realises that framing.
- **Each indirect seed's quoting frame** — the `frame_prefix`/`frame_suffix` of every `iin-*` entry in
  `src/kestrel/attacks/data/insertion_points.json` must be a neutral prefix and suffix that present the planted
  paragraph as a quoted excerpt of the document, email, OCR text or ticket that seed names, carrying no attack
  wording of its own (FR-064). Asserted structurally: the frame is present, the paragraph sits inside its quoted
  span, the joined form is absent from the framed message after normalisation, and the library seed is
  byte-identical (`tests/unit/test_override_placement.py`). Reviewed: that each frame is neutral and names the
  content its seed presents as retrieved. What the frame proves is that the agent followed an instruction
  presented as retrieved content inside the user turn; proof that an instruction travelled a real retrieval path
  is part 2's side channel.

## Justified outside tests — part 1

- 013/FR-046: replays stay excluded from the report exactly as today — the exclusion is feature 012's code path, unchanged here, and `tests/integration/test_replay_report_exclusion.py` (012) still proves it; the report's evidence additions are fed only runs that path already filtered.
- 013/FR-060: no new dependency — `pyproject.toml` is untouched by this feature; a process rule, as feature 012 justified its own.
- 013/FR-062: the part-1 / part-2 split and the documentation task are delivery process, satisfied by T040 (`docs/technical-design.md` section 8, the `CLAUDE.md` learned note) and the part-1 pull request itself.
- 013/SC-011: the required dependencies are unchanged — `pyproject.toml` is untouched; a process outcome, as 012's SC-011-style ids were justified.

## Justified outside tests — part 2 (implemented by the part-2 pull request)

Every id below belongs to the side channel, the honeypot tool, the callback listener, the protected-state check or
the HS-code target's cooperating side (tasks T041–T068), none of which part 1 ships. Each is "part 2 — implemented
by the part-2 pull request", which replaces these lines with its tests.

- 013/FR-019: part 2 — implemented by the part-2 pull request (the side-channel configuration).
- 013/FR-020: part 2 — implemented by the part-2 pull request (the side-channel URL validation and address guard).
- 013/FR-022: part 2 — implemented by the part-2 pull request (the correlation header).
- 013/FR-023: part 2 — the side-channel contract is a documentation requirement, satisfied by `contracts/side-channel.md`; its implementation is the part-2 pull request's.
- 013/FR-024: part 2 — implemented by the part-2 pull request (the tool-call log, de-duplicated by `seq`).
- 013/FR-025: part 2 — implemented by the part-2 pull request (the honeypot check).
- 013/FR-026: part 2 — implemented by the part-2 pull request (a canary in a decoded tool argument).
- 013/FR-028: part 2 — implemented by the part-2 pull request (the callback task and token).
- 013/FR-029: part 2 — implemented by the part-2 pull request (the listener route).
- 013/FR-031: part 2 — implemented by the part-2 pull request (the callback URL redaction at every model boundary).
- 013/FR-032: part 2 — implemented by the part-2 pull request (the protected-state snapshots).
- 013/FR-033: part 2 — implemented by the part-2 pull request (state values never stored, shown or logged).
- 013/FR-041: part 2 — implemented by the part-2 pull request (the side-channel form section).
- 013/FR-049: part 2 — implemented by the part-2 pull request (side-channel and callback traffic confinement; the model-input half is kept by part 1's redaction test).
- 013/FR-052: part 2 — implemented by the part-2 pull request (the HS-code target's tool-call recording and endpoints).
- 013/FR-053: part 2 — implemented by the part-2 pull request (the honeypot tool).
- 013/FR-054: part 2 — implemented by the part-2 pull request (the bounded outbound-request tool).
- 013/FR-055: part 2 — implemented by the part-2 pull request (the protected store and its tool).
- 013/FR-056: part 2 — implemented by the part-2 pull request (the target's offline tests and the part-2 e2e).
- 013/FR-058: the constitution amendment is the last pull request's edit (T064), never the spec-only or the part-1 one; satisfied by that diff, not by a test.
- 013/FR-066: part 2 — implemented by the part-2 pull request (the outbound tool's allow-list; its tests live under `targets/hs_code/tests`, outside the gate's scan, and are cited by the part-2 e2e).
- 013/FR-067: part 2 — implemented by the part-2 pull request (the tools' environment flag; tested beside FR-066).
- 013/FR-069: part 2 — implemented by the part-2 pull request (a replay whose URL the listener can no longer receive).
- 013/FR-070: part 2 — implemented by the part-2 pull request (the placeholder substitution on send).
- 013/FR-071: part 2 — implemented by the part-2 pull request (the side-channel header value in the mask list).
- 013/FR-072: part 2 — implemented by the part-2 pull request (the per-run callback hit cap).
- 013/FR-073: part 2 — implemented by the part-2 pull request (the route mounted only with a base URL; part 1 reports it unmounted, `tests/integration/test_evidence_api_ui.py`).
- 013/SC-005: part 2 — implemented by the part-2 pull request (the side-channel checks' outcomes).
- 013/SC-006: part 2 — implemented by the part-2 pull request (the callback hit outcomes and the models' inputs).
- 013/SC-015: part 2 — implemented by the part-2 pull request (the outbound tool's confinement and the usable-base rule).
- 013/SC-016: part 2 — implemented by the part-2 pull request (the hit cap and the unmounted route).
