"""Schema version 3 → 4 is additive, so an existing feature-003 database keeps its runs (data-model.md).

Adds targets.description and runs.use_prior_experience / runs.memory_written (feature 004)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore, UnknownSchemaVersion

# A feature-003 (version 3) database, kept verbatim so this test checks a real old database.
SCHEMA_V3 = """
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
    started_at TEXT NOT NULL, finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'single_turn', attacker_model TEXT, turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER, time_limit_s INTEGER, stopping_condition TEXT, succeeded_turn INTEGER);
CREATE INDEX idx_runs_target ON runs (target_id, started_at DESC);
CREATE UNIQUE INDEX uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
CREATE TABLE run_turns (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, attacker_message TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, judge_verdict TEXT, judge_reason TEXT, judge_progress TEXT,
    created_at TEXT NOT NULL);
CREATE INDEX idx_run_turns_run ON run_turns (run_id, position);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '3');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v3_db(tmp_path, vault):
    """A feature-003 database with one target and one finished adaptive run."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V3)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-10-23T10:00:00Z','3',"
                   " '2026-10-23T10:00:00Z','2026-10-23T10:00:00Z')")
        db.execute("INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                   " attacker_source, status, verdict, hard_evidence, reason, judge_used, judge_model, started_at,"
                   " finished_at, mode, attacker_model, turn_budget, turns_used) VALUES"
                   " (1,'spl-001','t','<seed>','system_prompt_leak','LLM07: System Prompt Leakage','library:1.0.0',"
                   " 'finished','failed',0,'held',1,'google/gemini-3.8-flash','2026-10-23T10:00:00Z',"
                   " '2026-10-23T10:00:05Z','adaptive','deepseek/deepseek-v3.2',6,3)")
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


def test_a_fresh_database_is_created_at_version_4(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "4"
    assert "description" in columns(path, "targets")
    assert {"use_prior_experience", "memory_written"} <= columns(path, "runs")


def test_a_v3_database_gains_the_new_columns_and_moves_to_4(v3_db, vault):
    assert version(v3_db) == "3"
    TargetStore(v3_db, vault)
    assert version(v3_db) == "4"
    assert "description" in columns(v3_db, "targets")
    assert {"use_prior_experience", "memory_written"} <= columns(v3_db, "runs")


def test_the_existing_run_survives_and_defaults_to_warm(v3_db, vault):
    store = TargetStore(v3_db, vault)
    run = store.list_runs(1)[0]
    assert run.mode == "adaptive" and run.verdict == "failed"
    assert run.use_prior_experience is True   # NOT NULL DEFAULT 1 applied to the migrated row
    assert run.memory_written is None         # write-back not attempted for a legacy run
    assert store.get_target(1).description is None


def test_opening_twice_is_harmless(v3_db, vault):
    TargetStore(v3_db, vault)
    TargetStore(v3_db, vault)
    assert version(v3_db) == "4"


def test_a_newer_version_is_refused(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
