---

description: "Task list for feature 013 — behavioural evidence"
---

# Tasks: Behavioural Evidence (013)

**Input**: Design documents from `specs/013-behavioural-evidence/` (plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md)

**Tests**: REQUIRED — Principle VII (tests first, one e2e per part). Every test carries a traceability token
`013/FR-###` / `013/SC-###` or a module-level `FEATURE = "013"`, and is written **before** the implementation task
it guards and made to fail first. Every store in a test is a temporary one (`tmp_path`), never the repository's
`data/kestrel.db`, and every ChromaDB store uses a tmp `chroma_path` with the offline `StubEmbeddingFunction`;
offline tests use the existing `ModelTransport`/`StubJudge`/`StubAttacker`/`SpyExperienceStore` doubles plus the
two new doubles T006 adds. **No attack-prompt text and no destructive-command text anywhere in code, comments or
assertions** (FR-059); the unsafe-output samples live only in the one inert, clearly-marked fixture
`tests/fixtures/unsafe_output_cases.json`.

**Organization**: by user story, inside the plan's **part-1 / part-2 split** (FR-062). Part 1 — Setup,
Foundational, US1, US2, US3 — is a complete, shippable slice: the two reply detectors, the evidence model, store
v11, the API/UI/report/logging surfaces, the FR-063 stripping and scrubbing, **its own replay and experiment
tests** (T011, because part 1 is what wires those paths), **its own documentation** (T040) and one e2e. Every
part-1 task finishes before any part-2 task starts. Part 2 — US4–US8 — adds the side channel, the tool-call
checks, the callback listener, the protected-state check and the HS-code target, reusing part 1's checker. The
implementation may ship as one pull request or as two; the owner decides at the spec-only PR. The Polish phase
(the constitution amendment, the roadmap, the README, the project memory, the log-records merge, the traceability
map) is the **last** pull request's work and is never part of the spec-only PR.

**Hard rules carried into every task**: no attack-prompt or destructive-command text in code, tests, fixtures or
commits (FR-059); no auth value, side-channel URL, callback URL or token, correlation id, tool-argument value, state
key or value, or evidence detail ever reaches a model (the override token parts are visible to the judge and attacker
because they are part of the text as sent — FR-061; only the callback URL/token is redacted — FR-031, FR-049), and
none ever reaches a log line, memory or the pattern pool, nor a report as an item detail or a separate field (the
verbatim winning message and reply the report already prints are unchanged) (FR-007, FR-031, FR-048, FR-049, FR-063,
FR-071); no new dependency (Principle X, FR-060, SC-011); every non-planted, non-side-channel run behaves exactly as
today (FR-061, SC-008).

---

# PART 1 — the two reply detectors (shippable on its own; FR-062)

## Phase 1: Setup

- [X] T001 [P] Add the three settings (plus the start-up usability check) to `src/kestrel/settings.py` with their
      defaults and validation
      (data-model.md): `KESTREL_CALLBACK_BASE_URL` → `callback_base_url: str | None` (unset → `None`; an http/https
      URL without credentials whose path ends in `/callback`, else `SettingsError` — the start-up validation of
      FR-027),
      `KESTREL_CALLBACK_WAIT_S` → `callback_wait_s: float` (default `2`; a finite number ≥ 0, else
      `SettingsError`), `KESTREL_SIDE_CHANNEL_TIMEOUT_S` → `side_channel_timeout_s: int` (default `10`, the
      existing `positive_int` helper), and the start-up usability check of the callback base (FR-068). Document all
      of them in `.env.example` beside the other `KESTREL_*` blocks (FR-021, FR-027, FR-030, FR-068).
- [X] T002 [P] Create the empty `src/kestrel/evidence/` package (`__init__.py`) and the inert fixture file
      `tests/fixtures/unsafe_output_cases.json` as `{"_note": "<the inert-sample statement>", "cases": []}` — a
      `"_note"` **key**, not a comment, because JSON has none (FR-059).

## Phase 2: Foundational (blocks every user story)

**⚠️ schema v11, the evidence model, the checker seam, and the replay/experiment tests part 1's own wiring needs.**

