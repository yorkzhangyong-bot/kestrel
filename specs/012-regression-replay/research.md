# Phase 0 Research: Regression Replay (012)

All decisions respect Principle X (no new dependency) and the clarifications recorded in `spec.md` (session
2026-11-19: the batch-replay cap is `KESTREL_REPLAY_BATCH_MAX_RUNS`, default 20, an experiment-produced run counts
toward it; the CI script's usage/API-error exit status is `3`).

## Code facts this builds on (verified in the worktree)

- **Single-turn send/score** (`runs.py::execute_run`): claims the row, sends the one prompt (`sender(...,
  prompt=prompt.text)`), checks `match_canary` first, calls `judge.judge(attack=prompt.text, reply=reply,
  timeout=...)` **with no `conversation` argument** only when no canary matched and a judge is configured, and
  finishes the row via the shared `_finish` helper, which emits the run's one `turn` line
  (`attacker_generated=False`, `source=f"library:{prompt.id}"`) and calls `store.finish_run`. There is no attacker
  call anywhere in this path today — replaying a single-turn source needs no new "skip the attacker" logic, only a
  different claim (`mode="replay"`, `source_run_id=`) and a different finish (`replay_outcome=` instead of letting
  the caller write back).
- **Adaptive send/score** (`attack/graph.py::run_adaptive`): a `StateGraph` of six nodes —
  `attacker → send → evidence → judge → record → decide → (attacker | END)`. `attacker_node` returns the masked
  seed on turn 1 and otherwise calls `attacker.next_message(...)`; **every other node is agnostic to where
  `pending_message` came from**. `evidence_node` sets `outcome` on a canary hit and routes straight to `record`,
  skipping `judge_node`. `judge_node` builds `conversation = state["conversation"] + [("attacker",
  pending_message), ("agent", pending_reply)]` and calls `judge.judge(attack=pending_message, reply=pending_reply,
  conversation=_format(conversation), timeout=...)` — **always** with a conversation string, even on turn 1. This
  confirms the owner's stated distinction (spec.md FR-008: a single-turn source judged like `execute_run`, an
  adaptive source judged per turn "like the adaptive judge node") is a real difference in what is sent to the
  judge model, not just an implementation detail — the two code paths must stay separate.
- **`decide_node`**'s cap logic: `if state["turns_used"] >= max_turns: cap = "turn_cap"`. `max_turns` is a plain
  parameter, not derived from anything else. Setting it to `min(len(source's recorded messages), the currently
  configured adaptive turn cap)` for a replay makes "every recorded message was sent" and "hit the turn cap"
  literally the same `stopping_condition == "turn_cap"` value the graph already produces — no new stopping
  condition, no new field on `_State`, needed to tell the two apart from *inside* the graph. Telling them apart
  from *outside* (to decide `fixed` vs `inconclusive`) only needs one more number: how many messages the source
  recorded (D5).
- **`record_node`**'s `judge_verdict` write is **not necessarily this turn's own verdict**: it always passes
  `state.get("last_verdict")`, which was last set by whichever turn's `judge_node` most recently ran — stale on a
  turn whose `evidence_node` short-circuited via canary (judge skipped) or whose `send_node` failed (judge never
  reached). By induction over the loop's own edges: reaching turn *N+1* requires turn *N*'s `send_node` to have
  succeeded **and** its `evidence_node` to have found no canary (otherwise the graph would already have ended at
  turn *N*) — so every turn **before** the run's last one was judged with its own call, and `run_turns.judge_verdict`
  on it is accurate. Staleness is possible **only on the run's final turn**, and only when that turn ended via a
  canary hit or a send failure. `build_comparison` (D8) must read the final turn's displayed verdict from the
  *run-level* fields (`hard_evidence`, `succeeded_turn`, `failure_step`, `verdict`) rather than blindly trusting
  `run_turns.judge_verdict` there, and may trust it for every earlier turn.
