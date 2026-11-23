"""Saved targets in one SQLite file, through the standard-library sqlite3 module, no ORM (data-model.md; research R6).

Rules the database can't check (URL, template and header rules, value length) are enforced by the API before saving.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from kestrel.secrets import Vault

SCHEMA_VERSION = "10"
FAMILIES = ("direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection")
VERDICTS = ("succeeded", "failed", "unclear")
MIN_CANARY_LENGTH = 8
# Feature 010 (FR-010): a run keeps at most this many of its log lines; the rest reach the stream only, and one
# `log.truncated` marker row records how many were dropped. A constant, not a setting.
RUN_LOG_CAP = 1000

# The `runs` table's columns: shared by a fresh database's CREATE TABLE (below) and the schema-v9 rebuild
# (`runs_new` in `_rebuild_runs_with_autoincrement`), so the two definitions cannot drift apart. SQLite cannot
# ALTER a column into AUTOINCREMENT, so an existing database is migrated by rebuilding the table from this same
# text (https://www.sqlite.org/lang_altertable.html, "Making Other Kinds Of Table Schema Changes").
RUNS_COLUMNS_SQL = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,                        -- v9: never reissued once a run row is gone
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL,
    prompt_title TEXT NOT NULL,
    prompt_text TEXT NOT NULL,                                   -- copied, so a library edit can't rewrite history
    family TEXT NOT NULL CHECK (family IN
        ('direct_injection', 'system_prompt_leak', 'tool_exfiltration', 'indirect_injection')),
    owasp_category TEXT NOT NULL,
    attacker_source TEXT NOT NULL,                               -- 'library:<version>' (FR-005, FR-019)
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'finished')),
    reply_text TEXT,                                             -- masked and cut; null when the send failed
    reply_truncated INTEGER NOT NULL DEFAULT 0,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('succeeded', 'failed', 'unclear')),
    hard_evidence INTEGER NOT NULL DEFAULT 0,                    -- set by a canary match alone (FR-018)
    reason TEXT,
    judge_used INTEGER NOT NULL DEFAULT 0,
    judge_model TEXT,
    failure_step TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    -- Added in schema version 3 (feature 003): single-turn runs leave these at their defaults/null.
    mode TEXT NOT NULL DEFAULT 'single_turn' CHECK (mode IN ('single_turn', 'adaptive', 'replay')),
    attacker_model TEXT,                                         -- the model driving an adaptive run (FR-015)
    turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER,
    time_limit_s INTEGER,
    stopping_condition TEXT,                                     -- how an adaptive run ended (FR-012)
    succeeded_turn INTEGER,                                      -- the turn it succeeded at, or null (FR-019)
    -- Added in schema version 4 (feature 004).
    use_prior_experience INTEGER NOT NULL DEFAULT 1,            -- warm (1, default) or cold (0), per run (FR-014)
    memory_written INTEGER,                                      -- null not attempted, 1 written, 0 failed (FR-010)
    -- Added in schema version 7 (feature 009): the judge prompt behind this run's verdict (null = not recorded).
    judge_prompt_id TEXT, judge_prompt_version TEXT,
    -- Added in schema version 10 (feature 012): a replay links to the run it re-tests and records one outcome.
    source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,  -- null unless mode = 'replay'
    replay_outcome TEXT CHECK (replay_outcome IS NULL OR
        replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive'))  -- null unless mode = 'replay'
"""
# The indexes on `runs`: also shared, textually, with `_rebuild_runs_with_autoincrement` (which must issue these
# as separate `execute()` calls rather than this joined form - see that method's docstring).
RUNS_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_runs_target ON runs (target_id, started_at DESC);
-- FR-010 as a property of the database, so two API workers can't both start a run on one target (any mode).
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),   -- trimmed, 1 to 100 characters
    name_key TEXT NOT NULL UNIQUE,                               -- name.casefold(): unique ignoring case (FR-013)
    url TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('POST', 'GET')),
    body_template TEXT NOT NULL,
    response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL,                       -- ISO-8601 UTC
    terms_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    description TEXT                                              -- v4: optional one-line purpose, non-secret (FR-020)
);
CREATE TABLE IF NOT EXISTS target_headers (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    value_encrypted TEXT NOT NULL                                -- Fernet token; never returned by the API
);
CREATE UNIQUE INDEX IF NOT EXISTS target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Added in schema version 2 (feature 002).
CREATE TABLE IF NOT EXISTS target_canaries (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    value TEXT NOT NULL CHECK (length(value) >= 8),              -- FR-025; plain text, not a credential (R7)
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS target_canaries_value ON target_canaries (target_id, value);
CREATE TABLE IF NOT EXISTS runs ({RUNS_COLUMNS_SQL});
{RUNS_INDEXES_SQL}
-- Added in schema version 3: the conversation of an adaptive run, one row per turn (FR-020).
CREATE TABLE IF NOT EXISTS run_turns (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    attacker_message TEXT NOT NULL,                             -- masked before storing (FR-021)
    reply_text TEXT,                                            -- masked and cut; null if the send failed
    reply_truncated INTEGER NOT NULL DEFAULT 0,
    judge_verdict TEXT, judge_reason TEXT, judge_progress TEXT,
    -- Added in schema version 7 (feature 009): which prompt version produced this turn (null = not recorded).
    attacker_prompt_id TEXT, attacker_prompt_version TEXT,
    judge_prompt_id TEXT, judge_prompt_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_turns_run ON run_turns (run_id, position);

-- Added in schema version 5 (feature 005): one cached, model-generated fix suggestion per successful run (FR-012,
-- FR-013). Keyed by run id so regenerating a report serves the cache instead of re-calling the model.
CREATE TABLE IF NOT EXISTS report_recommendations (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    recommendation TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL
);

-- Added in schema version 6 (feature 007, A/B harness): experiments and their two arms; each executed run links
-- back to the generic `runs` table, which already carries verdict/hard_evidence/tokens_used/attacker_model/etc.
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('single_turn', 'adaptive')),
    families TEXT NOT NULL,                      -- JSON array of family keys
    reps INTEGER NOT NULL CHECK (reps >= 1),
    seed_prompt_ids TEXT NOT NULL,               -- JSON object family -> prompt_id (FR-016)
    max_runs INTEGER NOT NULL CHECK (max_runs >= 1),
    token_budget_total INTEGER NOT NULL CHECK (token_budget_total >= 1),
    wall_clock_s INTEGER NOT NULL CHECK (wall_clock_s >= 1),
    status TEXT NOT NULL CHECK (status IN ('running', 'finished', 'stopped', 'failed')),
    stopped_reason TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiments_target ON experiments (target_id, created_at DESC);
-- At most one running experiment per target, so arms never contend for the single active-run slot (FR-008).
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiments_active ON experiments (target_id) WHERE status = 'running';
CREATE TABLE IF NOT EXISTS experiment_arms (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (label IN ('A', 'B')),
    attacker_model TEXT NOT NULL,                -- model name only; never a secret (Principle IV)
    judge_model TEXT NOT NULL,
    use_prior_experience INTEGER NOT NULL,       -- retrieval on (1) / off (0)
    turn_cap INTEGER NOT NULL CHECK (turn_cap >= 1),
    token_budget INTEGER NOT NULL CHECK (token_budget >= 1),
    write_back INTEGER NOT NULL DEFAULT 1,       -- cold arm = 0 (FR-005)
    run_order INTEGER,                           -- 1 or 2; set when the arm starts
    -- Added in schema version 7 (feature 009): a prompt-version A/B arm pins one prompt (null = default/active).
    prompt_arm_target TEXT, prompt_arm_version TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms ON experiment_arms (experiment_id, label);
CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    arm_id INTEGER NOT NULL REFERENCES experiment_arms(id) ON DELETE CASCADE,
    rep_index INTEGER NOT NULL,
    family TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,   -- null only if the run could not be claimed (FR-015)
    send_ok INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp ON experiment_runs (experiment_id, arm_id);

-- Added in schema version 8 (feature 010): the structured log lines kept for a run, in emission order (FR-010).
CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,                        -- 1-based emission order within the run's scope
    ts TEXT NOT NULL,                            -- copied from the record, for ordering and display
    event TEXT NOT NULL,                         -- copied from the record, for filtering
    record TEXT NOT NULL                         -- the exact JSON line that went to the stream
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_log_seq ON run_log (run_id, seq);
"""

# Columns added to `runs` in version 3; ALTER-added for a version-2 database (fresh ones get them from SCHEMA).
# The ALTER form omits the CHECK on `mode`; the base schema carries it, and code only ever writes valid modes.
ADAPTIVE_RUN_COLUMNS = (
    ("mode", "TEXT NOT NULL DEFAULT 'single_turn'"),
    ("attacker_model", "TEXT"), ("turn_budget", "INTEGER"), ("turns_used", "INTEGER"),
    ("token_budget", "INTEGER"), ("tokens_used", "INTEGER"), ("time_limit_s", "INTEGER"),
    ("stopping_condition", "TEXT"), ("succeeded_turn", "INTEGER"),
)

# Columns added to `runs` in version 4; ALTER-added for an older database (fresh ones get them from SCHEMA).
EXPERIENCE_RUN_COLUMNS = (
    ("use_prior_experience", "INTEGER NOT NULL DEFAULT 1"),
    ("memory_written", "INTEGER"),
)

# Columns added in version 7 (feature 009): prompt-version provenance on runs/run_turns and the prompt-version arm.
PROMPT_RUNS_COLUMNS = (("judge_prompt_id", "TEXT"), ("judge_prompt_version", "TEXT"))
PROMPT_RUN_TURN_COLUMNS = (
    ("attacker_prompt_id", "TEXT"), ("attacker_prompt_version", "TEXT"),
    ("judge_prompt_id", "TEXT"), ("judge_prompt_version", "TEXT"),
)
PROMPT_ARM_COLUMNS = (("prompt_arm_target", "TEXT"), ("prompt_arm_version", "TEXT"))


class NameTaken(Exception):
    """Another saved target has this display name, ignoring case."""


class TargetNotFound(LookupError):
    pass


class MissingStoredValue(LookupError):
    """A header asked to keep its stored value, but the target has no stored header with that name."""


class UnknownSchemaVersion(Exception):
    """The database was written by a different Kestrel; refuse it rather than mangle it (research R11)."""


class RunInProgress(Exception):
    """A run against this target is already in progress (FR-010)."""


class ExperimentInProgress(Exception):
    """An experiment against this target is already running (feature 007, FR-008)."""


@dataclass(frozen=True)
class StoredHeader:
    name: str
    readable: bool  # False when the current key can't decrypt the value


@dataclass(frozen=True)
class HeaderValue:
    name: str
    value: str | None = None  # None when the current key can't decrypt the value

    def __repr__(self) -> str:  # never print a header value
        return f"HeaderValue(name={self.name!r}, value={'<unreadable>' if self.value is None else '<hidden>'})"


@dataclass(frozen=True)
class Run:
    id: int
    target_id: int
    prompt_id: str
    prompt_title: str
    prompt_text: str
    family: str
    owasp_category: str
    attacker_source: str
    status: str
    started_at: str
    reply_text: str | None = None
    reply_truncated: bool = False
    verdict: str | None = None
    hard_evidence: bool = False
    reason: str | None = None
    judge_used: bool = False
    judge_model: str | None = None
    failure_step: str | None = None
    finished_at: str | None = None
    # Version 3 (feature 003); single-turn runs leave these at their defaults.
    mode: str = "single_turn"
    attacker_model: str | None = None
    turn_budget: int | None = None
    turns_used: int | None = None
    token_budget: int | None = None
    tokens_used: int | None = None
    time_limit_s: int | None = None
    stopping_condition: str | None = None
    succeeded_turn: int | None = None
    # Version 4 (feature 004).
    use_prior_experience: bool = True
    memory_written: bool | None = None  # None = write-back not attempted; False = failed; True = written
    # Version 7 (feature 009): the judge prompt behind this run's verdict; None = not recorded (or no judge).
    judge_prompt_id: str | None = None
    judge_prompt_version: str | None = None
    # Version 10 (feature 012): a replay links to the run it re-tests and records one outcome against it.
    source_run_id: int | None = None       # the run this one replays; null unless mode == "replay"
    replay_outcome: str | None = None      # "fixed" | "still_vulnerable" | "inconclusive"; null unless a replay


@dataclass(frozen=True)
class Turn:
    """One turn of an adaptive run's conversation (feature 003)."""
    position: int
    attacker_message: str
    reply_text: str | None = None
    reply_truncated: bool = False
    judge_verdict: str | None = None
    judge_reason: str | None = None
    judge_progress: str | None = None
    # Version 7 (feature 009): which prompt versions produced this turn; None = not recorded (or none applied:
    # the turn-1 library seed has no attacker prompt, a turn the judge skipped has no judge prompt).
    attacker_prompt_id: str | None = None
    attacker_prompt_version: str | None = None
    judge_prompt_id: str | None = None
    judge_prompt_version: str | None = None


@dataclass(frozen=True)
class LogLine:
    """One kept log line of a run (feature 010, FR-010): its order, time, event and the exact JSON record."""
    seq: int
    ts: str
    event: str
    record: str


@dataclass(frozen=True)
class StoredRecommendation:
    """A cached, model-generated fix suggestion for one successful run (feature 005, FR-012)."""
    run_id: int
    recommendation: str
    model: str | None
    created_at: str


@dataclass(frozen=True)
class ExperimentArm:
    """One arm of an experiment (feature 007, FR-002). Holds model names and settings only - never a secret."""
    id: int
    label: str
    attacker_model: str
    judge_model: str
    use_prior_experience: bool
    turn_cap: int
    token_budget: int
    write_back: bool
    # Feature 009: a prompt-version A/B arm pins one registry prompt ("attacker:<family>" or "judge"); null = active.
    prompt_arm_target: str | None = None
    prompt_arm_version: str | None = None
    run_order: int | None = None


@dataclass(frozen=True)
class Experiment:
    """One campaign run under arm A and arm B (feature 007, FR-003, FR-016)."""
    id: int
    target_id: int
    mode: str
    families: tuple[str, ...]
    reps: int
    seed_prompt_ids: dict[str, str]
    max_runs: int
    token_budget_total: int
    wall_clock_s: int
    status: str
    stopped_reason: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    arms: tuple[ExperimentArm, ...] = ()


@dataclass(frozen=True)
class ExperimentRunLink:
    """Tags an ordinary run with its experiment and arm (feature 007, FR-004)."""
    id: int
    experiment_id: int
    arm_id: int
    rep_index: int
    family: str
    run_id: int | None
    send_ok: bool
    created_at: str


@dataclass(frozen=True)
class Target:
    id: int
    name: str
    url: str
    method: str
    body_template: str
    response_path: str
    permission_confirmed_at: str
    terms_version: str
    created_at: str
    updated_at: str
    description: str | None = None
    headers: tuple[StoredHeader, ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class TargetStore:
    def __init__(self, db_path: Path, vault: Vault) -> None:
        self._path = Path(db_path)
        self._vault = vault
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        """Additive migrations, plus the version-9 `runs` rebuild. New tables (v2 canaries/runs, v3 turns, v5
        report_recommendations) come from the schema script (CREATE IF NOT EXISTS); the version-3 columns
        (adaptive) and version-4 columns (experience) on the existing tables are ALTER-added for an older database
        (R9). Versions 5 and 8 (feature 010's run_log) add only a new table. Version 9 cannot be additive: SQLite
        has no ALTER that adds AUTOINCREMENT to an existing column, so `_rebuild_runs_with_autoincrement` rebuilds
        `runs` once every additive column it needs has been added above. Version 10 (feature 012) cannot be
        additive either: SQLite cannot ALTER a CHECK constraint, so `_rebuild_runs_for_replay` rebuilds `runs` a
        second time to widen the `mode` CHECK and add `source_run_id`/`replay_outcome`."""
        row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = None if row is None else row["value"]
        if current == SCHEMA_VERSION:
            return
        if current is not None and current not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            raise UnknownSchemaVersion(
                f"This database is at schema version {current}, but this Kestrel understands {SCHEMA_VERSION}.")
        # An older database may lack the adaptive (v3), experience (v4) and prompt-version (v7) columns on `runs`.
        run_columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        for column, ddl in ADAPTIVE_RUN_COLUMNS + EXPERIENCE_RUN_COLUMNS + PROMPT_RUNS_COLUMNS:
            if column not in run_columns:
                db.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
        # The v7 prompt-version provenance on `run_turns` and the v7 prompt-arm columns on `experiment_arms`.
        turn_columns = {r["name"] for r in db.execute("PRAGMA table_info(run_turns)")}
        for column, ddl in PROMPT_RUN_TURN_COLUMNS:
            if column not in turn_columns:
                db.execute(f"ALTER TABLE run_turns ADD COLUMN {column} {ddl}")
        arm_columns = {r["name"] for r in db.execute("PRAGMA table_info(experiment_arms)")}
        for column, ddl in PROMPT_ARM_COLUMNS:
            if column not in arm_columns:
                db.execute(f"ALTER TABLE experiment_arms ADD COLUMN {column} {ddl}")
        # The v4 purpose description on `targets`.
        target_columns = {r["name"] for r in db.execute("PRAGMA table_info(targets)")}
        if "description" not in target_columns:
            db.execute("ALTER TABLE targets ADD COLUMN description TEXT")
        # Now that `runs` carries every current column, rebuild it under AUTOINCREMENT if it does not already
        # (a no-op for a database already migrated to v9, and for a fresh one: its `runs` came from SCHEMA above).
        TargetStore._rebuild_runs_with_autoincrement(db)
        # Then widen `mode`'s CHECK and add source_run_id/replay_outcome if that has not happened yet (a no-op for
        # a database already at v10, and for a fresh one, or one rebuilt above straight from pre-v9: either way
        # RUNS_COLUMNS_SQL already gave `runs` these columns, since both rebuilds and the fresh CREATE TABLE share
        # one definition).
        TargetStore._rebuild_runs_for_replay(db)
        if current is None:
            db.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        else:
            db.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (SCHEMA_VERSION,))

    @staticmethod
    def _rebuild_runs_with_autoincrement(db: sqlite3.Connection) -> None:
        """Schema v9 (post-review fix): give `runs.id` AUTOINCREMENT, so a run's id is never reissued once its row
        is gone (directly, or by a cascaded target deletion) — closing the path by which a reused numeric id could
        collide with a pattern `write_pattern` had derived from it (patterns now get their own unique id instead;
        `kestrel.experience.store.write_pattern`). SQLite cannot ALTER a column into AUTOINCREMENT, so this follows
        SQLite's own documented procedure for schema changes ALTER TABLE cannot express
        (https://www.sqlite.org/lang_altertable.html, "Making Other Kinds Of Table Schema Changes"): copy `runs`
        into a new table built from `RUNS_COLUMNS_SQL` (now with AUTOINCREMENT), drop the old one, rename the new
        one back, recreate its indexes, and require `PRAGMA foreign_key_check` to come back empty before
        committing. `sqlite_sequence` then holds the highest copied id, so a numeric id freed by a row deleted
        *before* this migration could still be issued once more — harmless, now that pattern ids are never derived
        from a run id.

        Four tables reference `runs` (`run_turns`, `report_recommendations` and `run_log` ON DELETE CASCADE,
        `experiment_runs` ON DELETE SET NULL). With foreign keys on, `DROP TABLE runs` performs an implicit DELETE
        that fires those actions and wipes or nulls every child row, so foreign keys must be off first. `PRAGMA
        foreign_keys` is a no-op inside an open transaction, and the first DML statement below (`INSERT INTO
        runs_new ... SELECT`) opens one implicitly, so the PRAGMA is set before it, while nothing but DDL
        (CREATE/DROP/ALTER, which do not open a transaction on their own) has run yet in this call. The index
        statements are issued individually here rather than via `RUNS_INDEXES_SQL` as one script, because
        `executescript` commits any open transaction before it runs — which would commit this rebuild before
        `foreign_key_check` has had a chance to refuse it.
        """
        definition = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'runs'").fetchone()
        if definition is None or "AUTOINCREMENT" in definition["sql"].upper():
            return   # no `runs` table yet (unreachable: SCHEMA already created it), or already rebuilt
        columns = ", ".join(r["name"] for r in db.execute("PRAGMA table_info(runs)"))
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("DROP TABLE IF EXISTS runs_new")   # left over from a previous, interrupted migration attempt
        db.execute(f"CREATE TABLE runs_new ({RUNS_COLUMNS_SQL})")
        db.execute(f"INSERT INTO runs_new ({columns}) SELECT {columns} FROM runs")
        db.execute("DROP TABLE runs")
        db.execute("ALTER TABLE runs_new RENAME TO runs")
        db.execute("CREATE INDEX IF NOT EXISTS idx_runs_target ON runs (target_id, started_at DESC)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active ON runs (target_id) WHERE status ="
                   " 'in_progress'")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"schema v9 migration would leave dangling foreign keys: {[tuple(v) for v in violations]}")
        db.commit()
        db.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _rebuild_runs_for_replay(db: sqlite3.Connection) -> None:
        """Schema v10 (feature 012): widen `mode`'s CHECK to accept 'replay' and add a self-referencing
        `source_run_id` plus `replay_outcome`. SQLite cannot ALTER a CHECK constraint, so this is a second rebuild
        of `runs`, following v9's own documented procedure and the same reasoning (foreign keys off before any
        DML; the index statements as separate `execute()` calls, never `executescript`, so the rebuild can still be
        refused before it commits; `PRAGMA foreign_key_check` empty before `commit()`).

        A plain rename loses `runs`' `sqlite_sequence` row: `DROP TABLE runs` deletes it outright, and the copy
        into `runs_new` only ever inserts the *surviving* rows, so `runs_new`'s own freshly-started sequence sits
        at the highest surviving id, not the highest id this table ever issued — a numeric id freed by a deletion
        *before* this rebuild (but after the v9 migration already made it unreissuable) would become reissuable
        again the moment the rename takes its place, undoing v9's own guarantee exactly when a later run might
        rely on it (a reissued id could collide with a surviving `memory:run:<id>` record,
        `experience/store.py::write_memory`). The fix: read the old table's own watermark before dropping it, and
        after the rename, restore the higher of that watermark and the highest id actually copied — in the same
        transaction as the rename, never a separate commit in between.
        """
        columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        if "source_run_id" in columns:
            return   # already rebuilt (or a fresh database, or one rebuilt above straight from pre-v9)
        existing = ", ".join(r["name"] for r in db.execute("PRAGMA table_info(runs)"))
        old_seq_row = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'runs'").fetchone()
        old_seq = old_seq_row["seq"] if old_seq_row is not None else 0
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("DROP TABLE IF EXISTS runs_new")   # left over from a previous, interrupted migration attempt
        db.execute(f"CREATE TABLE runs_new ({RUNS_COLUMNS_SQL})")
        db.execute(f"INSERT INTO runs_new ({existing}) SELECT {existing} FROM runs")
        db.execute("DROP TABLE runs")
        db.execute("ALTER TABLE runs_new RENAME TO runs")
        db.execute("CREATE INDEX IF NOT EXISTS idx_runs_target ON runs (target_id, started_at DESC)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active ON runs (target_id) WHERE status ="
                   " 'in_progress'")
        max_copied = db.execute("SELECT COALESCE(MAX(id), 0) AS m FROM runs").fetchone()["m"]
        db.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'runs'", (max(old_seq, max_copied),))
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"schema v10 migration would leave dangling foreign keys: {[tuple(v) for v in violations]}")
        db.commit()
        db.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """One connection per call; commits on success and rolls back on any error."""
        db = sqlite3.connect(self._path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA secure_delete = ON")
            with db:
                yield db
        finally:
            db.close()

    def create_target(self, *, name: str, url: str, method: str, headers: list[tuple[str, str]], body_template: str,
                      response_path: str, terms_version: str, description: str | None = None) -> Target:
        now = utc_now()
        try:
            with self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                    " permission_confirmed_at, terms_version, created_at, updated_at, description)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, name.casefold(), url, method, body_template, response_path, now, terms_version, now, now,
                     description))
                target_id = cursor.lastrowid
                self._insert_headers(db, target_id, [(n, self._vault.encrypt(v)) for n, v in headers])
        except sqlite3.IntegrityError as error:
            if "name_key" in str(error):
                raise NameTaken(name) from None
            raise
        return self.get_target(target_id)

    def update_target(self, target_id: int, *, name: str, url: str, method: str,
                      headers: list[tuple[str, str | None]], body_template: str, response_path: str,
                      terms_version: str, description: str | None = None) -> Target:
        """A value of None keeps the stored value of that header (FR-017); headers left out are removed.

        The permission date is renewed when the URL changes or newer terms are accepted (FR-018).
        """
        now = utc_now()
        try:
            with self.connect() as db:
                row = db.execute("SELECT url, terms_version, permission_confirmed_at FROM targets WHERE id = ?",
                                 (target_id,)).fetchone()
                if row is None:
                    raise TargetNotFound(target_id)
                stored = {h["name"].lower(): h["value_encrypted"] for h in self._header_rows(db, target_id)}
                encrypted = []
                for header_name, value in headers:
                    if value is None:
                        if header_name.lower() not in stored:
                            raise MissingStoredValue(header_name)
                        encrypted.append((header_name, stored[header_name.lower()]))
                    else:
                        encrypted.append((header_name, self._vault.encrypt(value)))
                renewed = url != row["url"] or terms_version != row["terms_version"]
                db.execute(
                    "UPDATE targets SET name = ?, name_key = ?, url = ?, method = ?, body_template = ?,"
                    " response_path = ?, permission_confirmed_at = ?, terms_version = ?, updated_at = ?,"
                    " description = ? WHERE id = ?",
                    (name, name.casefold(), url, method, body_template, response_path,
                     now if renewed else row["permission_confirmed_at"], terms_version, now, description, target_id))
                db.execute("DELETE FROM target_headers WHERE target_id = ?", (target_id,))
                self._insert_headers(db, target_id, encrypted)
        except sqlite3.IntegrityError as error:
            if "name_key" in str(error):
                raise NameTaken(name) from None
            raise
        return self.get_target(target_id)

    def delete_target(self, target_id: int) -> None:
        """Remove the target; its header rows go with it (ON DELETE CASCADE, overwritten by secure_delete)."""
        with self.connect() as db:
            if db.execute("DELETE FROM targets WHERE id = ?", (target_id,)).rowcount == 0:
                raise TargetNotFound(target_id)

    def key_matches(self) -> bool:
        """False when the current key can't decrypt a stored header value (research R5)."""
        with self.connect() as db:
            row = db.execute("SELECT value_encrypted FROM target_headers LIMIT 1").fetchone()
        return row is None or self._vault.decrypt(row["value_encrypted"]) is not None

    def list_targets(self) -> list[Target]:
        with self.connect() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM targets ORDER BY name_key, id")]
        return [self.get_target(target_id) for target_id in ids]

    def get_target(self, target_id: int) -> Target:
        with self.connect() as db:
            row = db.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
            if row is None:
                raise TargetNotFound(target_id)
            headers = tuple(StoredHeader(name=h["name"], readable=self._vault.decrypt(h["value_encrypted"]) is not None)
                            for h in self._header_rows(db, target_id))
        return Target(id=row["id"], name=row["name"], url=row["url"], method=row["method"],
                      body_template=row["body_template"], response_path=row["response_path"],
                      permission_confirmed_at=row["permission_confirmed_at"], terms_version=row["terms_version"],
                      created_at=row["created_at"], updated_at=row["updated_at"],
                      description=row["description"], headers=headers)

    def resolve_headers(self, target_id: int) -> list[HeaderValue]:
        """The decrypted header values, for the tester only; value is None when this key can't decrypt one."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            return [HeaderValue(name=h["name"], value=self._vault.decrypt(h["value_encrypted"]))
                    for h in self._header_rows(db, target_id)]

    # ---- canary strings (FR-024, FR-025) ----

    def set_canaries(self, target_id: int, values: list[str]) -> list[str]:
        """Replace the target's canaries. Stored as plain text: they are evidence, not credentials (R7)."""
        for value in values:
            if len(value) < MIN_CANARY_LENGTH:
                raise ValueError(f"A canary string must be at least {MIN_CANARY_LENGTH} characters.")
        if len(set(values)) != len(values):
            raise ValueError("The same canary string appears more than once on this target.")
        now = utc_now()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            db.execute("DELETE FROM target_canaries WHERE target_id = ?", (target_id,))
            db.executemany(
                "INSERT INTO target_canaries (target_id, position, value, created_at) VALUES (?, ?, ?, ?)",
                [(target_id, position, value, now) for position, value in enumerate(values)])
        return list(values)

    def list_canaries(self, target_id: int) -> list[str]:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            return [row["value"] for row in db.execute(
                "SELECT value FROM target_canaries WHERE target_id = ? ORDER BY position", (target_id,))]

    # ---- runs (FR-027 to FR-031) ----

    def claim_run(self, target_id: int, *, prompt_id: str, prompt_title: str, prompt_text: str, family: str,
                  owasp_category: str, attacker_source: str, mode: str = "single_turn",
                  attacker_model: str | None = None, turn_budget: int | None = None,
                  token_budget: int | None = None, time_limit_s: int | None = None,
                  use_prior_experience: bool = True, source_run_id: int | None = None) -> int:
        """Write the row before anything is sent, so a crash still leaves evidence an attack went out (R10).

        Adaptive runs pass mode='adaptive' with the attacker model and the budgets they were allowed (FR-015). A
        replay (feature 012) passes mode='replay' and source_run_id naming the run it re-tests."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            try:
                cursor = db.execute(
                    "INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                    " attacker_source, status, started_at, mode, attacker_model, turn_budget, token_budget,"
                    " time_limit_s, use_prior_experience, source_run_id) VALUES (?, ?, ?, ?, ?, ?, ?,"
                    " 'in_progress', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category, attacker_source,
                     utc_now(), mode, attacker_model, turn_budget, token_budget, time_limit_s,
                     int(use_prior_experience), source_run_id))
            except sqlite3.IntegrityError:
                # SQLite names the column, not the index, so ask the data rather than parse the message.
                open_run = db.execute("SELECT id FROM runs WHERE target_id = ? AND status = 'in_progress'",
                                      (target_id,)).fetchone()
                if open_run is not None:
                    raise RunInProgress(target_id) from None
                raise
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, *, verdict: str | None = None, hard_evidence: bool = False,
                   reason: str | None = None, judge_used: bool = False, judge_model: str | None = None,
                   reply_text: str | None = None, reply_truncated: bool = False,
                   failure_step: str | None = None, stopping_condition: str | None = None,
                   succeeded_turn: int | None = None, turns_used: int | None = None,
                   tokens_used: int | None = None, judge_prompt_id: str | None = None,
                   judge_prompt_version: str | None = None, replay_outcome: str | None = None) -> Run:
        """Finish a run. Adaptive runs also pass how they ended and their usage (FR-012, FR-015, FR-019). The judge
        prompt provenance (feature 009, FR-003) is null when the judge was not used. A replay (feature 012) passes
        replay_outcome, its one computed result against its source; every other caller leaves it null."""
        with self.connect() as db:
            updated = db.execute(
                "UPDATE runs SET status = 'finished', verdict = ?, hard_evidence = ?, reason = ?, judge_used = ?,"
                " judge_model = ?, reply_text = ?, reply_truncated = ?, failure_step = ?,"
                " stopping_condition = ?, succeeded_turn = ?, turns_used = ?, tokens_used = ?,"
                " judge_prompt_id = ?, judge_prompt_version = ?, replay_outcome = ?, finished_at = ?"
                " WHERE id = ? AND status = 'in_progress'",
                (verdict, int(hard_evidence), reason, int(judge_used), judge_model, reply_text,
                 int(reply_truncated), failure_step, stopping_condition, succeeded_turn, turns_used,
                 tokens_used, judge_prompt_id, judge_prompt_version, replay_outcome, utc_now(), run_id)).rowcount
            if updated == 0:
                raise LookupError(f"No run in progress with id {run_id}.")
        return self.get_run(run_id)

    def set_memory_written(self, run_id: int, written: bool) -> None:
        """Record whether this run's write-back to the experience store succeeded (FR-010)."""
        with self.connect() as db:
            if db.execute("UPDATE runs SET memory_written = ? WHERE id = ?",
                          (int(written), run_id)).rowcount == 0:
                raise LookupError(f"No run with id {run_id}.")

    def add_turn(self, run_id: int, *, position: int, attacker_message: str, reply_text: str | None = None,
                 reply_truncated: bool = False, judge_verdict: str | None = None, judge_reason: str | None = None,
                 judge_progress: str | None = None, attacker_prompt_id: str | None = None,
                 attacker_prompt_version: str | None = None, judge_prompt_id: str | None = None,
                 judge_prompt_version: str | None = None) -> None:
        """Record one conversation turn of an adaptive run (FR-020). The caller masks before calling. The prompt
        provenance (feature 009, FR-003) is null when no prompt produced it — the turn-1 library seed carries no
        attacker prompt, and a turn the judge did not run carries no judge prompt."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO run_turns (run_id, position, attacker_message, reply_text, reply_truncated,"
                " judge_verdict, judge_reason, judge_progress, attacker_prompt_id, attacker_prompt_version,"
                " judge_prompt_id, judge_prompt_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, position, attacker_message, reply_text, int(reply_truncated), judge_verdict,
                 judge_reason, judge_progress, attacker_prompt_id, attacker_prompt_version, judge_prompt_id,
                 judge_prompt_version, utc_now()))

    def list_turns(self, run_id: int) -> list[Turn]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM run_turns WHERE run_id = ? ORDER BY position", (run_id,)).fetchall()
        return [Turn(position=r["position"], attacker_message=r["attacker_message"], reply_text=r["reply_text"],
                     reply_truncated=bool(r["reply_truncated"]), judge_verdict=r["judge_verdict"],
                     judge_reason=r["judge_reason"], judge_progress=r["judge_progress"],
                     attacker_prompt_id=r["attacker_prompt_id"], attacker_prompt_version=r["attacker_prompt_version"],
                     judge_prompt_id=r["judge_prompt_id"], judge_prompt_version=r["judge_prompt_version"])
                for r in rows]

    def list_runs(self, target_id: int) -> list[Run]:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            rows = db.execute("SELECT * FROM runs WHERE target_id = ? ORDER BY started_at DESC, id DESC",
                              (target_id,)).fetchall()
        return [self._run(row) for row in rows]

    def get_run(self, run_id: int) -> Run:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError(f"No run with id {run_id}.")
        return self._run(row)

    # ---- kept log lines (feature 010, FR-010) ----

    def add_log_line(self, run_id: int, *, seq: int, ts: str, event: str, record: str) -> None:
        """Keep one log line of a run. `record` is the exact JSON line the stream carried; `(run_id, seq)` is
        unique."""
        with self.connect() as db:
            db.execute("INSERT INTO run_log (run_id, seq, ts, event, record) VALUES (?, ?, ?, ?, ?)",
                       (run_id, seq, ts, event, record))

    def list_log_lines(self, run_id: int) -> list[LogLine]:
        """A run's kept log lines in emission order; empty for a run that kept none (or predates schema 8)."""
        with self.connect() as db:
            rows = db.execute("SELECT seq, ts, event, record FROM run_log WHERE run_id = ? ORDER BY seq",
                              (run_id,)).fetchall()
        return [LogLine(seq=r["seq"], ts=r["ts"], event=r["event"], record=r["record"]) for r in rows]

    # ---- report recommendations (feature 005, FR-012/FR-013) ----

    def get_recommendation(self, run_id: int) -> StoredRecommendation | None:
        """The cached fix suggestion for a run, or None if none has been generated yet."""
        with self.connect() as db:
            row = db.execute("SELECT run_id, recommendation, model, created_at FROM report_recommendations"
                             " WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return StoredRecommendation(run_id=row["run_id"], recommendation=row["recommendation"],
                                    model=row["model"], created_at=row["created_at"])

    def save_recommendation(self, run_id: int, *, recommendation: str, model: str | None) -> None:
        """Cache (or replace) the fix suggestion for a run, so regenerating a report does not re-call the model."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO report_recommendations (run_id, recommendation, model, created_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(run_id) DO UPDATE SET recommendation = excluded.recommendation,"
                " model = excluded.model, created_at = excluded.created_at",
                (run_id, recommendation, model, utc_now()))

    # ---- experiments (feature 007, FR-003, FR-004, FR-016) ----

    def create_experiment(self, *, target_id: int, mode: str, families: list[str], reps: int,
                          seed_prompt_ids: dict[str, str], max_runs: int, token_budget_total: int,
                          wall_clock_s: int, arm_a: dict, arm_b: dict) -> Experiment:
        """Create a running experiment with its two arms. Raises ExperimentInProgress if one already runs here."""
        now = utc_now()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            try:
                cursor = db.execute(
                    "INSERT INTO experiments (target_id, mode, families, reps, seed_prompt_ids, max_runs,"
                    " token_budget_total, wall_clock_s, status, created_at, started_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                    (target_id, mode, json.dumps(list(families)), reps, json.dumps(dict(seed_prompt_ids)),
                     max_runs, token_budget_total, wall_clock_s, now, now))
            except sqlite3.IntegrityError:
                running = db.execute("SELECT id FROM experiments WHERE target_id = ? AND status = 'running'",
                                     (target_id,)).fetchone()
                if running is not None:
                    raise ExperimentInProgress(target_id) from None
                raise
            experiment_id = int(cursor.lastrowid)
            for label, arm in (("A", arm_a), ("B", arm_b)):
                db.execute(
                    "INSERT INTO experiment_arms (experiment_id, label, attacker_model, judge_model,"
                    " use_prior_experience, turn_cap, token_budget, write_back, prompt_arm_target,"
                    " prompt_arm_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (experiment_id, label, arm["attacker_model"], arm["judge_model"],
                     int(arm["use_prior_experience"]), arm["turn_cap"], arm["token_budget"],
                     int(arm.get("write_back", True)), arm.get("prompt_arm_target"),
                     arm.get("prompt_arm_version")))
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: int) -> Experiment:
        with self.connect() as db:
            row = db.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
            if row is None:
                raise LookupError(f"No experiment with id {experiment_id}.")
            arms = [self._arm(a) for a in db.execute(
                "SELECT * FROM experiment_arms WHERE experiment_id = ? ORDER BY label", (experiment_id,))]
        return self._experiment(row, arms)

    def list_experiments(self, target_id: int | None = None) -> list[Experiment]:
        with self.connect() as db:
            if target_id is None:
                rows = db.execute("SELECT * FROM experiments ORDER BY created_at DESC, id DESC").fetchall()
            else:
                rows = db.execute("SELECT * FROM experiments WHERE target_id = ? ORDER BY created_at DESC, id DESC",
                                  (target_id,)).fetchall()
            out = []
            for row in rows:
                arms = [self._arm(a) for a in db.execute(
                    "SELECT * FROM experiment_arms WHERE experiment_id = ? ORDER BY label", (row["id"],))]
                out.append(self._experiment(row, arms))
        return out

    def set_arm_order(self, arm_id: int, run_order: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE experiment_arms SET run_order = ? WHERE id = ?", (run_order, arm_id))

    def set_experiment_status(self, experiment_id: int, *, status: str, stopped_reason: str | None = None,
                              finished: bool = False) -> None:
        with self.connect() as db:
            if finished:
                db.execute("UPDATE experiments SET status = ?, stopped_reason = ?, finished_at = ? WHERE id = ?",
                           (status, stopped_reason, utc_now(), experiment_id))
            else:
                db.execute("UPDATE experiments SET status = ?, stopped_reason = ? WHERE id = ?",
                           (status, stopped_reason, experiment_id))

    def add_experiment_run(self, *, experiment_id: int, arm_id: int, rep_index: int, family: str,
                           run_id: int | None, send_ok: bool = True) -> None:
        """Link a run to its experiment and arm. A failed send records run_id=None, send_ok=False (not dropped)."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO experiment_runs (experiment_id, arm_id, rep_index, family, run_id, send_ok, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (experiment_id, arm_id, rep_index, family, run_id, int(send_ok), utc_now()))

    def experiment_run_links(self, experiment_id: int) -> list[ExperimentRunLink]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM experiment_runs WHERE experiment_id = ? ORDER BY id",
                              (experiment_id,)).fetchall()
        return [ExperimentRunLink(id=r["id"], experiment_id=r["experiment_id"], arm_id=r["arm_id"],
                                  rep_index=r["rep_index"], family=r["family"], run_id=r["run_id"],
                                  send_ok=bool(r["send_ok"]), created_at=r["created_at"]) for r in rows]

    def arm_runs(self, experiment_id: int, arm_id: int) -> list[Run]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.* FROM runs r JOIN experiment_runs er ON er.run_id = r.id"
                " WHERE er.experiment_id = ? AND er.arm_id = ? ORDER BY er.id", (experiment_id, arm_id)).fetchall()
        return [self._run(row) for row in rows]

    def experiment_progress(self, experiment_id: int) -> dict:
        """Completed-run count, total tokens, and per-arm completed counts (for the status endpoint)."""
        with self.connect() as db:
            completed = db.execute(
                "SELECT COUNT(*) AS n FROM experiment_runs WHERE experiment_id = ? AND run_id IS NOT NULL",
                (experiment_id,)).fetchone()["n"]
            tokens = db.execute(
                "SELECT COALESCE(SUM(r.tokens_used), 0) AS t FROM runs r"
                " JOIN experiment_runs er ON er.run_id = r.id WHERE er.experiment_id = ?",
                (experiment_id,)).fetchone()["t"]
            per_arm = {row["arm_id"]: row["n"] for row in db.execute(
                "SELECT arm_id, COUNT(*) AS n FROM experiment_runs WHERE experiment_id = ? AND run_id IS NOT NULL"
                " GROUP BY arm_id", (experiment_id,))}
        return {"completed": int(completed), "tokens": int(tokens), "per_arm": per_arm}

    @staticmethod
    def _arm(row: sqlite3.Row) -> ExperimentArm:
        return ExperimentArm(id=row["id"], label=row["label"], attacker_model=row["attacker_model"],
                             judge_model=row["judge_model"], use_prior_experience=bool(row["use_prior_experience"]),
                             turn_cap=row["turn_cap"], token_budget=row["token_budget"],
                             write_back=bool(row["write_back"]), prompt_arm_target=row["prompt_arm_target"],
                             prompt_arm_version=row["prompt_arm_version"], run_order=row["run_order"])

    @staticmethod
    def _experiment(row: sqlite3.Row, arms: list[ExperimentArm]) -> Experiment:
        return Experiment(id=row["id"], target_id=row["target_id"], mode=row["mode"],
                          families=tuple(json.loads(row["families"])), reps=row["reps"],
                          seed_prompt_ids=dict(json.loads(row["seed_prompt_ids"])), max_runs=row["max_runs"],
                          token_budget_total=row["token_budget_total"], wall_clock_s=row["wall_clock_s"],
                          status=row["status"], stopped_reason=row["stopped_reason"], created_at=row["created_at"],
                          started_at=row["started_at"], finished_at=row["finished_at"], arms=tuple(arms))

    def close_interrupted_runs(self) -> int:
        """Close anything a stopped process left open, so the target isn't locked by FR-010 forever (FR-031). An
        interrupted replay (feature 012) is closed inconclusive, never left with a null outcome (012/FR-012,
        FR-015); the CASE is a no-op for a non-replay row, whose replay_outcome is already null."""
        with self.connect() as db:
            return db.execute(
                "UPDATE runs SET status = 'finished', verdict = 'unclear', stopping_condition = 'interrupted',"
                " reason = 'Kestrel stopped while this run was in progress, so it was interrupted.',"
                " replay_outcome = CASE WHEN mode = 'replay' THEN 'inconclusive' ELSE replay_outcome END,"
                " finished_at = ? WHERE status = 'in_progress'", (utc_now(),)).rowcount

    def other_run_in_progress(self, target_id: int, *, excluding_run_id: int) -> bool:
        """Whether a run other than `excluding_run_id` is currently in progress on this target (feature 012,
        research D10) - the same state `claim_run`'s own `uq_runs_active` constraint already enforces, read
        directly for display (FR-006, FR-040, FR-042), never folded into `list_replayable_runs`."""
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM runs WHERE target_id = ? AND status = 'in_progress' AND id != ?",
                             (target_id, excluding_run_id)).fetchone()
        return row is not None

    def list_replayable_runs(self, target_id: int) -> list[Run]:
        """The finished, succeeded, non-replay runs of one target that a batch replay (feature 012) would process,
        oldest first (FR-028, FR-029). Unaffected by whether a different run is currently in progress on the
        target - that is `replay.compute_replay_status`'s own, display-time concern (research D10), never folded
        into this query, so the batch's own in-flight replays can never make the rest of its planned list look
        ineligible to itself.

        An adaptive run's eligibility is keyed on its actual `run_turns` rows via the `EXISTS` subquery, never the
        `turns_used` counter alone (defensive, review item 3): normal operation cannot produce a mismatch between
        the two, but the counter is never trusted over the rows for this decision."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            rows = db.execute(
                "SELECT * FROM runs WHERE target_id = ? AND status = 'finished' AND verdict = 'succeeded'"
                " AND mode != 'replay' AND (mode = 'single_turn'"
                " OR EXISTS (SELECT 1 FROM run_turns WHERE run_turns.run_id = runs.id))"
                " ORDER BY started_at ASC, id ASC", (target_id,)).fetchall()
        return [self._run(row) for row in rows]

    def run_ids_with_recorded_turns(self, target_id: int) -> set[int]:
        """Every run id of this target that has at least one `run_turns` row (feature 012, review round 2,
        R2): one query for the whole target, so the run-list endpoint can agree with the detail and the batch
        on an adaptive run's real eligibility instead of falling back to the untrusted `turns_used` counter per
        row."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT run_turns.run_id FROM run_turns"
                " JOIN runs ON runs.id = run_turns.run_id WHERE runs.target_id = ?", (target_id,)).fetchall()
        return {row["run_id"] for row in rows}

    @staticmethod
    def _run(row: sqlite3.Row) -> Run:
        return Run(id=row["id"], target_id=row["target_id"], prompt_id=row["prompt_id"],
                   prompt_title=row["prompt_title"], prompt_text=row["prompt_text"], family=row["family"],
                   owasp_category=row["owasp_category"], attacker_source=row["attacker_source"],
                   status=row["status"], started_at=row["started_at"], reply_text=row["reply_text"],
                   reply_truncated=bool(row["reply_truncated"]), verdict=row["verdict"],
                   hard_evidence=bool(row["hard_evidence"]), reason=row["reason"],
                   judge_used=bool(row["judge_used"]), judge_model=row["judge_model"],
                   failure_step=row["failure_step"], finished_at=row["finished_at"],
                   mode=row["mode"], attacker_model=row["attacker_model"], turn_budget=row["turn_budget"],
                   turns_used=row["turns_used"], token_budget=row["token_budget"], tokens_used=row["tokens_used"],
                   time_limit_s=row["time_limit_s"], stopping_condition=row["stopping_condition"],
                   succeeded_turn=row["succeeded_turn"],
                   use_prior_experience=bool(row["use_prior_experience"]),
                   memory_written=None if row["memory_written"] is None else bool(row["memory_written"]),
                   judge_prompt_id=row["judge_prompt_id"], judge_prompt_version=row["judge_prompt_version"],
                   source_run_id=row["source_run_id"], replay_outcome=row["replay_outcome"])

    @staticmethod
    def _header_rows(db: sqlite3.Connection, target_id: int) -> list[sqlite3.Row]:
        return db.execute("SELECT name, value_encrypted FROM target_headers WHERE target_id = ? ORDER BY position",
                          (target_id,)).fetchall()

    @staticmethod
    def _insert_headers(db: sqlite3.Connection, target_id: int, encrypted: list[tuple[str, str]]) -> None:
        db.executemany("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (?, ?, ?, ?)",
                       [(target_id, position, name, token) for position, (name, token) in enumerate(encrypted)])
