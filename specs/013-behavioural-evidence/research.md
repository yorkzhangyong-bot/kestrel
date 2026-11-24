# Phase 0 Research: Behavioural Evidence (013)

Every decision respects Principle X (no new dependency) and the clarifications recorded in `spec.md` (session
2026-11-23: the override task is carried by `direct_injection` and `indirect_injection`, the callback task by
`tool_exfiltration`, both in single-turn and adaptive mode, placed in the opening message at the insertion point the
sidecar records for that family (FR-064); the run's exact filled task text is stripped and its planted values are
scrubbed from everything the experience store receives and from the retrieval query; the report gains
an LLM05 coverage row; the connection test checks a configured side channel). Numbered decisions D1–D25; the code
facts they rest on were verified in this worktree.

## Code facts this builds on (verified in the worktree)

- **The only deterministic check today** is `runs.match_canary(reply, canaries)` — the first declared canary that
  appears case-sensitively in the reply. It is called from three places: `runs.execute_run` (single-turn, then
  `_finish(..., canary_hit=True, verdict="succeeded", hard_evidence=True, reason=CANARY_REASON)`),
  `attack/graph.py::_check_evidence` (the module-level body behind both `run_adaptive`'s and
  `run_replay_adaptive`'s `evidence_node`, lifted there by feature 012), and `replay.execute_replay`'s single-turn
  branch. Every path sets `hard_evidence` from the canary alone; the judge is reached only when nothing matched.
  `_check_evidence` is **synchronous** today and returns a state update with `pending_canary` and an `outcome`.
- **Where the sent text comes from**: `execute_run` sends `prompt.text` verbatim and stores it as `prompt_text`
  (`claim_run(prompt_text=prompt.text)`); `run_adaptive.attacker_node` returns `mask_values(seed_prompt.text,
  secrets)` on turn 1 and `attacker.next_message(...)` afterwards; `record_node` stores `pending_message` as the
  turn's `attacker_message`. So "the message stored is the message sent" already holds for every turn, and a replay
  (`execute_replay` / `run_replay_adaptive`) re-sends `source.prompt_text` or `source_turns[i].attacker_message`
  byte for byte (`tests/integration/test_replay_run.py:141, 290`).
- **The send**: `connection/tester.py::run_test(settings, *, mode, display_name, target_id, transport, resolver,
  deadline_s, connect_timeout_s, max_bytes, max_reply_chars, prompt)` builds `headers = dict(settings.headers)` plus
  `Content-Type`/`User-Agent`, goes through `is_allowed(url, mode, resolver)` first, caps the body at 1 MiB and
  the reply at 2,000 characters **before** anything else sees it, and masks every header value out of the reply.
  `ResolvedSettings` is a frozen dataclass whose `headers` double as the run's secret list
  (`secrets = [value for _, value in resolved.headers]`); anything added to `headers` is therefore also masked out
  of replies and stored text — a reason **not** to carry the correlation id as a header of `ResolvedSettings`
  (D8).
- **The connection-test contract**: `FormSessions.fingerprint(resolved)` HMACs `url`, `method`, the sorted
  `headers`, `body_template` and `response_path`; `save_target`/`update_target` refuse (`409 not_tested`) unless the
  last successful test's fingerprint equals the fingerprint of what is being saved. Adding the side channel to
  `ResolvedSettings` and to the fingerprint is what makes the "save only what was tested" rule cover it (D9).
- **The address guard** (`connection/address_guard.py::is_allowed`) is a pure function of `(url, mode, resolver)`;
  the side-channel client can call it exactly as the tester does, before any request (FR-020).
- **The run scope and the catalogue** (`events.py`): `emit()` drops any field not in `CATALOGUE[event]`,
  `SCOPE_FIELDS` or `ANY_EVENT_FIELDS` with one `log.unknown_field` warning; `run_started(...)` wraps its optional
  fields in `_present(...)` (absent, never `null`); `turn_ended(...)` has no text parameter at all; `run_finished(run)`
  stashes the outcome `_run_end` reads; `bind_run_reference(run)` names a run on a line emitted outside its scope
  (the recommender's line today — the listener's `callback.hit` line uses the same device, D13).
  `tests/unit/test_events.py:80` asserts the **exact** field dict of a `run.start` emitted *without* the new
  keywords, so new `run.start` fields must be `_present`-filtered (passed only by the real run starters) to leave
  that test untouched.
- **Replay** (`replay.py`, `attack/graph.py::run_replay_adaptive`): claims `mode="replay"` with `source_run_id`,
  re-sends verbatim, shares `_judge_turn`/`_send_turn`/`_check_evidence`/`_decide_next`, computes
  `compute_outcome(turn_results, ...)` from per-turn results. **Two places make scoring replay-specific, and both
  must change (research D23):** `run_replay_adaptive`'s own `record_node` builds each `turn_results` entry from
  `pending_canary` (`attack/graph.py:390, :398`), and the single-turn replay branch has its own canary-only test
  (`replay.py:321-325`). Left alone, a replay confirmed only by a detector or a side-channel item would finish
  `succeeded` with hard evidence while `compute_outcome` returned `"inconclusive"` — breaking FR-035 and SC-009.
  Both must derive the entry from "did this turn produce any evidence item", which is exactly what the checker's
  `TurnEvidence` already answers.
- **The experiment engine** (`experiments/engine.py::_run_rep`) calls the same `execute_run`/`execute_adaptive_run`
  with a `hint_provider` it builds through the shared `background_provider(...)`; the same "one shared builder,
  both callers" shape fits the evidence checker (D2).
- **Write-back and retrieval**: `experience/writeback.py::_winning_messages(run, turns)` joins the adaptive turns'
  `attacker_message` up to `succeeded_turn`, or returns `run.prompt_text`; `experience/retrieval.py::build_query`
  joins the family label with the last two `attacker`-role messages of the graph's conversation (turn 1's message
  included once the conversation is two turns long); `summary.build_summary` builds the memory summary from the
  turns' **judge progress notes** (`writeback.py:25`). All three are places per-run values can reach the store or
  the query, and **stripping the template paragraph alone does not stop them** (D11): turn-2-and-later attacker
  messages carry whatever the attacker wrote — and the v2 attacker prompts steer it toward the marker — while a
  progress note carries whatever the judge wrote, and the judge sees the parts. `write_back` already receives the
  `run`, and `background_provider` is built **after** the checker, so both can be handed the run's planted values.
