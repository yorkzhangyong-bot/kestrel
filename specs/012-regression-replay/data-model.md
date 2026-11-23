# Phase 1 Data Model: Regression Replay (012)

## Schema v10 (`src/kestrel/store.py`)

`SCHEMA_VERSION = "10"`. `_migrate`'s version-acceptance guard extends to `current not in ("1".."9")` (adds `"9"`).
`RUNS_COLUMNS_SQL` (shared by the fresh-database `CREATE TABLE runs` and every rebuild) changes in exactly three
places:

```sql
    mode TEXT NOT NULL DEFAULT 'single_turn' CHECK (mode IN ('single_turn', 'adaptive', 'replay')),
    ...
    -- Added in schema version 10 (feature 012): a replay links to the run it re-tests and records one outcome.
    source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,  -- null unless mode = 'replay'
    replay_outcome TEXT CHECK (replay_outcome IS NULL OR
        replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive'))  -- null unless mode = 'replay'
```

`RUNS_INDEXES_SQL` is unchanged (both existing indexes already cover a replay row correctly: `idx_runs_target`
orders by `target_id, started_at`, which a replay participates in like any run; `uq_runs_active` still allows only
one `in_progress` row per target regardless of mode).

### `_rebuild_runs_for_replay(db)` (new, beside `_rebuild_runs_with_autoincrement`)

Textually parallel to the v9 rebuild, with its own no-op guard:

```python
@staticmethod
def _rebuild_runs_for_replay(db: sqlite3.Connection) -> None:
    columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
    if "source_run_id" in columns:
        return   # already rebuilt (or a fresh database: SCHEMA already created the v10 shape)
    existing = ", ".join(r["name"] for r in db.execute("PRAGMA table_info(runs)"))
    # A plain rename loses `runs`' sqlite_sequence row (DROP TABLE deletes it),
    # so an id freed by a deletion *after* v9 but *before* this rebuild would be reissued — undoing v9's own
    # "never reissued" guarantee the moment it is needed (`experience/store.py::write_memory` still keys a memory
    # record `f"memory:run:{run_id}"`, so a reissued id can collide with a surviving, unrelated memory record).
    # Read the old table's own next-id watermark before dropping it, and restore the higher of that watermark and
    # the highest id actually copied, in the SAME transaction as the rename (never a separate commit in between).
    old_seq_row = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'runs'").fetchone()
    old_seq = old_seq_row["seq"] if old_seq_row is not None else 0
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("DROP TABLE IF EXISTS runs_new")
    db.execute(f"CREATE TABLE runs_new ({RUNS_COLUMNS_SQL})")
    db.execute(f"INSERT INTO runs_new ({existing}) SELECT {existing} FROM runs")
    db.execute("DROP TABLE runs")
    db.execute("ALTER TABLE runs_new RENAME TO runs")
    db.execute("CREATE INDEX IF NOT EXISTS idx_runs_target ON runs (target_id, started_at DESC)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active ON runs (target_id) WHERE status = 'in_progress'")
    max_copied = db.execute("SELECT COALESCE(MAX(id), 0) AS m FROM runs").fetchone()["m"]
    db.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'runs'", (max(old_seq, max_copied),))
    violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"schema v10 migration would leave dangling foreign keys: {[tuple(v) for v in violations]}")
    db.commit()
    db.execute("PRAGMA foreign_keys = ON")
```

