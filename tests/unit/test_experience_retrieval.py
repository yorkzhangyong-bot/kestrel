"""Warm retrieval: patterns semantic + family-scoped; memory by exact target id, recent-first, successes kept
(FR-016, FR-017, FR-018, SC-006, SC-014)."""
from kestrel.experience.store import ExperienceStore
from tests.support import StubEmbeddingFunction, fixture_library


def store(tmp_path) -> ExperienceStore:
    return ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())


def test_patterns_are_scoped_to_the_current_family(tmp_path):
    exp = store(tmp_path)
    exp.seed_patterns(fixture_library())  # documents are "<placeholder {family} prompt N>"
    docs = exp.retrieve_patterns(family="system_prompt_leak", query_text="anything", k=10)
    assert docs, "some patterns come back"
    assert all("system_prompt_leak" in d for d in docs)          # SC-014: 0 from other families


def test_pattern_k_limits_the_count(tmp_path):
    exp = store(tmp_path)
    exp.seed_patterns(fixture_library())
    assert len(exp.retrieve_patterns(family="direct_injection", query_text="x", k=2)) <= 2


def write_mem(exp, *, run_id, target_id, verdict="failed", family="system_prompt_leak"):
    exp.write_memory(run_id=run_id, target_id=target_id, summary=f"note for run {run_id}", family=family,
                     owasp_category="LLM07: System Prompt Leakage", verdict=verdict, hard_evidence=False,
                     turns_used=1, stopping_condition="turn_cap", attacker_model="m")


def test_memory_is_exact_target_only(tmp_path):
    exp = store(tmp_path)
    write_mem(exp, run_id=1, target_id=1)
    write_mem(exp, run_id=2, target_id=2)   # a different target
    got = exp.retrieve_memory(target_id=1, family="system_prompt_leak", cap=10)
    assert {m.run_id for m in got} == {1}    # SC-006: never another target's memory


def test_memory_is_recent_first_and_keeps_same_family_successes(tmp_path):
    exp = store(tmp_path)
    # Oldest run (1) is a same-family success; runs 2..5 are recent failures.
    write_mem(exp, run_id=1, target_id=1, verdict="succeeded")
    for rid in (2, 3, 4, 5):
        write_mem(exp, run_id=rid, target_id=1, verdict="failed")
    got = exp.retrieve_memory(target_id=1, family="system_prompt_leak", cap=2)
    run_ids = {m.run_id for m in got}
    assert {5, 4} <= run_ids          # the two most recent
    assert 1 in run_ids               # the older same-family success is kept despite the cap (FR-016)
    assert 2 not in run_ids and 3 not in run_ids


def test_a_cross_family_success_is_not_forced_in(tmp_path):
    exp = store(tmp_path)
    write_mem(exp, run_id=1, target_id=1, verdict="succeeded", family="direct_injection")  # other family
    for rid in (2, 3):
        write_mem(exp, run_id=rid, target_id=1, verdict="failed", family="system_prompt_leak")
    got = exp.retrieve_memory(target_id=1, family="system_prompt_leak", cap=1)
    assert 1 not in {m.run_id for m in got}  # only same-family successes are preserved past the cap