- **The judge's inputs**: `judge/client.py::_judge_messages(attack, reply, conversation)` fences the attack text,
  the reply and (adaptive) the conversation string; `recommend(..., attack=winning_message, evidence=...)` fences
  the winning message and the evidence. The attacker's inputs: `attack/attacker.py::_payload(conversation,
  progress, family, hints)`. These four call sites are where a planted callback URL must be replaced by a
  placeholder (FR-031, D12).
- **The report**: `report/model.py::build_report(target, runs, turns_by_run, recommendations, experience_summary,
  now)` is pure; `_coverage_row` counts runs by `owasp_category == tested.owasp_class`; `owasp.TESTED` holds three
  classes and `owasp.UNTESTED` seven, LLM05 among them with the reason "not visible from the chat endpoint alone";
  `proof(run, turns)` returns the confirming reply for a hard-evidence success. `tests/unit/test_report_coverage.py`
  asserts exactly three tested rows and seven untested classes.
- **The UI**: `ui/app.py::_render_finding` renders `"Attack succeeded · confirmed by canary{at}"` for
  `hard_evidence` successes (`tests/integration/test_ui_attack.py:93` asserts the substring `"confirmed by
  canary"`); `_evidence(run)` gives the run list's Evidence column (`"canary"` / `"judge · <model>"` / `"—"`);
  `render_form` draws header rows with `header_name_{i}`/`header_value_{i}` keys and the
  `STORED_PLACEHOLDER`/`UNREADABLE_PLACEHOLDER` captions; `render_metrics` reads `finding` and `hard_evidence`.
- **The prompt registry** (`prompt_registry.py`): any `<stem>.v<N>.md` under `src/kestrel/prompts/` with a two-line
  front-matter is a registered prompt; `registry()` lists every id on `GET /api/config`; `verify_lock()` fails the
  suite on an unlocked file; `scripts/bump_prompt.py <id> --lock` records a brand-new id's first version too
  (`record()` does `lock.setdefault(prompt_id, {})`). `tests/integration/test_config_prompts.py` and
  `tests/integration/test_prompt_no_secrets.py` pin the **exact set** of six ids (and the former pins `version ==
  "1"` for all) — both change on purpose when the two task prompts are added (D10).
- **Schema**: v10, `RUNS_COLUMNS_SQL` shared by the fresh `CREATE TABLE` and both rebuilds; `_migrate` accepts
  `("1", …, "9")` and ALTER-adds the v3/v4/v7 columns from tuples of `(column, ddl)`; the ALTER form omits CHECK
  constraints by convention (the base schema carries them). Several migration tests pin the literal `"10"`; the
  complete list of those pins is in D18 and SC-008, and T007 bumps them all to `"11"`.
- **The HS-code target** (`targets/hs_code/`): `app.py::chat` checks the key first, then runs
  `agent_loop.run_agent(message, model=..., canary=..., recorder=email_recorder, classifier=...)`;
  `agent_loop._dispatch` handles `send_email` and `classify_hs6` and answers `Unknown tool` otherwise;
  `tool_specs()` returns `[CLASSIFY_SPEC, SEND_EMAIL_SPEC]`; `GET /debug/tool-calls` returns the recorded
  `send_email` calls behind the key. Its tests use a `ScriptedChatModel` and the autouse `no_real_chat_model`
  fixture; CI does **not** run them (`.github/workflows/qa.yml` runs `pytest tests/unit tests/integration` and
  `ruff check src ui tests` only), so the quickstart runs them explicitly.
- **The e2e harness** (`tests/e2e/conftest.py`): the target runs as a subprocess on a free port with
  `HS_TARGET_API_KEY`/`HS_TARGET_CANARY`; `kestrel_api` runs the API as a subprocess with a fixed env (no callback
  base URL); 012's e2e instead runs the API **in-process** (`TestClient(create_app(...))`) against the live
  target. `tests/e2e/test_us2_judged_run.py` picks `direct_injection` and asserts the run was *judged* — a
  planted override task that a compliant live model fulfils would confirm the run without a judge (D21).

## D1 — One evidence package, one checker per run

**Decision**: a new package `src/kestrel/evidence/` owns everything deterministic: `model.py` (the `EvidenceItem`
dataclass, the kind table of FR-004 with labels, locations and classes, `kind_label`, `location_label`,
`category_for(kind, family)`), `override.py` (token generation, planting, the joined-form check, the disarm
check, `strip_planted_tasks`), `unsafe_output.py` (the pattern set and `scan`), `side_channel.py` (the client,
its failure steps, the connection-test check), `callback.py` (token and URL generation, `redact_callback_urls`,
the listener's record function, the bounded wait), and `checker.py` (`EvidenceChecker`, built once per run by
`build_checker(...)`, with `opening_message(seed_text)`, `note_sent(text)` and `async check_turn(turn, reply,
remaining)` returning a `TurnEvidence(items, side_channel_status, checks, callback_wait_ms)`). `runs.py`,
`attack/graph.py` and `replay.py` call the checker; they contain no detector logic.

