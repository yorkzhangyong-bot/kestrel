"""Schema version 9 -> 10 (feature 012) widens `runs.mode`'s CHECK to accept 'replay' and adds a self-referencing
`source_run_id` plus `replay_outcome`, following the same rebuild procedure (and the same sqlite_sequence gotcha)
v9's own migration proved out (CLAUDE.md "Learned notes", 2026-11-17)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, RunInProgress, TargetStore

FEATURE = "012"

# A feature-011 (version 9) database, kept verbatim so this test checks a real v9 database's rebuild, not whatever
# SCHEMA happens to look like today. Identical to v8 except `runs.id` already has AUTOINCREMENT and meta is '9'.
SCHEMA_V9 = """
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
    mode TEXT NOT NULL DEFAULT 'single_turn', attacker_model TEXT, turn_budget INTEGER, turns_used INTEGER,
    token_budget INTEGER, tokens_used INTEGER, time_limit_s INTEGER, stopping_condition TEXT,
    succeeded_turn INTEGER, use_prior_experience INTEGER NOT NULL DEFAULT 1, memory_written INTEGER,
    judge_prompt_id TEXT, judge_prompt_version TEXT);
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
INSERT INTO meta (key, value) VALUES ('schema_version', '9');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v9_db(tmp_path, vault):
    """A feature-011 database: one target, two finished runs, and one row in each table that references `runs`
    (run_turns, report_recommendations and run_log by CASCADE, experiment_runs by SET NULL), so the v10 rebuild is
    proved against every child, not just `runs` itself."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V9)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-10T10:00:00Z','9',"
                   " '2026-11-10T10:00:00Z','2026-11-10T10:00:00Z')")
        db.execute("INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                   " attacker_source, status, verdict, hard_evidence, started_at, finished_at) VALUES"
                   " (1,1,'spl-001','t','<seed>','system_prompt_leak','LLM07: System Prompt Leakage',"
                   " 'library:1.0.0','finished','succeeded',1,'2026-11-10T10:00:00Z','2026-11-10T10:00:05Z')")
        db.execute("INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                   " attacker_source, status, verdict, hard_evidence, started_at, finished_at) VALUES"
                   " (2,1,'tex-001','t2','<seed2>','tool_exfiltration','LLM06: Excessive Agency','library:1.0.0',"
                   " 'finished','failed',0,'2026-11-10T10:01:00Z','2026-11-10T10:01:05Z')")
        db.execute("INSERT INTO run_turns (run_id, position, attacker_message, created_at) VALUES"
                   " (1, 1, '<turn>', '2026-11-10T10:00:01Z')")
        db.execute("INSERT INTO report_recommendations (run_id, recommendation, model, created_at) VALUES"
                   " (1, 'Harden.', 'm', '2026-11-10T10:00:06Z')")
        db.execute("INSERT INTO run_log (run_id, seq, ts, event, record) VALUES"
                   " (1, 1, '2026-11-10T10:00:00Z', 'run.start', '{\"event\": \"run.start\"}')")
        db.execute("INSERT INTO experiments (target_id, mode, families, reps, seed_prompt_ids, max_runs,"
                   " token_budget_total, wall_clock_s, status, created_at) VALUES"
                   " (1, 'single_turn', '[\"tool_exfiltration\"]', 1, '{}', 50, 500000, 3600, 'finished',"
                   " '2026-11-10T10:00:00Z')")
        db.execute("INSERT INTO experiment_arms (experiment_id, label, attacker_model, judge_model,"
                   " use_prior_experience, turn_cap, token_budget) VALUES (1, 'A', 'm', 'j', 1, 6, 40000)")
        # The one SET NULL child of `runs`: linked to run 2, so the rebuild must leave this link intact.
        db.execute("INSERT INTO experiment_runs (experiment_id, arm_id, rep_index, family, run_id, created_at)"
                   " VALUES (1, 1, 0, 'tool_exfiltration', 2, '2026-11-10T10:01:00Z')")
    db.close()
    return path


def version(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def runs_table_sql(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()[0]
    finally:
        db.close()


def foreign_key_violations(path) -> list:
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        return db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        db.close()


def runs_indexes(path) -> dict[str, tuple[int, int, list[str]]]:
    """The indexes CREATE INDEX made on `runs` (no automatic ones): name -> (unique, partial, columns)."""
    db = sqlite3.connect(path)
    try:
        found = {}
        for _seq, name, unique, origin, partial in db.execute("PRAGMA index_list(runs)").fetchall():
            if origin == "c":
                found[name] = (unique, partial, [row[2] for row in db.execute(f"PRAGMA index_info({name})")])
        return found
    finally:
        db.close()


def runs_sequence(path) -> int | None:
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'runs'").fetchone()
        return None if row is None else row[0]
    finally:
        db.close()


CLAIM = dict(prompt_title="t3", prompt_text="<seed3>", family="system_prompt_leak",
             owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def test_a_fresh_database_is_created_at_version_10_with_the_widened_mode_check(tmp_path, vault):  # 012/FR-020
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "11"
    assert "'REPLAY'" in runs_table_sql(path).upper()


def test_a_v9_database_is_rebuilt_and_keeps_every_row(v9_db, vault):  # 012/FR-020
    assert version(v9_db) == "9"
    assert "SOURCE_RUN_ID" not in runs_table_sql(v9_db).upper()

    store = TargetStore(v9_db, vault)

    assert version(v9_db) == SCHEMA_VERSION == "11"
    assert foreign_key_violations(v9_db) == []

    runs = {r.id: r for r in store.list_runs(1)}
    assert set(runs) == {1, 2}
    # Every pre-existing run is not a replay: both new columns land at their implicit default, NULL.
    assert runs[1].source_run_id is None and runs[1].replay_outcome is None
    assert runs[2].source_run_id is None and runs[2].replay_outcome is None
    assert runs[1].verdict == "succeeded" and runs[1].prompt_id == "spl-001"

    # Children of a surviving run (CASCADE) are untouched: the parent was renamed, not deleted-and-not-replaced.
    assert [t.attacker_message for t in store.list_turns(1)] == ["<turn>"]
    assert store.get_recommendation(1).recommendation == "Harden."
    assert [line.event for line in store.list_log_lines(1)] == ["run.start"]
    # The one SET NULL child still points at its run: the rebuild did not fire the cascade action.
    assert store.experiment_run_links(1)[0].run_id == 2


def test_both_runs_indexes_survive_and_still_guard_one_active_run_per_target(v9_db, tmp_path, vault):  # 012/FR-020
    expected = {"idx_runs_target": (0, 0, ["target_id", "started_at"]),
                "uq_runs_active": (1, 1, ["target_id"])}
    fresh = tmp_path / "fresh" / "kestrel.db"
    TargetStore(fresh, vault)
    assert runs_indexes(fresh) == expected

    store = TargetStore(v9_db, vault)

    assert runs_indexes(v9_db) == expected
    store.claim_run(1, prompt_id="spl-002", **CLAIM)
    with pytest.raises(RunInProgress):
        store.claim_run(1, prompt_id="spl-003", **CLAIM)


def test_a_replay_row_round_trips_and_the_mode_check_accepts_exactly_three_values(v9_db, vault):  # 012/FR-004,
    # FR-005, FR-020
    store = TargetStore(v9_db, vault)
    db = sqlite3.connect(v9_db)
    with db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            "INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
            " attacker_source, status, mode, source_run_id, replay_outcome, started_at, finished_at) VALUES"
            " (101, 1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
            " 'library:1.0.0', 'finished', 'replay', 1, 'fixed', '2026-11-19T10:00:00Z', '2026-11-19T10:00:05Z')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                " attacker_source, status, mode, started_at) VALUES"
                " (1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
                " 'library:1.0.0', 'finished', 'bogus', '2026-11-19T10:00:00Z')")
    db.close()

    replay = store.get_run(101)
    assert replay.mode == "replay" and replay.source_run_id == 1 and replay.replay_outcome == "fixed"
    assert foreign_key_violations(v9_db) == []


def test_deleting_the_shared_target_removes_the_source_and_the_replay_together(v9_db, vault):  # 012/FR-020
    store = TargetStore(v9_db, vault)
    db = sqlite3.connect(v9_db)
    with db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            "INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
            " attacker_source, status, mode, source_run_id, started_at) VALUES"
            " (101, 1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
            " 'library:1.0.0', 'finished', 'replay', 1, '2026-11-19T10:00:00Z')")
    db.close()

    store.delete_target(1)

    assert foreign_key_violations(v9_db) == []
    with pytest.raises(Exception):
        store.get_run(1)
    with pytest.raises(Exception):
        store.get_run(101)


def test_migrating_an_already_v10_database_a_second_time_is_a_no_op(v9_db, vault):  # 012/FR-020
    TargetStore(v9_db, vault)
    before = runs_table_sql(v9_db)
    TargetStore(v9_db, vault)
    assert version(v9_db) == "11"
    assert runs_table_sql(v9_db) == before


def test_the_sqlite_sequence_watermark_survives_the_rebuild(tmp_path, vault):  # 012/FR-020 (the v9 gotcha)
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V9)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-10T10:00:00Z','9',"
                   " '2026-11-10T10:00:00Z','2026-11-10T10:00:00Z')")
        for i in range(1, 6):   # five runs, ids 1..5
            db.execute("INSERT INTO runs (target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
                       " attacker_source, status, verdict, started_at) VALUES"
                       " (1, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
                       " 'library:1.0.0', 'finished', 'failed', '2026-11-10T10:00:00Z')")
        db.execute("DELETE FROM runs WHERE id IN (4, 5)")   # only 1..3 survive; AUTOINCREMENT keeps seq at 5
    db.close()
    assert runs_sequence(path) == 5

    store = TargetStore(path, vault)

    assert {r.id for r in store.list_runs(1)} == {1, 2, 3}
    newest = store.claim_run(1, prompt_id="spl-002", **CLAIM)
    assert newest > 5   # never a freed, reissued id (4 or 5)


def test_an_interrupted_replay_is_closed_inconclusive_never_left_null(tmp_path, vault):  # 012/FR-012, FR-015,
    # FR-020
    path = tmp_path / "data" / "kestrel.db"
    store = TargetStore(path, vault)
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="10")
    other_target = store.create_target(name="B", url="http://t2/chat", method="POST", headers=[], body_template="{}",
                                       response_path="$.reply", terms_version="10")
    source = store.claim_run(target.id, prompt_id="spl-001", **CLAIM)
    store.finish_run(source, verdict="succeeded", hard_evidence=True)
    db = sqlite3.connect(path)
    with db:
        db.execute("PRAGMA foreign_keys = ON")
        # Two different targets, each with its own one in_progress row (uq_runs_active allows only one per target).
        db.execute(
            "INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
            " attacker_source, status, mode, source_run_id, started_at) VALUES"
            " (101, ?, 'spl-001', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
            " 'library:1.0.0', 'in_progress', 'replay', ?, '2026-11-19T10:00:00Z')", (target.id, source))
        db.execute(
            "INSERT INTO runs (id, target_id, prompt_id, prompt_title, prompt_text, family, owasp_category,"
            " attacker_source, status, mode, started_at) VALUES"
            " (102, ?, 'spl-002', 't', '<seed>', 'system_prompt_leak', 'LLM07: System Prompt Leakage',"
            " 'library:1.0.0', 'in_progress', 'single_turn', '2026-11-19T10:00:00Z')", (other_target.id,))
    db.close()

    closed = store.close_interrupted_runs()

    assert closed == 2
    replay = store.get_run(101)
    assert replay.status == "finished" and replay.replay_outcome == "inconclusive"
    non_replay = store.get_run(102)
    assert non_replay.status == "finished" and non_replay.replay_outcome is None
