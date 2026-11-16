"""The recall@k fixture check (feature 011, contracts/recall-fixture.md): a fresh temporary store is seeded from
`tests/fixtures/retrieval_recall.json` through the real seeding path, and every labelled query runs through
`query_patterns` + `select_patterns` with the fixture's own k, floor and threshold on the lexical stub (FR-014,
SC-005). The same file guards the fixture itself — ids, families, the published distances and their margins, the
hash buckets of the vocabulary, and that every text is placeholder vocabulary only, never attack wording — so a
change to the stub, the selection or the fixture fails loudly instead of eroding the yardstick."""
import json
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from kestrel.attacks.library import FAMILIES, ID_PATTERN
from kestrel.experience.retrieval import CANDIDATE_MULTIPLIER, select_patterns, squared_distance
from kestrel.experience.store import ExperienceStore
from tests.support import StubEmbeddingFunction, lexical_tokens

FEATURE = "011"

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval_recall.json"
# The contract's vocabulary: 21 neutral words, collision-free under the stub's hash (research D8).
VOCABULARY = ("placeholder approach alpha step one variant plain again beta two framing gamma three staged delta "
              "four opening orchestra rehearsal tuesday evening").split()
MARGIN = 0.1          # every published distance keeps at least this from both controls (the contract's table)
TOLERANCE = 1e-6      # on the published 4-decimal values
LIB_PREFIX = "pattern:lib:"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _library(fixture: dict):
    """A duck-typed library (`version`, `prompts` with `id`, `text`, `family`, `owasp_category`), so the fixture
    goes through `seed_patterns` exactly as the shipped library does."""
    prompts = [SimpleNamespace(id=p["id"], text=p["text"], family=p["family"],
                               owasp_category=FAMILIES[p["family"]]["owasp_category"]) for p in fixture["patterns"]]
    return SimpleNamespace(version="fixture", prompts=prompts)


@pytest.fixture
def seeded(tmp_path, fixture) -> ExperienceStore:
    store = ExperienceStore(tmp_path / "chroma", embedding_function=StubEmbeddingFunction())
    assert store.seed_patterns(_library(fixture)) == len(fixture["patterns"])
    return store


@pytest.fixture
def retrieved(seeded, fixture) -> list[dict]:
    """Every query run as production does: a pool of `k × 4` clamped to the family, then the selection with the
    fixture's own controls. Each entry keeps the candidates (the store's own distances and embeddings) and the
    selected ids without the `pattern:lib:` prefix."""
    results = []
    for query in fixture["queries"]:
        pool = min(fixture["k"] * CANDIDATE_MULTIPLIER, seeded.count("pattern", family=query["family"]))
        candidates = seeded.query_patterns(family=query["family"], query_text=query["text"], n=pool)
        selection = select_patterns(candidates, k=fixture["k"], distance_floor=fixture["distance_floor"],
                                    dedupe_threshold=fixture["dedupe_threshold"])
        results.append({"query": query, "candidates": candidates,
                        "selected": [c.id.removeprefix(LIB_PREFIX) for c in selection.selected]})
    return results


def _recall(expected: list[str], selected: list[str]) -> float:
    return len(set(expected) & set(selected)) / len(expected)


# ---- the score (FR-014, SC-005) ----


def test_mean_recall_at_k_meets_the_fixtures_minimum(retrieved, fixture):  # FR-014, SC-005
    labelled = [r for r in retrieved if r["query"]["expected"]]
    assert labelled, "the fixture labels at least one query with expected ids"
    recalls = [_recall(r["query"]["expected"], r["selected"]) for r in labelled]
    assert sum(recalls) / len(recalls) >= fixture["min_recall"]
    assert fixture["min_recall"] == 1.0 and all(recall == 1.0 for recall in recalls)   # SC-005: every expected id
    assert all(len(r["selected"]) <= fixture["k"] for r in retrieved)


def test_no_relevant_queries_select_nothing_with_the_floor_on(retrieved):  # FR-014, SC-005
    negatives = [r for r in retrieved if r["query"].get("no_relevant")]
    assert negatives, "the fixture labels at least one query as having no relevant pattern"
    for result in negatives:
        assert result["query"]["expected"] == [] and result["selected"] == []
        assert result["candidates"], "the negative query had candidates to drop — the floor did the work"


