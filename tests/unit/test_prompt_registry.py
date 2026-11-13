"""The prompt registry over the prompt files: three kinds at version 1, load_prompt/has/text_for/active_version,
the file format, and the version shape (009/FR-001, 009/FR-002, 009/FR-009)."""
from pathlib import Path

import pytest

from kestrel import prompt_registry as pr
from kestrel.store import FAMILIES

FEATURE = "009"

EXPECTED_IDS = {
    "attacker:direct_injection",
    "attacker:system_prompt_leak",
    "attacker:tool_exfiltration",
    "attacker:indirect_injection",
    "judge",
    "recommender",
}


def _write(directory: Path, prompt_id: str, version: str, text: str) -> Path:
    path = pr.prompt_path(prompt_id, version, directory)
    path.write_text(pr.format_prompt_file(prompt_id, version, text), encoding="utf-8", newline="\n")
    return path


def test_registry_lists_the_three_kinds_at_version_1():  # 009/FR-001, 009/FR-002
    entries = pr.registry()
    assert {e.id for e in entries} == EXPECTED_IDS
    assert all(e.version == "1" for e in entries)
    assert all(e.text and e.fingerprint == pr.fingerprint(e.text) for e in entries)


def test_every_prompt_is_a_front_matter_file_and_no_prompt_text_lives_in_python():  # 009/FR-001, 009/FR-011
    for entry in pr.registry():
        path = pr.prompt_path(entry.id, entry.version)
        assert path.is_file() and path.parent == pr.PROMPTS_DIR
        assert path.read_text(encoding="utf-8").startswith(f"---\nid: {entry.id}\nversion: {entry.version}\n---\n")
    import kestrel.attack.attacker as attacker
    import kestrel.judge.client as judge
    for module, name in ((attacker, "SYSTEM_PROMPT"), (attacker, "GOALS"), (judge, "SYSTEM_PROMPT"),
                         (judge, "RECOMMEND_SYSTEM_PROMPT")):
        assert not hasattr(module, name)   # the files are the only source of a prompt's text


def test_load_prompt_returns_the_active_text_and_its_reference():  # 009/FR-001
    text, ref = pr.load_prompt("judge")
    assert ref == "judge@1"
    assert text == pr.text_for("judge", "1") == next(e.text for e in pr.registry() if e.id == "judge")


def test_no_summariser_prompt_is_registered():  # 009 — three model-facing kinds only
    assert not any("summar" in e.id for e in pr.registry())


def test_has_and_active_version():  # 009/FR-009
    assert pr.has("judge", "1")
    assert not pr.has("judge", "99")
    assert not pr.has("attacker:nope", "1")
    assert pr.active_version("judge") == "1"
    with pytest.raises(pr.PromptNotRegistered):
        pr.active_version("attacker:nope")
    with pytest.raises(pr.PromptNotRegistered):
        pr.load_prompt("attacker:nope")


def test_text_for_unknown_is_refused():  # 009/FR-009
    with pytest.raises(pr.PromptNotRegistered):
        pr.text_for("judge", "99")
    with pytest.raises(pr.PromptNotRegistered):
        pr.text_for("recommender", "nope")


def test_families_are_the_attacker_prompts_on_disk():  # 009/FR-001
    assert set(pr.families()) == set(FAMILIES)


def test_the_highest_file_version_is_active_and_older_ones_stay_readable(tmp_path, monkeypatch):  # 009/FR-001
    monkeypatch.setattr(pr, "PROMPTS_DIR", tmp_path)
    _write(tmp_path, "judge", "1", "first judge text")
    _write(tmp_path, "judge", "2", "second judge text")
    _write(tmp_path, "judge", "10", "tenth judge text")   # numeric order, not lexicographic
    assert pr.active_version("judge") == "10"
    assert pr.load_prompt("judge") == ("tenth judge text", "judge@10")
    assert pr.text_for("judge", "2") == "second judge text"
    assert [(e.id, e.version) for e in pr.registry()] == [("judge", "10")]
    assert pr.has("judge", "1") and not pr.has("judge", "3")


