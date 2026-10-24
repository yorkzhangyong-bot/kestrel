"""Saved targets in one SQLite file, through the standard-library sqlite3 module, no ORM (data-model.md; research R6).

Rules the database can't check (URL, template and header rules, value length) are enforced by the API before saving.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from kestrel.secrets import Vault

SCHEMA_VERSION = "3"
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
    updated_at TEXT NOT NULL
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
    succeeded_turn INTEGER                                       -- the turn it succeeded at, or null (FR-019)
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
"""

# Columns added to `runs` in version 3; ALTER-added for a version-2 database (fresh ones get them from SCHEMA).
# The ALTER form omits the CHECK on `mode`; the base schema carries it, and code only ever writes valid modes.
ADAPTIVE_RUN_COLUMNS = (
    ("mode", "TEXT NOT NULL DEFAULT 'single_turn'"),
    ("attacker_model", "TEXT"), ("turn_budget", "INTEGER"), ("turns_used", "INTEGER"),
    ("token_budget", "INTEGER"), ("tokens_used", "INTEGER"), ("time_limit_s", "INTEGER"),
    ("stopping_condition", "TEXT"), ("succeeded_turn", "INTEGER"),
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
        """Additive migrations. New tables come from the schema script (CREATE IF NOT EXISTS); the version-3
        columns on the existing `runs` table are ALTER-added for a version-2 database (R9)."""
        row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = None if row is None else row["value"]
        if current == SCHEMA_VERSION:
            return
        if current is not None and current not in ("1", "2"):
            raise UnknownSchemaVersion(
                f"This database is at schema version {current}, but this Kestrel understands {SCHEMA_VERSION}.")
        # A version-2 database already has `runs` without the adaptive columns; add any that are missing.
        present = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        for column, ddl in ADAPTIVE_RUN_COLUMNS:
            if column not in present:
                db.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
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
                      response_path: str, terms_version: str) -> Target:
        now = utc_now()
        try:
            with self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                    " permission_confirmed_at, terms_version, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, name.casefold(), url, method, body_template, response_path, now, terms_version, now, now))
                target_id = cursor.lastrowid
                self._insert_headers(db, target_id, [(n, self._vault.encrypt(v)) for n, v in headers])
        except sqlite3.IntegrityError as error:
            if "name_key" in str(error):
                raise NameTaken(name) from None
            raise
        return self.get_target(target_id)

    def update_target(self, target_id: int, *, name: str, url: str, method: str,
                      headers: list[tuple[str, str | None]], body_template: str, response_path: str,
                      terms_version: str) -> Target:
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
                    " response_path = ?, permission_confirmed_at = ?, terms_version = ?, updated_at = ? WHERE id = ?",
                    (name, name.casefold(), url, method, body_template, response_path,
                     now if renewed else row["permission_confirmed_at"], terms_version, now, target_id))
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
                      created_at=row["created_at"], updated_at=row["updated_at"], headers=headers)

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
                  token_budget: int | None = None, time_limit_s: int | None = None) -> int:
        """Write the row before anything is sent, so a crash still leaves evidence an attack went out (R10).

        Adaptive runs pass mode='adaptive' with the attacker model and the budgets they were allowed (FR-015)."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            try:
                cursor = db.execute(
                    "INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                    " attacker_source, status, started_at, mode, attacker_model, turn_budget, token_budget,"
                    " time_limit_s) VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, ?, ?)",
                    (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category, attacker_source,
                     utc_now(), mode, attacker_model, turn_budget, token_budget, time_limit_s))
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
                   succeeded_turn=row["succeeded_turn"])

    @staticmethod
    def _header_rows(db: sqlite3.Connection, target_id: int) -> list[sqlite3.Row]:
        return db.execute("SELECT name, value_encrypted FROM target_headers WHERE target_id = ? ORDER BY position",
                          (target_id,)).fetchall()

    @staticmethod
    def _insert_headers(db: sqlite3.Connection, target_id: int, encrypted: list[tuple[str, str]]) -> None:
        db.executemany("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (?, ?, ?, ?)",
                       [(target_id, position, name, token) for position, (name, token) in enumerate(encrypted)])
