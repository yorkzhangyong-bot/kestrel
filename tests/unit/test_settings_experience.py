"""Feature-004 settings: the ChromaDB path and the retrieval bounds, from KESTREL_* env vars (research R12)."""
import pytest

from kestrel.settings import REPO_ROOT, SettingsError, load_settings


def test_defaults_when_unset():
    s = load_settings({})
    assert s.chroma_path == REPO_ROOT / "data" / "chroma"
    assert s.experience_pattern_k == 5
    assert s.experience_memory_cap == 10


def test_absolute_chroma_path_is_kept(tmp_path):
    s = load_settings({"KESTREL_CHROMA_PATH": str(tmp_path / "store")})
    assert s.chroma_path == tmp_path / "store"


def test_relative_chroma_path_is_under_repo_root():
    s = load_settings({"KESTREL_CHROMA_PATH": "var/chroma"})
    assert s.chroma_path == REPO_ROOT / "var" / "chroma"


def test_pattern_k_and_memory_cap_override():
    s = load_settings({"KESTREL_EXPERIENCE_PATTERN_K": "8", "KESTREL_EXPERIENCE_MEMORY_CAP": "20"})
    assert s.experience_pattern_k == 8 and s.experience_memory_cap == 20


@pytest.mark.parametrize("name", ["KESTREL_EXPERIENCE_PATTERN_K", "KESTREL_EXPERIENCE_MEMORY_CAP"])
@pytest.mark.parametrize("value", ["0", "-1", "nope"])
def test_bad_bounds_are_refused(name, value):
    with pytest.raises(SettingsError):
        load_settings({name: value})


# ---- feature 011: the distance floor and the near-identical threshold (011/FR-012) ----


def test_retrieval_controls_default_to_on_with_the_shipped_values():  # 011/FR-012
    s = load_settings({})
    assert s.experience_distance_floor == 1.8 and s.experience_dedupe_threshold == 0.15


@pytest.mark.parametrize("value", ["off", "OFF", "Off"])
def test_off_switches_a_control_off(value):  # 011/FR-012
    s = load_settings({"KESTREL_EXPERIENCE_DISTANCE_FLOOR": value, "KESTREL_EXPERIENCE_DEDUPE_THRESHOLD": value})
    assert s.experience_distance_floor is None and s.experience_dedupe_threshold is None


@pytest.mark.parametrize("raw, expected", [("0", 0.0), ("0.25", 0.25), ("2", 2.0)])
def test_a_non_negative_number_is_the_value(raw, expected):  # 011/FR-012
    s = load_settings({"KESTREL_EXPERIENCE_DISTANCE_FLOOR": raw, "KESTREL_EXPERIENCE_DEDUPE_THRESHOLD": raw})
    assert s.experience_distance_floor == expected and s.experience_dedupe_threshold == expected


@pytest.mark.parametrize("name", ["KESTREL_EXPERIENCE_DISTANCE_FLOOR", "KESTREL_EXPERIENCE_DEDUPE_THRESHOLD"])
@pytest.mark.parametrize("value", ["-1", "abc", "on", "nan", "inf", "-inf", "1e999"])
def test_an_invalid_control_value_refuses_to_start_naming_the_variable(name, value):  # 011/FR-012
    with pytest.raises(SettingsError, match=name):
        load_settings({name: value})


def test_the_two_controls_are_parsed_independently():  # 011/FR-012
    s = load_settings({"KESTREL_EXPERIENCE_DISTANCE_FLOOR": "off", "KESTREL_EXPERIENCE_DEDUPE_THRESHOLD": "0.3"})
    assert s.experience_distance_floor is None and s.experience_dedupe_threshold == 0.3
    s = load_settings({"KESTREL_EXPERIENCE_DISTANCE_FLOOR": "1.2", "KESTREL_EXPERIENCE_DEDUPE_THRESHOLD": "off"})
    assert s.experience_distance_floor == 1.2 and s.experience_dedupe_threshold is None


def test_settings_retrieval_bundles_k_floor_and_threshold():  # 011/FR-012
    from kestrel.settings import RetrievalSettings

    assert load_settings({}).retrieval == RetrievalSettings(k=5, distance_floor=1.8, dedupe_threshold=0.15)
    s = load_settings({"KESTREL_EXPERIENCE_PATTERN_K": "3", "KESTREL_EXPERIENCE_DISTANCE_FLOOR": "off"})
    assert s.retrieval == RetrievalSettings(k=3, distance_floor=None, dedupe_threshold=0.15)