- **Masking**: `mask_values(seed_prompt.text, secrets)` / `mask_values(reply.message, secrets)` happen once, at the
  point a message or reply is first produced, before it ever reaches `state` or the store. A recorded
  `run_turns.attacker_message` is therefore already masked; resending it verbatim (FR-001) needs no further
  masking step and no access to the real secret value — the replay path never calls `mask_values` on an attacker
  message at all, only on the *new* reply it receives (exactly as the normal adaptive path already does for every
  reply).
- **Provenance** (009/010): `attacker_ref`/`judge_ref` (`runs.py`) and `prompt_registry.split_ref` give
  `(prompt_id, version)` pairs; `add_turn(..., attacker_prompt_id=, attacker_prompt_version=, judge_prompt_id=,
  judge_prompt_version=)` and `finish_run(..., judge_prompt_id=, judge_prompt_version=)` already accept these as
  plain optional keyword arguments with no validation beyond "null means not recorded". A replay needs no new
  provenance machinery: the judge side calls the same `judge_ref`/`split_ref` functions against the **currently**
  configured judge (FR-009); the attacker-prompt side is simply **copied** from the source's own
  `run_turns.attacker_prompt_id`/`.attacker_prompt_version` (or, for a single-turn source, there is none to copy —
  single-turn runs carry no attacker prompt at all, library-seeded only).
