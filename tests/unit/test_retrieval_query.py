"""The retrieval query (feature 011, contracts/retrieval.md): the family label plus the attacker's own last two
messages, in conversation order — never an `agent` message, which is the target's masked reply — so nothing the
target writes steers which patterns the attacker is shown (FR-001). Placeholder texts only."""
from kestrel.attacks.library import family_label
from kestrel.experience.retrieval import QUERY_MESSAGES, build_query

FEATURE = "011"

FAMILY = "system_prompt_leak"
LABEL = family_label(FAMILY)
SEED = "<placeholder seed message>"


def test_the_window_is_two_attacker_messages():  # FR-001
    assert QUERY_MESSAGES == 2


def test_turn_two_is_the_label_plus_the_seed():  # FR-001
    assert build_query(FAMILY, [("attacker", SEED), ("agent", "<reply placeholder 1>")]) == (f"{LABEL} {SEED}", 1)


def test_agent_messages_never_enter_the_query():  # FR-001
    conversation = [("attacker", SEED), ("agent", "<reply placeholder 1>"),
                    ("attacker", "<attacker turn 2>"), ("agent", "<reply placeholder 2>")]
    text, used = build_query(FAMILY, conversation)
    assert (text, used) == (f"{LABEL} {SEED} <attacker turn 2>", 2)
    assert "reply" not in text


def test_only_the_last_two_attacker_messages_in_order_after_the_label():  # FR-001
    conversation = [("attacker", SEED), ("agent", "<reply placeholder 1>"),
                    ("attacker", "<attacker turn 2>"), ("agent", "<reply placeholder 2>"),
                    ("attacker", "<attacker turn 3>"), ("agent", "<reply placeholder 3>")]
    assert build_query(FAMILY, conversation) == (f"{LABEL} <attacker turn 2> <attacker turn 3>", 2)


def test_an_empty_conversation_is_the_label_alone():  # FR-001
    assert build_query(FAMILY, []) == (LABEL, 0)


def test_only_the_exact_attacker_role_counts():  # FR-001
    conversation = [("Attacker", "<x>"), ("attacker ", "<y>"), ("user", "<z>"), ("system", "<w>"),
                    ("attacker", SEED)]
    assert build_query(FAMILY, conversation) == (f"{LABEL} {SEED}", 1)


def test_the_label_is_the_family_label_also_for_an_unknown_family():  # FR-001
    assert build_query("made_up_family", [("attacker", SEED)]) == (f"made up family {SEED}", 1)
