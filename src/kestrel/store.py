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

SCHEMA_VERSION = "12"
FAMILIES = ("direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection")
VERDICTS = ("succeeded", "failed", "unclear")
MIN_CANARY_LENGTH = 8
# Feature 010 (FR-010): a run keeps at most this many of its log lines; the rest reach the stream only, and one
# `log.truncated` marker row records how many were dropped. A constant, not a setting.
RUN_LOG_CAP = 1000
# Feature 013 (FR-072): the most callback hits the listener stores for one run row (consumed or not); a later
# request is still answered like a stored hit, stores nothing, and is logged once per run. A constant, not a setting.
CALLBACK_HITS_CAP = 100
# Feature 013: the evidence kinds (FR-004) and locations (FR-003) the run_evidence table accepts, the planted-token
# kinds, and the side-channel statuses a run row records (FR-034).
EVIDENCE_KINDS = ("canary_in_reply", "instruction_override", "unsafe_executable_output", "canary_in_tool_argument",
                  "honeypot_tool_invoked", "canary_callback", "protected_state_changed")
EVIDENCE_LOCATIONS = ("reply", "tool_call", "callback", "state")
PLANTED_TOKEN_KINDS = ("override", "callback")
SIDE_CHANNEL_STATUSES = ("not_configured", "checked", "unavailable")

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
        replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive')),  -- null unless mode = 'replay'
    -- Added in schema version 11 (feature 013): the side channel's per-run correlation id and how it fared.
    correlation_id TEXT,                                          -- null unless the target had a side channel
    side_channel_status TEXT CHECK (side_channel_status IS NULL OR
        side_channel_status IN ('not_configured', 'checked', 'unavailable')),  -- null (pre-013) reads as not_configured
    -- Added in schema version 12 (feature 014, checkpointer and approve node). Whether this run was started with
    -- "Ask before each turn" ticked, captured once at claim time, never rewritten (research D5) — the checkpoint's
    -- own state is the only live answer to "is it still asking".
    ask_before_each_turn INTEGER NOT NULL DEFAULT 0,
    -- Whether this run was claimed through the live, checkpointed run-start path (research D22) — never set by a
    -- single-turn claim, a replay claim, an experiment repetition's claim, a resume or a decision.
    is_checkpointed INTEGER NOT NULL DEFAULT 0,
    -- The attacker prompt reference this run is pinned to, recorded at claim time (research D16); a resumed or
    -- decided run's attacker client is rebuilt against exactly this reference, never whatever is currently active.
    attacker_prompt_id TEXT, attacker_prompt_version TEXT,
    -- This run's idle clock (research D26): set at claim, updated only on an accepted lease release. Nullable only
    -- because a pre-migration row never had one; every row this feature itself claims always sets it.
    last_activity_at TEXT
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