- **Schema v9's rebuild** (`store.py::_rebuild_runs_with_autoincrement`) is the direct precedent for v10: `PRAGMA
  foreign_keys = OFF` before any DML (DDL alone does not open a transaction, so the PRAGMA still lands before the
  first implicit `BEGIN`); `runs_new` built from `RUNS_COLUMNS_SQL`; `INSERT INTO runs_new (<dynamic column list
  from PRAGMA table_info(runs)>) SELECT <same list> FROM runs`; drop, rename, **two separate `execute()` calls**
  for the indexes (never `executescript`, which would commit before `PRAGMA foreign_key_check` gets to run);
  `foreign_key_check` must come back empty; commit; `PRAGMA foreign_keys = ON`. Copying only the *old* table's
  column list into the *new* table means any column present in the new `RUNS_COLUMNS_SQL` but absent from the old
  table (exactly `source_run_id` and `replay_outcome`, for every pre-v10 row) is simply left at its implicit
  default — `NULL` — for every row that already exists, which is exactly correct: no pre-existing run is a
  replay. The rebuild's own no-op guard (`_rebuild_runs_with_autoincrement` checks `"AUTOINCREMENT" in
  definition["sql"].upper()`) cannot be reused for v10 (a v9-already-rebuilt table already has AUTOINCREMENT but
  not the new columns); v10 needs its **own** no-op guard, checking for `source_run_id` in `PRAGMA
  table_info(runs)` instead.
- **Self-reference under cascade**: every `runs` row a target owns is deleted together, in one
  `DELETE FROM targets WHERE id = ?` → `ON DELETE CASCADE` → one implicit `DELETE FROM runs WHERE target_id = ?`
  that removes a source and its replay(s) in the same statement (they always share one `target_id`, since FR-003
  forbids replaying to a different target). A self-referencing `source_run_id ... ON DELETE CASCADE` therefore
  never actually fires *across* a target boundary in any path this feature adds; it must still be declared
  correctly (and proven empirically, as the CLAUDE.md gotcha for v9 insists no FK behaviour here is assumed) so
  that `PRAGMA foreign_key_check` stays clean and a future feature that deletes a single run (not yet a thing
  Kestrel has) inherits a sane default rather than an unconsidered one.
- **Report filtering** (`report/model.py::build_report`): a pure function over whatever `runs` list its caller
  passes in; `api/main.py::target_report` is the only caller, building that list from `store.list_runs(target_id)`
  with no filtering today. Excluding replay runs (FR-027) is a one-line filter at that call site
  (`[r for r in runs if r.mode != "replay"]`), not a change to `build_report`'s own contract — `recommendations_for`
  then naturally never sees a replay run either, since it only receives what `target_report` passes it.
- **Experience isolation** (004/011): `background_provider(...)` and `write_back(...)` are called from exactly two
  places today — `api/main.py::start_run` and `experiments/engine.py::_run_rep`. Neither `replay.py` nor the new
  `attack/graph.py::run_replay_adaptive` needs to import `kestrel.experience.*` at all; the absence of the import
  is itself a structural guarantee, checked by a test that still asserts zero calls on a `SpyExperienceStore`
  (defence in depth, matching how 011 proved its own isolation property).
- **Events** (010): `SCOPE_FIELDS` already includes `mode`, so every line inside a replay's `run_scope()` carries
  `mode: "replay"` for free, with **no catalogue change** — only event-specific fields need a catalogue entry.
  `target_id` is also a `SCOPE_FIELD`, so a batch-level line emitted *outside* any single replay's scope (there is
  no one `run_id` for a whole batch) can still carry `target_id` as an explicit field without a catalogue entry,
  exactly the way `events.connection_test(...)` already emits `target_id` unscoped (`scoped=False`). `turn_ended`'s
  existing `attacker_generated: bool` parameter already controls whether `attacker_model`/`attacker_prompt` appear
  on a `turn` line; passing `attacker_generated=False` for every turn of a replay (not just turn 1) needs **no
  signature change** to `events.turn_ended` at all.
- **`GET /api/config`**'s `ConfigOut`/settings pattern (`experience_pattern_k` etc.) is the direct precedent for
  reporting `KESTREL_REPLAY_BATCH_MAX_RUNS`: a `positive_int(name, default)`-parsed `Settings` field, surfaced on
  `ConfigOut` the same way the experiment caps already are not surfaced today (`experiment_max_runs` is *not* on
  `ConfigOut`) — but the owner's clarification explicitly asks for the replay cap to be reported "on `GET
  /api/config`", so this feature adds that field even though the precedent (`experiment_max_runs`) does not have
  one; see D12.
- **The UI never re-derives eligibility for anything else either**: `_render_attack_form`'s "Run attack" button is
  disabled from `attacker.get("configured")`, a value the API already computed — the same shape FR-042 asks for
  here (`replayable` / `replay_blocked_reason` / `replay_advisory` as API-computed booleans/strings the screen
  only reads). Unlike that button, though, the Run-attack path never pre-checks permission/terms either (it just
  tries and surfaces the 409 if any) — `replayable` deliberately does more: it is false whenever permission is
  missing or terms are outdated too, a MAJOR finding (round 2) the first draft missed by computing `replayable`
  from `check_replayable(run)` alone, which only ever looks at the run's own fields and knows nothing about its
  target.
- **`_render_finding` returns early for a failed-to-send run** (`ui/app.py:520-525`, `if run.get("failure_step"):
  ... return`), before reaching any code that would come after it in the function body — a MAJOR finding (round 2)
  the first draft's placement of the Replay button inside this function would have hit: a button written after
  that `return` simply never renders for a run that failed to send, even though such a run is a legitimate
  "not succeeded" case the button must still show, disabled.

## Decisions

- **D1 — One replay engine, two branches, not two engines.** `replay.py::execute_replay` dispatches on
  `source.mode`: a single-turn source is replayed by a small function shaped exactly like `execute_run` (reusing
  `match_canary`, `judge_ref`, and the no-conversation judge call); an adaptive source is replayed by
  `attack/graph.py::run_replay_adaptive`, a second compiled graph that shares four of `run_adaptive`'s six nodes
  (`judge_node`, `send_node`, `evidence_node`, `decide_node`, each lifted to a parameterised module-level function
  — D14) and defines its own `attacker_node`/`record_node` beside `run_adaptive`'s.
  *Alternatives considered*: one generic engine for both shapes (rejected: would force either the single-turn
  judge call to gain a spurious `conversation` argument, contradicting FR-008's explicit "judged like `execute_run`
  for a single-turn source", or the adaptive path to lose its per-turn conversation — the two judge-call shapes
  are a deliberate, owner-stated requirement, not an implementation detail to optimise away). A fake `_Attacker`
  object whose `next_message` returns canned text, fed into the *existing* `run_adaptive` unmodified (rejected for
  the same reason, plus it would still call `attacker_ref`/`events.model_request(kind="attacker", ...)` bookkeeping
  that FR-002 forbids for a replay — "no attacker model is constructed or called").
- **D2 — The turn cap *is* the stopping rule for "ran out of recorded messages".** `run_replay_adaptive` is called
  with `max_turns = min(len(recorded_messages), current adaptive_max_turns)`. When every recorded message is sent
  without success, the existing `decide_node` stops the graph with `stopping_condition = "turn_cap"` at
  `turns_used == max_turns`, with no new code. The *only* new logic needed outside the graph is comparing
  `final_turns_used` against `len(recorded_messages)` (D5) to tell "sent them all, none worked" (candidate for
  `fixed`) from "the *current*, possibly lower, cap cut the replay short" (always `inconclusive`).
- **D3 — Schema v10 rebuilds `runs` a second time, by the same documented procedure.** `RUNS_COLUMNS_SQL` (shared,
  as today, by the fresh-database `CREATE TABLE` and every rebuild) gains the widened `mode` CHECK,
  `source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE`, and `replay_outcome TEXT CHECK (replay_outcome IS
  NULL OR replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive'))`. A new `_rebuild_runs_for_replay`
  method, textually parallel to `_rebuild_runs_with_autoincrement`, runs immediately after it in `_migrate`, guarded
  by its own no-op check (`"source_run_id" not in {existing columns}`). `SCHEMA_VERSION` becomes `"10"`; the
  version-acceptance guard in `_migrate` (`current not in (...)`) gains `"9"`.
  *Alternatives considered*: add `source_run_id` and `replay_outcome` via plain `ALTER TABLE ... ADD COLUMN`
  (SQLite does permit adding a nullable, default-free column with a `REFERENCES` clause) and rebuild *only* for
  the `mode` CHECK (rejected: two migration steps for one schema version is more moving parts than one rebuild
  that already has to happen anyway for the CHECK, and splits the "what does a v10 database look like" story across
  two code paths for no benefit — "three similar lines" is fine, two rebuild methods one version apart is not the
  same kind of repetition).
- **D4 — The self-reference is proven empirically, not assumed**, exactly as the CLAUDE.md gotcha for v9 insists:
  `tests/unit/test_store_migration_v10.py` builds a pre-v10 (schema-9-shaped) database by hand, runs `_migrate`,
  and asserts (a) `PRAGMA foreign_key_check` is empty immediately after, (b) a row written as `mode='replay'` with
  a `source_run_id` pointing at an existing run round-trips through `get_run`, (c) deleting the shared target
  removes **both** the source and the replay row in one statement with no orphan and no FK violation, and (d) the
  `mode` CHECK now accepts `'replay'` and still rejects a bogus value. This is the task's own explicit instruction,
  not an optional nicety.
- **D5 — The outcome rule reads every turn's own result, never the run's one aggregate `verdict` (revised after a
  SEVERE finding, round 1 review).** The first draft of this decision computed `compute_outcome(verdict:
  str | None, turns_sent: int, recorded_total: int)` from the *finished run's* single `verdict` field. That field
  is wrong for this purpose: `attack/graph.py::decide_node`'s cap-stop line (`"verdict": state["last_verdict"] or
  "unclear"`) takes whichever turn's `judge_node` call *most recently* set `last_verdict`, and `judge_node` leaves
  `last_judged_turn`/`outcome` untouched on a `JudgeError` or a "no judge configured" turn — so the run keeps
  going, and a *later* turn's `"failed"` silently overwrites an *earlier* turn's unresolved `"unclear"`. A replay
  whose turn 1 errors and whose turns 2+ are cleanly judged `"failed"` would read, by final `verdict` alone, as
  `"failed"` with every message sent — **fixed** — when the honest answer, because turn 1 was never resolved, is
  **inconclusive**. The reviewer's reproduction is exactly this: turn 1 unclear (a judge error), turns 2+ failed.
  The fix: `compute_outcome(turn_results: list[str | None], recorded_total: int)` takes the **sequence of
  per-turn results** (one entry per turn actually attempted; `None` for an unclear verdict, a judge error, no
  judge configured and no canary, or a send failure):
  - any entry `"succeeded"` → `"still_vulnerable"` (FR-013) — checked first, regardless of how many turns were
    sent, mirroring "stop at the first success" (FR-010).
  - `len(turn_results) == recorded_total` and every entry `"failed"` → `"fixed"` (FR-014) — every recorded message
    was sent **and every one of them, individually**, failed; one `None` anywhere in the list (not just the last
    entry) now correctly forces the next branch.
  - anything else → `"inconclusive"` (FR-015): a `None` entry anywhere, or `len(turn_results) < recorded_total`
    (a send failure, or the current turn/token/time limit cutting the replay short before the transcript ended).
  `turn_results` is captured **live**, turn by turn, inside the replay's own `record_node` (data-model.md,
  "Capturing `turn_results` live") — not reconstructed afterward from stored `run_turns` rows, which would
  reintroduce a milder version of the same staleness problem D7 already documents for `build_comparison`'s
  *display* concern (a different, lower-stakes use of the same stored data). For a single-turn source,
  `recorded_total = 1` and `turn_results` has zero entries if the send failed, one entry otherwise — the same
  function, no special-casing. *Alternatives considered*: reconstructing `turn_results` after the fact from
  `store.list_turns(run_id)` plus D7's terminal-turn correction (rejected: works, by the same induction D7 relies
  on, but adds a database round-trip and a second place that has to get the terminal-turn special case right,
  for a value — the actual outcome a user acts on — that matters more than the display-only comparison D7 serves;
  capturing it live needs only one list and one `.append()` already sitting next to code that computes the exact
  same signal for the existing `turn` log line).
- **D6 — Eligibility is one predicate, reused by both the single endpoint and the batch query.**
  `replay.py::check_replayable(run: Run) -> None` raises `ReplayOfReplay(run.source_run_id)` when `run.mode ==
  "replay"`, or `NotReplayable(reason)` when `run.status != "finished"`, `run.verdict != "succeeded"`, or (adaptive
  only, defensive) `run.turns_used in (None, 0)`. `store.list_replayable_runs(target_id)` expresses the same rule
  directly in SQL (`status = 'finished' AND verdict = 'succeeded' AND mode != 'replay' AND (mode = 'single_turn' OR
  turns_used >= 1)`, ordered `started_at ASC, id ASC`) for the batch path, so the two can never drift — exactly the
  concern that made 011 give retrieval one shared `background_provider` instead of two copies.
- **D7 — Per-turn comparison verdicts read the run's own terminal fields, not a blindly-trusted
  `run_turns.judge_verdict`.** `build_comparison` walks the source's (and the replay's) turns in position order;
  for every turn except the last one it sent, the stored `judge_verdict` is accurate (the code-facts induction
  above); for the **last** turn either run sent, the displayed verdict is derived from that run's own
  `hard_evidence`/`succeeded_turn`/`failure_step`/`verdict` fields (`"succeeded (canary)"` when `hard_evidence` and
  `succeeded_turn` name that turn; the failure step's own message when `failure_step` is set; otherwise the stored
  `judge_verdict`, which is accurate whenever the judge genuinely ran on that exact turn). A turn present in the
  source's recorded list past the replay's last sent turn is marked "not sent" (FR-010, FR-017). For a single-turn
  pair, there is exactly one synthetic "turn" per run, built from the run's own top-level fields (no `run_turns`
  row exists for either).
- **D8 — The comparison is computed at read time, never stored.** `GET /api/runs/{id}` for a run whose `mode ==
  "replay"` loads its source via `store.get_run(run.source_run_id)` (and both runs' turns) and calls
  `build_comparison` fresh on every request. Both runs are immutable once finished, so this is always consistent
  and needs no cache-invalidation story — the same reasoning the 010 kept-log already relies on ("a finished run's
  rows never change").
- **D9 — The report filter lives at the one call site, not inside `build_report`.** `api/main.py::target_report`
  passes `[r for r in store.list_runs(target_id) if r.mode != "replay"]` to `build_report`/`recommendations_for`;
  `report/model.py` and `report/recommend.py` are untouched (FR-027), keeping `build_report`'s "pure function over
  already-fetched data" contract exactly as `contracts/report-module.md` (005) describes it today.
- **D10 — The UI carries no eligibility logic at all; the API computes `replayable`, the blocked reason and the
  advisory from the run, its target, and the current turn limit together (revised, MAJOR finding round 2
  review).** `check_replayable(run)` (D6) alone is not enough: it only ever sees the run's own fields, so it
  cannot know whether the run's *target* currently lacks permission or carries outdated terms — both of which
  must also block a replay (FR-006), and both of which the first draft of this decision left for the UI to
  discover only at click time, the same way the "Run attack" button already works (which is fine there, but not
  what FR-042 asks for here). `RunSummary`/`RunDetail` instead gain three server-computed fields: `replayable:
  bool`, `replay_blocked_reason: str | None` (one of the six exact strings FR-004 to FR-006 define, present only
  when `replayable` is false), and `replay_advisory: str | None` (the over-turn-limit caption FR-040 defines,
  independent of `replay_blocked_reason` — a replayable run can still carry one). All three come from one
  function taking the run, its target (for `permission_confirmed_at` and `terms_version`) and the currently
  configured adaptive turn limit — never the run alone — so a target whose permission or terms lapsed after a
  run succeeded is reflected immediately, without waiting for a click. The replay endpoint's own refusal reuses
  the identical reason string `replay_blocked_reason` would have shown, so the two can never read differently for
  the same run. The Replay button's `disabled=not run["replayable"]` and its caption come straight from these
  fields, the same pattern the existing "Run attack" button uses for `attacker.get("configured")` — except this
  button must render **before** `_render_finding`'s failure-step early return (see the code fact above), not
  after it, so it still appears, disabled, for a run that never got a reply at all.
- **D11 — Both new endpoints stay synchronous; the UI never calls the batch one (revised, MAJOR finding round 1
  review).** Per the owner's text ("runs stay synchronous, as `POST /api/runs` is today") and FR-038: no
  background task, no poll-for-status endpoint, for either a single replay or a batch. The spec asks for a
  **single-run** Replay button only (FR-040) — there is no batch action in the UI at all, so `ui/api_client.py`
  gets only `replay_run(run_id)`, with a timeout that covers one replay (the adaptive time limit plus a margin,
  the same shape `run_attack`'s own timeout already uses over the adaptive wall clock — never the batch's much
  larger bound). The **CI script** is the one caller of the batch endpoint, and sizes its own timeout for the
  batch's worst case instead (`cap × per_replay_time_limit_s + 60`, research D13) — the first draft of this
  decision gave the sizing job to a UI client (`batch_replay`) that the spec never asked for.
- **D12 — The batch cap is a first-class setting, reported on `GET /api/config`.** `KESTREL_REPLAY_BATCH_MAX_RUNS`
  (default 20) is parsed by the existing `positive_int(name, default)` helper (`settings.py`) — the same parser
  already used for `KESTREL_EXPERIMENT_MAX_RUNS` and the adaptive caps, so an invalid value refuses to start exactly
  as those do. It is namespaced `replay_batch_max_runs` on `Settings` and surfaced as a new `ReplayOut(max_batch_runs:
  int)` field on `ConfigOut`, per the owner's explicit clarification that it be "reported on `GET /api/config`".
- **D13 — The CI script is a small, standalone `httpx` client, not an import of `ui/api_client.py`.** `scripts/`
  already depends on `kestrel` (the backend package) in `import_attacks.py`/`export_judge_samples.py`, never on
  `ui/` (a Streamlit app, not a library); `check_replay.py` defines its own ~10-line request helper reading
  `KESTREL_API_URL`/`KESTREL_API_TOKEN` (the same two environment variable names `ui/api_client.py` reads, so one
  CI job's environment serves both), keeping the existing one-directional dependency (`ui` → API; `scripts` → API
  or `kestrel`; never `scripts` → `ui`). Its HTTP timeout for the batch call defaults to
  `cap × per_replay_time_limit_s + 60`, both read from `GET /api/config` (MAJOR finding, round 1 review: the
  batch is synchronous and can legitimately run for `cap` replays' worth of wall-clock time, while `httpx`
  defaults to a 5 s timeout). **`per_replay_time_limit_s` (POSSIBLE finding round 2, accepted) is
  `max(settings.adaptive_time_limit_s, runs.TOTAL_DEADLINE_S)`** — the longer of the two per-run deadlines the
  server actually enforces, not the adaptive one alone, since a batch can replay single-turn sources too (whose
  own deadline, 90 s today, is a plain module constant in `runs.py`, not a `Settings` field) — reported as a new
  `ConfigOut.replay.per_replay_time_limit_s` rather than making the script know about two separate constants
  itself; at the shipped defaults (300 s adaptive, 90 s single-turn) this is 300 s, so a cap of 20 is a 6060 s
  worst case. `--timeout SECONDS` overrides the computed default outright (`contracts/ci-script.md`).
- **D14 — `run_adaptive`'s per-turn nodes are lifted to module-level functions where their behaviour is identical
  live or replayed; `attacker_node`/`record_node` are written separately where it is not (MINOR finding, round 1
  review).** `judge_node`, `send_node`, `evidence_node` and `decide_node` are closures defined *inside*
  `run_adaptive` today — not separately callable, and the first draft of this plan's claim that `run_adaptive`'s
  `judge_node`/`record_node` are simply "reused as-is" by `run_replay_adaptive` was not something Python actually
  permits without either duplicating their bodies or lifting them out. Since all four of those nodes are
  genuinely identical in substance whether the turn's message came from the attacker model or from a recorded
  transcript (FR-008: the per-turn judge-call shape is explicitly unchanged for a replay), they become
  module-level functions parameterised by what they used to close over, and both `run_adaptive` and
  `run_replay_adaptive` wire thin node closures to them — a mechanical, behaviour-preserving extraction, proven by
  `run_adaptive`'s own existing tests passing unmodified afterward (a task, not an assumption; FR-049).
  `attacker_node` and `record_node` are **not** shared (a model call versus a list lookup; run-wide-constant
  provenance versus per-turn copied provenance; `attacker_generated` is `turn >= 2` live but always `False`
  replayed) — `run_replay_adaptive` defines its own two, "written beside" `run_adaptive`'s rather than
  parameterising them, per the reviewer's own offered alternative. Both of the replay's own node closures index
  `source_turns` at the **same** `turn - 1` (with `turn = state["turns_used"] + 1`, exactly how the live
  `attacker_node` already names the current turn) for both the message lookup and the provenance copy — the first
  draft's task description used `source_turns[turns_used]` for one and `source_turns[turns_used - 1]` for the
  other, an off-by-one between two expressions that must read the same turn's data (data-model.md).
  *Import cycle*: `replay.py` must import `run_replay_adaptive` **from** `graph.py` (to dispatch an adaptive
  source there); `compute_outcome` (D5) is needed **inside** `run_replay_adaptive`, and it lives in `replay.py` —
  so `graph.py` importing it at module level would create exactly the cycle `runs.py`'s own docstring already
  warns about for `run_adaptive`. Resolved the same way that import cycle already is: a **lazy** `from
  kestrel.replay import compute_outcome` inside `run_replay_adaptive`'s own body, mirroring `runs.py:155`'s
  existing `from kestrel.attack.graph import run_adaptive` (also lazy, also inside the function that needs it,
  also for the same reason). *Alternative considered*: relocate `compute_outcome` to `runs.py` or `graph.py`
  itself, so no lazy import is needed anywhere (rejected: `compute_outcome` is single-turn-and-adaptive-agnostic
  replay scoring, conceptually `replay.py`'s; moving it to avoid one lazy import would scatter replay's own logic
  across modules for a cosmetic reason runs.py already shows is unnecessary).
- **D15 — An interrupted or crashed replay is never left without an outcome (MAJOR finding, round 1 review).**
  `store.py::close_interrupted_runs` (the start-up sweep), `replay.py::execute_replay`'s single-turn exception
  handler (mirroring `runs.py::execute_run`'s own), and a **new** exception handler around
  `run_replay_adaptive`'s `compiled.ainvoke(...)` call (`run_adaptive` has no such handler today — an uncaught
  exception there relies entirely on the sweep) all set `replay_outcome = 'inconclusive'` on their way out, so a
  finished replay row's `replay_outcome` is never `NULL` (FR-012, FR-015; data-model.md, "Interrupted and crashed
  replays"). The new adaptive-replay exception handler is deliberately **not** added to `run_adaptive` itself
  (FR-049) and is therefore not part of the D14 extraction — it differs between the live and replayed cases by
  design, not by oversight. **POLISH finding, round 3 review — named, not left implicit**: both of these
  post-claim handlers (the single-turn one inline in `execute_replay`, the adaptive one in `run_replay_adaptive`)
  close the row and then `raise ReplayFailed(run_id) from error` — a new exception, `replay.py::ReplayFailed`,
  carrying the closed run's id — instead of a bare `raise` of the original exception; data-model.md's
  `execute_replay` docstring names exactly which branch closes the row. A failure **before** `claim_run` ever
  succeeds propagates unchanged (never wrapped in `ReplayFailed`, which would name a run id that does not exist).
- **D16 — A server-computed `finding` flag, not a mode check, drives the headline cards (MINOR finding, round 2
  review).** `RunSummary` gains `finding: bool` — true for a run whose `verdict == "succeeded"` and whose `mode !=
  "replay"`, computed once, server-side, in the same `run_summary(...)` helper that already builds every other
  summary field. **POLISH finding, round 3 review — one boolean cannot produce two cards**: `ui/app.py::render_metrics`
  (`app.py:909-911`) drives its three headline cards from `finding` together with the run's own `hard_evidence`,
  never a mode check of its own — Confirmed sums runs where `finding` and `hard_evidence` are both true; Suspected
  sums runs where `finding` is true and `hard_evidence` is false; "Runs" (the total count) is unaffected and still
  counts every run, replay included, finding or not. The UI needed a mode check in the first draft of this task
  (`r.get("mode") != "replay"`), which FR-042 (no replay-specific logic in the screen) forbids just as much for a
  card as for the Replay button itself. The same `finding` flag is exactly what FR-027's report-level exclusion
  already computes inline at the `target_report` call site (research D9) — this decision just gives the UI a
  server-computed equivalent instead of asking it to repeat that logic.
- **D17 — A batch stops, not crashes, when one of its own replays fails unexpectedly (POSSIBLE finding round 2,
  accepted; redesigned POLISH finding round 3).** `execute_batch_replay`'s loop wraps each `execute_replay` call:
  on success, record the `BatchEntry` and continue; on `RunInProgress` (a collision, already handled, D-adjacent
  to FR-029), stop with `stop_reason="run_in_progress"`; on `ReplayFailed` (D15 — `execute_replay` raises this,
  chained, once it has already closed that entry's own run inconclusive and logged the cause by class and stack
  only, never its message, FR-045), build that entry's `BatchEntry` from the now-closed row
  (`store.get_run(error.run_id)`), include it as the batch's **last** entry (it did produce a run, just not a
  clean one), and stop with `stop_reason="replay_failed"`. A failure **before** `claim_run` ever succeeds — no
  row exists to build an entry from — is a bare exception, never `ReplayFailed`; the loop stops the batch the
  same way (`stop_reason="replay_failed"`) but adds **no** entry for that source, which instead joins
  `not_replayed_source_ids` like every other source the batch never reached. The batch endpoint itself never
  raises and never answers 500 for either case: one entry's failure is data the batch result carries, not an
  error the batch request suffered. The CI script's exit logic needs no new case for this — an incomplete batch
  (`complete: false`) already resolves to exit `1` (a completed `still_vulnerable` entry) or `2`
  ("could not conclude", FR-036) regardless of *why* it stopped early.
