"""The selection (feature 011, contracts/retrieval.md): a nearest-first walk over a bounded candidate pool under a
distance floor and a near-identical threshold — far hits dropped instead of padding to k, a near-duplicate skipped
without spending a slot, nearest first, the count identity on every walk, short of k only when the pool is
exhausted (FR-003, FR-004, FR-005, SC-002, SC-003). Hand-built candidates with known vectors; placeholder texts."""
import random

from kestrel.experience.retrieval import Selection, select_patterns, squared_distance
from kestrel.experience.store import Candidate

FEATURE = "011"

DIM = 16


def unit(axis: int) -> tuple[float, ...]:
    """A one-hot vector: two different axes are at squared distance 2, the same axis at 0."""
    return tuple(1.0 if i == axis else 0.0 for i in range(DIM))


def candidate(name: str, distance: float, embedding: tuple[float, ...]) -> Candidate:
    return Candidate(id=f"pattern:lib:{name}", document=f"placeholder document {name}", distance=distance,
                     embedding=embedding)


def ids(selection: Selection) -> list[str]:
    return [i.removeprefix("pattern:lib:") for i in selection.pattern_ids]


def check_identity(selection: Selection) -> None:
    assert selection.candidate_count == selection.dropped_floor + selection.dropped_duplicate + len(selection.selected)


# a: near, b: near, c and d: far; a2 is a near-duplicate of a (same vector); all others pairwise distinct (2.0)
A, A2, B, C, D = (candidate("a", 0.2, unit(0)), candidate("a2", 0.3, unit(0)), candidate("b", 0.5, unit(1)),
                  candidate("c", 1.5, unit(2)), candidate("d", 1.7, unit(3)))


def test_a_floor_between_near_and_far_keeps_only_the_near_ones():  # FR-003, SC-002
    selection = select_patterns([A, B, C, D], k=5, distance_floor=1.0, dedupe_threshold=0.1)
    assert ids(selection) == ["a", "b"] and selection.dropped_floor == 2 and selection.dropped_duplicate == 0
    assert selection.candidate_count == 4 and selection.distances == [0.2, 0.5]
    check_identity(selection)
    assert all(hit.distance <= 1.0 for hit in selection.selected)


def test_a_floor_nothing_passes_selects_nothing():  # FR-003, SC-002
    selection = select_patterns([A, B, C, D], k=5, distance_floor=0.1, dedupe_threshold=0.1)
    assert ids(selection) == [] and selection.dropped_floor == selection.candidate_count == 4
    check_identity(selection)


def test_with_the_floor_off_alone_the_far_hit_returns_but_a_duplicate_is_still_skipped():  # FR-003, FR-004
    selection = select_patterns([A, A2, C], k=5, distance_floor=None, dedupe_threshold=0.1)
    assert ids(selection) == ["a", "c"] and selection.dropped_floor == 0 and selection.dropped_duplicate == 1
    check_identity(selection)


def test_with_the_threshold_off_alone_both_of_the_pair_return_but_the_far_hit_is_still_dropped():  # FR-003, FR-004
    selection = select_patterns([A, A2, C], k=5, distance_floor=1.0, dedupe_threshold=None)
    assert ids(selection) == ["a", "a2"] and selection.dropped_floor == 1 and selection.dropped_duplicate == 0
    check_identity(selection)


def test_with_both_controls_off_the_result_is_the_k_nearest_as_in_feature_004():  # FR-003, SC-002
    selection = select_patterns([A, A2, B, C, D], k=3, distance_floor=None, dedupe_threshold=None)
    assert ids(selection) == ["a", "a2", "b"] and (selection.dropped_floor, selection.dropped_duplicate) == (0, 0)
    assert selection.candidate_count == 3   # the walk stops once k are selected: later candidates are not examined
    check_identity(selection)


def test_a_duplicate_is_skipped_and_the_distinct_third_fills_the_selection():  # FR-004, FR-005
    selection = select_patterns([A, A2, B], k=2, distance_floor=1.0, dedupe_threshold=0.1)
    assert ids(selection) == ["a", "b"] and selection.dropped_duplicate == 1 and selection.candidate_count == 3
    check_identity(selection)
    for first in selection.selected:   # no two selected hits within the threshold of each other (SC-003)
        for second in selection.selected:
            assert first is second or squared_distance(first.embedding, second.embedding) > 0.1


def test_a_threshold_of_none_skips_nothing():  # FR-004
    selection = select_patterns([A, A2, B], k=3, distance_floor=None, dedupe_threshold=None)
    assert ids(selection) == ["a", "a2", "b"] and selection.dropped_duplicate == 0


