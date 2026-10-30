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

SCHEMA_VERSION = "6"
FAMILIES = ("direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection")
VERDICTS = ("succeeded", "failed", "unclear")
MIN_CANARY_LENGTH = 8

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
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
    mode TEXT NOT NULL DEFAULT 'single_turn' CHECK (mode IN ('single_turn', 'adaptive')),
    attacker_model TEXT,                                         -- the model driving an adaptive run (FR-015)
    turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER,
    time_limit_s INTEGER,
    stopping_condition TEXT,                                     -- how an adaptive run ended (FR-012)
    succeeded_turn INTEGER,                                      -- the turn it succeeded at, or null (FR-019)
    -- Added in schema version 4 (feature 004).
    use_prior_experience INTEGER NOT NULL DEFAULT 1,            -- warm (1, default) or cold (0), per run (FR-014)
    memory_written INTEGER                                       -- null not attempted, 1 written, 0 failed (FR-010)
);
CREATE INDEX IF NOT EXISTS idx_runs_target ON runs (target_id, started_at DESC);
-- FR-010 as a property of the database, so two API workers can't both start a run on one target (any mode).
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
-- Added in schema version 3: the conversation of an adaptive run, one row per turn (FR-020).
CREATE TABLE IF NOT EXISTS run_turns (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    attacker_message TEXT NOT NULL,                             -- masked before storing (FR-021)
    reply_text TEXT,                                            -- masked and cut; null if the send failed
    reply_truncated INTEGER NOT NULL DEFAULT 0,
    judge_verdict TEXT, judge_reason TEXT, judge_progress TEXT,
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
    run_order INTEGER                            -- 1 or 2; set when the arm starts
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
        """Additive migrations. New tables (v2 canaries/runs, v3 turns, v5 report_recommendations) come from the
        schema script (CREATE IF NOT EXISTS); the version-3 columns (adaptive) and version-4 columns (experience)
        on the existing tables are ALTER-added for an older database (R9). Version 5 adds only a new table."""
        row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = None if row is None else row["value"]
        if current == SCHEMA_VERSION:
            return
        if current is not None and current not in ("1", "2", "3", "4", "5"):
            raise UnknownSchemaVersion(
                f"This database is at schema version {current}, but this Kestrel understands {SCHEMA_VERSION}.")
        # An older database may lack the adaptive (v3) and experience (v4) columns on `runs`; add any missing.
        run_columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        for column, ddl in ADAPTIVE_RUN_COLUMNS + EXPERIENCE_RUN_COLUMNS:
            if column not in run_columns:
                db.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
        # The v4 purpose description on `targets`.
        target_columns = {r["name"] for r in db.execute("PRAGMA table_info(targets)")}
        if "description" not in target_columns:
            db.execute("ALTER TABLE targets ADD COLUMN description TEXT")
        if current is None:
            db.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        else:
            db.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (SCHEMA_VERSION,))

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
                  use_prior_experience: bool = True) -> int:
        """Write the row before anything is sent, so a crash still leaves evidence an attack went out (R10).

        Adaptive runs pass mode='adaptive' with the attacker model and the budgets they were allowed (FR-015)."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            try:
                cursor = db.execute(
                    "INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                    " attacker_source, status, started_at, mode, attacker_model, turn_budget, token_budget,"
                    " time_limit_s, use_prior_experience) VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, ?,"
                    " ?, ?)",
                    (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category, attacker_source,
                     utc_now(), mode, attacker_model, turn_budget, token_budget, time_limit_s,
                     int(use_prior_experience)))
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
                   tokens_used: int | None = None) -> Run:
        """Finish a run. Adaptive runs also pass how they ended and their usage (FR-012, FR-015, FR-019)."""
        with self.connect() as db:
            updated = db.execute(
                "UPDATE runs SET status = 'finished', verdict = ?, hard_evidence = ?, reason = ?, judge_used = ?,"
                " judge_model = ?, reply_text = ?, reply_truncated = ?, failure_step = ?,"
                " stopping_condition = ?, succeeded_turn = ?, turns_used = ?, tokens_used = ?, finished_at = ?"
                " WHERE id = ? AND status = 'in_progress'",
                (verdict, int(hard_evidence), reason, int(judge_used), judge_model, reply_text,
                 int(reply_truncated), failure_step, stopping_condition, succeeded_turn, turns_used,
                 tokens_used, utc_now(), run_id)).rowcount
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
                 judge_progress: str | None = None) -> None:
        """Record one conversation turn of an adaptive run (FR-020). The caller masks before calling."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO run_turns (run_id, position, attacker_message, reply_text, reply_truncated,"
                " judge_verdict, judge_reason, judge_progress, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, position, attacker_message, reply_text, int(reply_truncated), judge_verdict,
                 judge_reason, judge_progress, utc_now()))

    def list_turns(self, run_id: int) -> list[Turn]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM run_turns WHERE run_id = ? ORDER BY position", (run_id,)).fetchall()
        return [Turn(position=r["position"], attacker_message=r["attacker_message"], reply_text=r["reply_text"],
                     reply_truncated=bool(r["reply_truncated"]), judge_verdict=r["judge_verdict"],
                     judge_reason=r["judge_reason"], judge_progress=r["judge_progress"]) for r in rows]

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
                    " use_prior_experience, turn_cap, token_budget, write_back) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (experiment_id, label, arm["attacker_model"], arm["judge_model"],
                     int(arm["use_prior_experience"]), arm["turn_cap"], arm["token_budget"],
                     int(arm.get("write_back", True))))
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
                             write_back=bool(row["write_back"]), run_order=row["run_order"])

    @staticmethod
    def _experiment(row: sqlite3.Row, arms: list[ExperimentArm]) -> Experiment:
        return Experiment(id=row["id"], target_id=row["target_id"], mode=row["mode"],
                          families=tuple(json.loads(row["families"])), reps=row["reps"],
                          seed_prompt_ids=dict(json.loads(row["seed_prompt_ids"])), max_runs=row["max_runs"],
                          token_budget_total=row["token_budget_total"], wall_clock_s=row["wall_clock_s"],
                          status=row["status"], stopped_reason=row["stopped_reason"], created_at=row["created_at"],
                          started_at=row["started_at"], finished_at=row["finished_at"], arms=tuple(arms))

    def close_interrupted_runs(self) -> int:
        """Close anything a stopped process left open, so the target isn't locked by FR-010 forever (FR-031)."""
        with self.connect() as db:
            return db.execute(
                "UPDATE runs SET status = 'finished', verdict = 'unclear', stopping_condition = 'interrupted',"
                " reason = 'Kestrel stopped while this run was in progress, so it was interrupted.',"
                " finished_at = ? WHERE status = 'in_progress'", (utc_now(),)).rowcount

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
                   memory_written=None if row["memory_written"] is None else bool(row["memory_written"]))

    @staticmethod
    def _header_rows(db: sqlite3.Connection, target_id: int) -> list[sqlite3.Row]:
        return db.execute("SELECT name, value_encrypted FROM target_headers WHERE target_id = ? ORDER BY position",
                          (target_id,)).fetchall()

    @staticmethod
    def _insert_headers(db: sqlite3.Connection, target_id: int, encrypted: list[tuple[str, str]]) -> None:
        db.executemany("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (?, ?, ?, ?)",
                       [(target_id, position, name, token) for position, (name, token) in enumerate(encrypted)])
