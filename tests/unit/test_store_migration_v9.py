"""Schema version 8 -> 9 is the one rebuild migration: SQLite cannot ALTER a column into AUTOINCREMENT, so
`runs` is recreated rather than altered (data-model.md). Proves every row, and every row in a table that
references `runs` (including the one ON DELETE SET NULL link), survives the rebuild, and that a run id is never
reissued afterwards - the schema-level half of the independent review's regression (011/FR-006, 011/FR-007; the
ExperienceStore half is proved in test_experience_store_controls.py)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, RunInProgress, TargetStore, UnknownSchemaVersion

FEATURE = "011"

# A feature-010 (version 8) database, kept verbatim so this test checks a real old database's rebuild, not
# whatever SCHEMA happens to look like today.
SCHEMA_V8 = """
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
INSERT INTO meta (key, value) VALUES ('schema_version', '8');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v8_db(tmp_path, vault):
    """A feature-010 database: one target, two finished runs, and one row in each table that references `runs`
    (run_turns, report_recommendations and run_log by CASCADE, experiment_runs by SET NULL) - so the rebuild is
    proved against every child, not just `runs` itself."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V8)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at) VALUES"
                   " ('A','a','http://t/chat','POST','{}','$.reply','2026-11-10T10:00:00Z','8',"
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
        # The one SET NULL child of `runs`: linked to run 2, so deleting run 2 (below) must null this, not cascade.
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


def test_a_fresh_database_is_created_at_version_9_with_autoincrement(tmp_path, vault):  # 011/FR-006
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "12"   # bumped to 11 for feature 013, to 12 for feature 014
    assert "AUTOINCREMENT" in runs_table_sql(path).upper()


def test_a_v8_database_is_rebuilt_with_autoincrement_and_keeps_every_row(v8_db, vault):  # 011/FR-006, 011/FR-007
    assert version(v8_db) == "8"
    assert "AUTOINCREMENT" not in runs_table_sql(v8_db).upper()

    store = TargetStore(v8_db, vault)

    assert version(v8_db) == SCHEMA_VERSION == "12"   # bumped to 11 for feature 013, to 12 for feature 014
    assert "AUTOINCREMENT" in runs_table_sql(v8_db).upper()
    assert foreign_key_violations(v8_db) == []

    runs = {r.id: r for r in store.list_runs(1)}
    assert set(runs) == {1, 2}
    assert runs[1].verdict == "succeeded" and runs[1].prompt_id == "spl-001" and runs[1].hard_evidence is True
    assert runs[2].verdict == "failed" and runs[2].prompt_id == "tex-001"
    assert [t.attacker_message for t in store.list_turns(1)] == ["<turn>"]
    assert store.get_recommendation(1).recommendation == "Harden."
    assert [line.event for line in store.list_log_lines(1)] == ["run.start"]
    link = store.experiment_run_links(1)[0]
    assert link.run_id == 2   # the ON DELETE SET NULL child survived the rebuild with its link intact

    # Removing just the run (never the experiment that links to it) proves the rebuilt table still honours ON
    # DELETE SET NULL, raw SQL so the experiment itself is untouched (deleting the target below would cascade
    # the experiment away too, which would prove nothing about the run's own foreign key).
    db = sqlite3.connect(v8_db)
    with db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("DELETE FROM runs WHERE id = 2")
    db.close()
    assert store.experiment_run_links(1)[0].run_id is None
    assert {r.id for r in store.list_runs(1)} == {1}   # run 1 and its CASCADE children are untouched
    assert [t.attacker_message for t in store.list_turns(1)] == ["<turn>"]

    # Deleting the target that owns the newest remaining run frees its id in a pre-v9 database; AUTOINCREMENT
    # must stop it (and run 2's, already freed above) from ever being reissued.
    store.delete_target(1)
    other = store.create_target(name="B", url="http://t2/chat", method="POST", headers=[], body_template="{}",
                                response_path="$.reply", terms_version="9")
    newest = store.claim_run(other.id, prompt_id="spl-002", prompt_title="t3", prompt_text="<seed3>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    assert newest > 2


def test_the_rebuild_recreates_both_runs_indexes(v8_db, tmp_path, vault):  # 011/FR-006
    """Dropping the old `runs` drops its indexes with it, so the rebuild must recreate both exactly as a fresh v9
    database has them, and the partial unique one must still refuse a second in-progress run on one target, which is
    how `claim_run` keeps two workers from starting runs on the same target."""
    expected = {"idx_runs_target": (0, 0, ["target_id", "started_at"]),
                "uq_runs_active": (1, 1, ["target_id"])}
    fresh = tmp_path / "fresh" / "kestrel.db"
    TargetStore(fresh, vault)
    assert runs_indexes(fresh) == expected
    assert runs_indexes(v8_db) == expected   # the v8 fixture has both, so the rebuild has something to lose

    store = TargetStore(v8_db, vault)

    assert runs_indexes(v8_db) == expected
    claim = dict(prompt_title="t3", prompt_text="<seed3>", family="system_prompt_leak",
                 owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    store.claim_run(1, prompt_id="spl-002", **claim)
    with pytest.raises(RunInProgress):
        store.claim_run(1, prompt_id="spl-003", **claim)


def test_a_fresh_v9_database_never_reuses_a_deleted_runs_id(tmp_path, vault):  # 011/FR-006
    store = TargetStore(tmp_path / "data" / "kestrel.db", vault)
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[], body_template="{}",
                                 response_path="$.reply", terms_version="9")
    first = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")
    store.finish_run(first, verdict="failed")
    second = store.claim_run(target.id, prompt_id="spl-002", prompt_title="t2", prompt_text="<seed2>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(second, verdict="failed")
    highest_used = max(first, second)

    store.delete_target(target.id)   # cascades: both runs are gone; pre-v9 the next run would reuse `first`'s id

    other = store.create_target(name="B", url="http://t2/chat", method="POST", headers=[], body_template="{}",
                                response_path="$.reply", terms_version="9")
    third = store.claim_run(other.id, prompt_id="spl-003", prompt_title="t3", prompt_text="<seed3>",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")
    assert third > highest_used


def test_opening_twice_is_harmless(v8_db, vault):
    TargetStore(v8_db, vault)
    TargetStore(v8_db, vault)
    assert version(v8_db) == "12"   # bumped to 11 for feature 013, to 12 for feature 014


def test_an_unknown_future_version_is_still_refused(tmp_path, vault):  # R11 guard preserved
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
