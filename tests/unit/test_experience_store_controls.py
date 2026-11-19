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
OTHER_FAMILY = "direct_injection"
OTHER_OWASP = "LLM01: Prompt Injection"
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


# ---- write_pattern (FR-006, FR-007, FR-008, SC-004) ----

THRESHOLD = 0.3   # the stub's scale: identical texts are at 0, one token of six changed at ~0.333
DISTINCT = "orchestra rehearsal tuesday evening"   # shares no token (and no hash bucket) with any fixture pattern


def write(store, run_id, document, *, family=FAMILY, owasp=OWASP, threshold=THRESHOLD):
    return store.write_pattern(run_id=run_id, document=document, family=family, owasp_category=owasp,
                               dedupe_threshold=threshold)


def record(store, pattern_id) -> tuple[str, dict]:
    got = store._collection.get(ids=[pattern_id], include=["metadatas", "documents"])
    return got["documents"][0], got["metadatas"][0]


def test_a_success_equal_to_a_library_seed_merges_into_it(seeded):  # FR-006, FR-007
    from kestrel.experience.store import PatternWrite

    before = seeded.count("pattern")
    result = write(seeded, 101, SEED_TEXT)
    assert isinstance(result, PatternWrite)
    assert (result.outcome, result.pattern_id, result.hit_count) == ("merged", "pattern:lib:spl-001", 2)
    assert result.distance == pytest.approx(0.0, abs=1e-6)
    assert seeded.count("pattern") == before                       # no new record
    document, meta = record(seeded, "pattern:lib:spl-001")
    assert document == SEED_TEXT                                   # the document is untouched
    assert meta["hit_count"] == 2 and meta["last_hit_run_id"] == 101
    again = write(seeded, 102, SEED_TEXT)
    assert (again.outcome, again.hit_count) == ("merged", 3)
    assert record(seeded, "pattern:lib:spl-001")[1]["last_hit_run_id"] == 102


def test_a_distinct_success_is_added_with_a_hit_count_of_one(seeded):  # FR-006, FR-007
    result = write(seeded, 201, DISTINCT)
    assert result.outcome == "added" and result.hit_count == 1
    assert result.pattern_id.startswith("pattern:run:")   # a fresh uuid, never pattern:run:<run_id> (011 review)
    assert result.distance is not None and result.distance > THRESHOLD
    _, meta = record(seeded, result.pattern_id)
    assert meta["hit_count"] == 1 and meta["family"] == FAMILY and meta["origin_run_id"] == 201
    assert "last_hit_run_id" not in meta
    assert seeded.count("pattern") == len(fixture_library().prompts) + 1


def test_a_success_near_identical_only_to_another_familys_pattern_is_added_in_its_own_family(seeded):  # FR-006
    other_family_seed = "<placeholder direct_injection prompt 1>"   # the direct_injection seed, verbatim
    result = write(seeded, 301, other_family_seed, family=FAMILY)
    assert result.outcome == "added"
    assert result.pattern_id.startswith("pattern:run:")
    _, meta = record(seeded, result.pattern_id)
    assert meta["family"] == FAMILY and meta["origin_run_id"] == 301
    assert record(seeded, "pattern:lib:dir-001")[1]["hit_count"] == 1   # the other family's pattern is untouched


def test_two_near_identical_run_successes_add_once_then_merge(seeded):  # FR-006, SC-004
    first = write(seeded, 401, DISTINCT)
    second = write(seeded, 402, DISTINCT)
    third = write(seeded, 403, f"{DISTINCT} again")   # one token added: within the threshold on the stub's scale
    assert first.outcome == "added" and first.pattern_id.startswith("pattern:run:")
    assert (second.outcome, second.pattern_id, second.hit_count) == ("merged", first.pattern_id, 2)
    assert (third.outcome, third.pattern_id, third.hit_count) == ("merged", first.pattern_id, 3)
    assert 0 < third.distance <= THRESHOLD
    assert seeded.count("pattern") == len(fixture_library().prompts) + 1


def test_de_duplication_off_always_adds(seeded):  # FR-008
    result = write(seeded, 501, SEED_TEXT, threshold=None)
    assert result.outcome == "added" and result.hit_count == 1
    assert result.pattern_id.startswith("pattern:run:")
    assert result.distance is None
    assert seeded.count("pattern") == len(fixture_library().prompts) + 1
    assert record(seeded, "pattern:lib:spl-001")[1]["hit_count"] == 1
    assert record(seeded, result.pattern_id)[1]["origin_run_id"] == 501


def test_an_empty_family_adds_with_no_distance(tmp_path):  # FR-006
    store = ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())
    result = write(store, 601, SEED_TEXT)
    assert result.outcome == "added" and result.hit_count == 1
    assert result.pattern_id.startswith("pattern:run:")
    assert result.distance is None