Called from `_migrate` immediately after `_rebuild_runs_with_autoincrement(db)`, before the `meta.schema_version`
write. Every column copied by name from the *old* table's own `PRAGMA table_info`, exactly as v9 did — a database
already at v9 has no `source_run_id`/`replay_outcome` columns to copy, so every existing row's new columns land at
their implicit default, `NULL`, which is correct (no pre-existing run is a replay). `run_turns`,
`report_recommendations`, `run_log` (all `ON DELETE CASCADE` against `runs.id`) and `experiment_runs` (`ON DELETE
SET NULL`) are untouched by this rebuild and survive it with their links intact — the same four tables v9's own
rebuild already had to leave standing, and by the same mechanism (foreign keys off before the implicit `DELETE`
that renaming away `runs`'s old identity would otherwise cascade).

### Verified empirically (research D4), by `tests/unit/test_store_migration_v10.py`

1. `PRAGMA foreign_key_check` is empty immediately after `_migrate` runs against a hand-built schema-9 database.
2. A row inserted with `mode='replay', source_run_id=<existing run id>` round-trips through `get_run`.
3. Deleting the shared target removes the source row and the replay row together, in the one cascading `DELETE`,
   with `PRAGMA foreign_key_check` still empty afterward.
4. `INSERT INTO runs (..., mode) VALUES (..., 'bogus')` still raises `sqlite3.IntegrityError` (the widened CHECK
   accepts exactly the three named values, nothing else).
5. A `run_turns`, a `report_recommendations` and a `run_log` row attached to a surviving run are still readable
   after the rebuild (`CASCADE` did not fire for a row whose parent was *renamed*, not deleted-and-not-replaced);
   an `experiment_runs` row's `run_id` still points at its run (`SET NULL` likewise did not fire).
6. Both `runs` indexes (`idx_runs_target`, `uq_runs_active`) exist and are queryable after the rebuild.
7. **The sqlite_sequence fix**: seed a database, delete its highest-numbered runs so `sqlite_sequence.seq` for
   `runs` sits above the highest surviving id (for example, a sequence of 5 with only ids up to 3 surviving), run
   `_migrate`, insert one more run, and assert its new id is **above the pre-migration sequence**, never a
   reissued, freed one.

## `Run` (extended, `store.py`)

Two new fields, both defaulting to `None` (every pre-012 construction of `Run` stays valid):

```python
source_run_id: int | None = None       # v10: the run this one replays, only when mode == "replay"
replay_outcome: str | None = None      # v10: "fixed" | "still_vulnerable" | "inconclusive", only when mode == "replay"
```

`TargetStore._run(row)` reads both straight off the row (`row["source_run_id"]`, `row["replay_outcome"]`), same
pattern as every other column.

## `TargetStore` additions

- `claim_run(..., source_run_id: int | None = None)` — one more optional keyword on the existing method (not a new
  method): the `INSERT` gains the `source_run_id` column. Called by the replay engine with `mode="replay",
  source_run_id=source.id, prompt_id=source.prompt_id, prompt_title=source.prompt_title,
  prompt_text=source.prompt_text, family=source.family, owasp_category=source.owasp_category,
  attacker_source=source.attacker_source, attacker_model=None, use_prior_experience=False` plus the adaptive-only
  budgets when `source.mode == "adaptive"`.
- `finish_run(..., replay_outcome: str | None = None)` — one more optional keyword on the existing method: the
  `UPDATE` gains the `replay_outcome` column. Every existing caller (which never passes it) is unaffected; `null`
  is written for a non-replay run exactly as it already is implicitly.
- `list_replayable_runs(target_id: int) -> list[Run]` (new method) — raises `TargetNotFound` like every other
  per-target method; otherwise:

  ```sql
  SELECT * FROM runs
  WHERE target_id = ? AND status = 'finished' AND verdict = 'succeeded' AND mode != 'replay'
    AND (mode = 'single_turn' OR turns_used >= 1)
  ORDER BY started_at ASC, id ASC
  ```

  Used by the batch endpoint; a single-replay request instead loads the one run via `get_run` and runs
  `replay.check_replayable` on it (D6), so the two eligibility checks are the same predicate expressed twice —
  once as Python (clear per-run refusal reasons), once as SQL (an ordered set) — never allowed to diverge because
  both read exactly `status`, `verdict`, `mode` and (for adaptive) `turns_used`.

## `src/kestrel/replay.py` (new module)

```python
class NotReplayable(Exception):
    """`run` cannot be replayed; `.reason` is one of "in_progress" | "not_succeeded" | "no_message"."""
    def __init__(self, reason: str) -> None: ...
    reason: str

class ReplayOfReplay(Exception):
    """`run` is itself a replay; `.source_run_id` names the original to replay instead."""
    def __init__(self, source_run_id: int) -> None: ...
    source_run_id: int
```

```python
def check_replayable(run: Run) -> None:
    """Raise ReplayOfReplay or NotReplayable; return normally when `run` is eligible (FR-004, FR-005)."""
```

Truth table (`run.mode`, `run.status`, `run.verdict` → result):

| mode | status | verdict | result |
|------|--------|---------|--------|
| `replay` | any | any | `ReplayOfReplay(run.source_run_id)` |
| `single_turn`/`adaptive` | `in_progress` | — | `NotReplayable("in_progress")` |
| `single_turn`/`adaptive` | `finished` | `failed`/`unclear`/`None` | `NotReplayable("not_succeeded")` |
| `adaptive` | `finished` | `succeeded` | `NotReplayable("no_message")` only if `turns_used` is `None`/`0` (defensive; not reachable through normal operation — a succeeded adaptive run always recorded at least turn 1) |
| `single_turn`/`adaptive` | `finished` | `succeeded` | eligible |

`run.verdict is None` with `run.failure_step` set (a send that never completed) falls into the `failed`/`unclear`/
`None` row above like any other non-`"succeeded"` verdict — `"not_succeeded"` covers all three shapes with one
reason (FR-004's exact string does not distinguish them; `run.reason`/`run.failure_message` already explain the
send failure itself elsewhere on the run's own page).

### `compute_replay_status` — the display fields, from the run *and* its target

`check_replayable(run)` alone cannot tell the UI everything FR-040/FR-042 need displayed: it never looks past the
run's own columns, so it has no way to know the run's *target* currently lacks permission, carries outdated
terms, or currently has a different run in progress — all three of which must also block a replay (FR-006);
discovering them only by clicking is fine for "Run attack" but not what FR-042 asks for here. A second function
wraps it:

```python
REPLAY_BLOCKED_REASONS = {
    "in_progress": "A run still in progress can't be replayed.",
    "not_succeeded": "Only a succeeded run can be replayed.",
    "no_message": "This run has no recorded message to resend.",
    "permission_missing": "Tick the permission box and save the target before attacking it.",   # verbatim,
    "terms_outdated": "The terms of service have changed; read them and tick the box again.",    # same as a
                                                                                                    # normal run
    "run_in_progress": "A run against this target is already in progress.",   # same wording POST /api/runs
                                                                                 # already uses, api/main.py:354
}
REPLAY_ADVISORY_OVER_TURN_LIMIT = (
    "This source recorded more turns than the current adaptive limit; the replay can end at best "
    "still vulnerable or inconclusive.")

@dataclass(frozen=True)
class ReplayStatus:
    replayable: bool
    blocked_reason: str | None    # one of REPLAY_BLOCKED_REASONS' values, or the ReplayOfReplay message; None iff replayable
    advisory: str | None          # REPLAY_ADVISORY_OVER_TURN_LIMIT or None; independent of blocked_reason

def compute_replay_status(run: Run, target: Target, terms_version: str, adaptive_max_turns: int,
                          target_has_other_run_in_progress: bool) -> ReplayStatus:
    """FR-004 to FR-006, FR-040, FR-042. `terms_version` is the currently loaded terms (load_terms().version,
    api/main.py); `adaptive_max_turns` is settings.adaptive_max_turns; `target_has_other_run_in_progress` is
    whether a run *other than this one* is currently in progress on `run`'s own target. Checked in a fixed order
    — replay-of-a-replay, then `check_replayable`'s own three reasons, then permission, then terms, then another
    run in progress — the same order the single-replay endpoint's own 409 table checks them in, so the two can
    never disagree. Never raises."""
    try:
        check_replayable(run)
    except ReplayOfReplay as error:
        return ReplayStatus(False, f"This run is itself a replay of run #{error.source_run_id}.", None)
    except NotReplayable as error:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS[error.reason], None)
    if not target.permission_confirmed_at:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["permission_missing"], None)
    if target.terms_version != terms_version:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["terms_outdated"], None)
    if target_has_other_run_in_progress:
        return ReplayStatus(False, REPLAY_BLOCKED_REASONS["run_in_progress"], None)
    advisory = None
    if run.mode == "adaptive" and (run.turns_used or 0) > adaptive_max_turns:
        advisory = REPLAY_ADVISORY_OVER_TURN_LIMIT
    return ReplayStatus(True, None, advisory)
```

Called once per run wherever `RunSummary`/`RunDetail` is built (`api/main.py::run_summary`), never by the UI. The
`POST /api/runs/{id}/replay` endpoint's own refusal reuses `compute_replay_status` (or `check_replayable` plus the
same three target checks) so its error message is never allowed to read differently from what the run's own
detail already showed before the click. `target_has_other_run_in_progress` is deliberately **not** threaded into
`store.list_replayable_runs` or the batch's own eligibility query (`TargetStore` additions, above): it is
transient and target-wide, not a property of the source run itself, and the batch already enforces its own single
run-in-progress precondition once, before its first entry (FR-029) — folding it into the batch's per-source
eligibility query would let the batch's *own* in-flight replay make every other planned source in the same batch
look ineligible to itself.

### `finding` — the headline-card flag

```python
def is_finding(run: Run) -> bool:
    """True for a succeeded, non-replay run (FR-027). No mode check lives in the UI: ui/app.py::render_metrics
    drives its three headline cards from this flag together with the run's own `hard_evidence`, never a mode
    check of its own, since one boolean alone cannot produce two cards: Confirmed = runs where `finding` and
    `hard_evidence` are both true; Suspected = runs where `finding` is true and `hard_evidence` is false; Runs =
    every run, finding or not. api/main.py::target_report's own report-level exclusion (research D9) already
    computes the same `finding` condition inline."""
    return run.verdict == "succeeded" and run.mode != "replay"
```

`RunSummary.finding: bool` carries this, filled in `run_summary(...)` beside `replayable`/`replay_blocked_reason`/
`replay_advisory`.

```python
def compute_outcome(turn_results: list[str | None], recorded_total: int, winning_turn: int | None) -> str:
    """"fixed" | "still_vulnerable" | "inconclusive" (research D5; FR-012 to FR-016). `turn_results` has exactly
    one entry per turn actually attempted, in order — never an aggregate run-level verdict (see the "why not
    `run.verdict`" note below): each entry is "succeeded", "failed", or None (an unclear judge verdict, a judge
    error, no judge configured and no canary, or a send failure that ended the attempt before any judge call). A
    turn never reached because the replay stopped earlier has no entry at all, so `len(turn_results) <
    recorded_total` alone is enough to say not every message was sent. `winning_turn` is the source's own
    winning turn — the turn its original run succeeded at (`runs.succeeded_turn`, 1-based) — passed through only
    for a `recorded_total` of **more than one** message, where "fixed" additionally requires
    `turn_results[winning_turn - 1] == "failed"`: the source's later recorded messages were written to continue
    a conversation the *original* target produced, so once today's target's replies diverge, those later
    messages may no longer fit the conversation they were written for, and an all-"failed" judge run should still
    confirm the one turn whose failure actually matters. `winning_turn is None` for a multi-message source is the
    defensive case of a succeeded source with no recorded winning turn (not reachable through normal operation).
    For `recorded_total == 1` the check does not apply at all and `winning_turn` is ignored outright — a
    single-turn source's own `succeeded_turn` is always `None` (`store.py`'s schema: "single-turn runs leave
    these at their defaults/null"; `runs.py::execute_run` never sets it), so gating on `recorded_total > 1`,
    not on `winning_turn is None`, is what keeps a single-message source's outcome exactly as it was before this
    addition (FR-014)."""
    if any(result == "succeeded" for result in turn_results):
        return "still_vulnerable"
    if not (len(turn_results) == recorded_total and all(result == "failed" for result in turn_results)):
        return "inconclusive"
    if recorded_total > 1 and (winning_turn is None or not (1 <= winning_turn <= len(turn_results))
                                or turn_results[winning_turn - 1] != "failed"):
        return "inconclusive"
    return "fixed"
```

**Why not a single aggregate `verdict`:** `attack/graph.py::decide_node`'s existing cap-stop line
(`"verdict": state["last_verdict"] or "unclear"`) takes whatever `last_verdict` the *most recent* judge call set
— and `judge_node` on a `JudgeError` or a "no judge configured" turn leaves `outcome` unset and the run
**continues**, so an early turn's `unclear` can be silently overwritten by a later turn's `failed`. A replay
whose turn 1 is `unclear` (a judge error) and whose turns 2+ are all `failed` would, read as one final `verdict`,
look like `"failed"` with every message sent — scored **fixed** — when turn 1 was never actually resolved and the
honest answer is **inconclusive**. `compute_outcome` therefore never reads `run.verdict`/`run.turns_used` after
the fact; it is fed the *per-turn* results, captured live as each turn is decided (see "Capturing `turn_results`
live" below), so one bad turn can never be hidden by a later good one.

Truth table:

| any `"succeeded"`? | `len == recorded_total`? | every entry `"failed"`? | `recorded_total > 1`? | winning turn itself `"failed"`? | outcome |
|---|---|---|---|---|---|
| yes | (irrelevant) | (irrelevant) | (irrelevant) | (irrelevant) | `still_vulnerable` |
| no | yes | yes | **no** (`recorded_total == 1`) | not checked, `winning_turn` ignored | `fixed` |
| no | yes | yes | yes | yes | `fixed` |
| no | yes | yes | yes | no, or `winning_turn is None` | `inconclusive` |
| no | yes | no (at least one `None`/`"unclear"` entry, anywhere in the list — including turn 1) | — | — | `inconclusive` |
| no | no (a send failure, or the current turn/token/time limit cut it short) | — | — | — | `inconclusive` |

`winning_turn` itself is always `source.succeeded_turn`, passed straight through on both the single-turn and
adaptive branches — never recomputed; the single-turn branch's own `None` value is simply never inspected,
because `compute_outcome` gates the whole check on `recorded_total > 1` first.

**Capturing `turn_results` live, for an adaptive replay** (`run_replay_adaptive`, research D14): the replay's own
`record_node` closure — which already computes `judged = state.get("last_judged_turn") == turn` and
`canary = bool(state.get("pending_canary", False))` for the existing `turn` log line (`events.turn_ended(...,
judged=judged, verdict=state.get("last_verdict") if judged else None, ...)`) — appends exactly the same signal to
a plain list held in `run_replay_adaptive`'s own local scope:
`turn_results.append("succeeded" if canary else (state.get("last_verdict") if judged else None))`. This needs no
new graph state and no change to the live `run_adaptive`'s own `record_node` (which has no such list to append
to): it is one line in the **replay's own, separately-defined** `record_node` (research D14). After
`compiled.ainvoke(...)` returns, `turn_results` already holds one entry per turn the replay actually sent — no
re-reading of (possibly stale, research D7) stored `run_turns` rows is needed to compute the outcome, though D7's
own stale-terminal-turn correction is still needed separately, for `build_comparison`'s *display* of the finished
pair (`build_comparison` runs later, from storage only, with no access to this transient list).
For the single-turn branch (`replay.py::execute_replay`), `turn_results` is built the same way inline, without a
graph: `[]` if the send failed, else `["succeeded"]` on a canary hit, else `["succeeded"/"failed"/"unclear"]` from
the judge call (or `[None]` if no judge is configured).

## Interrupted and crashed replays always get an outcome

A replay row must never finish `status = 'finished'` with `replay_outcome IS NULL` — "no answer" is itself
**inconclusive** (FR-012, FR-015), never a silent gap. Three paths can leave a replay's row open or raise before
`compute_outcome` runs, and all three now set `replay_outcome = 'inconclusive'` explicitly:

1. **The start-up sweep** (`store.py::close_interrupted_runs`, called from `api/main.py`'s start-up, line ~104):
   its `UPDATE` gains one more assignment, conditional on mode, so a non-replay row is untouched:
   ```sql
   UPDATE runs SET status = 'finished', verdict = 'unclear', stopping_condition = 'interrupted',
     reason = 'Kestrel stopped while this run was in progress, so it was interrupted.',
     replay_outcome = CASE WHEN mode = 'replay' THEN 'inconclusive' ELSE replay_outcome END,
     finished_at = ? WHERE status = 'in_progress'
   ```
   (`replay_outcome` is already `NULL` on every non-replay row, so the `ELSE` branch is a no-op for them — written
   explicitly so the rule is visible in the SQL, not assumed.)
2. **`execute_replay`'s single-turn branch**, on an unexpected exception: `except Exception as error:
   store.finish_run(run_id, verdict="unclear", reason="The run failed unexpectedly.",
   replay_outcome="inconclusive"); raise ReplayFailed(run_id) from error` — mirroring `runs.py::execute_run`'s
   own `except Exception` (`runs.py:126-129`) for closing the row, but raising the named `ReplayFailed` (below)
   instead of the original exception unchanged. Reachable only from replay code, so no conditional is needed — it
   is always a replay here.
3. **`run_replay_adaptive`'s own exception handler** — a genuine *addition* to the graph function, since the
   live `run_adaptive` has **no** such handler today (an uncaught exception from `compiled.ainvoke(...)` there
   propagates all the way up, relying solely on the next start-up's sweep, path 1). `run_replay_adaptive` wraps
   its `await compiled.ainvoke(...)` in `try/except Exception as error: store.finish_run(run_id,
   verdict="unclear", reason="The run failed unexpectedly.", replay_outcome="inconclusive");
   events.run_finished(...); raise ReplayFailed(run_id) from error` — closing the row immediately rather than
   leaving it to the sweep, exactly as `execute_run` already does for a single-turn run, and raising the same
   named exception path 2 does. `run_adaptive` itself is **not** given this handler (FR-049: nothing about a
   normal run changes); the asymmetry is deliberate and is the reason this is listed as its own fix rather than
   folded into the "shared helpers" refactor below (research D14), since it is NOT shared with `run_adaptive`.

Verified by `tests/unit/test_store_migration_v10.py` (path 1, by hand-crafting an `in_progress` replay row and
running the sweep) and `tests/integration/test_replay_run.py` (paths 2 and 3, by injecting a fault into the sender
and into a monkeypatched graph node respectively).

```python
@dataclass(frozen=True)
class TurnComparison:
    position: int
    sent: bool                      # False only for a recorded message the replay never reached (FR-017)
    source_verdict: str | None      # this turn's own verdict on the source run ("succeeded" | "failed" |
                                     #   "unclear" | None for "not judged" — never a stale value, research D7)
    replay_verdict: str | None      # the same, for the replay; None when `sent` is False

@dataclass(frozen=True)
class Comparison:
    source_run_id: int
    replay_run_id: int
    outcome: str                                  # "fixed" | "still_vulnerable" | "inconclusive"
    source_verdict: str | None; source_hard_evidence: bool
    source_judge_model: str | None; source_judge_prompt: str | None    # f"{id}@{version}" or None
    replay_verdict: str | None; replay_hard_evidence: bool
    replay_judge_model: str | None; replay_judge_prompt: str | None
    turns: tuple[TurnComparison, ...]              # exactly one synthetic entry for a single-turn pair
    multi_turn_caption: str | None                 # the exact FR-041 caption text when len(turns) > 1, else None

def build_comparison(source: Run, source_turns: list[Turn], replay: Run, replay_turns: list[Turn]) -> Comparison:
    """Pure; no I/O (research D8 — called fresh on every GET of a replay run's detail)."""
```

`build_comparison`'s per-turn walk (research D7): for `source.mode == "adaptive"`, iterate `source_turns` by
`position`; a position with no matching `replay_turns` entry is `sent=False, replay_verdict=None`. For every turn
**except the last one either run actually sent**, `source_verdict`/`replay_verdict` is that run's own
`run_turns.judge_verdict` (accurate by the code-facts induction). For the **last** turn a run sent, the verdict is
derived from that run's own top-level fields instead: `"succeeded"` when `hard_evidence and succeeded_turn ==
position`; the judge's own `judge_verdict` when that turn was genuinely judged (`judge_used and (succeeded_turn is
None or succeeded_turn != position)` and the judge did not error); `None` ("not judged") when the turn ended by a
send failure (`failure_step` set) before any judge call. For `source.mode == "single_turn"`, there is exactly one
`TurnComparison(position=1, sent=True, source_verdict=<source.verdict>, replay_verdict=<replay.verdict>)` (a
single-turn replay's one message always either sends or the whole replay is `inconclusive` with no partial state
to show). `multi_turn_caption` is exactly the FR-041 string (**"A multi-turn replay re-tests the recorded
messages, not an adaptive attack."**) when `len(source_turns) > 1`, else `None` — a static function of the
source's own recorded message count, not of anything about the replay's own result.

```python
@dataclass(frozen=True)
class BatchEntry:
    source_run_id: int
    replay_run_id: int
    family: str
    source_verdict: str | None
    source_hard_evidence: bool     # canary vs. judge opinion, per entry, independent of the replay's own (Principle II)
    replay_verdict: str | None
    replay_hard_evidence: bool
    outcome: str

@dataclass(frozen=True)
class BatchResult:
    target_id: int
    entries: tuple[BatchEntry, ...]
    counts: dict[str, int]   # {"fixed": n, "still_vulnerable": n, "inconclusive": n}; always sum(counts.values()) == len(entries)
    complete: bool           # False only when the batch stopped partway through (never a 409 for that); always
                             #   True for a cap refusal, which never starts
    stop_reason: str | None  # "run_in_progress" (a collision) | "replay_failed" (one entry's own unexpected
                             #   error); None when complete is True
    not_replayed_source_ids: tuple[int, ...]   # every planned source never reached; empty when complete is True
    failed_source_run_id: int | None = None   # spec-change (review item 5): the source whose replay crashed,
    # only when stop_reason == "replay_failed" - it has an entry of its own (store.get_run(error.run_id)) when
    # the failure came after its claim, or is the first of not_replayed_source_ids when it came before the
    # claim; None for every other stop_reason. A reader must never infer the crashed source from its position in
    # `entries` - a before-claim failure adds no entry for it at all, leaving the *previous*, cleanly judged
    # source as the list's last entry, which a naive "the last entry is always the crashed one" reading would
    # misattribute.
```

```python
async def execute_replay(store, *, source: Run, source_turns: list[Turn], resolved, mode, judge,
                         sender=run_test, transport=None, resolver=default_resolver,
                         adaptive_max_turns: int, adaptive_token_budget: int, adaptive_time_limit_s: int,
                         clock=time.monotonic) -> Run:
    """Dispatch on source.mode (research D1). Raises nothing eligibility-related — the caller runs
    check_replayable(source) first, before claiming anything (FR-004 to FR-006).

    **How a failed replay is reported, named explicitly:** Once `store.claim_run(...)` has succeeded (a row exists), any exception from sending or
    judging is handled the same way on both branches: the row is closed (`store.finish_run(run_id,
    verdict="unclear", reason="The run failed unexpectedly.", replay_outcome="inconclusive")`), the failure is
    logged the same way any other run's own unexpected failure already is (exc_type and stack only, never the
    message, FR-045), and `ReplayFailed(run_id)` is raised, chained from the original (`raise ReplayFailed(run_id)
    from error`) — `ReplayFailed` is a new exception (below) carrying the *closed* run's id, so a caller never
    has to re-derive which row it was. For `source.mode == "adaptive"`, this closing and raising happens inside
    `run_replay_adaptive` itself (T018 — it is the one with the turn-level state to close the row correctly);
    `execute_replay`'s own adaptive branch does nothing further, letting `ReplayFailed` propagate unchanged. For
    `source.mode == "single_turn"`, `execute_replay` has no inner function to delegate to, so it does the same
    closing-and-raising itself, inline, mirroring `run_replay_adaptive`'s shape instead of `runs.py::execute_run`'s
    bare `raise` (which this decision supersedes). The single-replay endpoint lets `ReplayFailed` surface like any
    other unhandled run failure (the row is already closed, the target is not left locked). A failure **before**
    `claim_run` succeeds — no row exists yet — propagates as whatever bare exception was raised, **never** wrapped
    in `ReplayFailed` (which names a run id that would not exist); `execute_batch_replay` (below) and the
    single-replay endpoint both treat that as an ordinary unhandled error, not a closed-row failure."""

class ReplayFailed(Exception):
    """`.run_id`: the replay run that `execute_replay` already closed
    (`verdict="unclear", replay_outcome="inconclusive"`) before raising this, chained from the original error
    (`raise ReplayFailed(run_id) from error`). Lets a caller — the batch loop below, or anything else — build a
    result from the now-closed row without re-deriving its id or guessing whether closing already happened."""
    def __init__(self, run_id: int) -> None:
        super().__init__(run_id)
        self.run_id = run_id

async def execute_batch_replay(store, *, target_id: int, cap: int, resolved_provider, judge, sender=run_test,
                               transport=None, resolver=default_resolver, adaptive_caps) -> BatchResult:
    """store.list_replayable_runs(target_id); refuse (BatchTooLarge) before sending anything if len() > cap;
    otherwise execute_replay for each, oldest first, one at a time (FR-028 to FR-033). Never raises for a single
    entry's own failure (research D17): a
    RunInProgress collision stops with stop_reason="run_in_progress" (that entry excluded — its claim never
    succeeded, so it produced no run); a `ReplayFailed` from execute_replay means that entry's own run is already
    closed inconclusive — build its BatchEntry from the now-closed row (`store.get_run(error.run_id)`), append it
    as the batch's last entry, and stop with stop_reason="replay_failed"; any **other** exception (one that
    escaped *before* `claim_run` ever succeeded, so there is no row to build an entry from) also stops the batch
    with stop_reason="replay_failed", but adds **no** entry — that source goes straight into
    not_replayed_source_ids like every other unreached one. Either way returns a BatchResult with complete=False
    and not_replayed_source_ids naming the rest — never an exception the caller has to handle as an error."""

class BatchTooLarge(Exception):
    """`.count`, `.cap`: more replayable runs than the configured maximum (FR-031)."""
```

## `attack/graph.py` addition (restructured: `judge_node` and `record_node` are closures defined *inside*
`run_adaptive` today, not separately callable module-level functions a sibling function could call without
either duplicating the closure's body or lifting it out. Research D14 resolves this.)

Four of the six nodes genuinely do not care whether the message they are sending was attacker-generated or
replayed — `send_node`, `evidence_node`, `judge_node`, `decide_node` — so their bodies are lifted out of
`run_adaptive` into module-level functions parameterised by whatever they used to close over, and **both**
`run_adaptive` and the new `run_replay_adaptive` define thin node closures that call them:

```python
async def _judge_turn(state: _State, *, judge, judge_prompt: str | None, remaining: Callable[[], float],
                      requests: list[int]) -> _State:
    """judge_node's existing body, unchanged in substance (FR-008): identical conversation shape, identical
    token/event accounting. `requests` is a one-item mutable counter (a closure can mutate a list in place but
    cannot rebind an int by reference) — run_adaptive's `judge_requests` becomes requests[0] += 1 here."""
    # ... exactly today's judge_node body ...

async def _send_turn(state: _State, *, resolved, mode, sender, transport, resolver, remaining, secrets) -> _State:
    """send_node's existing body, unchanged in substance (stated explicitly so the lift cannot silently drop it):
    still masks the reply with mask_values(outcome.reply_text or "", secrets) before returning it (today's
    graph.py:138) — a replay's own stored reply is masked exactly as a live run's is, never the attacker message
    (which arrives already masked, FR-001). `secrets` is a parameter, not something the lifted function closes
    over — `run_adaptive` and `run_replay_adaptive` each pass their own target's secret values, the same list
    `send_node` reads from the enclosing scope today; the lift carries it through explicitly rather than letting
    it drop."""
def _check_evidence(state: _State, canaries: list[str]) -> _State: ...
def _decide_next(state: _State, *, max_turns, token_budget, remaining) -> _State: ...
```

`run_adaptive`'s own `judge_node`/`send_node`/`evidence_node`/`decide_node` become one-line wrappers
(`async def judge_node(state): return await _judge_turn(state, judge=judge, judge_prompt=judge_prompt,
remaining=remaining, requests=judge_requests_box)`) — behaviour-preserving by construction, proven by
`run_adaptive`'s own existing test suite passing **unmodified** after the extraction (a regression gate this
feature's tasks add, not merely assume; FR-049).

`attacker_node` and `record_node` are **not** shared — their bodies genuinely differ (a model call versus a list
lookup; run-wide-constant provenance versus per-turn copied provenance, and `attacker_generated` is `turn >= 2`
for a live run but always `False` for a replay) — so `run_replay_adaptive` defines its **own** two closures,
written beside `run_adaptive`'s, rather than parameterising them:

```python
async def run_replay_adaptive(store, *, target_id: int, source: Run, source_turns: list[Turn], canaries: list[str],
                              resolved, judge, sender=run_test, mode="local", transport=None,
                              resolver=default_resolver, max_turns: int, token_budget: int, time_limit_s: float,
                              clock=time.monotonic) -> Run:
    """run_adaptive's six-node shape, minus hint_provider, sharing _judge_turn/_send_turn/_check_evidence/
    _decide_next (above) and replacing attacker_node/record_node:

    Both nodes compute the current, 1-based turn number the same way the live attacker_node already does —
    `turn = state["turns_used"] + 1` — and index source_turns at `turn - 1` (0-based) **consistently** for both
    the message and the provenance lookup: both must read the *same* turn's data, so both use
    `source_turns[turn - 1]`.

    attacker_node: turn = state["turns_used"] + 1; events.turn_started(turn) and {"pending_canary": False} in the
        returned state, exactly as today's attacker_node does on turn 1 (graph.py:110-112 — every turn of a
        replay is "turn 1" in this sense, no model call ever runs) — then {"pending_message":
        source_turns[turn - 1].attacker_message} (already masked, resent verbatim, FR-001) when turn <=
        len(source_turns), else sets outcome (stopping_condition="turn_cap") — the same decide_node path a live
        run's turn-cap stop already uses (research D2).

    record_node: turn = state["turns_used"] + 1; as today's record_node, but attacker_prompt_id/version come
        from source_turns[turn - 1] (copied, never freshly computed — no attacker ran) — and **only** those two;
        judge_prompt_id/version are **not** copied from the source — they are the replay's own current judge
        call's reference, exactly as _judge_turn already produces for a live run (FR-022, FR-009) — and
        attacker_generated=False unconditionally (every turn, not just turn 1 — no events.turn_ended signature
        change, research "Events" code-fact); additionally appends this turn's own result to a local
        `turn_results` list (see compute_outcome above) before returning.

    After compiled.ainvoke(...) (wrapped in the try/except of the "Interrupted and crashed replays" section
    above, which raises ReplayFailed on an unexpected failure), replay_outcome = replay.compute_outcome(
    turn_results, len(source_turns), source.succeeded_turn) — `compute_outcome` and `ReplayFailed` both lazily
    imported together, before the `try`: `from kestrel.replay import compute_outcome, ReplayFailed` inside this
    function, exactly the way `runs.py:155` already imports `run_adaptive` lazily to avoid a module-level import
    cycle (research D14: `replay.py` must import `run_replay_adaptive` *from* `graph.py`, so `graph.py` cannot
    also import *from* `replay.py` at module level without creating one) — then store.finish_run(...,
    replay_outcome=replay_outcome, judge_prompt_id=..., judge_prompt_version=...)."""
```

## Settings (`settings.py`)

```python
DEFAULT_REPLAY_BATCH_MAX_RUNS = 20   # feature 012, confirmed with the product owner 2026-11-19
```

`Settings.replay_batch_max_runs: int = DEFAULT_REPLAY_BATCH_MAX_RUNS`, parsed by the existing `positive_int(name,
default)` helper as `KESTREL_REPLAY_BATCH_MAX_RUNS` — invalid (non-positive, non-integer) refuses to start, exactly
as every other `positive_int` setting already does.

## API schema additions (`api/schemas.py`) — shapes only; full contract in `contracts/api.md`

- `RunSummary`/`RunDetail`: `source_run_id: int | None = None`, `replay_outcome: str | None = None`,
  `finding: bool` (true for a succeeded, non-replay run — `is_finding(run)` above; together with `hard_evidence`,
  drives the UI's Confirmed/Suspected headline cards with no mode check in the UI itself), `replayable: bool`,
  `replay_blocked_reason: str | None = None` (present only when
  `replayable` is `False`; one of `ReplayStatus.blocked_reason`'s seven exact strings),
  `replay_advisory: str | None = None` (new, independent of `replay_blocked_reason` — a replayable run can still
  carry one, `ReplayStatus.advisory`). All three replay-status fields are filled from one call to
  `compute_replay_status(run, target, terms_version, adaptive_max_turns, target_has_other_run_in_progress)` in
  `run_summary(...)`, never from the run's own fields alone.
- `RunDetail`: `comparison: ReplayComparisonOut | None = None` — present only when `mode == "replay"`; built by
  `build_comparison` at request time (research D8), including its `multi_turn_caption`. Named
  `ReplayComparisonOut`, **not** `ComparisonOut`: `ComparisonOut` already exists, `api/schemas.py:314`, used by
  the feature-007 experiment result at `api/schemas.py:348` and `api/main.py:716` — an unrelated shape, two
  numbers and a caveat for an A/B significance test. Reusing or shadowing that name would collide; this feature's
  comparison is new and distinct.
- `TurnComparisonOut`, `ReplayComparisonOut`: mirror `TurnComparison`/`Comparison` field for field.
- `BatchReplayEntryOut`, `BatchReplayResultOut`: mirror `BatchEntry`/`BatchResult`, including the two
  `*_hard_evidence` fields and (on the result) `complete`/`stop_reason`/`not_replayed_source_ids`/
  `failed_source_run_id` (spec-change, review item 5).
- `ConfigOut.replay: ReplayOut` where `ReplayOut(max_batch_runs: int, per_replay_time_limit_s: int)` (research
  D12; `per_replay_time_limit_s = max(settings.adaptive_time_limit_s, runs.TOTAL_DEADLINE_S)`, research D13 — the
  CI script's own batch timeout needs the longer of the two per-run deadlines the server actually enforces, since
  a batch can include single-turn sources too).
