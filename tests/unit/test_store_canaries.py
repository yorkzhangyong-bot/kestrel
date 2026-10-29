"""Canary strings on a target: plain text, at least 8 characters, unique per target (FR-024, FR-025, research R7)."""
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import TargetNotFound, TargetStore

FEATURE = "002"


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


def create(store, name="HS Agent"):
    return store.create_target(name=name, url="http://agent.test/chat", method="POST",
                               headers=[("X-API-Key", "test-key-123")], body_template='{"message": "{{prompt}}"}',
                               response_path="$.reply", terms_version="2")


def test_a_target_starts_with_no_canaries(store):
    target = create(store)
    assert store.list_canaries(target.id) == []


def test_canaries_are_stored_and_read_back_in_full(store):
    """Not a credential: the user has to read one to paste it into their agent (R7)."""
    target = create(store)
    store.set_canaries(target.id, ["KESTREL-CANARY-7Q4M2X", "SECOND-CANARY-VALUE"])
    assert store.list_canaries(target.id) == ["KESTREL-CANARY-7Q4M2X", "SECOND-CANARY-VALUE"]


def test_the_order_entered_is_kept(store):
    target = create(store)
    store.set_canaries(target.id, ["zzzz-last-one", "aaaa-first-one", "mmmm-middle-one"])
    assert store.list_canaries(target.id) == ["zzzz-last-one", "aaaa-first-one", "mmmm-middle-one"]


def test_setting_canaries_replaces_the_previous_set(store):
    target = create(store)
    store.set_canaries(target.id, ["FIRST-CANARY-VALUE"])
    store.set_canaries(target.id, ["SECOND-CANARY-VALUE"])
    assert store.list_canaries(target.id) == ["SECOND-CANARY-VALUE"]


def test_an_empty_list_clears_them(store):
    target = create(store)
    store.set_canaries(target.id, ["FIRST-CANARY-VALUE"])
    store.set_canaries(target.id, [])
    assert store.list_canaries(target.id) == []


@pytest.mark.parametrize("value", ["", "short", "1234567"])
def test_a_canary_under_8_characters_is_refused(store, value):
    """A short canary would match an innocent reply by chance, and chance is not hard evidence (FR-025)."""
    target = create(store)
    with pytest.raises(ValueError, match="8"):
        store.set_canaries(target.id, [value])
    assert store.list_canaries(target.id) == []


def test_the_same_canary_twice_on_one_target_is_refused(store):
    target = create(store)
    with pytest.raises(ValueError, match="more than once"):
        store.set_canaries(target.id, ["KESTREL-CANARY-7Q4M2X", "KESTREL-CANARY-7Q4M2X"])
    assert store.list_canaries(target.id) == []


def test_the_same_canary_on_two_targets_is_allowed(store):
    first, second = create(store, "First"), create(store, "Second")
    store.set_canaries(first.id, ["KESTREL-CANARY-7Q4M2X"])
    store.set_canaries(second.id, ["KESTREL-CANARY-7Q4M2X"])
    assert store.list_canaries(first.id) == store.list_canaries(second.id) == ["KESTREL-CANARY-7Q4M2X"]


def test_deleting_the_target_deletes_its_canaries(store):
    target = create(store)
    store.set_canaries(target.id, ["KESTREL-CANARY-7Q4M2X"])
    store.delete_target(target.id)
    with pytest.raises(TargetNotFound):
        store.list_canaries(target.id)


def test_an_unknown_target_is_refused(store):
    with pytest.raises(TargetNotFound):
        store.set_canaries(999, ["KESTREL-CANARY-7Q4M2X"])