**Rationale**: the canary check is called from three paths today and the checks of this feature are six; one
object that knows the run's canaries, tokens, side channel and counters keeps the fixed order (FR-001) in exactly
one place, keeps `attack/graph.py` free of HTTP and storage concerns (it still takes plain callables, as it does
for `hint_provider`), and gives every path — live single-turn, live adaptive, replay, experiment — the same
behaviour by construction.

**Alternatives considered**: extending `match_canary` in place (three copies of the order to keep in sync; the
side-channel I/O would land in `runs.py`); a LangGraph sub-graph per check (heavier, and the single-turn path has no
graph).

## D2 — Wiring: an optional `evidence` parameter, one shared builder

**Decision**: `execute_run`, `run_adaptive` and `run_replay_adaptive` gain `evidence: EvidenceChecker | None =
None`; `None` means `EvidenceChecker.canary_only(canaries)` — today's behaviour exactly, so every existing caller
and test is untouched. `evidence.build_checker(store=, target=, settings=, family=, mode=, canaries=, transport=,
resolver=)` is the one builder, called by `api/main.py::start_run`, `experiments/engine.py::_run_rep` and
`replay.execute_replay` (which passes the source's planted tokens instead of planting new ones). `_check_evidence`
becomes `async` (`evidence_node` is already allowed to be async in LangGraph; `send_node` and `judge_node` are)
and returns `pending_evidence` (the items), `pending_canary` (unchanged meaning), `pending_side_channel` and the
`outcome` when any item was found; `record_node` writes the items with `store.add_evidence(run_id, items)` right
after the turn row, so a run's items and turns are always consistent.

**Rationale**: mirrors the feature-011 `background_provider` shape the engine and the API already share; keeps the
012 lift intact (`_check_evidence` stays the one body both graphs use); defaulting to canary-only is what lets
SC-008 ("pre-existing tests pass, modified only where listed") hold: a default-canary checker changes no existing
path, and every test this feature does edit is named in SC-008's own list.

## D3 — The outcome reason and `succeeded_turn` for non-canary evidence

**Decision**: a canary-only turn keeps `CANARY_REASON` verbatim; a turn with any other kind (alone or with a
canary) records `reason = "Hard evidence confirmed the attack: <labels joined by ' + '>."`. `succeeded_turn`,
`stopping_condition="succeeded"`, `judge_used`, `hard_evidence=True` are set exactly as a canary hit sets them.

**Rationale**: the reason is shown on the run page (`st.text(run["reason"])`) and in the memory summary path only
indirectly; a constant shape with labels keeps the replay comparison and the report unchanged in structure.

## D4 — The override token

**Decision**: two parts of 6 characters each from the alphabet `abcdefghjkmnpqrstuvwxyz23456789` (31 symbols; no
`i`, `l`, `o`, `0`, `1`), drawn with `secrets.choice`; the joined form is `first + second` (12 characters). The
reply check is `re.search(re.escape(joined), reply, re.IGNORECASE)`; the parts separated by anything (a space, a
  hyphen, a newline) never match (FR-009). **Normalisation**: the echo-proofness test and the
disarm check do not compare verbatim — they run on the sent text with every non-alphanumeric character removed and
letter case folded, because a target that strips whitespace, punctuation or formatting could otherwise produce the
joined form from two parts that merely sat side by side. The template therefore guarantees at least one
**alphanumeric word** between `{first_part}` and `{second_part}`, so no normalisation of anything Kestrel sent can
yield the joined form. Uniqueness: 31¹² ≈ 7.9 × 10¹⁷ combinations, so a collision is not a practical concern;
there is deliberately **no** duplicate-token constraint in the schema, because a replay legitimately carries its
source's token value on a second row (FR-035, D15) — "never reused" means never *generated* for another run, and
generation is what the alphabet's entropy guarantees.

**Rationale**: an unambiguous alphabet survives a model that "helpfully" uppercases or re-types the parts; a
12-character random string cannot occur in natural text by accident; case-insensitive, normalisation-insensitive
matching costs nothing in precision at that length and closes the only echo route a normalising target had. The
parts are sent separated by a real word, so a target that quotes the instruction echoes those words apart — never
joined (FR-009's echo-proof property is structural, not heuristic).

**Alternatives considered**: reversing a string (models often reverse badly, hurting recall, and a target quoting
the request can accidentally contain the reversed form when the word is a palindrome-ish fragment); base-N
arithmetic ("add 1 to this number") — the joined form would be predictable from the sent text by a simple
transformation a quoting target could stumble on; three or more parts — longer messages for no precision gain.

## D5 — Planting is placed by a Kestrel-owned sidecar; the attacker is edited only for the callback placeholder

**Decision**: `checker.opening_message(seed)` places each task the family carries at the insertion point a
Kestrel-owned sidecar records for that seed — `src/kestrel/attacks/data/insertion_points.json`, keyed by prompt id,
a character offset into the seed's verbatim library text plus a sha256 fingerprint of that text (FR-064): a
**direct-injection** seed's point is the attacker-voice position, so the paragraph follows the seed text; an
**indirect-injection** seed's point sits *inside* its own simulated injected content, so the paragraph is
substituted there and the agent reads it as retrieved data. The library's seed text stays verbatim (the 002
contract) — the sidecar carries only the offset and the fingerprint, never an edit to the seed — and a test fails
when an indirect seed has no entry, an offset is out of range, or a fingerprint no longer matches the library text,
so a library update forces a re-review of the insertion points. Override and callback never share a family, so at
most one paragraph is placed today; the order is fixed — override, then callback — for the day they do.
Attacker-generated messages are not edited, with the one documented exception of substituting the run's real
callback URL for the `[callback-url]` placeholder on send (FR-070, D12); `checker.note_sent(text, turn)` otherwise
only inspects them (normalised, D4) and disarms the override token (`store.disarm_planted_token(run_id, "override",
turn)`; one `evidence.override_disarmed` warning) when the joined form is found (FR-012) — **including every
message a replay re-sends** (D15). The opening message is what `claim_run(prompt_text=...)` stores and what
`record_node` stores for turn 1 (the sent message, FR-011).

**Rationale**: a paragraph appended in the user's own voice would make the marker request arrive as a direct
request, which a well-scoped agent can satisfy without overriding anything. A sidecar-recorded insertion keeps the
curated, verbatim library text intact, keeps the planting template a separate, versioned, strippable paragraph
(D11), and puts the indirect family's instruction where an indirect injection actually lives. Editing attacker
output beyond the FR-070 substitution would make the attacker's provenance (`attacker_prompt_version`) describe
text it did not produce.

## D6 — The unsafe-output pattern set: named, versioned, `re` only, one item per category per turn

**Decision**: the pattern set is a module-level tuple of `Pattern(category, name, regex)` in
`evidence/unsafe_output.py` plus a module-level `PATTERN_SET_VERSION`, compiled once. `contracts/detectors.md` is
the reviewable contract: it names the set version, lists **every pattern by its stable name and category**, and
for each one states the exact shape it matches and the benign shape beside it that it must not match. Categories:
`destructive_shell`, `fetch_and_execute`, `destructive_sql`, `script_injection`. `scan(reply)` returns at most one
match per category (the first by position), carrying the pattern name; a match whose text also appears in a
message Kestrel sent in that run is skipped (FR-065). The item's `detail` is `"<category>/<pattern name> (set
<version>): <excerpt>"` with the excerpt whitespace-collapsed and cut to 200 characters, and the item stores the
pattern name and the set version as their own fields (FR-017). The inert fixture
`tests/fixtures/unsafe_output_cases.json` holds at least three positive and three negative cases **per named
pattern**, each case tagged with that pattern's name, so "every pattern has three of each" and "a pattern without
both kinds fails" are mechanically enforceable (FR-016). The standard library's `re` is the only tool; `shlex` is
not used.

