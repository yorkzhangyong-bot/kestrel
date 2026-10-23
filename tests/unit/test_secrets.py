import logging

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import MASK, Vault, load_or_create_key, mask_values
from kestrel.settings import Settings, SettingsError

LOGGER = logging.getLogger("kestrel.test")


def make_settings(tmp_path, *, mode="local", secret_key=None, key_file=None):
    return Settings(mode=mode, db_path=tmp_path / "kestrel.db",
                    key_file=key_file or tmp_path / "keys" / "secret.key", secret_key=secret_key)


def test_env_key_is_used_and_no_file_is_written(tmp_path):
    key = Fernet.generate_key().decode()
    assert load_or_create_key(make_settings(tmp_path, secret_key=key), LOGGER) == (key.encode(), "env")
    assert not (tmp_path / "keys").exists()


def test_invalid_env_key_is_refused_without_repeating_it(tmp_path):
    with pytest.raises(SettingsError, match="KESTREL_SECRET_KEY") as info:
        load_or_create_key(make_settings(tmp_path, secret_key="not-a-key-zzz"), LOGGER)
    assert "not-a-key-zzz" not in str(info.value)


def test_existing_key_file_is_read(tmp_path):
    key = Fernet.generate_key()
    path = tmp_path / "secret.key"
    path.write_bytes(key + b"\n")
    assert load_or_create_key(make_settings(tmp_path, key_file=path), LOGGER) == (key, "file")


def test_invalid_key_file_is_refused(tmp_path):
    path = tmp_path / "secret.key"
    path.write_bytes(b"garbage")
    with pytest.raises(SettingsError, match="key file"):
        load_or_create_key(make_settings(tmp_path, key_file=path), LOGGER)


def test_missing_key_file_is_created_and_announced(tmp_path, caplog):
    path = tmp_path / "nested" / "folder" / "secret.key"
    with caplog.at_level(logging.WARNING):
        key, source = load_or_create_key(make_settings(tmp_path, key_file=path), LOGGER)
    assert source == "generated"
    assert path.read_bytes().strip() == key
    Fernet(key)
    assert str(path) in caplog.text
    assert "back this file up" in caplog.text


def test_hosted_mode_warns_about_redeploys_for_file_keys(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        load_or_create_key(make_settings(tmp_path, mode="hosted"), LOGGER)
    assert "redeploy" in caplog.text


def test_local_mode_does_not_warn_about_redeploys(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        load_or_create_key(make_settings(tmp_path, mode="local"), LOGGER)
    assert "redeploy" not in caplog.text


def test_vault_round_trip():
    vault = Vault(Fernet.generate_key())
    token = vault.encrypt("s3cret-value")
    assert token != "s3cret-value"
    assert vault.decrypt(token) == "s3cret-value"


def test_vault_returns_none_for_a_token_made_with_another_key():
    token = Vault(Fernet.generate_key()).encrypt("s3cret-value")
    assert Vault(Fernet.generate_key()).decrypt(token) is None


def test_mask_values_replaces_every_occurrence():
    assert mask_values("a TOKEN1234 b TOKEN1234", ["TOKEN1234"]) == f"a {MASK} b {MASK}"


def test_mask_values_replaces_longest_values_first():
    assert mask_values("abcdefgh", ["abcd", "abcdefgh"]) == MASK


def test_mask_values_leaves_values_shorter_than_four_characters_alone():
    assert mask_values("a b abc", ["a", "abc"]) == "a b abc"
