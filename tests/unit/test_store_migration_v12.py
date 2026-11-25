"""Schema version 11 -> 12 (feature 014, the LangGraph checkpointer) is additive: five new `runs` columns
(ask_before_each_turn, is_checkpointed, attacker_prompt_id, attacker_prompt_version, last_activity_at), two new
tables for the custom checkpoint saver (checkpoints, checkpoint_writes), and one new unique index
(uq_run_turns_position) - no rebuild of any existing table. Follows the per-version convention of
test_store_migration_v11.py: a hand-written version-11 database, kept verbatim so a real v11 database's upgrade is
what is checked (014/FR-003, FR-004).
"""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import DuplicateTurnPositions, SCHEMA_VERSION, TargetStore

FEATURE = "014"

# A feature-013 (version 11) database: v10's shape plus the four new evidence tables and the two correlation
# columns on `runs`.
SCHEMA_V11 = """
CREATE TABLE targets (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
    method TEXT NOT NULL, body_template TEXT NOT NULL, response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL, terms_version TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, description TEXT);
CREATE TABLE target_headers (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, name TEXT NOT NULL, value_encrypted TEXT NOT NULL);
CREATE UNIQUE INDEX target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE target_canaries (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, value TEXT NOT NULL CHECK (length(value) >= 8), created_at TEXT NOT NULL);
CREATE UNIQUE INDEX target_canaries_value ON target_canaries (target_id, value);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL, prompt_title TEXT NOT NULL, prompt_text TEXT NOT NULL, family TEXT NOT NULL,
    owasp_category TEXT NOT NULL, attacker_source TEXT NOT NULL, status TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, verdict TEXT, hard_evidence INTEGER NOT NULL DEFAULT 0,
    reason TEXT, judge_used INTEGER NOT NULL DEFAULT 0, judge_model TEXT, failure_step TEXT,
    started_at TEXT NOT NULL, finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'single_turn' CHECK (mode IN ('single_turn', 'adaptive', 'replay')),
    attacker_model TEXT, turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER, time_limit_s INTEGER, stopping_condition TEXT,
    succeeded_turn INTEGER, use_prior_experience INTEGER NOT NULL DEFAULT 1, memory_written INTEGER,
    judge_prompt_id TEXT, judge_prompt_version TEXT,
    source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    replay_outcome TEXT CHECK (replay_outcome IS NULL OR
        replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive')),
    correlation_id TEXT,
    side_channel_status TEXT CHECK (side_channel_status IS NULL OR
        side_channel_status IN ('not_configured', 'checked', 'unavailable')));
CREATE INDEX idx_runs_target ON runs (target_id, started_at DESC);
CREATE UNIQUE INDEX uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
CREATE TABLE run_turns (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, attacker_message TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, judge_verdict TEXT, judge_reason TEXT, judge_progress TEXT,
    attacker_prompt_id TEXT, attacker_prompt_version TEXT, judge_prompt_id TEXT, judge_prompt_version TEXT,
    created_at TEXT NOT NULL);
CREATE INDEX idx_run_turns_run ON run_turns (run_id, position);
CREATE TABLE report_recommendations (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    recommendation TEXT NOT NULL, model TEXT, created_at TEXT NOT NULL);
CREATE TABLE experiments (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    mode TEXT NOT NULL, families TEXT NOT NULL, reps INTEGER NOT NULL, seed_prompt_ids TEXT NOT NULL,
    max_runs INTEGER NOT NULL, token_budget_total INTEGER NOT NULL, wall_clock_s INTEGER NOT NULL,
    status TEXT NOT NULL, stopped_reason TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE TABLE experiment_arms (
    id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    label TEXT NOT NULL, attacker_model TEXT NOT NULL, judge_model TEXT NOT NULL,
    use_prior_experience INTEGER NOT NULL, turn_cap INTEGER NOT NULL, token_budget INTEGER NOT NULL,
    write_back INTEGER NOT NULL DEFAULT 1, run_order INTEGER, prompt_arm_target TEXT, prompt_arm_version TEXT);
CREATE TABLE experiment_runs (
    id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    arm_id INTEGER NOT NULL REFERENCES experiment_arms(id) ON DELETE CASCADE, rep_index INTEGER NOT NULL,
    family TEXT NOT NULL, run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    send_ok INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE run_log (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, ts TEXT NOT NULL, event TEXT NOT NULL, record TEXT NOT NULL);
CREATE UNIQUE INDEX uq_run_log_seq ON run_log (run_id, seq);
CREATE TABLE run_evidence (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('canary_in_reply', 'instruction_override', 'unsafe_executable_output',
        'canary_in_tool_argument', 'honeypot_tool_invoked', 'canary_callback', 'protected_state_changed')),
    location TEXT NOT NULL CHECK (location IN ('reply', 'tool_call', 'callback', 'state')),
    owasp_category TEXT NOT NULL, detail TEXT NOT NULL, pattern_name TEXT, pattern_set_version TEXT,
    created_at TEXT NOT NULL);
CREATE INDEX idx_run_evidence_run ON run_evidence (run_id, turn, id);
CREATE TABLE run_planted_tokens (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('override', 'callback')), token TEXT NOT NULL, prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL, disarmed_turn INTEGER, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX uq_run_planted_tokens ON run_planted_tokens (run_id, kind);
CREATE INDEX idx_run_planted_tokens_token ON run_planted_tokens (token);
CREATE TABLE callback_hits (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    method TEXT NOT NULL, received_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX idx_callback_hits_run ON callback_hits (run_id, consumed);
CREATE TABLE target_side_channels (
    target_id INTEGER PRIMARY KEY REFERENCES targets(id) ON DELETE CASCADE,
    url TEXT NOT NULL, header_name TEXT, header_value_encrypted TEXT, honeypot_tool TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '11');
"""

