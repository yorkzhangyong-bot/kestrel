"""The roadmap edit of feature 011 (FR-019, SC-011): the implementation pull request lists "Retrieval controls" under
Done as 011 and renumbers the planned items — regression replay 012, behavioural evidence expansion 013, community
prompt feed 014 — including the cross-reference to regression replay inside the community-feed item, with no stale
reference to a former number. A documentation check: it reads `docs/roadmap.md`, nothing else."""
import re
from pathlib import Path

FEATURE = "011"

ROADMAP = Path(__file__).resolve().parents[2] / "docs" / "roadmap.md"


def _sections() -> dict[str, str]:
    """The roadmap's `## ` sections by heading."""
    text = ROADMAP.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## (.+)$", text)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def test_retrieval_controls_is_listed_under_done_as_011():  # FR-019, SC-011
    sections = _sections()
    assert "**011 — Retrieval controls**" in sections["Done"]
    assert "Retrieval controls" not in sections["From reviewer feedback"]
    done_bullet = next(line for line in sections["Done"].splitlines() if "011 — Retrieval controls" in line)
    for phrase in ("attacker", "floor", "hit count", "embedding model", "recall@k", "memory.retrieval", "#27"):
        assert phrase in done_bullet, phrase


def test_the_planned_items_are_renumbered_with_no_stale_numbers():  # FR-019, SC-011
    # Feature 012 (Regression replay) has since shipped and moved to Done per its own FR-050
    # (test_012_is_listed_under_done_below); only 013 and 014 are still planned here.
    planned = _sections()["Next features"]
    assert "**Feature 013 — Behavioural evidence expansion.**" in planned
    assert "**Feature 014 — Community prompt feed.**" in planned
    assert "Regression replay (012) is unaffected" in planned   # a cross-reference inside 014's own bullet
    assert "Feature 011" not in planned and "(011)" not in planned   # 0 stale references to the former numbers
    numbers = re.findall(r"\*\*Feature (\d{3}) — ", planned)
    assert sorted(numbers) == ["013", "014"]


def test_012_is_listed_under_done_and_no_longer_planned():  # 012/FR-050
    sections = _sections()
    assert "**012 — Regression replay**" in sections["Done"]
    assert "Feature 012 — Regression replay." not in sections["Next features"]
