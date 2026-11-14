"""Schema version 7 -> 8 is additive: a feature-009 database keeps its data and gains the `run_log` table of kept
log lines, deleted with its run (010/FR-010)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, LogLine, TargetStore, UnknownSchemaVersion

FEATURE = "010"


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


def version(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def tables(path) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


@pytest.fixture
def v7_db(tmp_path, vault):
    """A feature-009 (version 7) database with a target and a finished run: version 8 minus the run_log table."""
    path = tmp_path / "data" / "kestrel.db"
    store = TargetStore(path, vault)
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "k-1234")],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply",
                                 terms_version="7")
    run_id = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(run_id, verdict="failed")
    db = sqlite3.connect(path)
    with db:
        db.execute("DROP TABLE run_log")
        db.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
    db.close()
    return path


def test_a_fresh_database_is_created_at_version_8_with_the_run_log(tmp_path, vault):  # FR-010
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION == "8"
    assert "run_log" in tables(path)


def test_a_v7_database_gains_the_run_log_and_keeps_its_runs(v7_db, vault):  # FR-010
    assert version(v7_db) == "7" and "run_log" not in tables(v7_db)
    store = TargetStore(v7_db, vault)
    assert version(v7_db) == "8" and "run_log" in tables(v7_db)
    assert store.get_run(1).verdict == "failed"      # the existing run survived
    assert store.list_log_lines(1) == []             # a pre-feature run simply has no kept lines


def test_lines_round_trip_in_seq_order_and_seq_is_unique_per_run(v7_db, vault):  # FR-010
    store = TargetStore(v7_db, vault)
    store.add_log_line(1, seq=2, ts="2026-11-13T10:00:01.000Z", event="run.end", record='{"event":"run.end"}')
    store.add_log_line(1, seq=1, ts="2026-11-13T10:00:00.000Z", event="run.start", record='{"event":"run.start"}')
    assert store.list_log_lines(1) == [
        LogLine(seq=1, ts="2026-11-13T10:00:00.000Z", event="run.start", record='{"event":"run.start"}'),
        LogLine(seq=2, ts="2026-11-13T10:00:01.000Z", event="run.end", record='{"event":"run.end"}')]
    with pytest.raises(sqlite3.IntegrityError):
        store.add_log_line(1, seq=2, ts="t", event="turn", record="{}")


def test_deleting_the_target_deletes_its_runs_lines(v7_db, vault):  # FR-010
    store = TargetStore(v7_db, vault)
    store.add_log_line(1, seq=1, ts="t", event="run.start", record="{}")
    store.delete_target(1)
    db = sqlite3.connect(v7_db)
    try:
        assert db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 0
    finally:
        db.close()


def test_opening_twice_is_harmless(v7_db, vault):
    TargetStore(v7_db, vault)
    TargetStore(v7_db, vault)
    assert version(v7_db) == "8"


def test_an_unknown_version_is_still_refused(tmp_path, vault):  # FR-010 (the R11 guard preserved)
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
