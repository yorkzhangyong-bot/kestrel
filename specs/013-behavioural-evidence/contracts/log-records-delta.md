# Contract delta: the 010 log stream, for behavioural evidence (013)

Rows to merge into `specs/010-structured-logging/contracts/log-records.md`'s event catalogue, verbatim, when this
feature's implementation PR lands (carrying the `spec-change:` note the traceability gate requires, FR-047). No
existing row changes meaning; three existing rows gain fields, one new per-turn event and three new standalone
events are added, and every new field joins `events.CATALOGUE`.

Every field below is a count, a status, a kind, a step, a turn number or a method. **No** field carries a token or
part, a URL, a correlation id, an auth value, a tool argument value, a state key or value, an evidence detail,
reply text or attack text (FR-048, the existing 010 deny-list). The evidence **kinds** are enum values (the seven
of FR-004), not detail.

## Existing rows, fields added

| `event` | New field(s) | Present |
|---------|--------------|---------|
| `run.start` | `side_channel` (`not_configured`/`configured`), `callback_listener` (`on`/`off` — whether the listener is enabled at all, which `callback_planted` alone cannot distinguish from "this family carries no callback task"), `override_planted` (bool), `callback_planted` (bool) | omitted when the emitter does not pass them (the 010 convention); the real run starters always pass all four, so every run's own `run.start` carries them |
| `turn` | `evidence_kinds` (list of the kinds found on the turn, detection order; `[]` when none), `evidence_count` (int) | always. **`hard_evidence` on this row is redefined**: it now means "this turn produced at least one evidence item of any kind", not "a canary matched" (`canary_hit` keeps that narrower meaning) |
| `run.end` | `evidence_kinds` (distinct kinds across the run, detection order; `[]` when none), `evidence_count` (int), `side_channel_status` (`not_configured`/`checked`/`unavailable`) | always |

`run.start`'s existing fields are unchanged. The four new ones follow the **one** convention the 010 contract
already states — a field is omitted when it does not apply, never emitted as `null` — and are passed by the real
run starters only, through the existing `_present(...)` path. `tests/unit/test_events.py`'s exact-field assertion
on a bare `run.start` (emitted with none of them) therefore stays green: the fields are added to the
`run_started(...)` helper's own `_present` dict keyed on real arguments, exactly as `source_run_id` was for 012.
The four `run.start` fields follow the omit-when-absent rule and have no "always present" exception; by contrast,
the `turn` and `run.end` fields listed in the table above are always present on their rows.

## New per-turn event

| `event` | Level | Emitted | Fields (beyond the common + scope ones) |
|---------|-------|---------|------------------------------------------|
| `evidence.check` | INFO | once per turn, after the deterministic checks run and before `turn` | `checks` (the checks run this turn, in order: a sublist of `canary`, `instruction_override`, `unsafe_executable_output`, `tool_calls`, `callback`, `state`), `evidence_kinds` (kinds found, detection order; `[]` when none), `evidence_count` (int), `side_channel_status` (`not_configured`/`checked`/`unavailable`), `callback_wait_ms` (the bounded wait actually spent; omitted when no callback task was planted), `state_changed_keys` (int: how many top-level protected-state keys differed — the **count only**, never a key name or value, FR-033; omitted when the state check did not run) |

Ordering inside a run's scope becomes, per turn: `(memory.retrieval)? → (model.request kind=attacker)? →
target.request → evidence.check → (model.request kind=judge)? → turn`. A turn that found deterministic evidence has
no `model.request kind=judge` line, exactly as a canary-decided turn has none today.

## New standalone events

| `event` | Level | Emitted | Fields |
|---------|-------|---------|--------|
| `evidence.side_channel_unavailable` | WARNING | a side-channel request failed during a run (inside the run's scope) | `step` (one of the six `side_channel_*` steps, including `side_channel_header_unreadable`) |
| `evidence.override_disarmed` | WARNING | the joined override form appeared (after normalisation) in a message Kestrel sent — the opening message, an attacker-generated one, or one a replay re-sent — so the token was disarmed (inside the run's scope) | `turn` (already a scope field) |
| `callback.hit` | INFO | the listener accepted a hit for a run in progress (bound to that run with `events.bind_run_reference`, like the recommender line; stream only, never kept) | `method` (`GET`/`POST`/`PUT`/`HEAD`) |
| `callback.ignored` | WARNING | the listener declined to store a request: an unknown token or a finished run (unscoped; once per `reason_kind` per process), or a run in progress already at its hit cap (bound to that run with `bind_run_reference`; once per run per process, FR-072) | `reason_kind` (`unknown_token`/`run_not_in_progress`/`hit_cap_reached`) |

The field is `reason_kind`, not `reason`: `tests/unit/test_events.py` enforces a deny-list over every catalogued
field name, and `reason` is on it because a reason is free text everywhere else in Kestrel (a judge's reason, a
run's reason). `experience.unavailable` set the same precedent in feature 011. The value is an enum either way.

`callback.hit` carries the run's scope fields through `bind_run_reference` and the `method`; it carries no token,
no URL and no caller address. `callback.ignored` carries only `reason_kind`: it is unscoped for `unknown_token` and
`run_not_in_progress` (there is no run to name) and bound to the run for `hit_cap_reached` (the capped request
still answers `204`, so this line is its only trace). With no base URL configured the route is not mounted and
neither line is ever emitted (FR-073).

## New catalogue entries (field names added to `events.CATALOGUE`)

- `run.start`: `side_channel`, `callback_listener`, `override_planted`, `callback_planted`
- `turn`: `evidence_kinds`, `evidence_count`
- `run.end`: `evidence_kinds`, `evidence_count`, `side_channel_status`
- `evidence.check`: `checks`, `evidence_kinds`, `evidence_count`, `side_channel_status`, `callback_wait_ms`,
  `state_changed_keys`
- `evidence.side_channel_unavailable`: `step`
- `evidence.override_disarmed`: `()` (turn is a scope field)
- `callback.hit`: `method`
- `callback.ignored`: `reason_kind`

Each entry joins `events.CATALOGUE` with the code that emits its line: part 1 adds the `run.start`, `turn` and
`run.end` fields, `evidence.check` and `evidence.override_disarmed`; the other three arrive with part 2's
side channel and listener.

## Deny-list check (unchanged)

The 013 redaction tests assert that across the offline suite's whole stream, 0 lines carry an override token or
part, a callback URL, a correlation id, an auth value, a tool argument value, a state key or value, an evidence
detail, reply text or attack text — counted with the run's real per-run marker strings (SC-007). Model and side
channel are referred to only by the enum statuses above.