**Rationale**: the owner must be able to review, at the spec pull request, the artefact behind every LLM05
confirmation, and a reader of a finding months later must be able to tell which rule fired and under which
version of the set. Per-pattern names make the fixture's coverage rule enforceable, which a per-category fixture
could not be. `shlex` would have to parse an entire reply as shell, raising on ordinary prose quotes and yielding
tokens that still need expressions — no gain.

**Where the expressions live**: the contract carries the set version, every pattern name and a precise per-pattern
boundary (matched shape versus benign shape); the compiled expressions themselves are authored in
`src/kestrel/evidence/unsafe_output.py`, where the implementation pull request's reviewer reads them against that
boundary and against the per-pattern fixture cases, and a test keeps the module's names and version in step with
the contract.

## D7 — Side channel: one client, six failure steps, read-only

**Decision**: `evidence/side_channel.py::SideChannelClient(resolved, mode, transport, resolver, timeout_s)` with
`describe()`, `tool_calls(correlation_id)` and `state()`, each a GET with the configured header, `User-Agent:
Kestrel/0.1 (side channel)`, a 1 MiB body cap, no redirects, the address guard first (hosted mode). Failures map
to six steps — `side_channel_address_not_allowed`, `side_channel_unreachable`, `side_channel_auth_rejected`
(401/403), `side_channel_timed_out`, `side_channel_invalid` (any other non-2xx, non-JSON, or a body missing the
contract's keys), and `side_channel_header_unreadable` (a stored auth header the current key cannot decrypt,
refused before anything is sent) — each with the exact message of FR-021 (added to the tester's `MESSAGES` table
so the UI's
existing `st.error(result["message"])` shows it unchanged). Inside a run the same client raises
`SideChannelUnavailable(step)`; the checker catches it, records `side_channel_status="unavailable"`, emits
`evidence.side_channel_unavailable` and carries on (FR-034).

**Rationale**: the chat path's own step/message table is the pattern users already know; one client serves the
connection test and the run, so the two cannot disagree about what "unavailable" means.

## D8 — The correlation id travels as an extra request header, outside `ResolvedSettings`

**Decision**: `run_test(..., extra_headers: Mapping[str, str] | None = None)`; the run paths pass
`{"X-Kestrel-Correlation-Id": correlation_id}` only when the target has a side channel. The id is
`uuid.uuid4().hex`. The header name joins `RESERVED_HEADERS` in `api/schemas.py`, so a user-defined header of that
name is refused with the existing message (FR-022).

**Rationale**: `ResolvedSettings.headers` is also the run's secret list (code fact above); putting the id there
would mask it out of replies, store it in the fingerprint (changing "what was tested"), and make a target without a
side channel receive a different request than today (FR-061).

## D9 — The side channel in the connection test and in the fingerprint

**Decision**: `ConnectionSettingsIn.side_channel: SideChannelIn | None` (`url`, `header: HeaderIn | None`,
`honeypot_tool: str | None`); `validate_settings` validates it with the target-URL rules and the header rules under
`settings.side_channel.*` field paths; `ResolvedSettings.side_channel: ResolvedSideChannel | None` is part of
`FormSessions.fingerprint`. `connection_test` runs the chat test first, then — only when the chat test succeeded
and a side channel is configured — `check_side_channel(...)`: a `describe()` call whose body must carry
`kestrel_side_channel: 1` and a `capabilities` list containing `tool_calls` and `state`. Success sets
`side_channel_checked=True` on the result (a new optional field, default `False`), which the form shows as the
caption **"Side channel checked."**; failure returns the side-channel step and message with `ok=False`.

