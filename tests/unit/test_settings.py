from pathlib import Path

import pytest

from kestrel.settings import SettingsError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_and_hosted_modes_are_accepted():
    assert load_settings({"KESTREL_MODE": "local"}).mode == "local"
    assert load_settings({"KESTREL_MODE": "hosted"}).mode == "hosted"


def test_unset_mode_means_hosted():
    assert load_settings({}).mode == "hosted"
    assert load_settings({"KESTREL_MODE": ""}).mode == "hosted"


def test_unknown_mode_is_refused():
    with pytest.raises(SettingsError, match="KESTREL_MODE"):
        load_settings({"KESTREL_MODE": "dev"})


def test_db_path_defaults_to_data_folder_under_repo_root():
    assert load_settings({}).db_path == REPO_ROOT / "data" / "kestrel.db"


def test_relative_db_path_resolves_against_repo_root():
    assert load_settings({"KESTREL_DB_PATH": "tmp/test.db"}).db_path == REPO_ROOT / "tmp" / "test.db"


def test_absolute_db_path_is_kept(tmp_path):
    path = tmp_path / "kestrel.db"
    assert load_settings({"KESTREL_DB_PATH": str(path)}).db_path == path


def test_key_file_defaults_to_home_folder():
    assert load_settings({}).key_file == Path("~/.kestrel/secret.key").expanduser()


def test_key_file_can_be_set(tmp_path):
    path = tmp_path / "my.key"
    assert load_settings({"KESTREL_KEY_FILE": str(path)}).key_file == path


def test_secret_key_is_optional():
    assert load_settings({}).secret_key is None
    assert load_settings({"KESTREL_SECRET_KEY": "abc"}).secret_key == "abc"
