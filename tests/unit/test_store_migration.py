"""Schema version 1 → 2 is additive, so an existing database keeps its targets (data-model.md, research R11, FR-029)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, UnknownSchemaVersion, TargetStore

SECRET = "s3cret-header-value"

# The schema exactly as feature 001 shipped it. Kept verbatim so this test keeps checking a real
# old database rather than whatever the current schema happens to be.
SCHEMA_V1 = """
CREATE TABLE targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    name_key TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('POST', 'GET')),
    body_template TEXT NOT NULL,
    response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL,
    terms_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE target_headers (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    value_encrypted TEXT NOT NULL
);
CREATE UNIQUE INDEX target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '1');
"""


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def v1_db(tmp_path, vault):
    """A feature 001 database holding one target with one encrypted header."""
    path = tmp_path / "data" / "kestrel.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA_V1)
        db.execute("INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                   " permission_confirmed_at, terms_version, created_at, updated_at)"
                   " VALUES ('HS Agent', 'hs agent', 'http://agent.test/chat', 'POST', '{}', '$.reply',"
                   " '2026-10-23T10:00:00Z', '1', '2026-10-23T10:00:00Z', '2026-10-23T10:00:00Z')")
        db.execute("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (1, 0, ?, ?)",
                   ("X-API-Key", vault.encrypt(SECRET)))
    db.close()
    return path


def version(path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    finally:
        db.close()


def tables(path) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        db.close()


def test_a_fresh_database_is_created_at_version_2(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    assert version(path) == SCHEMA_VERSION
    assert {"targets", "target_headers", "target_canaries", "runs", "meta"} <= tables(path)


def test_a_version_1_database_gains_the_new_tables_and_moves_to_2(v1_db, vault):
    assert version(v1_db) == "1"
    TargetStore(v1_db, vault)
    assert version(v1_db) == SCHEMA_VERSION
    assert {"target_canaries", "runs"} <= tables(v1_db)


def test_migration_keeps_the_target_and_its_encrypted_header(v1_db, vault):
    store = TargetStore(v1_db, vault)
    target = store.get_target(1)
    assert target.name == "HS Agent"
    assert [h.name for h in target.headers] == ["X-API-Key"]
    assert target.headers[0].readable is True
    assert [h.value for h in store.resolve_headers(1)] == [SECRET]


def test_migration_adds_no_canaries_or_runs_to_an_existing_target(v1_db, vault):
    store = TargetStore(v1_db, vault)
    assert store.list_canaries(1) == []
    assert store.list_runs(1) == []


def test_opening_twice_is_harmless(v1_db, vault):
    TargetStore(v1_db, vault)
    TargetStore(v1_db, vault)
    assert version(v1_db) == SCHEMA_VERSION
    assert len(TargetStore(v1_db, vault).list_targets()) == 1


def test_a_database_from_a_newer_kestrel_is_refused_rather_than_mangled(tmp_path, vault):
    path = tmp_path / "data" / "kestrel.db"
    TargetStore(path, vault)
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    db.close()
    with pytest.raises(UnknownSchemaVersion, match="99"):
        TargetStore(path, vault)