def test_the_selection_is_nearest_first_whatever_the_input_order():  # FR-005
    shuffled = [D, B, C, A]
    random.Random(7).shuffle(shuffled)
    selection = select_patterns(shuffled, k=5, distance_floor=None, dedupe_threshold=None)
    assert ids(selection) == ["a", "b", "c", "d"] and selection.distances == [0.2, 0.5, 1.5, 1.7]


def test_a_hit_at_exactly_the_floor_is_kept():  # FR-003 (edge case)
    selection = select_patterns([A, C, D], k=5, distance_floor=1.5, dedupe_threshold=None)
    assert ids(selection) == ["a", "c"] and selection.dropped_floor == 1
    check_identity(selection)


def test_two_hits_at_exactly_the_threshold_are_near_identical():  # FR-004 (edge case)
    half = tuple(0.5 if i in (0, 1) else 0.0 for i in range(DIM))   # squared distance 0.5 from unit(0)
    assert squared_distance(unit(0), half) == 0.5
    pair = [candidate("a", 0.2, unit(0)), candidate("h", 0.4, half)]
    at_threshold = select_patterns(pair, k=2, distance_floor=None, dedupe_threshold=0.5)
    assert ids(at_threshold) == ["a"] and at_threshold.dropped_duplicate == 1
    below = select_patterns(pair, k=2, distance_floor=None, dedupe_threshold=0.49)
    assert ids(below) == ["a", "h"] and below.dropped_duplicate == 0


def test_the_walk_stops_once_k_are_selected_and_the_floor_counts_every_farther_candidate():  # FR-003, SC-003
    early = select_patterns([A, B, C, D], k=1, distance_floor=None, dedupe_threshold=None)
    assert ids(early) == ["a"] and early.candidate_count == 1
    farther = select_patterns([A, B, C, D], k=5, distance_floor=0.4, dedupe_threshold=None)
    assert ids(farther) == ["a"] and farther.dropped_floor == 3 and farther.candidate_count == 4
    check_identity(early)
    check_identity(farther)


def pool(k: int, duplicates: int, distinct: int) -> list[Candidate]:
    """One selected candidate, then `duplicates` near-duplicates of it, then `distinct` distinct ones, nearest
    first (all within any floor)."""
    first = [candidate("first", 0.1, unit(0))]
    dups = [candidate(f"dup{i}", 0.2 + i * 0.001, unit(0)) for i in range(duplicates)]
    rest = [candidate(f"new{i}", 0.5 + i * 0.001, unit(1 + i)) for i in range(distinct)]
    return first + dups + rest


def test_a_pool_of_4k_with_3k_minus_1_duplicates_yields_k_without_examining_the_last():  # FR-004, SC-003
    k = 3
    candidates = pool(k, 3 * k - 1, k)
    assert len(candidates) == 4 * k
    selection = select_patterns(candidates, k=k, distance_floor=None, dedupe_threshold=0.1)
    assert len(selection.selected) == k and selection.dropped_duplicate == 3 * k - 1
    assert selection.candidate_count == 4 * k - 1   # the last distinct candidate is never examined
    check_identity(selection)


def test_a_pool_of_4k_minus_1_with_k_minus_1_distinct_yields_k_with_every_candidate_examined():  # SC-003
    k = 3
    candidates = pool(k, 3 * k - 1, k - 1)
    assert len(candidates) == 4 * k - 1
    selection = select_patterns(candidates, k=k, distance_floor=None, dedupe_threshold=0.1)
    assert len(selection.selected) == k and selection.candidate_count == 4 * k - 1
    check_identity(selection)


def test_a_pool_of_4k_minus_2_with_k_minus_2_distinct_is_short_of_k_only_because_it_is_exhausted():  # SC-003
    k = 3
    candidates = pool(k, 3 * k - 1, k - 2)
    assert len(candidates) == 4 * k - 2
    selection = select_patterns(candidates, k=k, distance_floor=None, dedupe_threshold=0.1)
    assert len(selection.selected) == k - 1 and selection.candidate_count == 4 * k - 2   # every candidate examined
    check_identity(selection)


def test_k_zero_and_an_empty_pool_select_nothing():  # FR-005
    assert select_patterns([A, B], k=0, distance_floor=1.0, dedupe_threshold=0.1).selected == ()
    empty = select_patterns([], k=5, distance_floor=1.0, dedupe_threshold=0.1)
    assert empty.selected == () and empty.candidate_count == 0 and empty.distances == []