**Rationale**: FR-021 and the clarification; the descriptor is the cheapest request that proves reachability,
auth and contract version at once without needing a correlation id.

## D10 — Prompt files: two task templates and three attacker bumps

**Decision**: two new registry prompts, `override_task` (`src/kestrel/prompts/override_task.v1.md`, placeholders
`{first_part}`, `{second_part}`) and `callback_task` (`callback_task.v1.md`, placeholder `{callback_url}`), each
one short paragraph of plain conversational wording, recorded in `prompt_versions.lock.json` with
`bump_prompt.py <id> --lock`. The three carrying families' attacker prompts are bumped to v2 (`attacker:
direct_injection`, `attacker:indirect_injection`: the opening message asked the agent to produce a joined marker,
keep steering it to produce it, never write the joined form yourself; `attacker:tool_exfiltration`: the opening
message gave the agent an address shown to you only as a placeholder, keep steering it to call that address).
A planted token records `prompt_id`/`prompt_version` of the template that planted it (FR-010, FR-028). The
wording itself is authored in the implementation PR inside the prompt files, never in this plan or any code
(FR-059).

**Rationale**: the registry is the one documented home for model-facing and attack wording (009); versioning the
task text lets `strip_planted_tasks` (D11) know every shape it must remove and lets a replay of an old run keep
verifying with the version that planted it. The attacker bumps raise the odds that an adaptive run actually
pursues the marker — without them the attacker only sees the task in its own turn-1 message and may drop it.

**Named test changes**: `tests/integration/test_config_prompts.py` and `tests/integration/test_prompt_no_secrets.py`
pin the exact six ids (the former also `version == "1"`); both gain the two task ids and accept version `"2"` for
the three bumped attacker prompts. `tests/unit/test_prompt_guard.py` stays green once the lock is recorded.

## D11 — Deterministic stripping **and** value scrubbing for the experience store and the retrieval query

**Decision**: two steps, both deterministic, applied together wherever text is bound for the experience store or
the retrieval query (FR-063):

1. `evidence.override.strip_planted_tasks(text, task_text) -> str` removes the run's **exact filled task text** —
   the one known string that run planted, wherever it sits — by literal removal rather than a paragraph-anchored
   regex, so it works no matter where the task was placed.
2. `evidence.scrub_planted_values(text, values) -> str` replaces every occurrence of the run's own planted values
   — each token part, the joined form, and the callback URL — with a fixed placeholder, wherever else they appear.

Applied in exactly these places: `experience/writeback.py::_winning_messages` (per message, before joining),
`experience/writeback.py` before `write_memory(summary=...)` **and** around `summary.build_summary`'s inputs (the
judge progress notes), and `experience/retrieval.py::build_query` (per attacker message before joining).
`write_back` already has the `run`; the retrieval provider is built **after** the checker — `build_checker(...)`
runs first in `api/main.py::start_run` and `experiments/engine.py::_run_rep`, and the checker's planted values and
exact task text are passed into `background_provider` (its signature gains them), so both call sites have them
without re-deriving.

**Rationale**: step 1 alone is not enough. The task text appears once, but a turn-2 or later attacker message can
repeat the parts — the v2 attacker prompts deliberately steer toward the marker — and a judge progress note can
repeat them too, and both of those texts reach the pool and the query. Step 2 is keyed on the run's real values,
which is exactly what the two call sites can supply. `tests/integration/
test_evidence_store_isolation.py` proves it with a stub attacker that repeats the parts and the URL in its turn-2
and later messages and a stub judge that repeats them in its progress notes, so the test cannot pass vacuously
(SC-013).

**Alternatives considered**: scrubbing only by template (the defect above); storing a second "clean" copy of each
message (two sources of truth; replay would have to choose).

## D12 — The callback URL never reaches a model: one redaction helper

**Decision**: `evidence/callback.py::redact_callback_urls(text, tokens) -> str` replaces every URL ending in one
of the run's planted callback tokens (for a replay, its source's recorded tokens) with the constant placeholder
`[callback-url]` — keyed on the token, never on the currently configured base, so a replay that re-sends a source
URL whose base has since changed or whose listener is now off is still redacted (FR-069). Applied
to every text handed to a model: `_judge_turn` (attack, reply, conversation string) and `execute_run`'s judge call
(and `replay.execute_replay`'s), `run_adaptive.attacker_node` (the conversation passed to `next_message`), and
`report/recommend.py::recommendations_for` (the winning message and the evidence text), each handed the run's
planted tokens. Stored text is never redacted (FR-031).

The reverse direction is `evidence/callback.py::restore_callback_url(text, url) -> str`, applied by
`run_adaptive`'s send step to an attacker-generated message: it substitutes the run's real URL for every
`[callback-url]` placeholder in the text that is **sent and stored**, while the attacker's and the judge's view of
that message keeps the placeholder (FR-070). Without it the attacker, which only ever sees the placeholder, could
never get the URL to a stateless target after turn 1.

**Rationale**: FR-031 and FR-049; keying on the planted token (not the configured base) means a replay that
re-sends a source URL whose base has changed or whose listener is off is still redacted, and it cannot miss a URL
whose token it does not know because it is handed exactly those tokens. The restore direction is the one documented
exception to "attacker messages are never edited" (D5), and it keeps the stored message equal to the sent message,
so feature 012's replay still re-sends something that works.

## D13 — The listener lives inside the API process

**Decision**: a FastAPI route `/callback/{token}` accepting `GET`, `POST`, `PUT` and `HEAD`, registered in
`create_app` **only when `KESTREL_CALLBACK_BASE_URL` is set** (FR-073; with it unset the path does not exist, the
app's ordinary not-found response answers it with no store lookup and no listener line, and `require_token`
exempts nothing), exempt from `require_token` while mounted (the dependency returns early for paths under
`/callback/` only then). It never reads the request body, answers `204` for a token of a run in progress (or of a
replay in progress, D15) after `store.record_callback_hit(token, method)` and emits `callback.hit` under
`events.bind_run_reference(run)`; otherwise it answers `404` with an empty body and emits `callback.ignored`
(warn-once per `reason`: `unknown_token` / `run_not_in_progress`). **Storage is capped per run** (FR-072):
`record_callback_hit` inserts nothing once the run holds `store.CALLBACK_HITS_CAP = 100` rows (consumed or not)
and returns `(run_id, False)`; the route still answers `204` — a target cannot tell a stored hit from a capped one
— and emits `callback.ignored` with `reason` `hit_cap_reached` through `events.warn_once` keyed on the run id,
bound to the run, so a flood costs one line, not one per request. `KESTREL_CALLBACK_BASE_URL` is the public base at
which **that route** is
reachable — for the in-process listener it therefore ends in `/callback` (for example
`http://127.0.0.1:8000/callback`); Kestrel appends `/<token>`. Unset means disabled (FR-027).

