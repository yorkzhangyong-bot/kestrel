"""The two deterministic steps FR-063 applies at every experience-store and retrieval-query boundary: removing
the run's exact filled task text wherever it sits, and replacing the run's own planted values wherever else they
appear. Stripping the template alone is not enough — a later attacker message or a judge progress note can repeat
a part or the URL — which is why both run together (research D11)."""
from kestrel.evidence import override

FEATURE = "013"

TOKEN = override.OverrideToken(first="abcdef", second="ghjkmn")
DIRECT_SEED = "<a placeholder direct-injection seed>"
INDIRECT_SEED = "First sentence of a placeholder seed. The content it presents as retrieved data."
CALLBACK_URL = "http://127.0.0.1:8000/callback/f00dcafef00dcafef00dcafe"
# A placeholder standing in for a filled callback task: the strip test needs only an exact known string that
# carries the URL, never the planting wording itself (FR-059).
CALLBACK_TASK = f"<a placeholder callback task carrying {CALLBACK_URL}>"


def paragraph() -> str:
    return override.override_task_paragraph(TOKEN)[0]


def test_stripping_removes_the_task_from_a_direct_seeds_attacker_voice_position():  # FR-063
    point = override.InsertionPoint(offset=len(DIRECT_SEED), fingerprint=override.fingerprint(DIRECT_SEED))
    sent = override.place_task(DIRECT_SEED, point, paragraph())
    assert paragraph() in sent
    assert override.strip_planted_tasks(sent, [paragraph()]) == DIRECT_SEED


def test_stripping_removes_the_task_from_inside_an_indirect_seeds_injected_content():  # FR-063
    point = override.insertion_point("indirect_injection", "iin-x", INDIRECT_SEED)
    sent = override.place_task(INDIRECT_SEED, point, paragraph())
    assert sent != INDIRECT_SEED and paragraph() in sent
    assert override.strip_planted_tasks(sent, [paragraph()]) == INDIRECT_SEED


def test_stripping_removes_a_callback_task_appended_in_the_users_voice():  # FR-063
    sent = f"<a placeholder tool-exfiltration seed>\n\n{CALLBACK_TASK}"
    assert override.strip_planted_tasks(sent, [CALLBACK_TASK]) == "<a placeholder tool-exfiltration seed>"


def test_stripping_removes_the_task_wherever_it_sits():  # FR-063
    for sent in (f"{paragraph()} then the rest", f"before {paragraph()}", f"a {paragraph()} b"):
        stripped = override.strip_planted_tasks(sent, [paragraph()])
        assert paragraph() not in stripped and stripped.strip()


def test_a_text_with_no_task_text_comes_back_byte_identical():  # FR-063
    for text in ("<an ordinary attacker message>", "", "the agent refused", DIRECT_SEED):
        assert override.strip_planted_tasks(text, [paragraph(), CALLBACK_TASK]) == text


def test_scrubbing_replaces_every_planted_value_wherever_else_it_appears():  # FR-063
    values = [TOKEN.joined, TOKEN.first, TOKEN.second, CALLBACK_URL]
    text = (f"the agent wrote {TOKEN.joined}, I had asked for {TOKEN.first} and {TOKEN.second}, "
            f"and the address {CALLBACK_URL} was never called")
    scrubbed = override.scrub_planted_values(text, values)
    for value in values:
        assert value not in scrubbed
    assert scrubbed.count(override.SCRUB_PLACEHOLDER) == 4
    assert "the agent wrote" in scrubbed and "was never called" in scrubbed


def test_the_joined_form_is_replaced_before_either_of_its_parts_can_split_it():  # FR-063
    scrubbed = override.scrub_planted_values(f"it said {TOKEN.joined}", [TOKEN.first, TOKEN.second, TOKEN.joined])
    assert scrubbed == f"it said {override.SCRUB_PLACEHOLDER}"   # one placeholder, not two


def test_scrubbing_leaves_text_without_a_planted_value_unchanged():  # FR-063
    for text in ("<an ordinary attacker message>", "", "no markers here at all"):
        assert override.scrub_planted_values(text, [TOKEN.joined, TOKEN.first, TOKEN.second, CALLBACK_URL]) == text
    assert override.scrub_planted_values("some text", []) == "some text"


def test_the_two_steps_together_leave_no_trace_of_the_run_in_a_sent_message():  # FR-063, SC-013
    point = override.InsertionPoint(offset=len(DIRECT_SEED), fingerprint=override.fingerprint(DIRECT_SEED))
    sent = override.place_task(DIRECT_SEED, point, paragraph())
    echoed = f"{sent}\n\nthe agent replied with {TOKEN.joined}"
    cleaned = override.scrub_planted_values(override.strip_planted_tasks(echoed, [paragraph()]),
                                            [TOKEN.joined, TOKEN.first, TOKEN.second])
    for value in (TOKEN.joined, TOKEN.first, TOKEN.second):
        assert value not in cleaned
    assert DIRECT_SEED in cleaned   # the attack content itself is what the pool keeps
