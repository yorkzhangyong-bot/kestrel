import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, NameTaken, TargetNotFound, TargetStore

SECRET = "s3cret-header-value"


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "data" / "kestrel.db"


@pytest.fixture
def store(db_path, vault) -> TargetStore:
    return TargetStore(db_path, vault)


def create(store, name="HS Agent", headers=(("X-API-Key", SECRET),), **fields):
    values = dict(url="http://agent.test/chat", method="POST", body_template='{"message": "{{prompt}}"}',
                  response_path="$.reply", terms_version="1")
    return store.create_target(name=name, headers=list(headers), **{**values, **fields})


def test_create_list_and_get_round_trip(store):
    target = create(store)
    assert target.name == "HS Agent" and target.url == "http://agent.test/chat" and target.method == "POST"
    assert target.permission_confirmed_at and target.terms_version == "1"
    assert [(h.name, h.readable) for h in target.headers] == [("X-API-Key", True)]
    assert [t.id for t in store.list_targets()] == [target.id]
    assert store.get_target(target.id) == target


def test_header_values_are_stored_encrypted_and_only_resolve_headers_decrypts_them(store, db_path):
    target = create(store)
    with sqlite3.connect(db_path) as db:
        raw = db.execute("SELECT value_encrypted FROM target_headers").fetchone()[0]
    assert raw != SECRET and SECRET not in raw
    assert SECRET not in repr(store.get_target(target.id)) and SECRET not in repr(store.list_targets())
    assert [(h.name, h.value) for h in store.resolve_headers(target.id)] == [("X-API-Key", SECRET)]


@pytest.mark.parametrize("first, second", [("HS Agent", "hs agent"), ("Ärger", "ärger")])
def test_display_names_are_unique_ignoring_case(store, first, second):
    create(store, name=first)
    with pytest.raises(NameTaken):
        create(store, name=second)


def test_the_method_check_rejects_other_methods(store):
    with pytest.raises(sqlite3.IntegrityError):
        create(store, method="PUT")


def test_header_names_are_unique_per_target_ignoring_case(store):
    with pytest.raises(sqlite3.IntegrityError):
        create(store, headers=(("X-Key", "value-1234"), ("x-key", "value-5678")))
    assert store.list_targets() == []  # the whole save was rolled back


def test_reopening_the_file_keeps_the_data(db_path, vault):
    target = create(TargetStore(db_path, vault))
    assert TargetStore(db_path, vault).get_target(target.id).name == "HS Agent"


def test_pragmas_are_on_and_the_schema_version_is_recorded(store):
    with store.connect() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA secure_delete").fetchone()[0] == 1
        # The constant, not a literal: the version moves with each migration (test_store_migration.py pins it).
        assert db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == SCHEMA_VERSION


def test_targets_are_listed_by_name(store):
    for name in ("beta", "Alpha", "gamma"):
        create(store, name=name)
    assert [t.name for t in store.list_targets()] == ["Alpha", "beta", "gamma"]


def test_an_unknown_id_raises_target_not_found(store):
    with pytest.raises(TargetNotFound):
        store.get_target(99)
    with pytest.raises(TargetNotFound):
        store.resolve_headers(99)
