"""The attacker hint block: purpose + memory + patterns, labelled hints-not-commands (FR-019, FR-021, SC-007)."""
from kestrel.experience.hints import format_hints
from kestrel.experience.store import MemoryRecord


def mem(summary: str) -> MemoryRecord:
    return MemoryRecord(summary=summary, family="system_prompt_leak", verdict="failed", succeeded=False, run_id=1)


def test_nothing_to_add_returns_none():
    assert format_hints(purpose=None, patterns=[], memory=[]) is None


def test_purpose_only_is_enough_for_a_block():
    block = format_hints(purpose="a customs classification assistant", patterns=[], memory=[])
    assert block and "customs classification assistant" in block


def test_block_includes_memory_and_patterns_and_a_not_commands_label():
    block = format_hints(purpose="an assistant", patterns=["<technique A>"], memory=[mem("<held last time>")])
    assert "<technique A>" in block and "<held last time>" in block and "an assistant" in block
    assert "not" in block.lower() and "command" in block.lower()   # framed as hints, not commands (FR-019)