-- Added in schema version 11 (feature 013, behavioural evidence): additive only, no rebuild (FR-057).
-- One row per evidence item: a deterministic finding on one turn of a run (FR-003, FR-004, FR-007).
CREATE TABLE IF NOT EXISTS run_evidence (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL,                             -- 1 for a single-turn run
    kind TEXT NOT NULL CHECK (kind IN ('canary_in_reply', 'instruction_override', 'unsafe_executable_output',
        'canary_in_tool_argument', 'honeypot_tool_invoked', 'canary_callback', 'protected_state_changed')),
    location TEXT NOT NULL CHECK (location IN ('reply', 'tool_call', 'callback', 'state')),
    owasp_category TEXT NOT NULL,                      -- the kind's class, or the family's for canary_in_reply
    detail TEXT NOT NULL,                              -- non-secret (FR-007): never a token, a URL or a state value
    pattern_name TEXT,                                 -- unsafe_executable_output only: the stable pattern name
    pattern_set_version TEXT,                          -- unsafe_executable_output only: the set version it fired under
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_evidence_run ON run_evidence (run_id, turn, id);
-- What a run planted, and whether its override token is still armed (FR-008, FR-012, FR-028, FR-035).
CREATE TABLE IF NOT EXISTS run_planted_tokens (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('override', 'callback')),
    token TEXT NOT NULL,                               -- override: the joined form; callback: the URL's last segment
    prompt_id TEXT NOT NULL,                           -- the task template that planted it
    prompt_version TEXT NOT NULL,
    disarmed_turn INTEGER,                             -- override only: the turn whose sent message held the joined
    created_at TEXT NOT NULL                           --   form; null = armed; copied as-is to a replay
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_planted_tokens ON run_planted_tokens (run_id, kind);
CREATE INDEX IF NOT EXISTS idx_run_planted_tokens_token ON run_planted_tokens (token);
-- Requests the callback listener accepted for a run in progress (FR-029, FR-030, FR-072).
CREATE TABLE IF NOT EXISTS callback_hits (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    method TEXT NOT NULL,                              -- 'GET' | 'POST' | 'PUT' | 'HEAD'
    received_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0                -- 1 once a turn's check turned it into an evidence item
);
CREATE INDEX IF NOT EXISTS idx_callback_hits_run ON callback_hits (run_id, consumed);
-- The optional side channel of a target (FR-019); the header value is a Fernet token, never returned by the API.
CREATE TABLE IF NOT EXISTS target_side_channels (
    target_id INTEGER PRIMARY KEY REFERENCES targets(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    header_name TEXT,                                  -- null = no auth header
    header_value_encrypted TEXT,
    honeypot_tool TEXT,                                -- null = no honeypot check
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Added in schema version 12 (feature 014): the custom checkpoint saver's own two tables, covering LangGraph's
-- full checkpoint-tuple shape (config, checkpoint, metadata, parent_config, pending_writes). No foreign key to
-- runs: thread_id is a plain text column (str(run_id)); reconciliation and deletion are Kestrel's own
-- responsibility (research D11), not ON DELETE CASCADE's.
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT NOT NULL,                      -- self.serde.dumps_typed(checkpoint)'s own type tag
    checkpoint BLOB NOT NULL,
    metadata BLOB NOT NULL,                  -- includes kestrel_graph_version (research D18)
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints (thread_id, checkpoint_ns, checkpoint_id DESC);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,                    -- negative for a control write (upserted); >= 0 for a regular write
                                              --   (inserted only if absent, research D10)
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    task_path TEXT NOT NULL DEFAULT '',      -- ordering only (research D10); not part of the primary key
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
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

# Columns added to `runs` in version 11 (feature 013); ALTER-added for an older database, the v3/v4/v7 way (the
# ALTER form omits the CHECK on `side_channel_status`; the base schema carries it, and code only writes valid values).
EVIDENCE_RUN_COLUMNS = (("correlation_id", "TEXT"), ("side_channel_status", "TEXT"))

# Columns added to `runs` in version 12 (feature 014); ALTER-added for an older database, the same way.
CHECKPOINT_RUN_COLUMNS = (
    ("ask_before_each_turn", "INTEGER NOT NULL DEFAULT 0"), ("is_checkpointed", "INTEGER NOT NULL DEFAULT 0"),
    ("attacker_prompt_id", "TEXT"), ("attacker_prompt_version", "TEXT"), ("last_activity_at", "TEXT"),
)


class DuplicateTurnPositions(Exception):
    """Schema 12 migration found a duplicate (run_id, position) pair in run_turns before it could create
    uq_run_turns_position (research D6); this database needs manual inspection before it can be opened."""


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
    # Version 11 (feature 013): the side channel's per-run correlation id and status; None on a pre-013 row, which
    # reads as "not_configured" (FR-034).
    correlation_id: str | None = None
    side_channel_status: str | None = None
    # Version 12 (feature 014): the checkpointer and the approve node.
    ask_before_each_turn: bool = False
    is_checkpointed: bool = False
    attacker_prompt_id: str | None = None
    attacker_prompt_version: str | None = None
    last_activity_at: str | None = None   # research D26 - this run's own idle clock


@dataclass(frozen=True)
class PlantedToken:
    """What a run planted in its opening message (feature 013): an override token (the joined form) or a callback
    token (the URL's last segment), the template version that planted it, and whether it is still armed
    (`disarmed_turn` is None). A replay carries its source's rows, armed state included (FR-035)."""
    kind: str                 # "override" | "callback"
    token: str
    prompt_id: str            # "override_task" | "callback_task"
    prompt_version: str
    disarmed_turn: int | None = None
    created_at: str | None = None

    @property
    def armed(self) -> bool:
        return self.disarmed_turn is None

    @property
    def prompt_ref(self) -> str:
        return f"{self.prompt_id}@{self.prompt_version}"

    def __repr__(self) -> str:   # the value is evidence material, not a credential, but never belongs in a log
        return (f"PlantedToken(kind={self.kind!r}, prompt={self.prompt_ref!r}, armed={self.armed}, "
                f"disarmed_turn={self.disarmed_turn!r})")


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


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now() -> str:
    return _iso(datetime.now(timezone.utc))


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
        second time to widen the `mode` CHECK and add `source_run_id`/`replay_outcome`. Version 11 (feature 013)
        is additive again: four new tables from the schema script and two nullable `runs` columns ALTER-added
        below (FR-057) - no rebuild, so the v9/v10 helpers stay the no-ops they already are for a v10 database.
        Version 12 (feature 014) is additive too: the checkpoint saver's own two tables come from the schema
        script (idempotent CREATE TABLE IF NOT EXISTS); five more `runs` columns are ALTER-added below the same
        way; and uq_run_turns_position is created here, after a check that refuses to start loudly if an existing
        database already holds a duplicate (run_id, position) pair in run_turns - never in the schema script,
        which runs unconditionally above before this check could ever see one."""
        row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = None if row is None else row["value"]
        if current == SCHEMA_VERSION:
            return
        if current is not None and current not in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"):
            raise UnknownSchemaVersion(
                f"This database is at schema version {current}, but this Kestrel understands {SCHEMA_VERSION}.")
        # An older database may lack the adaptive (v3), experience (v4), prompt-version (v7), evidence (v11) and
        # checkpointer (v12) columns on `runs`.
        run_columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        for column, ddl in (ADAPTIVE_RUN_COLUMNS + EXPERIENCE_RUN_COLUMNS + PROMPT_RUNS_COLUMNS
                            + EVIDENCE_RUN_COLUMNS + CHECKPOINT_RUN_COLUMNS):
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
        TargetStore._check_no_duplicate_turn_positions(db)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_run_turns_position ON run_turns (run_id, position)")
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

    @staticmethod
    def _check_no_duplicate_turn_positions(db: sqlite3.Connection) -> None:
        """Schema 12 (research D6): refuse loudly, before uq_run_turns_position is ever created, if an existing
        database already holds a duplicate (run_id, position) pair in run_turns (not reachable through any code
        path this project has ever shipped, but not provably impossible either) - never a bare
        sqlite3.IntegrityError from the index statement itself, and never a silent guess at which duplicate row
        to keep."""
        duplicate = db.execute(
            "SELECT run_id, position FROM run_turns GROUP BY run_id, position HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise DuplicateTurnPositions(
                f"schema 12 migration found duplicate (run_id, position) rows in run_turns "
                f"(run_id={duplicate['run_id']}, position={duplicate['position']}) and refuses to start - this "
                f"database needs manual inspection before it can be opened.")

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
        """Remove the target; its header rows go with it (ON DELETE CASCADE, overwritten by secure_delete). Its
        runs' own checkpoint threads are deleted first (feature 014, research D11): the checkpoint tables carry
        no foreign key of their own, so cascading the target's runs away would otherwise leave them orphaned."""
        self.delete_checkpoints_for_target(target_id)
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
                  use_prior_experience: bool = True, source_run_id: int | None = None,
                  correlation_id: str | None = None, side_channel_status: str = "not_configured",
                  ask_before_each_turn: bool = False, is_checkpointed: bool = False,
                  attacker_prompt_id: str | None = None, attacker_prompt_version: str | None = None,
                  judge_model: str | None = None, judge_prompt_id: str | None = None,
                  judge_prompt_version: str | None = None, now: datetime | None = None) -> int:
        """Write the row before anything is sent, so a crash still leaves evidence an attack went out (R10).

        Adaptive runs pass mode='adaptive' with the attacker model and the budgets they were allowed (FR-015). A
        replay (feature 012) passes mode='replay' and source_run_id naming the run it re-tests. A run on a target
        with a side channel (feature 013) passes its correlation id and `side_channel_status='checked'`; the
        status is written here, at claim time, so a crashed or interrupted run never leaves it null (013/FR-034).

        Feature 014: only the live, checkpointed run-start path ever passes `is_checkpointed=True` or the
        provenance-pin keywords (research D16, D22); every other caller leaves them at their defaults.
        `ask_before_each_turn=True` is rejected outright for any mode other than 'adaptive' (research D5) - the
        API layer turns this into its own 422. `now` (research D26) defaults to the real wall clock; the live
        run-start path passes `now=app_state.clock()` explicitly, so `last_activity_at` agrees with whatever
        clock a test has substituted for it."""
        if side_channel_status not in SIDE_CHANNEL_STATUSES:
            raise ValueError(f"side_channel_status must be one of {SIDE_CHANNEL_STATUSES}, "
                             f"not {side_channel_status!r}.")
        if ask_before_each_turn and mode != "adaptive":
            raise ValueError("ask_before_each_turn=True is only valid for mode='adaptive'.")
        last_activity_at = _iso(now) if now is not None else utc_now()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            try:
                cursor = db.execute(
                    "INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                    " attacker_source, status, started_at, mode, attacker_model, turn_budget, token_budget,"
                    " time_limit_s, use_prior_experience, source_run_id, correlation_id, side_channel_status,"
                    " ask_before_each_turn, is_checkpointed, attacker_prompt_id, attacker_prompt_version,"
                    " judge_model, judge_prompt_id, judge_prompt_version, last_activity_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                    " ?)",
                    (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category, attacker_source,
                     utc_now(), mode, attacker_model, turn_budget, token_budget, time_limit_s,
                     int(use_prior_experience), source_run_id, correlation_id, side_channel_status,
                     int(ask_before_each_turn), int(is_checkpointed), attacker_prompt_id, attacker_prompt_version,
                     judge_model, judge_prompt_id, judge_prompt_version, last_activity_at))
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

    # ---- behavioural evidence (feature 013): items, planted tokens and the side-channel status ----

    def set_side_channel_status(self, run_id: int, status: str) -> None:
        """The one in-run update of a run's side-channel status (013/FR-034): `checked` -> `unavailable` on the
        first failed side-channel request. `finish_run` leaves the column alone."""
        if status not in SIDE_CHANNEL_STATUSES:
            raise ValueError(f"status must be one of {SIDE_CHANNEL_STATUSES}, not {status!r}.")
        with self.connect() as db:
            if db.execute("UPDATE runs SET side_channel_status = ? WHERE id = ?", (status, run_id)).rowcount == 0:
                raise LookupError(f"No run with id {run_id}.")

    def add_evidence(self, run_id: int, items) -> None:
        """Insert one `run_evidence` row per evidence item, in the order given (013/FR-003). The caller builds the
        items with non-secret details only (013/FR-007); the table's CHECKs refuse an unknown kind or location."""
        now = utc_now()
        with self.connect() as db:
            db.executemany(
                "INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, pattern_name,"
                " pattern_set_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, item.turn, item.kind, item.location, item.owasp_category, item.detail,
                  item.pattern_name, item.pattern_set_version, now) for item in items])

    def list_evidence(self, run_id: int) -> list:
        """A run's evidence items by `(turn, id)` — the order they were found in (013/FR-003)."""
        from kestrel.evidence.model import EvidenceItem   # the store stays importable without the package's callers
        with self.connect() as db:
            rows = db.execute("SELECT * FROM run_evidence WHERE run_id = ? ORDER BY turn, id", (run_id,)).fetchall()
        return [EvidenceItem(kind=r["kind"], turn=r["turn"], location=r["location"],
                             owasp_category=r["owasp_category"], detail=r["detail"], pattern_name=r["pattern_name"],
                             pattern_set_version=r["pattern_set_version"], created_at=r["created_at"]) for r in rows]

    def evidence_kinds_by_run(self, target_id: int) -> dict[int, list[str]]:
        """Every run of this target that has evidence items: `{run_id: [distinct kinds, detection order]}`, in one
        query for the whole target — for the run list (013/FR-038, FR-040)."""
        order = {kind: index for index, kind in enumerate(EVIDENCE_KINDS)}
        with self.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT run_evidence.run_id AS run_id, run_evidence.kind AS kind FROM run_evidence"
                " JOIN runs ON runs.id = run_evidence.run_id WHERE runs.target_id = ?", (target_id,)).fetchall()
        out: dict[int, list[str]] = {}
        for row in rows:
            out.setdefault(int(row["run_id"]), []).append(row["kind"])
        return {run_id: sorted(kinds, key=lambda kind: order.get(kind, len(order))) for run_id, kinds in out.items()}

    def evidence_counts_by_run(self, target_id: int) -> dict[int, int]:
        """How many evidence items each run of this target carries — the companion of `evidence_kinds_by_run`,
        one query for the whole target, for the run list's `evidence_count` (013/FR-038)."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT run_evidence.run_id AS run_id, COUNT(*) AS n FROM run_evidence"
                " JOIN runs ON runs.id = run_evidence.run_id WHERE runs.target_id = ?"
                " GROUP BY run_evidence.run_id", (target_id,)).fetchall()
        return {int(row["run_id"]): int(row["n"]) for row in rows}

    def add_planted_token(self, run_id: int, *, kind: str, token: str, prompt_id: str, prompt_version: str) -> None:
        """Record what a run planted (013/FR-008, FR-028); a second token of the same kind on one run is refused by
        the unique index (a run plants at most one of each)."""
        if kind not in PLANTED_TOKEN_KINDS:
            raise ValueError(f"kind must be one of {PLANTED_TOKEN_KINDS}, not {kind!r}.")
        with self.connect() as db:
            db.execute("INSERT INTO run_planted_tokens (run_id, kind, token, prompt_id, prompt_version, created_at)"
                       " VALUES (?, ?, ?, ?, ?, ?)", (run_id, kind, token, prompt_id, prompt_version, utc_now()))

    def list_planted_tokens(self, run_id: int) -> list[PlantedToken]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM run_planted_tokens WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [PlantedToken(kind=r["kind"], token=r["token"], prompt_id=r["prompt_id"],
                             prompt_version=r["prompt_version"], disarmed_turn=r["disarmed_turn"],
                             created_at=r["created_at"]) for r in rows]

    def disarm_planted_token(self, run_id: int, kind: str, turn: int) -> None:
        """Record the turn a token was disarmed from (013/FR-012, FR-035): a value only ever moves toward an
        earlier turn — a later call for a later turn is a no-op — so a replay's copy, inherited disarmed from its
        source's turn k, can be disarmed earlier by its own re-sent message but never re-armed or pushed back."""
        with self.connect() as db:
            db.execute("UPDATE run_planted_tokens SET disarmed_turn = ? WHERE run_id = ? AND kind = ?"
                       " AND (disarmed_turn IS NULL OR disarmed_turn > ?)", (turn, run_id, kind, turn))

    def copy_planted_tokens(self, source_run_id: int, replay_run_id: int) -> int:
        """Copy every planted-token row of the source to the replay, `disarmed_turn` carried across unchanged
        (013/FR-035): a token the source disarmed is disarmed on the replay from that same turn. Returns the count."""
        with self.connect() as db:
            rows = db.execute("SELECT kind, token, prompt_id, prompt_version, disarmed_turn FROM run_planted_tokens"
                              " WHERE run_id = ? ORDER BY id", (source_run_id,)).fetchall()
            now = utc_now()
            db.executemany(
                "INSERT INTO run_planted_tokens (run_id, kind, token, prompt_id, prompt_version, disarmed_turn,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(replay_run_id, r["kind"], r["token"], r["prompt_id"], r["prompt_version"], r["disarmed_turn"], now)
                 for r in rows])
        return len(rows)

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

    def has_turn(self, run_id: int, position: int) -> bool:
        """A point lookup against uq_run_turns_position (feature 014, research D6): whether this turn's row
        already exists, so the lifted record step can skip an already-recorded write without re-reading it."""
        with self.connect() as db:
            return db.execute("SELECT 1 FROM run_turns WHERE run_id = ? AND position = ?",
                              (run_id, position)).fetchone() is not None

    def add_turn_with_evidence(self, run_id: int, *, position: int, attacker_message: str,
                               reply_text: str | None = None, reply_truncated: bool = False,
                               judge_verdict: str | None = None, judge_reason: str | None = None,
                               judge_progress: str | None = None, attacker_prompt_id: str | None = None,
                               attacker_prompt_version: str | None = None, judge_prompt_id: str | None = None,
                               judge_prompt_version: str | None = None, evidence_items=()) -> None:
        """The turn row and its evidence items (if any), in one atomic transaction (feature 014, research D6):
        either both exist or neither does, even under an interruption immediately after. Idempotent: a second call
        for the same (run_id, position) is a no-op (uq_run_turns_position's own point lookup, inside the same
        transaction, so a retried caller can never duplicate either)."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM run_turns WHERE run_id = ? AND position = ?",
                          (run_id, position)).fetchone() is not None:
                return
            db.execute(
                "INSERT INTO run_turns (run_id, position, attacker_message, reply_text, reply_truncated,"
                " judge_verdict, judge_reason, judge_progress, attacker_prompt_id, attacker_prompt_version,"
                " judge_prompt_id, judge_prompt_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, position, attacker_message, reply_text, int(reply_truncated), judge_verdict,
                 judge_reason, judge_progress, attacker_prompt_id, attacker_prompt_version, judge_prompt_id,
                 judge_prompt_version, utc_now()))
            if evidence_items:
                now = utc_now()
                db.executemany(
                    "INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, pattern_name,"
                    " pattern_set_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(run_id, item.turn, item.kind, item.location, item.owasp_category, item.detail,
                      item.pattern_name, item.pattern_set_version, now) for item in evidence_items])

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

    def highest_log_seq(self, run_id: int) -> int:
        """The highest kept-line seq already stored for this run, or 0 (feature 014, research D20): a resumed or
        decided segment's own kept-line counter starts from here, never restarting the run's own sequence."""
        with self.connect() as db:
            row = db.execute("SELECT MAX(seq) AS m FROM run_log WHERE run_id = ?", (run_id,)).fetchone()
        return int(row["m"]) if row is not None and row["m"] is not None else 0

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

    # ---- the checkpointer and the idle clock (feature 014) ----

    def touch_last_activity(self, run_id: int, *, now: datetime | None = None) -> None:
        """This run's idle clock (research D26), updated only by an accepted execution-lease release."""
        with self.connect() as db:
            db.execute("UPDATE runs SET last_activity_at = ? WHERE id = ?",
                      (_iso(now) if now is not None else utc_now(), run_id))

    def delete_checkpoint(self, run_id: int) -> None:
        """Delete this run's checkpoint rows from both tables (research D11); a no-op if none exist."""
        thread_id = str(run_id)
        with self.connect() as db:
            db.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,))
            db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))

    def delete_checkpoints_for_target(self, target_id: int) -> None:
        """Delete every checkpoint thread belonging to this target's own run ids (research D11) - called before
        deleting the target itself, since the checkpoint tables carry no foreign key of their own."""
        with self.connect() as db:
            run_ids = [str(row["id"]) for row in db.execute("SELECT id FROM runs WHERE target_id = ?", (target_id,))]
        if not run_ids:
            return
        placeholders = ",".join("?" * len(run_ids))
        with self.connect() as db:
            db.execute(f"DELETE FROM checkpoint_writes WHERE thread_id IN ({placeholders})", run_ids)
            db.execute(f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})", run_ids)

    def list_in_progress_checkpointed_runs(self) -> list[Run]:
        """Every row the start-up sweep's own classification (and the periodic idle-stop check) must inspect
        (feature 014): in_progress, is_checkpointed, mode == 'adaptive' - the one and only classification input
        (research D22)."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE status = 'in_progress' AND is_checkpointed = 1"
                " AND mode = 'adaptive'").fetchall()
        return [self._run(row) for row in rows]

    def list_checkpoint_thread_ids(self) -> set[str]:
        """Every thread_id with at least one row in `checkpoints` (feature 014): the start-up sweep's own input
        for finding an orphaned checkpoint whose `runs` row is not currently in_progress at all."""
        with self.connect() as db:
            return {row["thread_id"] for row in db.execute("SELECT DISTINCT thread_id FROM checkpoints")}

    def close_non_checkpointed_interrupted_runs(self) -> int:
        """The start-up sweep's own pre-existing, unconditional close (feature 014, FR-013): every in_progress row
        that is not a live, checkpointed adaptive run - every non-adaptive mode, every row not claimed through the
        live run-start path - closed exactly as `close_interrupted_runs` already closes every row. A checkpointed
        adaptive row is left untouched here; the async, classifying sweep (api/main.py's lifespan) decides its
        fate instead."""
        with self.connect() as db:
            return db.execute(
                "UPDATE runs SET status = 'finished', verdict = 'unclear', stopping_condition = 'interrupted',"
                " reason = 'Kestrel stopped while this run was in progress, so it was interrupted.',"
                " replay_outcome = CASE WHEN mode = 'replay' THEN 'inconclusive' ELSE replay_outcome END,"
                " finished_at = ? WHERE status = 'in_progress' AND NOT (is_checkpointed = 1 AND mode = 'adaptive')",
                (utc_now(),)).rowcount

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
                   source_run_id=row["source_run_id"], replay_outcome=row["replay_outcome"],
                   correlation_id=row["correlation_id"], side_channel_status=row["side_channel_status"],
                   ask_before_each_turn=bool(row["ask_before_each_turn"]), is_checkpointed=bool(row["is_checkpointed"]),
                   attacker_prompt_id=row["attacker_prompt_id"], attacker_prompt_version=row["attacker_prompt_version"],
                   last_activity_at=row["last_activity_at"])

    @staticmethod
    def _header_rows(db: sqlite3.Connection, target_id: int) -> list[sqlite3.Row]:
        return db.execute("SELECT name, value_encrypted FROM target_headers WHERE target_id = ? ORDER BY position",
                          (target_id,)).fetchall()

    @staticmethod
    def _insert_headers(db: sqlite3.Connection, target_id: int, encrypted: list[tuple[str, str]]) -> None:
        db.executemany("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (?, ?, ?, ?)",
                       [(target_id, position, name, token) for position, (name, token) in enumerate(encrypted)])
