"""The attack library validates itself at load time, so a broken library fails loudly (contracts/attack-library.md).

The fixtures here carry placeholder text, not real attack prompts: these tests check the rules, not the content.
"""
import json

import pytest

from kestrel.attacks.library import (FAMILIES, MAX_PROMPT_CHARS, AttackLibrary, LibraryError, build_library,
                                     load_library)

OWASP = {key: meta["owasp_category"] for key, meta in FAMILIES.items()}


def prompt(index: int, family: str, **over) -> dict:
    return {"id": f"fix-{index:03d}", "title": f"Fixture prompt {index}", "text": f"<fixture prompt text {index}>",
            "family": family, "owasp_category": OWASP[family], "source": "Fixture source",
            "source_url": "https://example.test/fixture", "licence": "CC BY 4.0", **over}


def library(prompts=None, version="1.0.0") -> dict:
    """Four prompts per family, so the count rules pass and a single rule can be broken per test."""
    if prompts is None:
        prompts = []
        index = 1
        for family in FAMILIES:
            for _ in range(4):
                prompts.append(prompt(index, family))
                index += 1
    return {"version": version, "prompts": prompts}


def test_a_well_formed_library_loads(tmp_path):
    lib = build_library(library())
    assert isinstance(lib, AttackLibrary)
    assert lib.version == "1.0.0"
    assert len(lib.prompts) == 16


def test_rule_1_version_must_be_a_non_empty_string():
    for bad in ("", "   ", None, 2):
        with pytest.raises(LibraryError, match="version"):
            build_library({**library(), "version": bad})


def test_rule_2_ids_are_unique_and_match_the_pattern():
    prompts = library()["prompts"]
    clashing = [*prompts[:-1], {**prompts[-1], "id": prompts[0]["id"]}]
    with pytest.raises(LibraryError, match="more than once"):
        build_library(library(clashing))
    for bad in ("FIX-001", "fixture-001", "fix-1", "fix-0001", ""):
        broken = [{**prompts[0], "id": bad}, *prompts[1:]]
        with pytest.raises(LibraryError, match="identifier"):
            build_library(library(broken))


def test_rule_3_family_must_be_one_of_the_four():
    prompts = library()["prompts"]
    with pytest.raises(LibraryError, match="attack families"):
        build_library(library([{**prompts[0], "family": "social_engineering"}, *prompts[1:]]))


def test_rule_4_owasp_category_must_match_the_family():
    prompts = library()["prompts"]
    wrong = {**prompts[0], "owasp_category": "LLM09: Overreliance"}
    with pytest.raises(LibraryError, match="OWASP"):
        build_library(library([wrong, *prompts[1:]]))


@pytest.mark.parametrize("field", ["title", "text", "source", "licence"])
def test_rule_5_required_text_fields_must_be_filled(field):
    prompts = library()["prompts"]
    with pytest.raises(LibraryError, match=field):
        build_library(library([{**prompts[0], field: "  "}, *prompts[1:]]))


def test_rule_6_each_family_needs_at_least_three_prompts():
    """Kept at 16 prompts, so this trips the per-family rule and not the total-count rule."""
    prompts = library()["prompts"]
    others = [p for p in prompts if p["family"] != "tool_exfiltration"]
    thin = [p for p in prompts if p["family"] == "tool_exfiltration"][:2]
    padding = [prompt(200 + i, "direct_injection") for i in range(2)]
    starved = others + thin + padding
    assert len(starved) == 16
    with pytest.raises(LibraryError, match="at least 3"):
        build_library(library(starved))


def test_rule_7_the_library_holds_between_16_and_24_prompts():
    with pytest.raises(LibraryError, match="between 16 and 24"):
        build_library(library(library()["prompts"][:12]))
    too_many = library()["prompts"]
    extra = [prompt(100 + i, "direct_injection") for i in range(9)]
    with pytest.raises(LibraryError, match="between 16 and 24"):
        build_library(library(too_many + extra))


def test_rule_8_no_two_prompts_share_the_same_text():
    prompts = library()["prompts"]
    duplicate = {**prompts[1], "text": prompts[0]["text"]}
    with pytest.raises(LibraryError, match="same text"):
        build_library(library([prompts[0], duplicate, *prompts[2:]]))


def test_a_prompt_longer_than_the_cap_is_refused():
    """Principle VIII allows plain conversation only; the cap stops a prompt becoming a flooding payload."""
    prompts = library()["prompts"]
    huge = {**prompts[0], "text": "x" * (MAX_PROMPT_CHARS + 1)}
    with pytest.raises(LibraryError, match="characters"):
        build_library(library([huge, *prompts[1:]]))


def test_families_report_their_category_and_count():
    lib = build_library(library())
    families = {f["key"]: f for f in lib.families()}
    assert set(families) == set(FAMILIES)
    assert families["system_prompt_leak"]["owasp_category"] == OWASP["system_prompt_leak"]
    assert families["system_prompt_leak"]["prompt_count"] == 4
    assert families["system_prompt_leak"]["label"] == FAMILIES["system_prompt_leak"]["label"]


def test_prompts_in_a_family_are_returned(my_library=None):
    lib = build_library(library())
    found = lib.prompts_in("tool_exfiltration")
    assert len(found) == 4
    assert {p.family for p in found} == {"tool_exfiltration"}


def test_pick_by_id_returns_that_prompt():
    lib = build_library(library())
    wanted = lib.prompts_in("direct_injection")[2]
    assert lib.pick("direct_injection", wanted.id).id == wanted.id


def test_pick_without_an_id_returns_one_from_that_family():
    lib = build_library(library())
    for _ in range(20):
        assert lib.pick("system_prompt_leak").family == "system_prompt_leak"


def test_pick_eventually_returns_more_than_one_prompt():
    """Uniformly at random, not a fixed first entry (contracts/attack-library.md)."""
    lib = build_library(library())
    seen = {lib.pick("direct_injection").id for _ in range(200)}
    assert len(seen) > 1


def test_an_unknown_family_or_id_is_refused():
    lib = build_library(library())
    with pytest.raises(LookupError, match="family"):
        lib.pick("nonsense")
    with pytest.raises(LookupError, match="family"):
        lib.prompts_in("nonsense")
    with pytest.raises(LookupError, match="prompt"):
        lib.pick("direct_injection", "fix-999")


def test_a_prompt_id_from_another_family_is_refused():
    lib = build_library(library())
    other = lib.prompts_in("tool_exfiltration")[0]
    with pytest.raises(LookupError, match="prompt"):
        lib.pick("direct_injection", other.id)


def test_load_library_reads_the_shipped_file():
    """The real library must satisfy every rule above, so a bad edit breaks the build (FR-001 to FR-005)."""
    lib = load_library()
    assert lib.version
    assert 16 <= len(lib.prompts) <= 24
    for family in FAMILIES:
        assert len(lib.prompts_in(family)) >= 3
    for p in lib.prompts:
        assert p.source and p.source_url and p.licence  # provenance is not optional (research R8)


def test_load_library_reports_the_file_it_could_not_read(tmp_path):
    broken = tmp_path / "library.json"
    broken.write_text(json.dumps(library(library()["prompts"][:2])), encoding="utf-8")
    with pytest.raises(LibraryError, match=str(broken.name)):
        load_library(broken)