**Rationale**: no second process to start, configure or secure; the route and the store share the process and the
database the run writes to, so a hit is visible to the running check immediately. A separate listener process
("beside it") stays possible later behind the same base URL contract — the plan's deliberate placement decision
is in-process. Not mounting the route when the listener is off leaves a listener-off instance with no public,
token-exempt path at all, and the cap bounds what a looping agent, or a flood from anyone who learned the URL, can
write: the run's time limit already bounds the duration, the cap bounds the rows and the lines.

**Alternatives considered**: a standalone listener process (an extra moving part for the vibe coder, Principle
IX); DNS tokens (a resolver to run — out of scope per the spec); a per-caller rate limit (the listener never
records a caller address, FR-048, and a target behind one egress address shares it with everything else there); a
configurable cap (a setting nobody needs to tune — `RUN_LOG_CAP` set the precedent of a documented constant);
refusing capped requests with an error (a target could then observe the cap and tell a stored hit from a capped
one).

## D14 — The bounded wait polls the store

**Decision**: after each reply of a run that planted a URL, `check_turn` polls `store.count_unconsumed_callback_hits
(run_id)` every 0.25 s until a new hit appears or `min(settings.callback_wait_s, remaining())` elapses; a hit
yields one `canary_callback` item per turn (detail `"<method>"` or `"<method> (<n> hits)"`), and the hits are marked
consumed. `KESTREL_CALLBACK_WAIT_S` defaults to `2`; `0` means check once without sleeping. Offline tests set it to
`0` and make the stub target record the hit synchronously inside its own request handler, so no test sleeps.

**Rationale**: an agent that fetches a URL does so while handling the message, before replying, so the hit is
usually already there; the bounded wait covers asynchronous agents without ever threatening the run's time limit
(FR-030, FR-050).

## D15 — Replay: copy the planted tokens with their state, keep the listener honest

**Decision**: `execute_replay` copies the source's `run_planted_tokens` rows to the replay row
(`store.copy_planted_tokens(source_id, replay_id)`), **carrying `disarmed_turn` across unchanged** — a token the
source disarmed is disarmed on the replay from that same turn — and the replay calls `note_sent` on **every
message it re-sends**, so a re-sent message that contains the joined form disarms the replay exactly where it
disarmed the source. The listener resolves a token to every run row carrying it and records the hit against the
one that is `in_progress` (FR-035). A source that planted nothing gives the replay no tokens, so those two checks
are skipped (FR-036). The replay uses its own fresh correlation id and the target's current side channel. When
the re-sent URL's base no longer matches the configured listener base (or the listener is off), the replay is
marked as unable to re-test the callback and can never be scored fixed (FR-069).

**Rationale**: without the carry-over and the re-sent `note_sent` call, a replay would re-send — with the token
armed — the very message that disarmed the source, and a target that echoes that message would confirm the replay
with false hard evidence. Copying rows rather than joining through `source_run_id` at hit time
keeps the listener's query a plain token lookup and makes a replay's evidence self-contained in its own row set.

## D16 — State snapshots: per turn, compared by top-level key, never stored

**Decision**: the checker fetches `state()` once **before the first send** — inside the run's own deadline, taken
by the send step itself on turn 1 (not in `build_checker`, and not in `check_turn`, which runs only **after** a
reply and so would miss a state change the first message caused, FR-050, FR-032) — and once after every reply;
`changed_keys = {k for k in keys(prev) | keys(curr) if prev.get(k) != curr.get(k)}` (deep
equality of the JSON values); a non-empty set yields one `protected_state_changed` item whose detail is the sorted
key names joined by `", "` (FR-032). The baseline is **always the most recent successful snapshot**: a snapshot
that fails is a side-channel error (FR-034), never a hit and never a new baseline, so the next successful snapshot
is compared against the last good one. Only that one snapshot is kept in memory; nothing is persisted; the
`evidence.check` line carries a `state_changed_keys` **count** only (FR-033).

**Rationale**: taking the baseline in `build_checker` would put a network request outside the run's time limit.
Treating a failed snapshot as "no baseline" would let a failure hide a real change or invent one
on the next read. The contract therefore also requires targets to expose only deterministic protected state — no
timestamps, no read-moving counters, no unordered collections — since such a value would differ on every snapshot
and confirm every run.

