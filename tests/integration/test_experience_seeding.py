"""Start-up seeding is idempotent and carries no target identity (FR-004, FR-005, SC-002)."""
from kestrel.experience.store import ExperienceStore
from tests.support import StubEmbeddingFunction, fixture_library

FEATURE = "004"


def store(tmp_path) -> ExperienceStore:
    return ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())


def test_seeding_writes_one_pattern_per_library_prompt(tmp_path):
    library = fixture_library()
    exp = store(tmp_path)
    written = exp.seed_patterns(library)
    assert written == len(library.prompts)
    assert exp.count("pattern") == len(library.prompts)


def test_reseeding_adds_no_duplicates(tmp_path):
    library = fixture_library()
    exp = store(tmp_path)
    exp.seed_patterns(library)
    exp.seed_patterns(library)
    exp.seed_patterns(library)
    assert exp.count("pattern") == len(library.prompts)  # SC-002


def test_pattern_metadata_carries_family_owasp_source_and_no_target(tmp_path):
    library = fixture_library()
    exp = store(tmp_path)
    exp.seed_patterns(library)
    got = exp._collection.get(where={"type": "pattern"})  # white-box: inspect stored metadata
    assert got["metadatas"], "patterns were written"
    for meta in got["metadatas"]:
        assert meta["family"] in {"direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection"}
        assert meta["owasp_category"] and meta["source"].startswith("library:")
        # no target identity ever (FR-005)
        assert "target_id" not in meta and "url" not in meta and "name" not in meta
