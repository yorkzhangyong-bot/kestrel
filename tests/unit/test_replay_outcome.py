"""`compute_outcome`: the pure mapping from a replay's own per-turn results to fixed / still_vulnerable /
inconclusive (data-model.md "research D5"; 012/FR-012 to FR-016, 012/SC-002).

`turn_results` is the sequence of each turn's own result, captured live as the replay runs - never the run's one
final `verdict`, which a later clean failure could otherwise hide an earlier unresolved turn behind."""
import pytest

from kestrel.replay import compute_outcome

FEATURE = "012"


# ---- any success wins, regardless of how many turns were sent (FR-013) ----


@pytest.mark.parametrize("turn_results, recorded_total", [
    (["succeeded"], 1),
    (["failed", "succeeded"], 3),          # stopped early at its own success - not misread as "cut short"
    (["succeeded", "failed", "failed"], 3),
])
def test_any_succeeded_entry_is_still_vulnerable(turn_results, recorded_total):  # FR-013
    assert compute_outcome(turn_results, recorded_total, winning_turn=None) == "still_vulnerable"


# ---- the single-message case: recorded_total == 1, the winning-turn check never applies (FR-014) ----


def test_a_single_message_source_judged_failed_is_fixed_regardless_of_winning_turn():  # FR-014
    assert compute_outcome(["failed"], 1, winning_turn=None) == "fixed"
    assert compute_outcome(["failed"], 1, winning_turn=1) == "fixed"   # an adaptive source that won on turn 1


def test_a_single_message_source_with_an_unresolved_turn_is_inconclusive():  # FR-015
    assert compute_outcome([None], 1, winning_turn=None) == "inconclusive"


def test_a_single_message_source_that_never_sent_is_inconclusive():  # FR-015 (the send itself failed)
    assert compute_outcome([], 1, winning_turn=None) == "inconclusive"


# ---- the multi-message case without the winning-turn addition: every turn sent and judged failed ----


def test_every_recorded_message_sent_and_failed_with_the_winning_turn_itself_failed_is_fixed():  # FR-014
    assert compute_outcome(["failed", "failed", "failed"], 3, winning_turn=3) == "fixed"


def test_fewer_turns_sent_than_recorded_is_inconclusive_even_if_all_sent_ones_failed():  # FR-015
    assert compute_outcome(["failed", "failed"], 3, winning_turn=3) == "inconclusive"


def test_an_unresolved_turn_anywhere_is_inconclusive_including_the_first():  # FR-015, SC-002
    """The exact regression case: a naive implementation reading only the last entry, or the run's own aggregate
    verdict, would wrongly call this "fixed" - turn 1 was never resolved, so it must not be hidden behind turns
    2 and 3's clean failures."""
    assert compute_outcome([None, "failed", "failed"], 3, winning_turn=3) == "inconclusive"


@pytest.mark.parametrize("turn_results", [
    ["failed", None, "failed"],
    ["failed", "failed", None],
])
def test_an_unresolved_turn_anywhere_else_is_also_inconclusive(turn_results):  # FR-015, SC-002
    assert compute_outcome(turn_results, 3, winning_turn=3) == "inconclusive"


# ---- the winning-turn addition itself, recorded_total > 1 (FR-014) ----


def test_the_winning_turn_not_reached_is_inconclusive_even_if_every_sent_turn_failed():  # FR-014
    """The current turn limit cut the replay short before it reached its own winning (= last recorded) turn."""
    assert compute_outcome(["failed", "failed"], 3, winning_turn=3) == "inconclusive"


def test_the_winning_turn_sent_but_unresolved_is_inconclusive_even_if_every_other_turn_failed():  # FR-014
    assert compute_outcome(["failed", "failed", None], 3, winning_turn=3) == "inconclusive"


def test_no_recorded_winning_turn_on_a_multi_message_source_is_inconclusive_never_fixed():  # FR-015 (fail closed;
    # defensive: not reachable through normal operation, since a real run's winning turn is always its own last
    # recorded turn)
    assert compute_outcome(["failed", "failed", "failed"], 3, winning_turn=None) == "inconclusive"


def test_a_winning_turn_position_outside_the_sent_range_is_inconclusive():  # FR-015 (defensive)
    assert compute_outcome(["failed", "failed", "failed"], 3, winning_turn=5) == "inconclusive"


def test_position_indexing_on_a_synthetic_winning_turn_a_real_source_cannot_produce():  # FR-014
    """Not a shape any real run produces (a run's winning turn is always its own last recorded turn), but
    compute_outcome's position-indexing logic must still handle it correctly."""
    assert compute_outcome(["failed", "failed", "failed"], 3, winning_turn=2) == "fixed"
