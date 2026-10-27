"""Schema version 2 → 3 is additive, so an existing feature-002 database keeps its runs (data-model.md, R9)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore, UnknownSchemaVersion

# A feature-002 (version 2) database, kept verbatim so this test checks a real old database.
SCHEMA_V2 = """
CREATE TABLE targets (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
    method TEXT NOT NULL, body_template TEXT NOT NULL, response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL, terms_version TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE target_headers (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, name TEXT NOT NULL, value_encrypted TEXT NOT NULL);
CREATE UNIQUE INDEX target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE target_canaries (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, value TEXT NOT NULL CHECK (length(value) >= 8), created_at TEXT NOT NULL);
CREATE UNIQUE INDEX target_canaries_value ON target_canaries (target_id, value);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL, prompt_title TEXT NOT NULL, prompt_text TEXT NOT NULL, family TEXT NOT NULL,
    owasp_category TEXT NOT NULL, attacker_source TEXT NOT NULL, status TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, verdict TEXT, hard_evidence INTEGER NOT NULL DEFAULT 0,
    reason TEXT, judge_used INTEGER NOT NULL DEFAULT 0, judge_model TEXT, failure_step TEXT,
    started_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX idx_runs_target ON runs (target_id, started_at DESC);
CREATE UNIQUE INDEX uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '2');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v2_db(tmp_path, vault):
    """A feature-002 database with one target and one finished single-turn run."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V2)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-10-23T10:00:00Z','2',"
                   " '2026-10-23T10:00:00Z','2026-10-23T10:00:00Z')")
        db.execute("INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                   " attacker_source, status, verdict, hard_evidence, reason, judge_used, judge_model, started_at,"
                   " finished_at) VALUES (1,'spl-001','t','<seed>','system_prompt_leak','LLM07: System Prompt Leakage',"
                   " 'library:1.0.0','finished','failed',0,'held',1,'google/gemini-3.8-flash',"
                   " '2026-10-23T10:00:00Z','2026-10-23T10:00:05Z')")
    db.close()
    return path


def version(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def columns(path, table):
    db = sqlite3.connect(path)
    try:
        return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


def tables(path):
    db = sqlite3.connect(path)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def test_a_fresh_database_is_created_at_version_3(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION  # current version (bumped past 3 in later features)
    assert "run_turns" in tables(path)
    assert {"mode", "attacker_model", "turn_budget", "token_budget", "stopping_condition"} <= columns(path, "runs")


def test_a_v2_database_gains_the_columns_and_run_turns_and_moves_to_3(v2_db, vault):
    assert version(v2_db) == "2"
    TargetStore(v2_db, vault)
    assert version(v2_db) == SCHEMA_VERSION
    assert "run_turns" in tables(v2_db)
    assert {"mode", "attacker_model", "turn_budget", "turns_used", "token_budget", "tokens_used",
            "time_limit_s", "stopping_condition", "succeeded_turn"} <= columns(v2_db, "runs")


def test_the_existing_run_survives_and_reads_as_single_turn(v2_db, vault):
    store = TargetStore(v2_db, vault)
    run = store.list_runs(1)[0]
    assert run.mode == "single_turn" and run.verdict == "failed" and run.attacker_model is None
    assert store.list_turns(run.id) == []  # a single-turn run has no conversation turns


def test_opening_twice_is_harmless(v2_db, vault):
    TargetStore(v2_db, vault)
    TargetStore(v2_db, vault)
    assert version(v2_db) == SCHEMA_VERSION


def test_a_newer_version_is_refused(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
