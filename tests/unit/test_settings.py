from pathlib import Path

import pytest

from kestrel.settings import (DEFAULT_ATTACKER_BASE_URL, DEFAULT_ATTACKER_MODEL, DEFAULT_JUDGE_BASE_URL,
                              DEFAULT_JUDGE_MODEL, SettingsError, load_settings)

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


def test_judge_model_and_base_url_have_defaults():
    settings = load_settings({})
    assert settings.judge_model == DEFAULT_JUDGE_MODEL
    assert settings.judge_base_url == DEFAULT_JUDGE_BASE_URL


def test_judge_model_and_base_url_can_be_set():
    settings = load_settings({"KESTREL_JUDGE_MODEL": "google/other", "KESTREL_JUDGE_BASE_URL": "https://h/v1/"})
    assert settings.judge_model == "google/other"
    assert settings.judge_base_url == "https://h/v1"  # trailing slash trimmed, so joining a path is predictable


def test_judge_key_prefers_its_own_variable_then_falls_back_to_openrouter():
    assert load_settings({"KESTREL_JUDGE_API_KEY": "a", "OPENROUTER_API_KEY": "b"}).judge_api_key == "a"
    assert load_settings({"OPENROUTER_API_KEY": "b"}).judge_api_key == "b"


def test_a_missing_judge_key_is_not_an_error():
    """Canary evidence still works without a judge, so an absent key must not stop Kestrel (FR-021)."""
    settings = load_settings({})
    assert settings.judge_api_key is None
    assert settings.judge_configured is False


def test_blank_judge_values_count_as_unset():
    settings = load_settings({"KESTREL_JUDGE_API_KEY": "   ", "KESTREL_JUDGE_MODEL": ""})
    assert settings.judge_api_key is None
    assert settings.judge_model == DEFAULT_JUDGE_MODEL


# --- feature 003: the attacker model and the adaptive caps ---

def test_attacker_model_and_base_url_have_defaults():
    s = load_settings({})
    assert s.attacker_model == DEFAULT_ATTACKER_MODEL == "deepseek/deepseek-v4.1-flash"
    assert s.attacker_base_url == DEFAULT_ATTACKER_BASE_URL


def test_attacker_model_and_base_url_can_be_set():
    s = load_settings({"KESTREL_ATTACKER_MODEL": "deepseek/other", "KESTREL_ATTACKER_BASE_URL": "https://h/v1/"})
    assert s.attacker_model == "deepseek/other"
    assert s.attacker_base_url == "https://h/v1"  # trailing slash trimmed


def test_attacker_key_prefers_its_own_variable_then_falls_back_to_openrouter():
    assert load_settings({"KESTREL_ATTACKER_API_KEY": "a", "OPENROUTER_API_KEY": "b"}).attacker_api_key == "a"
    assert load_settings({"OPENROUTER_API_KEY": "b"}).attacker_api_key == "b"


def test_a_missing_attacker_key_leaves_it_unconfigured():
    """An adaptive run needs the attacker; single-turn and canary evidence do not (FR-016)."""
    s = load_settings({})
    assert s.attacker_api_key is None and s.attacker_configured is False


def test_the_attacker_key_stays_out_of_the_repr():
    assert "sk-secret" not in repr(load_settings({"OPENROUTER_API_KEY": "sk-secret"}))


def test_the_adaptive_caps_default():
    s = load_settings({})
    assert s.adaptive_max_turns == 6
    assert s.adaptive_token_budget == 40000
    assert s.adaptive_time_limit_s == 300


def test_the_adaptive_caps_can_be_set():
    s = load_settings({"KESTREL_ADAPTIVE_MAX_TURNS": "2", "KESTREL_ADAPTIVE_TOKEN_BUDGET": "500",
                       "KESTREL_ADAPTIVE_TIME_LIMIT_S": "30"})
    assert (s.adaptive_max_turns, s.adaptive_token_budget, s.adaptive_time_limit_s) == (2, 500, 30)


def test_a_non_numeric_cap_is_refused():
    with pytest.raises(SettingsError, match="KESTREL_ADAPTIVE_MAX_TURNS"):
        load_settings({"KESTREL_ADAPTIVE_MAX_TURNS": "lots"})


def test_a_non_positive_cap_is_refused():
    with pytest.raises(SettingsError, match="KESTREL_ADAPTIVE_MAX_TURNS"):
        load_settings({"KESTREL_ADAPTIVE_MAX_TURNS": "0"})
