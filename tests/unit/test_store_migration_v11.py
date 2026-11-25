"""Schema version 10 -> 11 (feature 013) is additive: four new tables (run_evidence, run_planted_tokens,
callback_hits, target_side_channels) and two nullable `runs` columns (correlation_id, side_channel_status), with no
rebuild of any existing table (FR-057). Follows the per-version convention of test_store_migration_v10.py: a
hand-written version-10 database, kept verbatim so a real v10 database's upgrade is what is checked."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore

FEATURE = "013"

# A feature-012 (version 10) database: v9's shape plus the widened `mode` CHECK and the two replay columns.
SCHEMA_V10 = """
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
        replay_outcome IN ('fixed', 'still_vulnerable', 'inconclusive')));
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
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '10');
"""

NEW_TABLES = ("run_evidence", "run_planted_tokens", "callback_hits", "target_side_channels")
RUN_ROW = ("INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
           " attacker_source, status, verdict, hard_evidence, started_at, finished_at) VALUES"
           " (?, 1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
           " 'library:1.0.0', 'finished', ?, ?, '2026-11-20T10:00:00Z', '2026-11-20T10:00:05Z')")


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v10_db(tmp_path, vault):
    """A feature-012 database: one target, two finished runs (ids 1 and 2, then 3 deleted so the sequence sits
    above the surviving ids), and one row in each table that references `runs`."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V10)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-20T10:00:00Z','10',"
                   " '2026-11-20T10:00:00Z','2026-11-20T10:00:00Z')")
        db.execute(RUN_ROW, (1, "succeeded", 1))
        db.execute(RUN_ROW, (2, "failed", 0))
        db.execute(RUN_ROW, (3, "failed", 0))
        db.execute("DELETE FROM runs WHERE id = 3")   # AUTOINCREMENT keeps sqlite_sequence at 3
        db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                   " (1, 1, '<turn>', '2026-11-20T10:00:01Z')")
        db.execute("INSERT INTO report_recommendations (run_id, recommendation, model, created_at) VALUES"
                   " (1, 'Harden.', 'm', '2026-11-20T10:00:06Z')")
        db.execute("INSERT INTO run_log (run_id, seq, ts, event, record) VALUES"
                   " (1, 1, '2026-11-20T10:00:00Z', 'run.start', '{\"event\": \"run.start\"}')")
        db.execute("INSERT INTO experiments (target_id, mode, families, reps, seed_prompt_ids, max_runs,"
                   " token_budget_total, wall_clock_s, status, created_at) VALUES"
                   " (1, 'single_turn', '[\"tool_exfiltration\"]', 1, '{}', 50, 500000, 3600, 'finished',"
                   " '2026-11-20T10:00:00Z')")
        db.execute("INSERT INTO experiment_arms (experiment_id, label, attacker_model, judge_model,"
                   " use_prior_experience, turn_cap, token_budget) VALUES (1, 'A', 'm', 'j', 1, 6, 40000)")
        db.execute("INSERT INTO experiment_runs (experiment_id, arm_id, rep_index, family, run_id, created_at)"
                   " VALUES (1, 1, 0, 'tool_exfiltration', 2, '2026-11-20T10:01:00Z')")
    db.close()
    return path