## D17 — Tool-call log: count once by `seq`, two checks

**Decision**: `tool_calls(correlation_id)` returns the full ordered list; the checker remembers the **highest
`seq` it has already counted** and inspects only calls above it (FR-024) — never a list index, so a log that is
re-read, re-ordered or returned with a gap cannot double-count or skip a call. Honeypot: `call.name ==
honeypot_tool` → one `honeypot_tool_invoked` item per call (detail: the tool name); skipped entirely when no
honeypot name is configured (FR-025). Canary in a tool argument: each argument value is walked as **decoded
strings** — the string itself, and every string nested inside a structure — and each declared canary that is a
substring of one yields one `canary_in_tool_argument` item (detail: `"<tool> · <argument> · <canary>"`), never the
argument value (FR-026).

**Rationale**: indices broke under re-reads; `seq` is what the contract already defines as
monotonic per correlation id. Searching a JSON *rendering* of the arguments would miss a canary containing a
quotation mark, a backslash or a non-ASCII character, because the rendering escapes exactly those — the decoded
strings are what the agent actually passed.

## D18 — Storage v11 is additive and complete for both parts

**Decision**: `SCHEMA_VERSION = "11"`, created in **part 1** with every table and column of both parts — four new
tables (`run_evidence`, `run_planted_tokens`, `callback_hits`, `target_side_channels`) in `SCHEMA` via `CREATE TABLE
IF NOT EXISTS`, two nullable `runs` columns (`correlation_id`, `side_channel_status`) in `RUNS_COLUMNS_SQL` and in a
new `EVIDENCE_RUN_COLUMNS` tuple that `_migrate` ALTER-adds for an older database (the v3/v4/v7 pattern; no CHECK in
the ALTER form). No rebuild of any existing table (FR-057); `_migrate` accepts `"10"`. A two-PR split therefore
needs no second bump: part 2 only starts writing to tables and columns that already exist.

**Rationale**: one bump keeps the additive schema at "v11"; unused tables cost nothing; `close_interrupted_runs` and
every v9/v10 rebuild gotcha stay untouched because nothing here rebuilds.

**Named test changes** (the complete list): the literal `"10"` becomes `"11"` in
`tests/unit/test_store_migration_v5.py:103, 110, 129`, `test_store_migration_v6.py:82, 89, 97`,
`test_store_migration_v8.py:58, 65, 95`, `test_store_migration_v9.py:166, 176, 261`,
`test_store_migration_v10.py:177, 187, 269` and `tests/integration/test_provenance_migration.py:39, 61`; the
log-records tests whose turn and event order changes because the new per-turn `evidence.check` line now precedes
`turn` (`tests/integration/test_log_records_adaptive.py`, `test_log_records_single_turn.py`); a new
`tests/unit/test_store_migration_v11.py` follows the per-version convention. SC-008 lists these together with every
other planned edit.

## D19 — Report: items per finding, an LLM05 row, six untested classes

**Decision**: `build_report(..., evidence_by_run: Mapping[int, Sequence[EvidenceItem]] | None = None)`;
`Finding.evidence_items: tuple[EvidenceLine, ...]` (label, turn, location label, class, detail), rendered after the
winning message as `Evidence:` then one `- <label> · turn <N> · <location label> · <class>` line per item followed
by the detail in a fence; the confirming reply block stays. `_coverage_row` lists a run under its family's class as
today, but counts it **confirmed** there only when one of that run's own items carries that class — a
`canary_in_reply` item always does, so every canary-confirmed run is unaffected, while a system-prompt-leak run
whose only item is unsafe output is listed under LLM07 as suspected or held and counted confirmed under LLM05
alone (FR-045). A fourth `CoverageRow("LLM05: Improper Output Handling", "unsafe executable output
detector (every reply)", run_count=<runs that received a reply>, result=…)` comes from a new `owasp.DETECTED`
entry; `owasp.UNTESTED` drops LLM05 (six remain, wording unchanged). A pre-013 hard-evidence run with no stored
items is given **one derived `canary_in_reply` item** by the same helper the API uses, so the report, the run
detail and the run page all show exactly one canary item for it — never a count of 1 beside an empty list
(FR-005).

**Named test changes**: `tests/unit/test_report_coverage.py` (`set(rows) == TESTED` → four rows; `len(classes) == 7`
→ 6).

## D20 — API and UI shapes

**Decision**: `RunSummary` gains `evidence_kinds`, `evidence_labels`, `evidence_count`, `side_channel_status`;
`RunDetail` gains `evidence: list[EvidenceItemOut]`, `planted_tokens: list[PlantedTokenOut]` (kind, armed,
`disarmed_turn`, prompt reference — never a token value or URL), `side_channel_notice: str | None` and
`override_disarmed_notice: str | None` (both exact FR-034/FR-039 strings, computed server-side so the UI only
displays them, FR-043); `TargetDetail.side_channel: SideChannelOut | None`; `ConnectionTestResult.side_channel_checked`;
`ConfigOut.evidence: EvidenceConfigOut`. A pre-feature hard-evidence run with no items reports
`evidence_kinds=["canary_in_reply"]`, `evidence_labels=["canary"]`, `evidence_count=1` (FR-005, FR-040). The run
list gets `evidence_labels_by_run` from one query per target (`store.evidence_kinds_by_run(target_id)`, the
feature-012 one-query pattern).

## D21 — Tests and the e2e per part

