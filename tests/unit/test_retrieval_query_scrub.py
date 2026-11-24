"""The retrieval query never carries a run's planted values (013/FR-063, 013/SC-013): `build_query` strips the
run's exact filled task text and scrubs its token parts, the joined form and a callback URL from every attacker
message it joins — including a turn-2 message that repeats the parts, which stripping alone would not touch."""
from kestrel.attacks.library import family_label
from kestrel.experience.retrieval import build_query

FEATURE = "013"

FAMILY = "direct_injection"
LABEL = family_label(FAMILY)
FIRST, SECOND = "abcdef", "ghjkmn"
JOINED = FIRST + SECOND
URL = "http://127.0.0.1:8000/callback/f00dcafef00dcafef00dcafe"
TASK = f"<a placeholder task carrying {FIRST} then {SECOND}>"
SEED = f"<placeholder seed> {TASK}"
VALUES = [JOINED, FIRST, SECOND, URL]


def test_a_turn_two_message_that_repeats_the_parts_is_scrubbed_before_it_is_used_to_search():  # FR-063, SC-013
    conversation = [("attacker", SEED), ("agent", "<reply>"),
                    ("attacker", f"<turn 2> again {FIRST} and {SECOND}, the whole thing is {JOINED.upper()}"),
                    ("agent", "<reply>")]
    text, used = build_query(FAMILY, conversation, planted_values=VALUES, task_texts=[TASK])
    assert used == 2 and text.startswith(LABEL)
    for value in (FIRST, SECOND, JOINED, TASK):
        assert value not in text and value.upper() not in text
    assert "<placeholder seed>" in text and "<turn 2>" in text   # the attack content itself still searches


def test_a_callback_url_in_a_later_message_is_scrubbed_too():  # FR-063
    conversation = [("attacker", SEED), ("agent", "<reply>"), ("attacker", f"<turn 2> please open {URL}"),
                    ("agent", "<reply>")]
    text, _ = build_query(FAMILY, conversation, planted_values=VALUES, task_texts=[TASK])
    assert URL not in text and "<turn 2> please open" in text


def test_without_planted_values_the_query_is_exactly_what_it_was_before():  # FR-061
    conversation = [("attacker", "<placeholder seed>"), ("agent", "<reply>"), ("attacker", "<turn 2>"),
                    ("agent", "<reply>")]
    assert build_query(FAMILY, conversation) == (f"{LABEL} <placeholder seed> <turn 2>", 2)
    assert build_query(FAMILY, conversation, planted_values=[], task_texts=[]) == build_query(FAMILY, conversation)
