"""Schema version 5 -> 6 is additive: a feature-005 database keeps its data and gains the three experiment
tables (feature 007, data-model.md). Traces 007/FR-016."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore, UnknownSchemaVersion

# A feature-005 (version 5) database, enough to prove an old database migrates cleanly.
SCHEMA_V5 = """
CREATE TABLE targets (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
    method TEXT NOT NULL, body_template TEXT NOT NULL, response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL, terms_version TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, description TEXT);
CREATE TABLE target_headers (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, name TEXT NOT NULL, value_encrypted TEXT NOT NULL);
CREATE UNIQUE INDEX target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE runs (
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL, prompt_title TEXT NOT NULL, prompt_text TEXT NOT NULL, family TEXT NOT NULL,
    owasp_category TEXT NOT NULL, attacker_source TEXT NOT NULL, status TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, verdict TEXT, hard_evidence INTEGER NOT NULL DEFAULT 0,
    reason TEXT, judge_used INTEGER NOT NULL DEFAULT 0, judge_model TEXT, failure_step TEXT,
    started_at TEXT NOT NULL, finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'single_turn', attacker_model TEXT, turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER, time_limit_s INTEGER, stopping_condition TEXT, succeeded_turn INTEGER,
    use_prior_experience INTEGER NOT NULL DEFAULT 1, memory_written INTEGER);
CREATE UNIQUE INDEX uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
CREATE TABLE report_recommendations (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    recommendation TEXT NOT NULL, model TEXT, created_at TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '5');
"""

EXPERIMENT_TABLES = {"experiments", "experiment_arms", "experiment_runs"}


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v5_db(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V5)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-10-27T10:00:00Z','5',"
                   " '2026-10-27T10:00:00Z','2026-10-27T10:00:00Z')")
    db.close()
    return path


def version(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def tables(path):
    db = sqlite3.connect(path)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def test_a_fresh_database_is_created_at_version_6(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "6"
    assert EXPERIMENT_TABLES <= tables(path)


def test_a_v5_database_gains_the_tables_and_moves_to_6(v5_db, vault):
    assert version(v5_db) == "5"
    store = TargetStore(v5_db, vault)
    assert version(v5_db) == "6"
    assert EXPERIMENT_TABLES <= tables(v5_db)
    assert store.get_target(1).name == "A"   # the existing target survived


def test_opening_twice_is_harmless(v5_db, vault):
    TargetStore(v5_db, vault)
    TargetStore(v5_db, vault)
    assert version(v5_db) == "6"


def test_a_newer_version_is_refused(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
