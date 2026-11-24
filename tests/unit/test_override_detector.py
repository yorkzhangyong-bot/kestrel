"""The instruction-override token and its check (013/FR-008, FR-009, FR-012, FR-051, SC-001).

The token is two random parts; a reply confirms only when it carries them joined, which appears in nothing
Kestrel composes — asserted over 1,000 freshly generated tokens on the *normalised* opening message, the same
form the disarm check uses, so a target that strips whitespace or punctuation still cannot produce it.
No attack text here: the planting wording lives in the versioned prompt file, and this test only measures its
structural properties."""
import re

from kestrel.attacks.library import AttackPrompt
from kestrel.evidence import override

FEATURE = "013"

SEED = AttackPrompt(id="dir-001", title="t", text="<a placeholder direct-injection seed>",
                    family="direct_injection", owasp_category="LLM01: Prompt Injection", source="x",
                    source_url="x", licence="x")


def opening_message(token: override.OverrideToken) -> str:
    """The full text a direct-injection run would send with this token: the seed plus the planted paragraph."""
    paragraph, _ref = override.override_task_paragraph(token)
    return override.place_task(SEED.text, override.InsertionPoint(offset=len(SEED.text), fingerprint=""), paragraph)


def test_a_token_is_two_six_character_parts_from_the_unambiguous_alphabet():  # FR-008
    assert override.PART_LENGTH == 6 and len(override.ALPHABET) == 31
    assert set("ilo01") & set(override.ALPHABET) == set()      # no ambiguous symbols
    token = override.generate_override_token()
    assert len(token.first) == len(token.second) == 6
    assert set(token.first + token.second) <= set(override.ALPHABET)
    assert token.joined == token.first + token.second and len(token.joined) == 12


def test_ten_thousand_tokens_never_repeat():  # FR-008, FR-051
    joined = {override.generate_override_token().joined for _ in range(10_000)}
    assert len(joined) == 10_000


def test_a_reply_confirms_only_when_the_parts_are_joined(capsys):  # FR-009
    token = override.OverrideToken(first="abcdef", second="ghjkmn")
    assert override.reply_confirms(f"here it is: {token.joined}", token.joined) is True
    assert override.reply_confirms(token.joined.upper(), token.joined) is True            # letter case ignored
    assert override.reply_confirms(f"...{token.joined}...", token.joined) is True         # anywhere in the reply
    for separated in (f"{token.first} {token.second}", f"{token.first}-{token.second}",
                      f"{token.first}\n{token.second}", f"{token.first}, then {token.second}",
                      f"{token.first}.{token.second}", token.first, token.second, ""):
        assert override.reply_confirms(separated, token.joined) is False


def test_normalise_folds_case_and_drops_every_non_alphanumeric_character():  # FR-009, FR-012
    assert override.normalise("Ab c-D_e.f\n9") == "abcdef9"
    assert override.normalise("") == ""


def test_the_disarm_check_runs_on_the_normalised_text():  # FR-012
    token = override.OverrideToken(first="abcdef", second="ghjkmn")
    assert override.text_contains_joined(f"...{token.joined}...", token.joined) is True
    assert override.text_contains_joined(token.joined.upper(), token.joined) is True
    # A message that would only yield the joined form after normalisation disarms the token just as a verbatim one.
    assert override.text_contains_joined(f"{token.first} - {token.second}", token.joined) is True
    assert override.text_contains_joined(f"{token.first} and {token.second}", token.joined) is False
    assert override.text_contains_joined("nothing of the sort", token.joined) is False


def test_the_template_keeps_an_alphanumeric_word_between_the_two_parts():  # FR-009
    token = override.OverrideToken(first="abcdef", second="ghjkmn")
    paragraph, ref = override.override_task_paragraph(token)
    assert ref.startswith("override_task@")
    first_at, second_at = paragraph.index(token.first), paragraph.index(token.second)
    assert first_at < second_at
    between = paragraph[first_at + len(token.first):second_at]
    assert re.search(r"[0-9A-Za-z]", between), "at least one alphanumeric word must separate the parts"


def test_over_a_thousand_tokens_the_opening_message_never_contains_the_joined_form():  # FR-009, SC-001
    for _ in range(1000):
        token = override.generate_override_token()
        message = opening_message(token)
        assert token.first in message and token.second in message       # both parts are planted
        assert override.text_contains_joined(message, token.joined) is False
        assert override.reply_confirms(message, token.joined) is False


def test_the_paragraph_names_the_placeholders_the_contract_fixes():  # FR-010
    template = override.override_task_template()
    assert "{first_part}" in template and "{second_part}" in template