def test_a_pattern_without_a_hit_count_counts_as_one(seeded):  # FR-007
    seeded._collection.upsert(ids=["pattern:run:7"], documents=[DISTINCT],   # written before this feature
                              metadatas=[{"type": "pattern", "family": FAMILY, "owasp_category": OWASP,
                                          "source": "run:7", "origin_run_id": 7}])
    result = write(seeded, 701, DISTINCT)
    assert (result.outcome, result.pattern_id, result.hit_count) == ("merged", "pattern:run:7", 2)
    assert record(seeded, "pattern:run:7")[1]["hit_count"] == 2


def test_reseeding_keeps_hit_counts_and_gives_a_new_seed_one(seeded):  # FR-007
    from kestrel.attacks.library import build_library
    from tests.support import fixture_library_data

    write(seeded, 801, SEED_TEXT)   # merged into spl-001
    data = fixture_library_data()
    data["prompts"].append({**data["prompts"][5], "id": "spl-006", "title": "system_prompt_leak placeholder 6",
                            "text": "<placeholder system_prompt_leak prompt 6>"})
    seeded.seed_patterns(build_library(data))
    _, merged = record(seeded, "pattern:lib:spl-001")
    assert merged["hit_count"] == 2 and merged["last_hit_run_id"] == 801     # untouched by the re-seed
    assert record(seeded, "pattern:lib:spl-006")[1]["hit_count"] == 1       # a new seed id starts at one
    assert record(seeded, "pattern:lib:spl-002")[1]["hit_count"] == 1
    assert seeded.count("pattern") == len(fixture_library().prompts) + 1


def test_n_near_identical_successes_leave_one_pattern_with_hit_count_n_and_distinct_ones_add_n(seeded):  # SC-004
    seeds = len(fixture_library().prompts)
    results = [write(seeded, run_id, "placeholder orchestra rehearsal") for run_id in (901, 902, 903, 904)]
    assert seeded.count("pattern") == seeds + 1
    assert results[0].outcome == "added" and results[0].pattern_id.startswith("pattern:run:")
    assert all((r.outcome, r.pattern_id) == ("merged", results[0].pattern_id) for r in results[1:])
    assert record(seeded, results[0].pattern_id)[1]["hit_count"] == 4
    for run_id, text in ((911, "one two"), (912, "three four"), (913, "step staged")):   # pairwise disjoint
        result = write(seeded, run_id, text)
        assert result.outcome == "added" and result.hit_count == 1
        assert result.pattern_id.startswith("pattern:run:")
    assert seeded.count("pattern") == seeds + 4


def test_a_reused_run_id_does_not_corrupt_an_earlier_patterns_record(seeded):  # FR-006, FR-007
    """The independent review's regression. Before this fix, `write_pattern`'s add path upserted the id
    `pattern:run:<run_id>`, so once the target that owned a run was deleted (patterns carry no target identity,
    so that step alone never touches the store) and, on a pre-schema-v9 database, SQLite reissued that run's
    numeric id to a later run, a success for the new run silently overwrote the surviving, still-shared pattern:
    its document and hit count clobbered, its `last_hit_run_id` stale. Schema v9 stops SQLite from reissuing a
    run's id (tests/unit/test_store_migration_v9.py), but the store itself must not depend on that — this forces
    the same numeric run_id onto a second, unrelated success in another family directly, as if it had been reissued anyway."""
    first = write(seeded, 2001, DISTINCT)
    assert first.outcome == "added" and first.hit_count == 1
    second = write(seeded, 2002, DISTINCT)   # a near-identical success merges into the first pattern
    assert (second.outcome, second.pattern_id, second.hit_count) == ("merged", first.pattern_id, 2)

    # Run 2001's target is deleted here in the real system; its id is later reused by an unrelated success in
    # another family, the case the review reproduced (the overwritten record took the new family too).
    third = write(seeded, 2001, "canyon bicycle lighthouse marble", family=OTHER_FAMILY, owasp=OTHER_OWASP)
    assert third.outcome == "added" and third.hit_count == 1
    assert third.pattern_id != first.pattern_id and third.pattern_id.startswith("pattern:run:")

    document, meta = record(seeded, first.pattern_id)
    assert document == DISTINCT                                     # not overwritten by the id-2001 reuse
    assert (meta["family"], meta["owasp_category"]) == (FAMILY, OWASP)   # not moved to the reusing family
    assert meta["hit_count"] == 2 and meta["last_hit_run_id"] == 2002
    _, reused = record(seeded, third.pattern_id)
    assert (reused["family"], reused["origin_run_id"], reused["hit_count"]) == (OTHER_FAMILY, 2001, 1)
