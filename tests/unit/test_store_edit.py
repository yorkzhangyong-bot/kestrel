import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import NameTaken, TargetNotFound, TargetStore

SECRET = "s3cret-header-value"
FIELDS = dict(url="http://agent.test/chat", method="POST", body_template='{"message": "{{prompt}}"}',
              response_path="$.reply", terms_version="1")


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "kestrel.db"


@pytest.fixture
def vault() -> Vault:
    return Vault(Fernet.generate_key())


@pytest.fixture
def store(db_path, vault) -> TargetStore:
    return TargetStore(db_path, vault)


@pytest.fixture
def target(store):
    return store.create_target(name="HS Agent", headers=[("X-API-Key", SECRET), ("X-Other", "other-1234")], **FIELDS)


def update(store, target, *, headers, **changes):
    values = {**FIELDS, "name": target.name, **changes}
    return store.update_target(target.id, headers=headers, **values)


def values_of(store, target_id):
    return [(h.name, h.value) for h in store.resolve_headers(target_id)]


def test_none_keeps_the_stored_value_a_string_replaces_it_and_omitted_headers_are_removed(store, target):
    update(store, target, headers=[("X-API-Key", None)])
    assert values_of(store, target.id) == [("X-API-Key", SECRET)]
    update(store, target, headers=[("X-API-Key", "new-value-5678")])
    assert values_of(store, target.id) == [("X-API-Key", "new-value-5678")]


def test_permission_date_is_renewed_on_a_url_change_only(store, target, monkeypatch):
    import kestrel.store as store_module

    monkeypatch.setattr(store_module, "utc_now", lambda: "2030-01-01T00:00:00Z")
    renamed = update(store, target, headers=[("X-API-Key", None)], name="Renamed")
    assert renamed.name == "Renamed" and renamed.permission_confirmed_at == target.permission_confirmed_at
    moved = update(store, target, headers=[("X-API-Key", None)], url="http://agent.test/other")
    assert moved.permission_confirmed_at == "2030-01-01T00:00:00Z"


def test_permission_date_is_renewed_when_newer_terms_are_accepted(store, target, monkeypatch):
    import kestrel.store as store_module

    monkeypatch.setattr(store_module, "utc_now", lambda: "2030-01-01T00:00:00Z")
    assert update(store, target, headers=[], terms_version="2").permission_confirmed_at == "2030-01-01T00:00:00Z"


def test_renaming_to_a_taken_name_is_refused(store, target):
    store.create_target(name="Other", headers=[], **FIELDS)
    with pytest.raises(NameTaken):
        update(store, target, headers=[], name="other")


def test_delete_removes_the_target_and_its_header_rows(store, target, db_path):
    store.delete_target(target.id)
    with pytest.raises(TargetNotFound):
        store.get_target(target.id)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM target_headers").fetchone()[0] == 0
    with pytest.raises(TargetNotFound):
        store.delete_target(target.id)


def test_another_key_reports_headers_as_unreadable_instead_of_raising(db_path, target):
    other = TargetStore(db_path, Vault(Fernet.generate_key()))
    assert [(h.name, h.readable) for h in other.get_target(target.id).headers] == [("X-API-Key", False),
                                                                                   ("X-Other", False)]
    assert values_of(other, target.id) == [("X-API-Key", None), ("X-Other", None)]
    assert other.key_matches() is False


def test_the_current_key_matches(store, target):
    assert store.key_matches() is True
