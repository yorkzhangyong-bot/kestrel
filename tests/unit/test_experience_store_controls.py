"""The store's retrieval controls (feature 011, contracts/experience-store.md): `query_patterns` returns the
family's candidates nearest first with the collection's own distances and their stored embeddings (FR-003,
FR-005); `write_pattern` merges a near-identical success into the nearest same-family pattern, raising its hit
count, and adds a distinct one with a hit count of one (FR-006, FR-007, FR-008, SC-004). Temporary stores on the
lexical stub (thresholds on its scale); placeholder texts only."""
import pytest

from kestrel.experience.store import Candidate, ExperienceStore
from tests.support import StubEmbeddingFunction, fixture_library

FEATURE = "011"

FAMILY = "system_prompt_leak"
OWASP = "LLM07: System Prompt Leakage"
SEED_TEXT = "<placeholder system_prompt_leak prompt 1>"   # the fixture library's text for spl-001


@pytest.fixture
def seeded(tmp_path) -> ExperienceStore:
    store = ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())
    store.seed_patterns(fixture_library())
    return store


# ---- query_patterns (FR-003, FR-005) ----


def test_query_patterns_returns_only_the_familys_patterns_nearest_first(seeded):  # FR-003, FR-005
    found = seeded.query_patterns(family=FAMILY, query_text=f"System prompt leak {SEED_TEXT}", n=10)
    assert found and all(isinstance(candidate, Candidate) for candidate in found)
    assert all(c.id.startswith("pattern:lib:spl-") and "system_prompt_leak" in c.document for c in found)
    distances = [c.distance for c in found]
    assert distances == sorted(distances) and all(isinstance(d, float) for d in distances)
    assert found[0].id == "pattern:lib:spl-001"   # the seed itself is the nearest hit for its own query
    assert all(isinstance(c.embedding, tuple) and len(c.embedding) == StubEmbeddingFunction.DIM for c in found)
    assert all(isinstance(value, float) for value in found[0].embedding)


def test_n_is_clamped_to_the_familys_pattern_count(seeded):  # FR-003
    family_count = seeded.count("pattern", family="direct_injection")
    assert family_count == 5
    assert len(seeded.query_patterns(family="direct_injection", query_text="placeholder", n=100)) == family_count
    assert len(seeded.query_patterns(family="direct_injection", query_text="placeholder", n=2)) == 2


def test_an_empty_family_returns_nothing_without_error(tmp_path):  # FR-003
    store = ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())
    assert store.query_patterns(family=FAMILY, query_text="placeholder", n=5) == []
    assert store.query_patterns(family=FAMILY, query_text="placeholder", n=0) == []


def test_memory_records_never_appear_as_candidates(seeded):  # FR-005
    seeded.write_memory(run_id=1, target_id=1, summary=SEED_TEXT, family=FAMILY, owasp_category=OWASP,
                        verdict="failed", hard_evidence=False, turns_used=1, stopping_condition="turn_cap",
                        attacker_model="m")
    found = seeded.query_patterns(family=FAMILY, query_text=SEED_TEXT, n=10)
    assert len(found) == 5 and all(c.id.startswith("pattern:") for c in found)