NEW_RUNS_COLUMNS = ("ask_before_each_turn", "is_checkpointed", "attacker_prompt_id", "attacker_prompt_version",
                    "last_activity_at")
NEW_TABLES = ("checkpoints", "checkpoint_writes")
RUN_ROW = ("INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
           " attacker_source, status, started_at, finished_at) VALUES"
           " (?, 1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
           " 'library:1.0.0', 'finished', '2026-11-20T10:00:00Z', '2026-11-20T10:00:05Z')")


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v11_db(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V11)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-20T10:00:00Z','10',"
                   " '2026-11-20T10:00:00Z','2026-11-20T10:00:00Z')")
        db.execute(RUN_ROW, (1,))
        db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                   " (1, 1, '<turn>', '2026-11-20T10:00:01Z')")
    db.close()
    return path


def version(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def tables(path) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def columns(path, table) -> list[str]:
    db = sqlite3.connect(path)
    try:
        return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
    finally:
        db.close()


def indexes(path, table) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {row[1] for row in db.execute(f"PRAGMA index_list({table})")}
    finally:
        db.close()


def connect(path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def test_a_fresh_database_is_created_at_version_12_with_every_new_column_and_table(tmp_path, vault):  # FR-003, FR-004
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "12"
    run_columns = columns(path, "runs")
    assert set(NEW_RUNS_COLUMNS) <= set(run_columns)
    assert set(NEW_TABLES) <= tables(path)
    assert "task_path" in columns(path, "checkpoint_writes")
    assert "uq_run_turns_position" in indexes(path, "run_turns")


def test_the_two_new_columns_default_not_null_and_the_three_are_nullable(tmp_path, vault):  # FR-003
    path = tmp_path / "data" / "kestrel.db"
    store = TargetStore(path, vault)
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template="{}", response_path="$.reply", terms_version="10")
    run_id = store.claim_run(target.id, prompt_id="p", prompt_title="t", prompt_text="x", family="system_prompt_leak",
                             owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    run = store.get_run(run_id)
    assert run.ask_before_each_turn is False and run.is_checkpointed is False
    assert run.attacker_prompt_id is None and run.attacker_prompt_version is None
    assert run.last_activity_at is not None   # every claim sets it (research D26)


def test_a_v11_database_is_upgraded_additively_and_every_row_survives(v11_db, vault):  # FR-003, FR-004
    assert version(v11_db) == "11"
    before_runs_sql = connect(v11_db).execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()[0]

    store = TargetStore(v11_db, vault)

    assert version(v11_db) == SCHEMA_VERSION == "12"
    run_columns = columns(v11_db, "runs")
    assert set(NEW_RUNS_COLUMNS) <= set(run_columns)
    assert set(NEW_TABLES) <= tables(v11_db)
    run = store.get_run(1)
    assert run.ask_before_each_turn is False and run.is_checkpointed is False  # NOT NULL DEFAULT 0
    assert run.attacker_prompt_id is None and run.last_activity_at is None     # nullable, NULL on every old row
    # No rebuild happened: runs keeps its hand-written definition (ALTER appends the new columns to it).
    after_runs_sql = connect(v11_db).execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()[0]
    assert after_runs_sql.startswith(before_runs_sql.rstrip(")").rstrip())
    assert after_runs_sql.rstrip(")").rstrip().endswith("last_activity_at TEXT")
    assert [t.attacker_message for t in store.list_turns(1)] == ["<turn>"]


def test_uq_run_turns_position_refuses_a_second_row_at_the_same_position(v11_db, vault):  # FR-003, FR-004
    store = TargetStore(v11_db, vault)
    db = connect(v11_db)
    with pytest.raises(sqlite3.IntegrityError):
        with db:
            db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                       " (1, 1, '<dup>', '2026-11-20T10:00:02Z')")
    db.close()
    assert len(store.list_turns(1)) == 1


def test_migration_refuses_loudly_when_an_existing_database_already_holds_duplicate_turn_positions(tmp_path, vault):
    # 014/FR-003, FR-004: seeded by hand, bypassing every application-level guard (uq_run_turns_position does not
    # exist yet on this v11 database), so the migration's own check is what must catch it - not a bare
    # sqlite3.IntegrityError from the index statement, and not a silent partial migration.
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V11)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-20T10:00:00Z','10',"
                   " '2026-11-20T10:00:00Z','2026-11-20T10:00:00Z')")
        db.execute(RUN_ROW, (1,))
        db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                   " (1, 1, '<a>', '2026-11-20T10:00:01Z')")
        db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                   " (1, 1, '<b>', '2026-11-20T10:00:02Z')")
    db.close()

    with pytest.raises(DuplicateTurnPositions):
        TargetStore(path, vault)
    # Refused before the index was ever created, and before the schema version was bumped (never a silent
    # partial migration): the database is left exactly as it was found.
    assert version(path) == "11"
    assert "uq_run_turns_position" not in indexes(path, "run_turns")


def test_migrating_an_already_v12_database_a_second_time_is_a_no_op(v11_db, vault):  # FR-003, FR-004
    TargetStore(v11_db, vault)
    before = {name: connect(v11_db).execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
              for name in ("runs", *NEW_TABLES)}
    TargetStore(v11_db, vault)
    assert version(v11_db) == "12"
    after = {name: connect(v11_db).execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
             for name in ("runs", *NEW_TABLES)}
    assert after == before
