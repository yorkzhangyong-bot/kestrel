"""Schema version 4 → 5 is additive: an existing feature-004 database keeps its runs and gains
`report_recommendations` (feature 005, data-model.md). Round-trips get/save for the per-run cache."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore, UnknownSchemaVersion

# A feature-004 (version 4) database, kept verbatim so this test checks a real old database (no recommendations table).
SCHEMA_V4 = """
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
    id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL, prompt_title TEXT NOT NULL, prompt_text TEXT NOT NULL, family TEXT NOT NULL,
    owasp_category TEXT NOT NULL, attacker_source TEXT NOT NULL, status TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, verdict TEXT, hard_evidence INTEGER NOT NULL DEFAULT 0,
    reason TEXT, judge_used INTEGER NOT NULL DEFAULT 0, judge_model TEXT, failure_step TEXT,
    started_at TEXT NOT NULL, finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'single_turn', attacker_model TEXT, turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER, time_limit_s INTEGER, stopping_condition TEXT, succeeded_turn INTEGER,
    use_prior_experience INTEGER NOT NULL DEFAULT 1, memory_written INTEGER);
CREATE INDEX idx_runs_target ON runs (target_id, started_at DESC);
CREATE UNIQUE INDEX uq_runs_active ON runs (target_id) WHERE status = 'in_progress';
CREATE TABLE run_turns (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, attacker_message TEXT NOT NULL, reply_text TEXT,
    reply_truncated INTEGER NOT NULL DEFAULT 0, judge_verdict TEXT, judge_reason TEXT, judge_progress TEXT,
    created_at TEXT NOT NULL);
CREATE INDEX idx_run_turns_run ON run_turns (run_id, position);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '4');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v4_db(tmp_path, vault):
    """A feature-004 database with one target and one finished, succeeded run."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V4)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-10-27T10:00:00Z','4',"
                   " '2026-10-27T10:00:00Z','2026-10-27T10:00:00Z')")
        db.execute("INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                   " attacker_source, status, verdict, hard_evidence, started_at, finished_at) VALUES"
                   " (1,'spl-001','t','<seed>','system_prompt_leak','LLM07: System Prompt Leakage','library:1.0.0',"
                   " 'finished','succeeded',1,'2026-10-27T10:00:00Z','2026-10-27T10:00:05Z')")
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


def a_succeeded_run(store) -> int:
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="5")
    run_id = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True)
    return run_id


def test_a_fresh_database_is_created_at_version_5(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "5"
    assert "report_recommendations" in tables(path)


def test_a_v4_database_gains_the_table_and_moves_to_5(v4_db, vault):
    assert version(v4_db) == "4"
    store = TargetStore(v4_db, vault)
    assert version(v4_db) == "5"
    assert "report_recommendations" in tables(v4_db)
    assert store.list_runs(1)[0].verdict == "succeeded"   # the existing run survived the migration


def test_recommendation_round_trips_and_is_replaced_per_run(tmp_path, vault):
    store = TargetStore(tmp_path / "data" / "kestrel.db", vault)
    run_id = a_succeeded_run(store)
    assert store.get_recommendation(run_id) is None                       # nothing cached yet
    store.save_recommendation(run_id, recommendation="Refuse.", model="google/gemini-3.8-flash")
    cached = store.get_recommendation(run_id)
    assert cached.recommendation == "Refuse." and cached.model == "google/gemini-3.8-flash"
    store.save_recommendation(run_id, recommendation="Refuse harder.", model="m2")   # one row per run id
    assert store.get_recommendation(run_id).recommendation == "Refuse harder."


def test_opening_twice_is_harmless(v4_db, vault):
    TargetStore(v4_db, vault)
    TargetStore(v4_db, vault)
    assert version(v4_db) == "5"


def test_a_newer_version_is_refused(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
