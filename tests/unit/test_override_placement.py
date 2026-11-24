"""Where the planted override task goes (013/FR-064, FR-011, SC-014): the structural test.

The wording lives in a versioned prompt file and the insertion point in a Kestrel-owned sidecar, never in code
and never in the generated attack library. For an indirect-injection seed the point sits inside the seed's own
simulated injected content, wrapped in the quoting frame the sidecar records for that seed — a neutral prefix
and suffix presenting the paragraph as a quoted excerpt of the document, email, OCR text or ticket the seed names
— so the instruction reaches the agent as quoted retrieved content; for a direct-injection seed it is the
attacker-voice position, after the seed's text, with no frame. A seed whose fingerprint no longer matches the
library text, or whose offset is out of range, fails here — so a library update forces a re-review of the points
and the frames.

What the frame proves and does not prove: a framed seed simulates retrieved content *inside the user turn*, so a
confirmed run shows the agent followed an instruction presented as retrieved content; it does not show the
instruction travelled a real retrieval path (a tool result or a document the agent fetched itself) — that proof
comes with the part-2 side channel. The frame wording itself is a reviewed property (`traceability.md`, SC-014);
what is asserted here is structural: the frame is present, the paragraph sits inside its quoted span, and the
joined form is absent from the framed message after normalisation."""
import hashlib
import json

import pytest

from kestrel.attacks.library import load_library
from kestrel.evidence import override
from kestrel.evidence.checker import build_checker

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
        assert point.frame_prefix == "" and point.frame_suffix == ""   # no frame: the attacker's own voice
        assert point.frame("<paragraph>") == "<paragraph>"
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


def test_an_indirect_seeds_frame_presents_the_paragraph_as_a_quoted_excerpt(library, points):  # FR-064, SC-014
    """For every shipped indirect seed: the frame is present, the paragraph sits inside the frame's quoted span,
    and the whole framed text is what went into the seed at its point - the one string FR-063 strips again."""
    for seed in seeds(library, "indirect_injection"):
        point = points[seed.id]
        assert point.frame_prefix and point.frame_suffix
        assert point.frame_prefix.endswith('"') and point.frame_suffix.startswith('"')   # a quoted span
        placed = override.place_task(seed.text, point, "<paragraph>")
        opened = placed.index(point.frame_prefix)
        inside = placed.index("<paragraph>")
        closed = placed.index(point.frame_suffix, inside + len("<paragraph>"))
        assert opened == point.offset and opened < inside < closed
        assert placed == f"{seed.text[:point.offset]}{point.frame('<paragraph>')} {seed.text[point.offset:]}"
        # Only a run that plants the task carries the frame: the library seed itself has none of it.
        assert point.frame_prefix not in seed.text


def test_the_framed_message_never_carries_the_joined_form_even_after_normalisation(library, points):  # FR-009, FR-064
    for seed in seeds(library, "indirect_injection"):
        for _ in range(25):
            token = override.generate_override_token()
            paragraph = override.override_task_paragraph(token)[0]
            placed = override.place_task(seed.text, points[seed.id], paragraph)
            assert token.first in placed and token.second in placed
            assert not override.text_contains_joined(placed, token.joined)


def test_the_runs_task_text_is_the_framed_paragraph_as_one_string(library, points):  # FR-063, FR-064
    """What `planted_task_texts()` hands FR-063's stripping is exactly what `place_task` put into the seed - the
    frame and the paragraph as one string - so stripping restores the seed byte-identical; and it is the same
    text whether the builder knew the seed (the run starters pass it) or learnt it from the opening message."""
    for seed in seeds(library, "indirect_injection"):
        point = points[seed.id]
        known = build_checker(store=None, family=seed.family, canaries=[], seed=seed)
        [task] = known.planted_task_texts()
        [joined, first, second] = known.planted_values()
        paragraph = override.override_task_paragraph(override.OverrideToken(first, second))[0]
        assert task == point.frame(paragraph) and task != paragraph
        sent = known.opening_message(seed)
        assert task in sent and override.strip_planted_tasks(sent, [task]) == seed.text
        assert known.planted_task_texts() == [task]                 # the same text before and after composing
        assert override.strip_planted_tasks(sent, [paragraph]) != seed.text   # the bare paragraph leaves the frame

        learnt = build_checker(store=None, family=seed.family, canaries=[])
        assert learnt.planted_task_texts() != [point.frame(learnt.planted_task_texts()[0])]
        sent = learnt.opening_message(seed)
        [task] = learnt.planted_task_texts()
        assert task.startswith(point.frame_prefix) and override.strip_planted_tasks(sent, [task]) == seed.text
    direct = seeds(library, "direct_injection")[0]
    checker = build_checker(store=None, family=direct.family, canaries=[], seed=direct)
    [task] = checker.planted_task_texts()
    assert override.strip_planted_tasks(checker.opening_message(direct), [task]) == direct.text


def test_a_frame_field_that_is_not_text_is_refused_and_an_absent_frame_means_none(tmp_path):  # FR-064
    sidecar = tmp_path / "points.json"
    entry = {"offset": 3, "fingerprint": "f" * 64}
    sidecar.write_text(json.dumps({"version": "1", "points": {"iin-x": {**entry, "frame_prefix": 7}}}),
                       encoding="utf-8")
    with pytest.raises(override.InsertionPointError, match="frame"):
        override.load_insertion_points(sidecar)
    sidecar.write_text(json.dumps({"version": "1", "points": {"dir-x": entry}}), encoding="utf-8")
    assert override.load_insertion_points(sidecar)["dir-x"].frame("<paragraph>") == "<paragraph>"


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
