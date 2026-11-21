# Contract: the log stream (JSON Lines) and the event catalogue

Kestrel's log stream is the output of the `kestrel` logger (children included), written to the process's standard
error stream; the web server's own lines there are not part of it. Every line is one JSON object (FR-006);
`KESTREL_LOG_FORMAT=text` renders the same fields as `ts level event key=value …` instead. The event names and
field names below are the stable contract that tests, the kept log (`run_log`), the log endpoint and the viewer all
rely on. Illustrative values only — no attack text, no reply text, nothing from the FR-009 deny-list ever appears
in a record.

## Common fields

| Field | Type | Present |
|-------|------|---------|
| `ts` | string, ISO-8601 UTC with milliseconds, `Z` | always |
| `level` | `INFO` / `WARNING` / `ERROR` | always |
| `logger` | string (`kestrel`, `kestrel.connection`, …) | always |
| `event` | string, one of the catalogue below | always |
| `run_id`, `target_id`, `mode`, `family` | int, int, `single_turn`/`adaptive`, string | every record emitted inside a run's scope, and a post-scope record bound to a run (the recommender line) |
| `turn` | int | records about a turn |
| `experiment_id`, `arm` | int, `A`/`B` | every record of a run executed by an experiment; the experiment's own records |

Rules: fields are omitted when not applicable (consumers test presence); `null` appears only where the catalogue
marks a field `\| null` (the value exists but is unknown); values are never interpolated into text; an exception on
a record becomes `exc_type` (class name) and `stack` (`["file:line in function", …]`) — never its message — on any
event. A record may also carry `message`: **constant** text written by Kestrel (never a value, never interpolated);
it is the record's message for any other handler on the logger (a test's `caplog` shows it), and it is always
present on `message` events. The catalogue below is the allow-list of field names: a field outside it (and outside
the common fields, `message`, `exc_type`, `stack`) is dropped and reported once as `log.unknown_field`.
"Once" for every warning below means once per configured logger/tracer — one per process start in production
(the test suite configures a fresh one per app).

## Event catalogue