def version(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def table_sql(path, name) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
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


def foreign_key_violations(path) -> list:
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        return db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        db.close()


def runs_sequence(path) -> int | None:
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'runs'").fetchone()
        return None if row is None else row[0]
    finally:
        db.close()


def connect(path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def test_a_fresh_database_is_created_at_version_11_with_the_four_tables(tmp_path, vault):  # FR-057
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "12"
    assert set(NEW_TABLES) <= tables(path)
    assert {"correlation_id", "side_channel_status"} <= set(columns(path, "runs"))
    assert {"pattern_name", "pattern_set_version"} <= set(columns(path, "run_evidence"))


def test_a_v10_database_is_upgraded_additively_and_every_row_survives(v10_db, vault):  # FR-057
    assert version(v10_db) == "10"
    runs_sql_before = table_sql(v10_db, "runs")
    sequence_before = runs_sequence(v10_db)
    assert sequence_before == 3

    store = TargetStore(v10_db, vault)

    assert version(v10_db) == SCHEMA_VERSION == "12"
    assert foreign_key_violations(v10_db) == []
    assert set(NEW_TABLES) <= tables(v10_db)
    assert {"pattern_name", "pattern_set_version"} <= set(columns(v10_db, "run_evidence"))
    # Both new columns are ALTER-added, nullable, and NULL on every pre-existing row.
    runs = {r.id: r for r in store.list_runs(1)}
    assert set(runs) == {1, 2}
    assert runs[1].correlation_id is None and runs[1].side_channel_status is None
    assert runs[2].correlation_id is None and runs[2].side_channel_status is None
    assert runs[1].verdict == "succeeded" and runs[1].hard_evidence is True
    # No rebuild happened: the table keeps its hand-written definition (ALTER appends the two columns to it), the
    # sqlite_sequence watermark is untouched, and every child row is exactly where it was.
    runs_sql_after = table_sql(v10_db, "runs")
    assert runs_sql_after.startswith(runs_sql_before.rstrip(")").rstrip())
    assert runs_sql_after.rstrip(")").rstrip().endswith("last_activity_at TEXT")   # the last column v12 ALTER-adds
    assert runs_sequence(v10_db) == sequence_before
    assert [t.attacker_message for t in store.list_turns(1)] == ["<turn>"]
    assert store.get_recommendation(1).recommendation == "Harden."
    assert [line.event for line in store.list_log_lines(1)] == ["run.start"]
    assert store.experiment_run_links(1)[0].run_id == 2


def test_the_evidence_table_checks_its_kind_and_location(v10_db, vault):  # FR-003, FR-004, FR-057
    TargetStore(v10_db, vault)
    db = connect(v10_db)
    with db:
        db.execute("INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, pattern_name,"
                   " pattern_set_version, created_at) VALUES (1, 1, 'unsafe_executable_output', 'reply',"
                   " 'LLM05: Improper Output Handling', 'd', 'a_pattern', '1', '2026-11-20T10:00:04Z')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, created_at)"
                       " VALUES (1, 1, 'bogus_kind', 'reply', 'LLM01: Prompt Injection', 'd', '2026-11-20T10:00:04Z')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, created_at)"
                       " VALUES (1, 1, 'canary_in_reply', 'nowhere', 'LLM01: Prompt Injection', 'd',"
                       " '2026-11-20T10:00:04Z')")
    rows = db.execute("SELECT kind, pattern_name, pattern_set_version FROM run_evidence").fetchall()
    db.close()
    assert rows == [("unsafe_executable_output", "a_pattern", "1")]


def test_two_runs_may_share_a_planted_token_but_a_run_has_one_token_per_kind(v10_db, vault):  # FR-035, FR-057
    TargetStore(v10_db, vault)
    db = connect(v10_db)
    with db:
        for run_id in (1, 2):   # a replay copies its source's token: the same value on two rows is legal
            db.execute("INSERT INTO run_planted_tokens (run_id, kind, token, prompt_id, prompt_version, created_at)"
                       " VALUES (?, 'override', 'abcdefghjkmn', 'override_task', '1', '2026-11-20T10:00:00Z')",
                       (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO run_planted_tokens (run_id, kind, token, prompt_id, prompt_version, created_at)"
                       " VALUES (1, 'override', 'npqrstuvwxyz', 'override_task', '1', '2026-11-20T10:00:00Z')")
    db.close()


def test_deleting_a_target_cascades_through_runs_to_every_new_table(v10_db, vault):  # FR-057, spec Edge Cases
    store = TargetStore(v10_db, vault)
    db = connect(v10_db)
    with db:
        db.execute("INSERT INTO run_evidence (run_id, turn, kind, location, owasp_category, detail, created_at)"
                   " VALUES (1, 1, 'canary_in_reply', 'reply', 'LLM07: System Prompt Leakage', 'KESTREL-CANARY-X',"
                   " '2026-11-20T10:00:04Z')")
        db.execute("INSERT INTO run_planted_tokens (run_id, kind, token, prompt_id, prompt_version, created_at)"
                   " VALUES (1, 'callback', 'f00dcafef00dcafef00dcafe', 'callback_task', '1', '2026-11-20T10:00:00Z')")
        db.execute("INSERT INTO callback_hits (run_id, method, received_at) VALUES (1, 'GET', '2026-11-20T10:00:03Z')")
        db.execute("INSERT INTO target_side_channels (target_id, url, header_name, header_value_encrypted,"
                   " honeypot_tool, created_at, updated_at) VALUES (1, 'http://t/side-channel', 'X-API-Key', 'enc',"
                   " 'approve_duty_refund', '2026-11-20T10:00:00Z', '2026-11-20T10:00:00Z')")
    db.close()

    store.delete_target(1)

    assert foreign_key_violations(v10_db) == []
    db = connect(v10_db)
    for table in ("runs", "run_turns", "run_evidence", "run_planted_tokens", "callback_hits", "target_side_channels"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    db.close()


def test_migrating_an_already_v11_database_a_second_time_is_a_no_op(v10_db, vault):  # FR-057
    TargetStore(v10_db, vault)
    before = {name: table_sql(v10_db, name) for name in ("runs", *NEW_TABLES)}
    sequence = runs_sequence(v10_db)
    TargetStore(v10_db, vault)
    assert version(v10_db) == "12"
    assert {name: table_sql(v10_db, name) for name in ("runs", *NEW_TABLES)} == before
    assert runs_sequence(v10_db) == sequence
