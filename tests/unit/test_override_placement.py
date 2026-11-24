"""Where the planted override task goes (013/FR-064, FR-011, SC-014): the structural test.

The wording lives in a versioned prompt file and the insertion point in a Kestrel-owned sidecar, never in code
and never in the generated attack library. For an indirect-injection seed the point sits inside the seed's own
simulated injected content, so the instruction reaches the agent as retrieved data; for a direct-injection seed
it is the attacker-voice position, after the seed's text. A seed whose fingerprint no longer matches the library
text, or whose offset is out of range, fails here — so a library update forces a re-review of the points."""
import hashlib

import pytest

from kestrel.attacks.library import load_library
from kestrel.evidence import override

FEATURE = "013"

CARRYING = ("direct_injection", "indirect_injection")


@pytest.fixture(scope="module")
def library():
    return load_library()


@pytest.fixture(scope="module")
def points():
    return override.load_insertion_points()


def seeds(library, family):
    return library.prompts_in(family)


def test_every_carrying_seed_has_an_entry_and_no_other_seed_does(library, points):  # FR-011, FR-064
    carrying = {p.id for family in CARRYING for p in seeds(library, family)}
    assert set(points) == carrying
    others = {p.id for family in ("system_prompt_leak", "tool_exfiltration") for p in seeds(library, family)}
    assert others and not (others & set(points))


def test_every_entry_matches_its_seeds_current_library_text(library, points):  # FR-064
    for family in CARRYING:
        for seed in seeds(library, family):
            point = points[seed.id]
            assert point.fingerprint == hashlib.sha256(seed.text.encode("utf-8")).hexdigest()
            assert 0 < point.offset <= len(seed.text)


def test_a_direct_seeds_point_is_the_attacker_voice_position(library, points):  # FR-064
    for seed in seeds(library, "direct_injection"):
        point = points[seed.id]
        assert point.offset == len(seed.text)                      # the paragraph follows the seed's own text
        placed = override.place_task(seed.text, point, "<paragraph>")
        assert placed.startswith(seed.text) and placed.endswith("<paragraph>")


def test_an_indirect_seeds_point_sits_inside_its_simulated_injected_content(library, points):  # FR-064, SC-014
    for seed in seeds(library, "indirect_injection"):
        point = points[seed.id]
        # Strictly interior: the paragraph lands inside the seed's own content, never appended after it in
        # Kestrel's own voice (which is what an offset of len(text) would mean).
        assert 0 < point.offset < len(seed.text)
        placed = override.place_task(seed.text, point, "<paragraph>")
        assert placed != seed.text and "<paragraph>" in placed
        assert not placed.endswith("<paragraph>")                  # never in Kestrel's voice at the end
        assert placed.startswith(seed.text[:point.offset])
        assert placed.endswith(seed.text[point.offset:])
        # The point follows a sentence end, so the planted instruction reads as part of the retrieved content.
        assert seed.text[:point.offset].rstrip().endswith(".")


def test_the_runtime_lookup_returns_the_reviewed_point_for_every_shipped_seed(library, points):  # FR-064, SC-014
    """What a live run uses is the sidecar's reviewed point, never the derived fallback, for every shipped seed
    of both carrying families - so a library edit without a sidecar update fails here, not silently at run time."""
    for family in CARRYING:
        for seed in seeds(library, family):
            assert override.insertion_point(family, seed.id, seed.text) == points[seed.id]
    # And the fallback is what an edited seed would get: a point of the same shape, not the stale reviewed one.
    seed = seeds(library, "direct_injection")[0]
    edited = seed.text + " (edited)"
    assert override.insertion_point("direct_injection", seed.id, edited) != points[seed.id]
    assert override.insertion_point("direct_injection", seed.id, edited).offset == len(edited)


def test_a_seed_of_a_family_that_carries_no_task_is_sent_unchanged(library, points):  # FR-011
    for family in ("system_prompt_leak", "tool_exfiltration"):
        for seed in seeds(library, family):
            assert override.insertion_for(seed.id, seed.text) is None
            assert override.place_task(seed.text, None, "<paragraph>") == seed.text


def test_a_stale_fingerprint_or_an_out_of_range_offset_is_refused(library):  # FR-064
    seed = seeds(library, "indirect_injection")[0]
    with pytest.raises(override.InsertionPointError, match="fingerprint"):
        override.insertion_for(seed.id, seed.text + " (the library text changed)")
    out_of_range = {seed.id: override.InsertionPoint(offset=len(seed.text) + 5,
                                                     fingerprint=override.fingerprint(seed.text))}
    with pytest.raises(override.InsertionPointError, match="offset"):
        override.check_insertion_points({seed.id: seed.text}, out_of_range)


def test_the_override_template_declares_its_framing(library):  # SC-014
    from kestrel import prompt_registry
    files = prompt_registry.prompt_files()["override_task"]
    active = files[max(files, key=int)]
    assert active.framing == "override"   # structural, never judged by reading model behaviour