def test_exactly_one_of_each_duplicate_pair_is_selected(retrieved, fixture):  # FR-014, SC-005
    assert fixture["duplicate_pairs"], "the fixture labels at least one near-duplicate pair"
    for pair in fixture["duplicate_pairs"]:
        naming = [r for r in retrieved if set(r["query"]["expected"]) & set(pair)]
        assert naming, f"a query names one of the pair {pair}"
        for result in naming:
            chosen = set(result["selected"]) & set(pair)
            assert len(chosen) == 1 and chosen <= set(result["query"]["expected"])   # the nearer one, only


# ---- the fixture's own consistency ----


def test_every_expected_id_exists_and_every_family_is_known(fixture):  # FR-014
    ids = [p["id"] for p in fixture["patterns"]]
    assert len(ids) == len(set(ids)) and all(ID_PATTERN.match(pattern_id) for pattern_id in ids)
    assert all(p["family"] in FAMILIES for p in fixture["patterns"])
    assert all(q["family"] in FAMILIES for q in fixture["queries"])
    for query in fixture["queries"]:
        assert set(query["expected"]) <= set(ids)
        assert len(query["expected"]) <= fixture["k"]
        assert bool(query.get("no_relevant")) == (query["expected"] == [])
    for pair in fixture["duplicate_pairs"]:
        assert len(pair) == 2 and set(pair) <= set(ids)
    assert 0 < fixture["min_recall"] <= 1.0 and fixture["k"] >= 1
    assert fixture["distance_floor"] >= 0 and fixture["dedupe_threshold"] >= 0


def test_published_distances_are_reproduced_by_the_store(retrieved, fixture):  # FR-014
    """Query-to-pattern distances are the store's own values for the fixture's queries; pattern-to-pattern
    distances are the collection measure over the stored embeddings — what the selection de-duplicates on. Both
    are compared after rounding to 4 decimals, as the table publishes them."""
    published = fixture["expected_distances"]
    for index, pattern_id, expected in published["query_to_pattern"]:
        by_id = {c.id.removeprefix(LIB_PREFIX): c for c in retrieved[index]["candidates"]}
        assert pattern_id in by_id, f"query {index} never saw {pattern_id} — not a same-family pattern?"
        assert abs(round(by_id[pattern_id].distance, 4) - expected) <= TOLERANCE, (index, pattern_id)
    embeddings = {c.id.removeprefix(LIB_PREFIX): c.embedding for r in retrieved for c in r["candidates"]}
    for left, right, expected in published["pattern_to_pattern"]:
        assert left in embeddings and right in embeddings
        assert abs(round(squared_distance(embeddings[left], embeddings[right]), 4) - expected) <= TOLERANCE, (left,
                                                                                                             right)


def test_every_published_distance_keeps_its_margin_from_both_controls(fixture):  # FR-014
    published = fixture["expected_distances"]
    distances = [entry[2] for entry in published["query_to_pattern"]] + \
                [entry[2] for entry in published["pattern_to_pattern"]]
    assert distances
    for distance in distances:
        for control in (fixture["distance_floor"], fixture["dedupe_threshold"]):
            assert abs(distance - control) >= MARGIN, (distance, control)


def test_the_vocabulary_is_collision_free_under_the_stubs_hash():  # FR-014
    assert len(VOCABULARY) == 21 and len(set(VOCABULARY)) == 21
    buckets = {word: zlib.crc32(word.encode("utf-8")) % StubEmbeddingFunction.DIM for word in VOCABULARY}
    assert len(set(buckets.values())) == len(VOCABULARY), buckets


def test_every_text_is_placeholder_vocabulary_only(fixture):  # FR-014
    """The guard against attack wording: every pattern and query text is built from the contract's vocabulary."""
    texts = [p["text"] for p in fixture["patterns"]] + [q["text"] for q in fixture["queries"]]
    assert texts and all(texts)
    for text in texts:
        tokens = lexical_tokens(text)
        assert tokens and set(tokens) <= set(VOCABULARY), text