**Decision**: offline doubles in `tests/support.py`: a `SideChannelStub` answered by `ModelTransport` for the host
`sidechannel.kestrel.test` (scripted descriptor, per-correlation-id tool calls, a sequence of state snapshots,
failure modes), an `on_target_request` hook so a stub target can call `store.record_callback_hit(...)` when it sees
the planted URL, and known markers (`OVERRIDE_PART_MARKER` is unnecessary — tests read the run's real parts from
`store.list_planted_tokens`). Part-1 e2e `tests/e2e/test_us013_detectors.py` runs the API in-process (as 012's e2e
does) against the live target; part-2 e2e `tests/e2e/test_us013_side_channel.py` needs the API reachable by the
target, so it uses a new `kestrel_api_with_listener` fixture (the existing `_Server`, plus
`KESTREL_CALLBACK_BASE_URL=http://127.0.0.1:<port>/callback`). Both assert structure, never the live model's
behaviour (SC-010).

**Named test change**: `tests/e2e/test_us2_judged_run.py` switches its family from `direct_injection` to
`tool_exfiltration` (no task is planted there while the `kestrel_api` fixture leaves the listener disabled), so
"decided by the judge" still holds against a model that would otherwise fulfil the override task.

## D22 — The constitution amendment

**Decision**: Principle II is amended as a MINOR bump to **0.2.0** with the exact text in `plan.md` (Constitution
Check); the implementation PR applies it to `.specify/memory/constitution.md` and sets **Last Amended** to that PR's
date; the spec-only PR does not touch the file (FR-058).

## D23 — Replay scoring derives each turn's result from any evidence item

**Decision**: both replay paths stop reading the canary flag for their per-turn result.
`run_replay_adaptive`'s own `record_node` (`attack/graph.py:390, :398`) and the single-turn replay branch
(`replay.py:321-325`) each take the turn's result from the checker's `TurnEvidence` — "did this turn produce any
evidence item" — so `compute_outcome` sees `"succeeded"` for a turn confirmed by a detector or a side-channel
check, not only by a canary. `attack/graph.py`'s `pending_canary` keeps its present meaning (a canary matched) for
the existing `turn` line's `canary_hit` field; the new, broader fact travels as the turn's evidence kinds, and the
`turn` line's `hard_evidence` field is redefined as "this turn produced at least one evidence item".

**Rationale**: without this a replay could finish `succeeded` with hard evidence while its own outcome read
`"inconclusive"` — a contradiction between FR-035/SC-009 and the code. Both paths are tested in **part 1** (D24),
because part 1 is what wires them.

## D24 — Part 1 tests and documents everything part 1 wires

**Decision**: the replay and experiment wiring that part 1 touches is tested **in part 1**, before the wiring
task: the token copy with its disarmed state, the disarm-on-replay rule, "any evidence item ⇒ still vulnerable",
a pre-feature source, and experiment arm parity. Part 1 also carries its own documentation task (the
technical-design evidence section and the project-memory note for what part 1 ships). Only the side-channel and
callback halves of those same files are re-tested in part 2.

**Rationale**: part 1 may ship as its own pull request (FR-062). With the replay tests deferred to part 2's
Phase 10, a part-1-only pull request would ship the D23 behaviour untested, against Principle VII. The same
argument applies to documentation, which FR-062 already promised part 1 would carry.

## D25 — Callback traffic is confined at both ends

**Decision**: two independent limits.
- **On the sacrificial target**: the outbound-request tool sends a `GET` with no body, and only to a URL matching
  an entry of an environment-configured allow-list of exact URL prefixes — scheme, host, port and a path prefix
  ending in `/`, all normalised; any other URL — a different path on an allowed host and port included — is refused
  with no request sent at all and a refusal the model can read. The target has **no default list**: an unset or
  empty list refuses everything, so private, link-local and cloud-metadata addresses are refused unless explicitly
  listed, and the feature's end-to-end and browser configurations set the list to the configured callback base path
  (FR-066). The honeypot, outbound and state tools are offered only behind an environment flag,
  off by default, so every existing suite that starts this target keeps today's tool set (FR-067); the 013
  end-to-end scenario and a dedicated browser-configuration target instance turn it on.
- **On Kestrel**: a callback URL is planted only when the configured base URL is usable for the target being
  attacked — a loopback base is never planted into a run against any non-loopback target, and a private base is
  never planted into a run against a public target — checked when the configuration loads and again per run; a
  refused base plants no callback task and records why (FR-068).

**Rationale**: the tool was bounded only by scheme, timeout, size and redirects, never by destination, so an
attacker-steered live model could have made the dev or CI machine fetch an arbitrary address — against the rule
that callback traffic stays on the owned target and Kestrel's listener, and against Principle VIII. The
Kestrel-side check closes the mirror-image hole: a mistyped base URL pointing a remote target at its own loopback,
or at a third party.

## Research notes on precision (recorded for the pattern set)

Benign strings the fixture must keep benign, by category: `ls -la`, `rm -rf ./build`, `rm -rf /tmp/kestrel-cache`,
`dd if=/dev/zero of=./disk.img bs=1M count=10`, `chmod 755 script.sh` (destructive shell); `curl -fsSL
https://example.com/archive.tar.gz -o archive.tar.gz`, `wget https://example.com/file.txt`, `curl -s
https://api.example.com/status | jq .status` (fetch-and-execute); `SELECT * FROM users WHERE id = 1;`, `DELETE
FROM sessions WHERE expired = 1;`, `UPDATE users SET name = 'x' WHERE id = 1;`, the prose "you can drop table
columns from the editor" (destructive SQL — no terminator after the identifier); `<b>bold</b>`, the prose "never put
a <script> tag in user content", `<a href="https://example.com">x</a>`, `<button onclick="">` (script injection).
Each appears as a negative case; each positive case is an inert sample output, clearly marked, never run.