| `event` | Level | Emitted | Fields (beyond the common ones) |
|---------|-------|---------|----------------------------------|
| `run.start` | INFO | once, right after the run row is claimed | `prompt_id` (library seed id), `attacker_source`, `attacker_model` (adaptive only), `judge_model` (when configured), `attacker_prompt` (`attacker:<family>@N`, adaptive only), `judge_prompt` (`judge@N`, when configured), `turn_budget` (1 on a single-turn run), `token_budget` (adaptive only), `time_limit_s` (the 90 s deadline on a single-turn run), `use_prior_experience`; feature 012 (regression replay, `specs/012-regression-replay/contracts/log-records-delta.md`) adds `source_run_id` (the run being replayed, present only when `mode` is `replay`) |
| `turn` | INFO | once per turn, after the turn is recorded | `turn`, `source` (`library:<prompt_id>` or `attacker:<family>@N`; `attacker:<family>` with no `@N` when no version is known: legacy plain-text prompt — a feature-009 plain-text pin, for which this line's `attacker_prompt` and the attacker `model.request`'s `prompt` are null), `duration_ms`, `prompt_tokens`, `completion_tokens`, `total_tokens` (int \| null each: the turn's model requests summed, null when none reported — also when the turn made no model request), `cost_usd` (number \| null: `0` when the turn made no model request), `cost_note` (only when null), `attacker_model` and `attacker_prompt` (only on a turn the attacker generated), `judge_model` (only when a judge is configured), `judge_prompt` (only when a judge is configured: the reference of the judge request made on this turn, `null` on a canary-decided turn; equal to the turn's recorded judge provenance wherever that is recorded — a turn whose judge request failed names the request while its provenance stays null, FR-007), `message_chars`, `reply_chars` (int \| null), `reply_truncated`, `canary_hit`, `hard_evidence`, `judged`, `verdict` (`succeeded`/`failed`/`unclear` \| null: only when judged on this turn) |
| `model.request` | INFO (ERROR when `ok` is false) | once per logical model request | `kind` (`attacker`/`judge`/`recommender`), `model`, `prompt` (`id@N`), `latency_ms`, `ok`, `status` (int \| null), `error` (class name, only on failure), `attempts`, `prompt_tokens`, `completion_tokens`, `total_tokens` (int \| null each: what the provider reported over every attempt — null when it reported nothing, as on a transport error or an error status), `cost_usd` (number \| null), `cost_note` (only when `cost_usd` is null); judge: `verdict`, `hard_evidence` (always `false`); attacker: `message_chars` |
| `model.empty_content` | WARNING | the attacker returned empty content on an attempt | `attempt`, `finish_reason` (`stop`, `length`, `content_filter`, `tool_calls` or `error` as reported; `other` for any other provider value, so a provider string never reaches the line \| null: none reported), `completion_tokens`, `reasoning_tokens`, `total_tokens`, `reasoning_chars` |
| `target.request` | INFO | once per request sent to the target inside a run | `latency_ms`, `ok`, `status` (int \| null), `step` (the tester's step name), `reply_chars` (int \| null), `reply_truncated` |
| `connection.test` | INFO | once per connection test (outside a run) | `target_id` (only for a saved target), `latency_ms`, `ok`, `status` (int \| null), `step` |
| `memory.retrieval` | INFO | once per turn on which the run asks the experience store for background (prior experience on, store available — from turn 2: turn 1 sends the library seed and never asks) | `turn`, `warm` (`pattern_count > 0`), `pattern_count` (the patterns **selected**, feature 011), `memory_count` (both zero when nothing came back), `pattern_ids` (list of ids such as `pattern:lib:<prompt_id>`, empty when none); feature 011 (the retrieval controls, `specs/011-retrieval-controls/contracts/log-records-delta.md`): `k` (the bound in effect), `distance_floor` and `dedupe_threshold` (number \| null: the controls in effect, `null` when switched off), `candidate_count` (candidates examined, nearest first — always `dropped_floor + dropped_duplicate + pattern_count`), `dropped_floor` (candidates beyond the floor), `dropped_duplicate` (candidates skipped as near-identical to an already selected hit), `distances` (the selected hits' distances from the query, 4 decimals, nearest first; empty when none), `query_messages` (attacker messages in the query, 0–2) |
| `memory.retrieval_failed` | WARNING | the experience store raised while the attacker's background was being retrieved (the turn continues without it) | `exc_type`, `stack` |
| `memory.writeback` | INFO (ERROR when failed) | once per run, inside the run's scope, before `run.end` (a direct call outside a scope binds the run as a reference: the line names the run and goes to the stream only) | `written`, `pattern_written` (true when the success was recorded as a pattern — added **or** merged, feature 011), `error` (class name, only when failed); feature 011, only on a success: `pattern_outcome` (`added`: a new record was added; `merged`: an existing near-identical same-family pattern's hit count was raised), `pattern_id` (the pattern added, or merged into), `hit_count` (the pattern's hit count after this write-back), `pattern_distance` (number \| null: distance to the nearest existing same-family pattern, `null` when the family had none or de-duplication is off) |
| `memory.flag_failed` | ERROR | a failed write-back could not even be flagged on the run row | `exc_type`, `stack` |
| `recommendation.unavailable` | WARNING | report time: the recommender call for a finding failed, so the report omits that recommendation | `error` (class name) |
| `run.end` | INFO (ERROR when `error` is set) | once, the last record of the run's scope, after the write-back (every exit path) | `verdict` (\| null), `hard_evidence`, `stopping_condition` (\| null), `failure_step` (\| null), `judge_used` (at least one judge request was made), `turns_used`, `tokens_used`, `succeeded_turn` (\| null), `memory_written` (bool \| null: null when no write-back was attempted — always null for a replay, which never attempts one), `duration_ms`, `cost_usd` (number \| null), `cost_note` (only when null), `error` (class name, only when the run failed unexpectedly); feature 012 adds `replay_outcome` (`fixed`/`still_vulnerable`/`inconclusive`, present only when `mode` is `replay` — omitted entirely for a non-replay run, never `null`) |
| `replay.batch.start` | INFO | once, before the first entry of a batch replay is claimed (feature 012, `specs/012-regression-replay/contracts/log-records-delta.md`) | `target_id`, `replayable_count` (how many runs this batch will process), `cap` (the configured `KESTREL_REPLAY_BATCH_MAX_RUNS` in effect) |
| `replay.batch.end` | INFO (ERROR when `error` is set) | once, after every entry has finished or the batch stopped early (feature 012) | `target_id`, `fixed_count`, `still_vulnerable_count`, `inconclusive_count`, `duration_ms`, `complete` (`false` on a mid-batch collision or one entry's own unexpected failure), `stop_reason` (`run_in_progress`/`replay_failed`, present only when `complete` is `false`), `error` (class name, only on an unexpected failure of the batch request itself — never set merely because one entry's own replay failed, which is data the result carries, not an error the batch suffered) |
| `experiment.start` | INFO | once when an experiment starts executing | `experiment_id`, `target_id`, `mode`, `families`, `reps`, `max_runs`, `token_budget_total`, `wall_clock_s`, `arms` (list of `{label, attacker_model, judge_model, use_prior_experience, turn_cap, token_budget, write_back, prompt}`) |
| `experiment.cap` | WARNING | once, when a hard cap stops the experiment | `experiment_id`, `cap` (`max_runs`/`token_budget`/`wall_clock`), `completed_runs`, `tokens_used`, `elapsed_s` |
| `experiment.end` | INFO (ERROR when failed) | once when the experiment finishes, stops or fails | `experiment_id`, `status`, `stopped_reason` (`completed`, the cap, or `failed:<class>` — the stored value), `completed_runs`, `tokens_used`, `duration_ms`, `error` (class name, only when failed) |
| `library.unavailable` | WARNING | start-up: the attack library could not be loaded | `exc_type` |
| `experience.unavailable` | ERROR | start-up: the experience store cannot be used | `exc_type`, `reason_kind` (`embedding_function_mismatch`/`model_download`/`other`; feature 011 adds `embedding_model_mismatch` and `space_mismatch`); feature 011, only on a model mismatch: `stored_model` (the model name recorded in the collection), `expected_model` (the model name of the embedding function in use); only on a space mismatch: `stored_space` (the distance space the collection's index actually uses, e.g. `cosine`), `expected_space` (the pinned space, `l2`). For those two reason kinds the `message` is a **mismatch-specific constant** that states the remedy (verbatim): model — "The experience store was built by a different embedding model, so it is disabled for this session and runs will record loudly as not written back (Principle V). Rebuild the store directory, or run Kestrel with the model that built it."; space — "The experience store's index uses a different distance space than Kestrel expects, so it is disabled for this session and runs will record loudly as not written back (Principle V). Rebuild the store directory."; every other cause keeps the generic constant |
| `experience.seed_failed` | ERROR | start-up: the store could not be seeded | `exc_type`, `reason_kind` |
| `key.mismatch` | ERROR | start-up: the encryption key does not match the one used to save targets (no exception) | `message` (the constant explanation and remedy) |
| `experience.delete_failed` | ERROR | deleting a target: its memory could not be deleted from the experience store | `exc_type`, `target_id` |
| `log.truncated` | WARNING (kept row only, never on the stream) | written to the kept log when the cap was hit, as its last row | the common and run-scope fields copied from the run's `run.end`, `kept`, `dropped` |
| `log.sink_failed` | WARNING | once per error kind per process | `error` (class name), `for_run` (int) |
| `log.unknown_field` | WARNING | once per field name per process: an emitter passed a field outside the catalogue (the field is dropped) | `field`, `for_event` |
| `tracing.unavailable` | WARNING | once at start-up: flag on, packages missing — or the tracer could not be set up (an exporter the `OTEL_*` variables misconfigure) | `cause` (`package_missing` / `setup_failed`), `extra` (`kestrel[otel]`, package missing), `error` (class name, setup failed) |
| `tracing.export_failed` | WARNING | once per process: the collector refused the spans (a failure result) or could not be reached (an exception) | `error` (class name or `failure_result`) |
| `tracing.span_failed` | WARNING | once per cause: a span could not be created, annotated or ended (the run continues untraced for that span) | `error` (class name) |
| `log.format_failed` | WARNING | once per cause: a record could not be rendered in full (the line is written with its common fields only) | `error` (class name), `for_event` |
| `message` | any | every pre-existing free-text line that carries no failure (start-up paths and counts, key file, interrupted runs, store seeding count, experience-store version, …); feature 011 adds one constant, emitted once when a feature-004 store is stamped on first open: "Recorded the embedding model name and distance space on the experience store." (no fields) | `message` (constant text), and its values as fields: `path`, `count`, `stored_version`, `expected_version` |

## Example lines (illustrative values; shown pretty-printed, emitted on one line)

A judge request inside an adaptive run that belongs to an experiment:

```json
{"ts":"2026-11-13T10:15:02.418Z","level":"INFO","logger":"kestrel","event":"model.request",
 "run_id":42,"target_id":3,"mode":"adaptive","family":"direct_injection","turn":2,"experiment_id":7,"arm":"B",
 "kind":"judge","model":"google/gemini-3.8-flash","prompt":"judge@1","latency_ms":912,"ok":true,"status":200,
 "attempts":1,"prompt_tokens":640,"completion_tokens":58,"total_tokens":698,"cost_usd":0.001047,
 "verdict":"failed","hard_evidence":false}
```

An attacker request whose model has no configured price:

```json
{"ts":"2026-11-13T10:15:01.201Z","level":"INFO","logger":"kestrel","event":"model.request",
 "run_id":42,"target_id":3,"mode":"adaptive","family":"direct_injection","turn":2,
 "kind":"attacker","model":"deepseek/deepseek-v4.1-flash","prompt":"attacker:direct_injection@1",
 "latency_ms":1840,"ok":true,"status":200,"attempts":1,"prompt_tokens":812,"completion_tokens":96,
 "total_tokens":908,"cost_usd":null,"cost_note":"unavailable (no configured price for deepseek/deepseek-v4.1-flash)",
 "message_chars":214}
```

The turn those two requests belong to:

```json
{"ts":"2026-11-13T10:15:03.004Z","level":"INFO","logger":"kestrel","event":"turn",
 "run_id":42,"target_id":3,"mode":"adaptive","family":"direct_injection","turn":2,"experiment_id":7,"arm":"B",
 "source":"attacker:direct_injection@1","duration_ms":3410,"prompt_tokens":1452,"completion_tokens":154,
 "total_tokens":1606,"cost_usd":null,"cost_note":"unavailable (no configured price for deepseek/deepseek-v4.1-flash)",
 "attacker_model":"deepseek/deepseek-v4.1-flash","attacker_prompt":"attacker:direct_injection@1",
 "judge_model":"google/gemini-3.8-flash","judge_prompt":"judge@1","message_chars":214,"reply_chars":388,
 "reply_truncated":false,"canary_hit":false,"hard_evidence":false,"judged":true,"verdict":"failed"}
```

The same judge request in the text format (same fields, one line):

```text
2026-11-13T10:15:02.418Z INFO model.request run_id=42 target_id=3 mode=adaptive family=direct_injection turn=2 experiment_id=7 arm=B kind=judge model=google/gemini-3.8-flash prompt=judge@1 latency_ms=912 ok=true status=200 attempts=1 prompt_tokens=640 completion_tokens=58 total_tokens=698 cost_usd=0.001047 verdict=failed hard_evidence=false
```

## Ordering guarantees inside a run's scope

`run.start` first; per turn: (`memory.retrieval`)? → (`model.request` kind=attacker)? → `target.request` →
(`model.request` kind=judge)? → `turn`; then `memory.writeback` (when a write-back was attempted); then `run.end`
last. A single-turn run has no attacker request and no retrieval line. The kept log preserves this order through
`seq`. A record emitted for the run after its scope closed — the recommender's `model.request` at report time —
appears on the stream with the run id but is never kept (FR-010).

Feature 012 (regression replay): inside a replay's own scope the shape is the same with two lines always absent —
no `memory.retrieval` line ever (a replay never calls the experience store) and no `model.request` kind=attacker
line ever (a replay sends only the source's own recorded messages) — and `memory.writeback` is never emitted
either (a replay never attempts one; its `run.end` carries `memory_written: null`, the same value any run that
skipped a write-back already renders). `replay.batch.start`/`replay.batch.end` sit outside every per-replay scope —
there is no one `run_id` for a whole batch — the same way `connection.test` is already unscoped; a batch refused
before it starts (the cap, permission, terms, or an in-progress collision) emits neither line, just as a claim
`RunInProgress` refuses today never emits `run.start`.

## Deny-list (FR-009) — never in any field

Auth header values; API keys and tokens; the target URL in any form (no scheme/host/path either); the target
display name; attack message text; reply text; the judge's reason and progress text; provider or exception message
text. Allowed: identifiers, counts and lengths, category values, model slugs, prompt references, timings, token
counts, cost, pattern ids, step and status names, exception class names; feature 011 adds distances, the retrieval
settings in effect, embedding-model names and distance-space names (none of which is a secret) — never the
retrieval query, a pattern document or a message text.
