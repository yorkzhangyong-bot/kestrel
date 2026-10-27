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