def test_version_shape_is_a_positive_integer():  # 009/FR-005
    assert pr.is_valid_version("1") and pr.is_valid_version("12")
    for bad in ("0", "01", "1.0.0", "v1", "", "a"):
        assert not pr.is_valid_version(bad)


# --- the file format: a two-line YAML front-matter (id, version) above the text ---

def test_a_prompt_file_round_trips_through_format_and_parse(tmp_path):  # 009/FR-001
    text = 'line one\n\nline three with {"json": true} and a trailing space '
    path = tmp_path / "attacker_x.v3.md"
    path.write_text(pr.format_prompt_file("attacker:x", "3", text), encoding="utf-8", newline="\n")
    parsed = pr.parse_prompt_file(path)
    assert (parsed.id, parsed.version, parsed.text, parsed.path) == ("attacker:x", "3", text, path)


def test_the_text_is_insensitive_to_line_endings_and_trailing_newlines(tmp_path):  # 009/FR-005
    (tmp_path / "lf").mkdir()
    (tmp_path / "crlf").mkdir()
    (tmp_path / "lf" / "judge.v1.md").write_bytes(b"---\nid: judge\nversion: 1\n---\nhello\nworld\n")
    (tmp_path / "crlf" / "judge.v1.md").write_bytes(b"---\r\nid: judge\r\nversion: 1\r\n---\r\nhello\r\nworld\r\n\r\n")
    lf, crlf = pr.parse_prompt_file(tmp_path / "lf" / "judge.v1.md"), pr.parse_prompt_file(tmp_path / "crlf" / "judge.v1.md")
    assert lf.text == crlf.text == "hello\nworld"   # a checkout's line-ending convention cannot move a fingerprint
    assert pr.fingerprint(lf.text) == pr.fingerprint(crlf.text)


@pytest.mark.parametrize("name, content, problem", [
    ("judge.v1.md", "no front matter at all\n", "front-matter block"),
    ("judge.v1.md", "---\nid: judge\nversion: 1\ntext\n", "not closed"),
    ("judge.v1.md", "---\nid: judge\nversion: 2\n---\ntext\n", "does not match"),
    ("judge.v1.md", "---\nid: recommender\nversion: 1\n---\ntext\n", "does not match"),
    ("judge.v1.md", "---\nid: judge\nversion: 1\nactive: true\n---\ntext\n", "only 'id' and 'version'"),
    ("judge.v1.md", "---\nid: judge\n---\ntext\n", "missing version"),
    ("judge.v1.md", "---\nid: judge\nversion: 1\n---\n\n\n", "empty"),
    ("judge.md", "---\nid: judge\nversion: 1\n---\ntext\n", "named"),
    ("judge.v0.md", "---\nid: judge\nversion: 0\n---\ntext\n", "named"),
    ("judge.v1.0.0.md", "---\nid: judge\nversion: 1.0.0\n---\ntext\n", "named"),
])
def test_a_malformed_prompt_file_is_refused(tmp_path, name, content, problem):  # 009/FR-005
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="\n")
    with pytest.raises(pr.PromptFileError, match=problem):
        pr.parse_prompt_file(path)


def test_a_file_id_maps_a_colon_to_an_underscore():  # 009/FR-001 (a colon is not a legal Windows file-name char)
    assert pr.prompt_path("attacker:system_prompt_leak", "1").name == "attacker_system_prompt_leak.v1.md"
    assert pr.prompt_path("judge", "2").name == "judge.v2.md"


def test_an_unchanged_file_is_served_from_the_cache_and_a_changed_one_is_reread(tmp_path, monkeypatch):  # 009/FR-001
    monkeypatch.setattr(pr, "PROMPTS_DIR", tmp_path)
    path = _write(tmp_path, "judge", "1", "first")
    assert pr.load_prompt("judge")[0] == "first"
    assert pr.load_prompt("judge")[0] == "first"
    path.write_text(pr.format_prompt_file("judge", "1", "second, and longer"), encoding="utf-8", newline="\n")
    assert pr.load_prompt("judge")[0] == "second, and longer"