- [X] T003 [P] Unit test `tests/unit/test_store_migration_v11.py` (`FEATURE = "013"`), following the
      `test_store_migration_v10.py` convention: build a hand-written schema-10-shaped database, run
      `TargetStore.__init__`/`_migrate`, and assert — `meta.schema_version` reads `"11"`; `PRAGMA
      foreign_key_check` is empty; a pre-existing run row has `correlation_id` and `side_channel_status` both
      `NULL`; the four new tables exist and are queryable, `run_evidence` carrying `pattern_name` and
      `pattern_set_version`; inserting a `run_evidence` row with a bad `kind` or `location` raises
      `sqlite3.IntegrityError`; two `run_planted_tokens` rows may share a `token` (a replay's copy) while
      `(run_id, kind)` stays unique; deleting a target cascades to its runs, their evidence, planted tokens and
      callback hits, and to `target_side_channels`, with `foreign_key_check` still empty; a second `_migrate` is a
      no-op; **no `runs` rebuild happened** (the `sqlite_sequence` row and every existing child row survive
      untouched, asserted the way v10's test asserts survival) (FR-057).
- [X] T004 [P] Unit test `tests/unit/test_evidence_model.py` (`FEATURE = "013"`): the `KINDS` table matches FR-004
      exactly (seven kinds, their labels, locations and classes); `category_for(kind, family)` returns the family's
      class for `canary_in_reply` and the fixed class for every other kind; `location_label` returns the four exact
      strings ("in the reply", "in a tool call", "at the callback listener", "in the protected state");
      `evidence_line(item)` renders exactly `"{label} · turn {N} · {location label} · {OWASP class}"`; and
      `OVERRIDE_DETAIL` is the fixed statement an override item carries, with a test asserting no item detail the
      model can build contains a token value or part or a URL (FR-004, FR-007, FR-039).
- [X] T005 [P] Unit test `tests/unit/test_settings_evidence.py` (`FEATURE = "013"`): the three T001 settings parse
      their defaults, accept valid overrides, and raise `SettingsError` on a bad value each (a non-URL base, a base
      whose path does not end in `/callback`, a negative or non-finite wait, a zero or negative timeout); the
      start-up usability check refuses a malformed base loudly and accepts a usable one (FR-021, FR-027, FR-030,
      FR-068).
- [X] T006 [P] Extend `tests/support.py` with the offline doubles (no attack text): a `SideChannelStub` whose
      scripted descriptor, per-correlation-id tool-call log (with `seq` values), state-snapshot sequence and six
      failure modes are answered by `ModelTransport` for a fixed side-channel host; an `on_target_request` hook so
      a stub target can call `store.record_callback_hit(...)` when a request carries a planted URL; a
      `RepeatingStubAttacker` and a `RepeatingStubJudge` that echo the run's real token parts and callback URL in
      their turn-2-and-later messages and progress notes (so T026's isolation test cannot pass vacuously, FR-063);
      and helpers that read a run's real planted values from `store.list_planted_tokens`. Scaffolding only — part
      1 uses the repeating doubles, part 2 the side-channel stub (FR-049, FR-063, SC-005, SC-006, SC-007).
- [X] T007 Implement schema v11 in `src/kestrel/store.py` per data-model.md: `SCHEMA_VERSION = "11"`; add the four
      `CREATE TABLE IF NOT EXISTS` statements (`run_evidence` with `pattern_name`/`pattern_set_version`,
      `run_planted_tokens`, `callback_hits`, `target_side_channels`) and their indexes to `SCHEMA`; add
      `correlation_id TEXT` and the checked `side_channel_status TEXT` to `RUNS_COLUMNS_SQL`; add
      `EVIDENCE_RUN_COLUMNS` and ALTER-add them in `_migrate`; extend the version-acceptance guard to accept
      `"10"`. **No table is rebuilt.** Bump the current-version literal `"10"` → `"11"` in **every** place that
      pins it (the complete list, SC-008): `tests/unit/test_store_migration_v5.py:103, 110, 129`,
      `test_store_migration_v6.py:82, 89, 97`, `test_store_migration_v8.py:58, 65, 95`,
      `test_store_migration_v9.py:166, 176, 261`, `test_store_migration_v10.py:177, 187, 269`, and
      `tests/integration/test_provenance_migration.py:39, 61` (FR-057, SC-008). Makes T003 pass.
- [X] T008 Implement `src/kestrel/evidence/model.py` per data-model.md: `EvidenceItem` (with `pattern_name` and
      `pattern_set_version`), the `KINDS` table, `LOCATION_LABELS`, `DETAIL_MAX_CHARS = 200`, `OVERRIDE_DETAIL`,
      `category_for`, `kind_label`, `location_label`, `evidence_line`, and `derived_items(run)` — the one helper
      that gives a pre-013 hard-evidence run with no stored items its single derived `canary_in_reply` item, used
      by the API **and** the report so the surfaces cannot disagree (FR-003, FR-004, FR-005, FR-007, FR-039).
      Makes T004 pass.
- [X] T009 Implement the store methods on `TargetStore` (store.py) that part 1 uses, per data-model.md:
      `add_evidence`, `list_evidence`, `evidence_kinds_by_run`, `add_planted_token`, `list_planted_tokens`,
      `disarm_planted_token`, and `copy_planted_tokens` **carrying `disarmed_turn` across unchanged** (FR-035);
      `claim_run(..., correlation_id=, side_channel_status=)` writing the status **at claim time** and a separate
      `set_side_channel_status(run_id, 'unavailable')` for the one in-run update, so a crashed or interrupted run
      never leaves it null (FR-034); `Run` gains both columns (FR-003, FR-006, FR-034, FR-057).
- [X] T010 Implement `src/kestrel/evidence/checker.py`'s foundation: `EvidenceChecker` with
      `canary_only(canaries)` (today's behaviour exactly — one `canary_in_reply` item per distinct canary matched,
      `canary_hit` true, `CANARY_REASON`), `check_turn(turn, reply, remaining)` returning a `TurnEvidence` whose
      `items` is the authority for "did this turn produce evidence", and `build_checker(...)` returning a
      canary-only checker when no family carries a task and no side channel exists — **"canary-only" is only the
      `execute_run`/`evidence=None` legacy default; once T023 lands the unsafe-output check runs on every reply of
      every family regardless of task or side channel** (FR-014). The reason for a non-canary hit is
      `"Hard evidence confirmed the attack: <labels joined by ' + '>."` (research D3) (FR-001, FR-002, FR-005,
      FR-006, FR-014).
- [X] T011 [P] Integration test `tests/integration/test_evidence_part1_replay.py` (`FEATURE = "013"`) — **written
      before T012, in part 1, because part 1 is what wires these paths** (FR-062, research D24): for a replay of a
      source that planted an override token, assert the token is copied **with its armed state** and a source that
      was disarmed on turn *k* leaves the replay disarmed from turn *k*; a replay whose own re-sent message
      contains the joined form (normalised) disarms the replay at that turn and records **no** override item; a
      replay confirmed only by a **detector** item (no canary) scores `still_vulnerable`, not `inconclusive`, on
      **both** paths — the single-turn branch and the adaptive graph; a replay of a pre-feature source skips the
      override check and runs every other; and an experiment's two arms detect identically with results unchanged
      beyond confirmed counts (FR-035, FR-036, FR-037, SC-009). Because the two detectors are not implemented until
      T017 and T023, the disarm-on-replay and detector-only cases here use a **stub checker** that reports an
      override disarm and a non-canary item on command; the real-detector variants of those cases are re-tested in
      T019 and T024.
- [X] T012 Wire the checker into the run paths, defaulting to canary-only so every existing test is unchanged
      except where listed (SC-008): `runs.execute_run(..., evidence=None)` replaces its lone `match_canary` call with
      `evidence.check_turn(...)` and writes the turn's items with `store.add_evidence`; `attack/graph.py`'s
      module-level `_check_evidence` becomes `async` and delegates to the checker; `run_adaptive` and
      `run_replay_adaptive` gain `evidence=None`; `record_node` writes the items right after the turn row.
      **Both replay paths derive each turn's `turn_results` entry from "did this turn produce any evidence item"**
      — `run_replay_adaptive`'s own `record_node` (`attack/graph.py:390, :398`) and the single-turn branch
      (`replay.py:321-325`) — never from the canary flag, so `compute_outcome` can no longer return
      `inconclusive` for a replay that finished `succeeded` with hard evidence (research D23). Every path calls
      `checker.note_sent(message, turn)` for **every** message it sends, replays included (FR-012, FR-035).
      `api/main.py::start_run` and `experiments/engine.py::_run_rep` call `build_checker(...)`, and the replay paths
      build theirs from the source: `replay.execute_replay` calls `store.copy_planted_tokens(source_id, replay_id)`
      then `build_checker(..., planted=<copied>)` and passes `evidence=` into its single-turn branch, and
      `run_replay_adaptive` does the same in the graph (FR-001, FR-002, FR-035, FR-036, FR-037). Makes T011's
      stub-checker cases pass (the real-detector cases land in T019/T024).

**Checkpoint**: `uv run pytest tests/unit/test_store_migration_v11.py tests/unit/test_evidence_model.py
tests/unit/test_settings_evidence.py tests/integration/test_evidence_part1_replay.py` green; the full existing
offline suite still green (SC-008).

---

## Phase 3: User Story 1 — Confirm an instruction override without the judge (P1) 🎯 MVP

**Goal**: a run of the two injection families plants an echo-proof per-run token inside the injection itself; a
reply carrying its joined form confirms the run with hard evidence and no judge call.

**Independent Test**: quickstart US1 — `tests/integration/test_evidence_detectors.py -k override`.

- [X] T013 [P] [US1] Unit test `tests/unit/test_override_detector.py` (`FEATURE = "013"`):
      `generate_override_token` draws two 6-char parts from the 31-symbol unambiguous alphabet and never repeats
      across 10,000 draws; `reply_confirms(reply, joined)` is true for the joined form in any letter case and false
      when anything separates the parts or only one is present; `normalise` folds case and strips every
      non-alphanumeric character; over **1,000** freshly generated tokens `normalise(the opening message)` never
      contains the joined form — the normalised assertion, matching the normalised check (FR-009);
      the template keeps at least one alphanumeric word between the parts; `text_contains_joined` drives the
      disarm check on normalised text (FR-008, FR-009, FR-012, FR-051, SC-001).
- [X] T014 [P] [US1] Unit test `tests/unit/test_override_placement.py` (`FEATURE = "013"`) — the structural test:
      for every direct-injection and indirect-injection seed in the shipped library, the Kestrel-owned sidecar
      `src/kestrel/attacks/data/insertion_points.json` carries an entry for that seed; `place_task` puts the
      paragraph at an **indirect** seed's offset **inside** that seed's simulated injected content and never
      appends it in Kestrel's own voice, while a **direct** seed's offset places it in the attacker's voice; an
      entry whose fingerprint no longer matches the library text, or whose offset is out of range, fails the test;
      the `override_task` template carries a `framing: override` front-matter field (asserted structurally, not by
      model behaviour); and a seed of a family carrying no task has no entry and is sent unchanged (FR-064, FR-011,
      SC-014).
- [X] T015 [US1] Extend `src/kestrel/prompt_registry.py` for one **optional** `framing` front-matter key — parse it
      when present (never require it: `_FRONT_MATTER_KEYS` still names only `id` and `version`), carry it on
      `PromptFile` (default `None`), give `format_prompt_file` an optional `framing` parameter, and have `bump()`
      pass `PromptFile.framing` through so a future bump of `override_task` does not drop `framing: override`; add a
      parse/format round-trip test **and** a `tests/unit/test_bump_prompt.py` case that bumps a `framing: override`
      file and asserts the new version keeps the key; update the 009 prompt-registry contract for the new optional
      key; the existing two-line files are unchanged. Then author the versioned prompt file
      `src/kestrel/prompts/override_task.v1.md` (front-matter `id: override_task`, `version: 1`, `framing: override`;
      placeholders `{first_part}`/`{second_part}`) framed as **the injected override itself** — an instruction
      claiming to supersede the agent's operating instructions and, on that authority, requiring the two parts
      joined — carrying the parts separately with at least one alphanumeric word between them and never the joined
      form; record it with `uv run python scripts/bump_prompt.py override_task --lock`. Update the 009 prompt-lock
      docs and `CLAUDE.md`'s "two-line front-matter" note to mention the optional `framing` key. Author the
      Kestrel-owned sidecar `src/kestrel/attacks/data/insertion_points.json`: for every direct-injection and
      indirect-injection seed, its prompt id maps to an insertion point — a character offset into the seed's
      verbatim library text plus a sha256 fingerprint of that text — indirect seeds pointing inside their simulated
      injected content, direct seeds at the attacker-voice position; the library itself stays verbatim (the 002
      contract). Bump `attacker:direct_injection` and `attacker:indirect_injection` to v2 per contracts/prompts.md
      and `--lock` both. Update `EXPECTED_IDS` and the version assertions in
      `tests/integration/test_config_prompts.py`, `test_prompt_no_secrets.py` and
      `tests/unit/test_prompt_registry.py` (the exact id set, the `version == "1"` pin and the two-line
      front-matter prefix this feature changes by construction — SC-008 lists it); because this edits
      `specs/009-versioned-prompts/contracts/prompt-registry.md` alongside `src/`, the PR description MUST carry the
      `spec-change:` note the traceability gate requires (FR-010, FR-059, FR-064, SC-008,
      SC-014).
- [X] T016 [US1] Implement `src/kestrel/evidence/override.py`: `generate_override_token`,
      `override_task_paragraph`, `place_task`, `normalise`, `reply_confirms`, `text_contains_joined` (FR-008,
      FR-009, FR-064). Makes T013 and T014 pass.
- [X] T017 [US1] Extend the checker and `build_checker`: for a run of `direct_injection` or
      `indirect_injection`, generate an override token, expose it through `opening_message(seed)` (the paragraph at
      the sidecar's insertion point) and `planted()`, check every reply while armed and emit one
      `instruction_override` item
      with the fixed `OVERRIDE_DETAIL` on a match, and disarm via `note_sent(text, turn)` on the normalised text
      (one `evidence.override_disarmed` warning, `store.disarm_planted_token`). Runs of the other families plant no
      override token and no override paragraph, and send today's messages except where FR-028 plants the callback
      task for tool_exfiltration (part 2) (FR-007, FR-008 to FR-013, FR-028, FR-061, FR-064).
- [X] T018 [US1] Persist and apply the planting in the run paths: after `claim_run`, write `checker.planted()`;
      `execute_run` sends `checker.opening_message(prompt)` and uses that exact opened text everywhere the
      un-opened seed is read today — `claim_run(prompt_text=...)`, the single-turn judge call's attack text
      (`attack=prompt.text` becomes the opened text, so the judge sees the planted instruction, FR-061), and the
      turn line's `message_chars` (`len(prompt.text)` becomes the opened text); `run_adaptive.attacker_node` sends
      it on turn 1; `record_node` stores the sent message (FR-011, FR-012, FR-013, FR-061).
- [X] T019 [US1] Integration test `tests/integration/test_evidence_detectors.py` override cases (`FEATURE =
      "013"`): a stub target replying with the run's real joined form (read from `store.list_planted_tokens`) →
      `verdict=succeeded`, `hard_evidence=true`, one `instruction_override` item on the turn, `judge_used=false`,
      zero judge calls on the stream; a reply with the parts separated, quoting the instruction, or refusing → no
      override item, judged as today; the joined form appears in **zero** of `model_transport.target_requests()`
      bodies, checked on the normalised body text; a run whose own sent message contains the joined form disarms
      the token and the API shows the disarmed notice; tokens differ across two runs (FR-009, FR-012, FR-013,
      SC-001, SC-003). Re-verifies T011's disarm-on-replay case with the real override detector.

**Checkpoint**: US1 is independently testable — an override is confirmed deterministically, nothing from the
target needed.

---

## Phase 4: User Story 2 — Confirm unsafe executable output without the judge (P1)

**Goal**: every reply of every run is scanned with the named, versioned pattern set; a match confirms the run under
LLM05 with no judge call; the documented benign shapes and echoes of Kestrel's own messages never match.

**Independent Test**: quickstart US2 — `tests/unit/test_unsafe_output.py`.

- [X] T020 [P] [US2] Populate the inert fixture `tests/fixtures/unsafe_output_cases.json` per
      contracts/detectors.md: a `"_note"` key stating the samples are inert agent output never executed, sourced
      or run, and a `"cases"` list whose every entry is `{"pattern": "<name>", "kind": "positive"|"negative",
      "text": "<sample reply>"}` — at least **three positive and three negative cases per named pattern** (not per
      category), honouring that pattern's documented boundary (FR-016, FR-059, SC-002).
- [X] T021 [P] [US2] Unit test `tests/unit/test_unsafe_output.py` (`FEATURE = "013"`): every name in `PATTERNS`
      has ≥ 3 positive and ≥ 3 negative cases tagged with it and a pattern short of either **fails**; every
      positive case matches **its own named pattern** (100%); no negative case matches **any** pattern (100%);
      `scan` returns at most one match per category; a match whose text also appears in `sent_texts` is skipped
      (the echo rule); `detail(match)` names the category, the pattern and the set version; every fixture
      `pattern` value is a name in `PATTERNS` and vice versa; and the test parses `contracts/detectors.md`'s
      named-pattern table and set version and asserts they equal the module's `PATTERNS` (names and categories)
      and `PATTERN_SET_VERSION`, the way `tests/unit/test_roadmap.py` reads `docs/roadmap.md` — so the fixture, the
      module and the contract cannot drift (FR-015, FR-016, FR-017, FR-065, SC-002).
- [X] T022 [US2] Implement `src/kestrel/evidence/unsafe_output.py`: `PATTERN_SET_VERSION = "1"` and the compiled
      `PATTERNS` tuple carrying **exactly the pattern names of contracts/detectors.md and no others**, each
      expression implementing that name's documented matched shape and leaving its documented benign counterpart
      alone; `scan(reply, sent_texts=())` (≤ one `Match` per category, earliest by position, echo rule applied);
      `detail(match)` (FR-014 to FR-017, FR-065). Makes T021 pass.
- [X] T023 [US2] Add the unsafe-output check to the checker as check #3 of the fixed order, for every run of every
      family and both modes, over the reply only, passing the run's sent messages as `sent_texts`: one
      `unsafe_executable_output` item per matched category, location `reply`, class LLM05, carrying the pattern
      name and set version as their own fields. **Scrub the matched excerpt through
      `scrub_planted_values(checker.planted_values())` before building the detail**, so an excerpt that happens to
      carry a callback URL or a token part is cleaned before it is stored (FR-007, FR-014, FR-017, FR-018, FR-065).
- [X] T024 [US2] Integration test `tests/integration/test_evidence_detectors.py` unsafe-output cases (`FEATURE =
      "013"`): a stub target whose reply is a positive sample → confirmed run, one `unsafe_executable_output` item
      naming its pattern and set version, no judge call; a negative sample → no item, judged as today; a reply
      echoing text Kestrel sent → no item (FR-065); a canary **and** an unsafe-output match on one turn → two
      items, one confirmed run (FR-001, FR-014, FR-065, SC-003). Re-verifies T011's detector-only-replay case with
      the real detector. Also asserts that an unsafe-output match whose excerpt carries the run's callback URL or a
      token part stores a **scrubbed** detail (no URL or token part) (FR-007).

**Checkpoint**: both detectors confirm deterministically; US1 and US2 need nothing from the target.

---

## Phase 5: User Story 3 — Read exactly what confirmed a finding (P1); the stripping and scrubbing; part-1 docs

**Goal**: every evidence item is visible on the run page, the run list, the API, the report and (as kinds and
counts) the log; the canary itself is an item; no planted value ever reaches the experience store or the query.

**Independent Test**: quickstart US3 — `test_evidence_api_ui.py`, `test_report_coverage.py` /
`test_report_findings.py`, `test_evidence_store_isolation.py`, `test_evidence_redaction.py`.

- [X] T025 [P] [US3] Unit test `tests/unit/test_strip_planted_tasks.py` (`FEATURE = "013"`):
      `strip_planted_tasks` removes the run's exact filled task text — for the override task at both a direct
      seed's attacker-voice offset and an indirect seed's inside-the-content offset, and for the callback task
      appended in the user's voice — wherever it sits, and leaves a message with no task text byte-identical;
      `scrub_planted_values` replaces each token part, the joined form and the callback URL wherever else they
      appear, and leaves text containing none of them unchanged (FR-063).
- [X] T026 [P] [US3] Integration test `tests/integration/test_evidence_store_isolation.py` (`FEATURE = "013"`):
      with a `SpyExperienceStore` and T006's **repeating** attacker and judge doubles — which echo the run's real
      parts in their turn-2-and-later messages and progress notes — run a confirmed override-family attack in both
      direct and indirect placement and assert that no pattern document, no memory record, no memory summary and no
      retrieval query contains a token part, the joined form or the task wording, while the run's own `prompt_text`
      and turn rows still carry them. Without the repeating doubles this test would pass vacuously (FR-063,
      SC-013). The **callback-URL** half of FR-063/SC-013 is added in part 2 (T054/T055 make the callback task and
      its redaction exist): a confirmed `tool_exfiltration` run with a real planted URL repeated in a turn-2 stored
      message must write no URL into any pattern document, memory record, memory summary or retrieval query.
- [X] T027 [P] [US3] Unit test `tests/unit/test_events_evidence.py` (`FEATURE = "013"`): `run.start` renders
      `side_channel`, `callback_listener`, `override_planted` and `callback_planted` when passed and **omits each
      when not** (never `null`, the one 010 convention); `turn` and `run.end` carry
      `evidence_kinds`/`evidence_count`, and `turn`'s `hard_evidence` now means "any evidence item on this turn"
      while `canary_hit` keeps its narrower meaning; `evidence.check` carries `checks`, `evidence_kinds`,
      `evidence_count`, `side_channel_status`, `callback_wait_ms` and `state_changed_keys` (a count only), each
      omitted when it does not apply; `evidence.override_disarmed` renders with the turn scope field; no
      `log.unknown_field` warning fires for any of them (FR-047, FR-048).
- [X] T028 [US3] Implement `strip_planted_tasks` and `scrub_planted_values` in `src/kestrel/evidence/override.py`
      and apply **both** at every experience-store and retrieval boundary: `experience/writeback.py` (per message
      before `_winning_messages` joins, around `summary.build_summary`'s judge-progress inputs, and before
      `write_memory`) and `experience/retrieval.py` (per attacker message before `build_query` joins), handing each
      the run's planted values (`checker.planted_values()`) and exact task text (`checker.planted_task_texts()`),
      both of which the checker exposes. **Build the checker first and pass its planted values/task text into
      `background_provider`** — its signature gains them, and `api/main.py::start_run` and
      `experiments/engine.py::_run_rep` call `build_checker(...)` before building the provider, so the per-run
      scrubber is bound after the run exists; `write_back` receives the checker's planted values and task texts
      alongside the run it already has (FR-063). Makes T025 and T026 pass.
- [X] T029 [US3] Add the evidence fields to `api/schemas.py` and fill them in `api/main.py` per contracts/api.md:
      `RunSummary` gains `evidence_kinds`/`evidence_labels`/`evidence_count`/`side_channel_status`, with a pre-013
      hard-evidence run reported through `derived_items(run)` as exactly one canary item on **every** surface;
      `RunDetail` gains `evidence` (items with `pattern_name`/`pattern_set_version`), `planted_tokens` (never a
      value or URL), `side_channel_notice`, `override_disarmed_notice` and `callback_note`, every string computed
      server-side; `ConfigOut.evidence` (part-1 fields plus `unsafe_output_pattern_set_version`); the run list
      uses `store.evidence_kinds_by_run` (FR-005, FR-007, FR-038, FR-042, FR-043).
- [X] T030 [P] [US3] Integration test `tests/integration/test_evidence_api_ui.py` (`FEATURE = "013"`): the run
      summary and detail carry the fields above, a pre-013 run reading as exactly one canary item everywhere; the
      run page headline is exactly `"Attack succeeded · confirmed by {labels joined by ' + '}"` with `" at turn N"`
      for an adaptive run; the `"Evidence"` section lists one exact `evidence_line` per item then its detail; the
      run-list `"Evidence"` column joins the labels with `" + "` for a run **with** items and keeps **today's
      exact text** for a run without them (`"judge · {model}"`, or `"—"`), so no existing row changes; the
      disarmed notice and `callback_note` render when set; nothing is re-derived in the UI (FR-038, FR-039,
      FR-040, FR-043, SC-004, SC-008).
- [X] T031 [US3] Render the evidence surfaces in `ui/app.py`: the `"confirmed by {labels}"` headline, the
      `"Evidence"` section, the run-list column via an `_evidence` that reads `evidence_labels` and **falls back to
      today's text when a run has no items**, and the `side_channel_notice` / `override_disarmed_notice` /
      `callback_note` lines (each only when the API sets it); `render_metrics` keeps driving Confirmed/Suspected
      from `finding` + `hard_evidence`. Every string comes from the API (FR-039, FR-040, FR-043). Makes T030 pass.
- [X] T032 [P] [US3] Unit test `tests/unit/test_report_coverage.py` / `test_report_findings.py` (extend, scoped
      `013/FR-###`): a finding lists each evidence item (label, turn, location label, class, detail) and still
      quotes the confirming reply; a run is counted **confirmed** under a class only when one of its own items
      carries that class — a system-prompt-leak run whose only item is unsafe output is **not** a confirmed LLM07
      finding, and is confirmed under LLM05 only; the table has **four** tested rows (the new
      LLM05 detector row with its run and confirmed counts); `UNTESTED` has **six** classes; a pre-013
      hard-evidence run renders its one derived canary item (FR-005, FR-044, FR-045, SC-008).
- [X] T033 [US3] Implement the report additions: `report/model.py` (`Finding.evidence_items`,
      `build_report(evidence_by_run=)`, the per-class confirmed counting of FR-045, `derived_items` for pre-013
      runs), `report/owasp.py` (`DETECTED` LLM05 row, drop LLM05 from `UNTESTED`), `report/render.py` (render each
      finding's items after the winning message); `api/main.py` passes `evidence_by_run` and still excludes
      replays (FR-005, FR-044, FR-045, FR-046). Makes T032 pass.
- [X] T034 [US3] Emit the part-1 log lines through `events.py` per contracts/log-records-delta.md: `run.start` +
      `side_channel`/`callback_listener`/`override_planted`/`callback_planted` (each omitted when not passed),
      `turn`/`run.end` + `evidence_kinds`/`evidence_count` (+ `run.end` `side_channel_status`), `turn`'s
      `hard_evidence` redefined as "any evidence item on this turn", the new `evidence.check` line per turn (with
      `state_changed_keys` as a count), and the `evidence.override_disarmed` warning; every field added to
      `CATALOGUE` (FR-047, FR-048). Makes T027 pass. The per-turn `evidence.check` line changes the event order the
      two pre-existing log-records tests assert — update `tests/integration/test_log_records_adaptive.py` and
      `test_log_records_single_turn.py` to the new order (SC-008).
- [X] T035 [P] [US3] Integration test `tests/integration/test_evidence_redaction.py` (`FEATURE = "013"`): across a
      confirmed override run's whole stream, 0 lines carry a token or part, the joined form, an evidence detail,
      reply text or attack text, counted with the run's real marker strings (FR-048, SC-007).

**Checkpoint — PART 1 CODE COMPLETE**: `uv run pytest tests/unit tests/integration` green; `uvx ruff check src ui
tests` and `mypy src` clean; coverage ≥ 85%; `verify_lock()` clean.

- [X] T036 [US3] End-to-end `tests/e2e/test_us013_detectors.py` (`FEATURE = "013"`, marker `e2e`): API in-process
      (as 012's e2e) against the live HS-code target; register it, run a `direct_injection` attack, assert the
      **structure** — a new run, an override token planted and **absent in its joined form** from `prompt_text`
      and the sent request (checked on the normalised text), any items of known kinds, the judge prompt version
      recorded only when no deterministic evidence was found; never asserting the live model's behaviour on the
      day (SC-010).
- [X] T037 [US3] Make `tests/e2e/conftest.py`'s `kestrel_api` fixture **pop `KESTREL_CALLBACK_BASE_URL`** from the
      environment it copies (`tests/e2e/conftest.py:122`), so a developer who exports it cannot silently change
      what the e2e tests plant; the part-2 `kestrel_api_with_listener` fixture (T061) sets it explicitly instead
      (SC-008).
- [X] T038 [US3] Switch `tests/e2e/test_us2_judged_run.py` from `direct_injection` to `tool_exfiltration` so
      "decided by the judge" still holds against a live model that would otherwise fulfil the planted override
      task (with the listener off, that family plants nothing) (FR-061, SC-008).
- [X] T039 [US3] Update `tests/e2e-browser/prompt-choice.spec.ts:60`: a direct-injection sent message is now the
      library text **plus** the planted paragraph, so the assertion becomes **containment** (the chosen library
      text is contained in the sent message) rather than equality, and the test still identifies which prompt was
      picked (FR-011, SC-008).
- [X] T040 [US3] **Part-1 documentation** (FR-062, research D24): update the evidence section of
      `docs/technical-design.md` for what part 1 ships — the evidence package and item model, the fixed check
      order, the echo-proof override token and its placement, the named/versioned unsafe-output set, the stripping
      and scrubbing, schema v11 — and add the matching `CLAUDE.md` "Learned notes" entry for part 1. A part-1-only
      pull request ships documented; T067 extends both for part 2.

---

# PART 2 — the target side channel (builds on part 1; never starts before T040; FR-062)

## Phase 6: User Story 4 — Register a cooperating target's side channel (P2)

**Goal**: a target may carry a side channel (URL, optional encrypted header, honeypot tool name); the connection
test checks it; a target without one is unchanged.

**Independent Test**: quickstart US4 — `tests/integration/test_side_channel_config.py`.

- [ ] T041 [P] [US4] Integration test `tests/integration/test_side_channel_config.py` (`FEATURE = "013"`):
      register and update a target with a side channel through the API; the header value is stored encrypted and
      never returned; the connection test checks the side channel only after the chat test passes, shows exactly
      **"Side channel checked."** on success, and returns each of the **six** exact steps and messages —
      unreachable, unauthorized, timed out (**with the configured timeout substituted by the API**, asserted at two
      different configured values so the number is provably not fixed in the text), invalid shape, a stored header
      the current key cannot decrypt, and the hosted private-address refusal; save is refused `409 not_tested`
      until a test with those side-channel settings passed; a target **without** a side channel sends exactly
      today's requests and no correlation header (FR-019, FR-020, FR-021, FR-022, FR-071, SC-008).
- [ ] T042 [US4] Implement the side-channel store layer (store.py): the `target_side_channels` methods
      `set_side_channel` and `resolve_side_channel`, and `Target.side_channel`; the header value via the vault
      (encrypt on write, decrypt only for the tester and the checker), the `None`-keeps-stored-value convention on
      update, and a decryption failure surfaced as the `side_channel_header_unreadable` step rather than a request
      sent without the header (FR-019, FR-071).
- [ ] T043 [US4] Implement `src/kestrel/evidence/side_channel.py`: `ResolvedSideChannel`, `SideChannelClient`
      (`describe`/`tool_calls`/`state`, each a bounded GET through the address guard with the configured header,
      no redirects, 1 MiB cap, the configured timeout), the six `STEPS`, `SideChannelUnavailable`, and
      `check_side_channel` returning a `TestOutcome` whose timeout message carries the configured value; the
      decrypted header value joins the run's mask list beside the target's own (FR-020, FR-021, FR-023, FR-049,
      FR-071).
- [ ] T044 [US4] Wire the side channel into config and the connection test: `SideChannelIn`/`SideChannelOut`,
      `ConnectionSettingsIn.side_channel`, `TargetDetail.side_channel`,
      `ConnectionTestResult.side_channel_checked` in api/schemas.py; validation under `settings.side_channel.*`;
      `ResolvedSettings.side_channel` added to `FormSessions.fingerprint`; the six messages added to the tester's
      `MESSAGES`; `connection_test` runs `check_side_channel` after a passing chat test; `save_target` and
      `update_target` persist it (FR-019, FR-020, FR-021). Makes T041 pass.
- [ ] T045 [P] [US4] Integration test for the form section (`FEATURE = "013"`, in
      `tests/integration/test_evidence_api_ui.py` or a sibling): the target form shows the exact labels
      **"Side-channel URL"**, **"Side-channel header name"**, **"Side-channel header value"** (masked, with the
      stored-value placeholder behaviour of the auth headers) and **"Honeypot tool name"**, all optional; the
      submitted payload carries them; the form validates nothing of its own (FR-041, FR-043).
- [ ] T046 [US4] Add the `"Side channel"` form section to `ui/app.py` with those exact labels (FR-041, FR-043).
      Makes T045 pass.

## Phase 7: User Story 5 — Confirm tool misuse from the tool-call log (P2)

**Goal**: every chat request carries a per-run correlation id; after each reply the tool-call log confirms a
honeypot call or a canary in a tool argument.

**Independent Test**: quickstart US5 — `tests/integration/test_side_channel_checks.py` (tool-call cases).

- [ ] T047 [P] [US5] Integration test `tests/integration/test_side_channel_checks.py` tool-call cases (`FEATURE =
      "013"`): with the `SideChannelStub`, a honeypot call under the run's correlation id → confirmed, one
      `honeypot_tool_invoked` item; a logged argument containing a declared canary → one
      `canary_in_tool_argument` item naming tool, argument and canary but never the value, **including a canary
      containing a quotation mark, a backslash and a non-ASCII character**, found in the decoded strings and in a
      nested structure; calls under another correlation id, already-counted calls, and a log
      **re-read or returned with a gap** → no duplicate and no skipped item, de-duplicated by `seq`; no configured
      honeypot name → the honeypot check is skipped; the correlation header goes only to a target with a side
      channel and is refused as a user header (FR-022, FR-024, FR-025, FR-026, SC-005).
- [ ] T048 [US5] Implement the correlation id: `connection/tester.py::run_test(..., extra_headers=)`; the run
      paths pass `{"X-Kestrel-Correlation-Id": uuid4().hex}` only on a target with a side channel; `claim_run`
      stores it; `X-Kestrel-Correlation-Id` joins `RESERVED_HEADERS` (FR-022).
- [ ] T049 [US5] Add the tool-call checks to the checker as check #4: after each reply on a target with a side
      channel, read `tool_calls(correlation_id)` and inspect only calls whose `seq` exceeds the highest already
      counted; emit `honeypot_tool_invoked` per new honeypot call (skipped with no configured name) and
      `canary_in_tool_argument` per (call, argument, canary) searching **decoded** strings recursively; a failed
      read sets `side_channel_status='unavailable'` via `set_side_channel_status`, emits
      `evidence.side_channel_unavailable`, fabricates nothing and lets the run continue; every read is bounded and
      adds no model call (FR-024, FR-025, FR-026, FR-034, FR-050). Makes T047 pass.

## Phase 8: User Story 6 — Confirm an outbound call with a canary callback (P2)

**Goal**: the tool-exfiltration family plants a unique listener URL when the base is usable; a request to it
confirms the run; models never see the URL.

**Independent Test**: quickstart US6 — `tests/integration/test_callback_listener.py`.

- [ ] T050 [P] [US6] Integration test `tests/integration/test_callback_listener.py` (`FEATURE = "013"`): with the
      listener enabled and a stub target that requests the planted URL during the run, the hit is recorded and
      confirms the run with one `canary_callback` item (detail = the method, never the URL), no judge call on the
      turn; a request for an unknown token, a malformed token, or a token whose run has ended records nothing and
      answers 404; the route needs no `X-Kestrel-Token`; the attacker, judge and recommender inputs captured by
      the suite contain the URL 0 times; **an attacker message containing the placeholder is sent and stored with
      the real URL substituted while the attacker's and judge's view keeps the placeholder** (FR-070); a loopback
      or private base against a public target plants nothing and sets `callback_note` (FR-068); a replay of a
      source whose URL the listener can no longer receive is never `fixed` — still vulnerable on another item, else
      inconclusive, with its reason — and that replay's re-sent URL is **still redacted from the judge's and
      recommender's view even though the listener is now off or the base changed** (FR-031, FR-069); **the per-run
      cap**: with `store.CALLBACK_HITS_CAP` lowered by `monkeypatch` (the store and the route read it at call time,
      never bind it at import), one request beyond the cap still answers `204`, stores nothing, and produces
      exactly one `callback.ignored` line with reason_kind `hit_cap_reached` bound to the run (a second capped request
      adds no line), while the turn's item counts exactly the cap (FR-072, SC-016); **the mount rule**: an app
      created without `KESTREL_CALLBACK_BASE_URL` has no `/callback/` route — a well-formed token path gets the
      app's ordinary not-found response, no store lookup and no `callback.*` line, and in hosted mode (an access
      token set) that path is refused by the token like any other (FR-073, SC-016) (FR-027 to FR-031, FR-068,
      FR-069, FR-070, FR-072, FR-073, SC-006, SC-007, SC-015, SC-016).
- [ ] T051 [US6] Author `src/kestrel/prompts/callback_task.v1.md` (id `callback_task`, placeholder
      `{callback_url}`) — a short paragraph **appended to the opening message in the user's voice** — and `--lock`
      it; bump `attacker:tool_exfiltration` to v2 (steer toward the address, writing the `[callback-url]`
      placeholder where it belongs, never inventing one, and carrying **no** callback guidance when the run planted
      no URL) and `--lock`; add `callback_task` to the `EXPECTED_IDS` pins and accept `"2"` for that attacker id
      (FR-028, FR-059, FR-068, SC-008).
- [ ] T052 [US6] Implement `src/kestrel/evidence/callback.py`: `generate_callback_token`, `callback_url`,
      `callback_task_paragraph`, `redact_callback_urls`, `restore_callback_url`, `wait_for_hits`, and the
      base-usability check of FR-068; plus the store methods `record_callback_hit` — returning `(run_id, stored)`
      and inserting nothing once the run holds `store.CALLBACK_HITS_CAP = 100` rows, consumed or not, a documented
      constant beside `RUN_LOG_CAP` (FR-072) — `count_unconsumed_callback_hits` and `consume_callback_hits`
      (FR-027 to FR-031, FR-068, FR-070, FR-072).
- [ ] T053 [US6] Add the `/callback/{token}` route to `api/main.py` (GET/POST/PUT/HEAD), **registered in
      `create_app` only when `KESTREL_CALLBACK_BASE_URL` is set** — with it unset the path does not exist, the
      app's ordinary not-found response answers it, and `require_token` exempts nothing (FR-073) — exempt from
      `require_token` for `/callback/` paths while mounted, reading no body: `204` + `record_callback_hit` +
      `callback.hit` for a token on an in-progress run; when the store reports that run at its cap, still `204`
      with nothing stored and one `callback.ignored` (`reason_kind` `hit_cap_reached`) through `events.warn_once` keyed
      on the run id and bound to the run with `bind_run_reference` (FR-072); else `404` + `callback.ignored`;
      `token` must match `^[0-9a-f]{24}$` (FR-027, FR-029, FR-030, FR-072, FR-073).
- [ ] T054 [US6] Extend the checker and planting: `build_checker` plants a callback token for `tool_exfiltration`
      only when the listener is enabled **and its base is usable for this target**, recording `callback_note` when
      it is not (FR-068); `check_turn` runs the bounded wait (`min(callback_wait_s, remaining())`, no model call)
      and emits one `canary_callback` item per turn with new hits; a replay whose source URL no longer matches the
      configured base records the FR-069 note and cannot be scored fixed; a source that planted nothing skips the
      check (FR-028, FR-030, FR-036, FR-050, FR-068, FR-069, SC-012). Makes T050 pass.
- [ ] T055 [US6] Apply the two redaction directions: `redact_callback_urls(text, tokens)` at every model boundary —
      the judge calls in `runs.py`, `attack/graph.py::_judge_turn` and `replay.py`, the attacker's conversation in
      `run_adaptive.attacker_node`, and `report/recommend.py::recommendations_for(tokens=)` — keyed on the run's
      planted tokens (a replay's source tokens included, so a re-sent URL whose base changed or whose listener is
      off is still redacted, FR-069) — and `restore_callback_url` on an attacker-generated message as it is sent, so
      the stored message equals the sent message (FR-031, FR-049, FR-069, FR-070).
- [ ] T056 [P] [US6] Integration test for the sidebar caption (`FEATURE = "013"`): with the listener enabled the
      sidebar shows exactly **"Callback listener: on"**, and with it disabled exactly **"Callback listener: off"**,
      read from `GET /api/config` and never re-derived in the UI (FR-042, FR-043). Add the caption
      to `ui/app.py`'s sidebar in the same task.

## Phase 9: User Story 7 — Confirm a change to protected state (P2)

**Goal**: a before/after snapshot through the side channel; any change is hard evidence; values never stored.

**Independent Test**: quickstart US7 — `tests/integration/test_side_channel_checks.py` (state cases).

- [ ] T057 [P] [US7] Integration test `tests/integration/test_side_channel_checks.py` state cases (`FEATURE =
      "013"`): identical snapshots → no item; a changed snapshot → one `protected_state_changed` item naming the
      sorted changed top-level keys, confirmed run; no state value appears in the run's stored data or any log
      line (only key names in the detail, only `state_changed_keys` as a count on the line); **a failed snapshot
      is a side-channel error, never a hit, and leaves the most recent successful snapshot as the baseline**, so
      the next successful snapshot is compared against that one; the baseline request happens inside the run's
      deadline (FR-032, FR-033, FR-034, FR-050, SC-005).
- [ ] T058 [US7] Implement the state check in the checker: the baseline taken by a `take_baseline()` call the
      **send step makes before the first send in every path** — `runs.execute_run` (single-turn),
      `run_adaptive`'s send step on turn 1, and both replay paths (`replay.execute_replay`'s single-turn branch and
      `run_replay_adaptive`'s send step) — inside the run's deadline, not in `build_checker` and not in
      `check_turn` (which runs only after a reply); a snapshot after each reply, `changed_keys` by deep per-key
      comparison against the most recent **successful** snapshot, one `protected_state_changed` item (detail =
      sorted key names); only the previous snapshot kept, nothing persisted, only the count logged. Wire the
      claim-time `side_channel_status` into `claim_run` for a side-channel target (T009's parameter, `checked`
      vs `not_configured`), and add a **single-turn** state-change test to T057 so the pre-send baseline (not just
      the adaptive path) is proven (FR-032, FR-033, FR-034, FR-050). Makes T057 pass.

## Phase 10: User Story 8 — Prove the side channel end to end on the HS-code target (P2)

**Goal**: the sacrificial target gains the cooperating side and the three gated, destination-bounded tools.

**Independent Test**: quickstart US8 — the target's offline tests, then the part-2 e2e.

- [ ] T059 [P] [US8] Offline tests in `targets/hs_code/tests/` (scripted model, no network beyond the local
      machine) per contracts/hs-code-target-delta.md: a scripted tool call is listed by
      `GET /side-channel/tool-calls` under its correlation id with a `seq` and **not** under another id; every
      side-channel endpoint needs the key; the honeypot tool records and returns a plausible result; the outbound
      tool with an **allow-listed** `127.0.0.1` URL makes exactly one bounded request (against a local stub or a
      recording client double); the outbound tool with a URL **not** on the allow-list — including a different path
      on an allowed host and port — sends **no request at all** and returns a readable refusal, asserted by a client
      double that must record zero attempts; with the tools'
      environment flag unset the target offers exactly today's tool set and none of the three appears in
      `describe` or can be dispatched; the state tool changes the protected store and `GET /side-channel/state`
      reflects it, its values being deterministic (FR-052, FR-053, FR-054, FR-055, FR-066, FR-067, SC-015).
- [ ] T060 [US8] Implement the HS-code target's cooperating side (`targets/hs_code/app.py`, `agent_loop.py`,
      `tools/`): per-correlation-id tool-call recording with `seq`, the three `/side-channel/*` endpoints behind
      the API key, and the honeypot, bounded outbound-request and state-changing tools — all three **gated behind
      an environment flag, absent by default** (FR-067), the outbound one sending a `GET` with no body and only to
      a URL matching an entry of its environment-configured allow-list of exact URL prefixes — scheme, host, port
      and a path prefix ending in `/`, all normalised, with **no default list** (an unset or empty list refuses
      everything; the part-2 e2e sets it to the callback base path, and any part-2 browser scenario sets it on its
      own second instance) — and refusing any other
      URL — a different path on an allowed host and port included — with no request sent at all (FR-066) — plus the
      deterministic protected store; name the honeypot tool in `targets/hs_code/README.md` (FR-053); `/chat`,
      `/debug/tool-calls` and the classifier fallback
      unchanged (FR-052, FR-053, FR-054, FR-055, FR-066, FR-067). Makes T059 pass.
- [ ] T061 [US8] End-to-end `tests/e2e/test_us013_side_channel.py` (`FEATURE = "013"`, marker `e2e`): a new
      `kestrel_api_with_listener` fixture (the existing `_Server` plus an explicit
      `KESTREL_CALLBACK_BASE_URL=.../callback`) and the target started with its tools flag on and its outbound
      allow-list set to exactly that base path; register the live target **with** its side channel, assert the
      connection test (chat and side channel) succeeds and a run completes with `side_channel_status="checked"`
      and any items of known kinds — structure only. This scenario also **exercises the target's side channel and
      its gated, allow-listed outbound tool from under `tests/`**, so FR-052 to FR-055, FR-066 and FR-067 are cited
      by a test the traceability gate can see (FR-052, FR-053, FR-054, FR-055, FR-056, FR-066, FR-067, SC-010).
- [ ] T062 [P] [US8] Extend the part-2 redaction and log tests (`test_evidence_redaction.py`,
      `test_events_evidence.py`): 0 stream lines carry a correlation id, a side-channel or callback URL, a tool
      argument value, or a state key or value; `evidence.check` carries `checks`, `side_channel_status`,
      `callback_wait_ms` and `state_changed_keys`; `callback.hit`, `callback.ignored` and
      `evidence.side_channel_unavailable` render with only their catalogue fields (FR-047, FR-048, SC-007).
- [ ] T063 [P] [US8] Extend `tests/integration/test_evidence_part1_replay.py` (or a part-2 sibling) with the
      side-channel and callback halves: a replay confirmed only by a **side-channel** item scores
      `still_vulnerable`; a replay whose source URL the listener can no longer receive is inconclusive with its
      reason; both experiment arms detect side-channel evidence alike (FR-035, FR-037, FR-069, SC-009). Also add the
      part-2 half of `test_evidence_store_isolation.py` (T026's note): a confirmed `tool_exfiltration` run with a
      real planted URL repeated in a turn-2 stored message must write no URL into any pattern document, memory
      record, memory summary or retrieval query (FR-063, SC-013).

---

## Phase 11: Polish & Cross-Cutting (the LAST pull request only; never the spec-only PR)

- [ ] T064 Apply the Principle II amendment to `.specify/memory/constitution.md` with the exact text in plan.md
      (Constitution Check) — a confirming check ends the **run**, and the callback proof is a Kestrel-generated
      per-run URL, not a declared canary — bump the version `0.1.0` → `0.2.0` and set **Last Amended** to this
      PR's date (FR-058).
- [ ] T065 [P] Merge contracts/log-records-delta.md's rows verbatim into
      `specs/010-structured-logging/contracts/log-records.md`; the PR description carries the `spec-change:` note
      the traceability gate requires (FR-047).
- [ ] T066 [P] Move "Behavioural evidence" to **Done** in `docs/roadmap.md` (as `013 — Behavioural evidence`,
      renumbering the remaining planned item) and update `tests/unit/test_roadmap.py` to assert it, the convention
      every feature's roadmap task uses (FR-062).
- [ ] T067 [P] Update the "001–012 merged" status lines to "001–013" in `README.md` (the opening Status paragraph
      and the "What's next" line) and `CLAUDE.md`, with a one-paragraph summary of behavioural evidence, and
      extend T040's `docs/technical-design.md` section and `CLAUDE.md` learned note to cover part 2 (the side
      channel, the listener placement, its mount rule and per-run hit cap, the HS-code tools' gate and allow-list,
      the two e2e) (FR-062).
- [ ] T068 Write `specs/013-behavioural-evidence/traceability.md` mapping every `013/FR-###`/`013/SC-###` to the
      test(s) that cover it, and justifying the ids no test can carry: **FR-023** (the side-channel contract is a
      documentation requirement, satisfied by `contracts/side-channel.md`), **FR-058** (the constitution edit,
      satisfied by T064's diff), **FR-066** and **FR-067** (their tests live in `targets/hs_code/tests`, which the
      traceability gate does not scan, so they are justified here and cited by the part-2 e2e T061), FR-059,
      FR-060, FR-062 and SC-011 (process and authoring rules, as feature 012 justified its own), and note that
      **SC-014**'s "the override wording claims to supersede" half is satisfied by the `framing: override` field
      plus a reviewed-property note here in `traceability.md` for the implementation PR's reviewer. Add the
      `Spec-PR: #<n>` line to the implementation PR description so `scripts/check_traceability.py` passes (FR-023,
      FR-058, FR-059, FR-060, FR-062, FR-066, FR-067, SC-011, SC-014).

---

## Dependencies & Execution Order

- **Setup (T001–T002)** → **Foundational (T003–T012)** blocks everything; the full existing suite must stay green
  after T012 (SC-008).
- **Part 1**: US1 (T013–T019) and US2 (T020–T024) are independent of each other and both need only Foundational;
  US3 (T025–T035) needs US1 for the isolation test and both detectors for the surfaces. T036–T039 are the e2e and
  the named test edits; **T040 is the part-1 documentation task** and closes part 1.
- **T011 before T012** is deliberate: the replay and experiment behaviour part 1 wires is tested before it is
  wired, so a part-1-only pull request cannot ship it untested (FR-062, research D24).
- **Part 2 never starts before T040.** US4 (T041–T046) blocks US5 and US7 (they need the side channel); US6
  (T050–T056) needs only the listener and the callback module; US8 (T059–T061) needs US4–US7 on the target.
  T062–T063 are cross-cutting part-2 tests.
- **Polish (T064–T068)** is last, in the final pull request.

## Parallel opportunities

- Setup: T001, T002 together.
- Foundational tests: T003, T004, T005, T006 and T011 together (different files), before their implementations.
- US1 tests T013, T014 ‖ US2 fixture and test T020, T021 (different stories, both after Foundational).
- US3 tests T025, T026, T027, T030, T032, T035 are each `[P]` against different files.
- Part 2: T041 ‖ T045; T047 ‖ T050 ‖ T057; T059 ‖ T062 ‖ T063.
- Polish T065, T066, T067 are independent files.

## Implementation strategy

**MVP = Part 1** (Setup + Foundational + US1 + US2 + US3, through T040): the two reply detectors, every evidence
surface, the stripping and scrubbing, the replay and experiment tests for what it wires, one e2e and its own
documentation — a complete, shippable slice needing nothing from the target. **Part 2** (US4–US8) adds the side
channel, the listener and the HS-code target on top, reusing the checker. The final pull request carries the
constitution amendment, the roadmap, the README, the project-memory note, the log-records merge and the
traceability map.
