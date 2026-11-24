"""The roadmap edit of feature 011 (FR-019, SC-011): the implementation pull request lists "Retrieval controls" under
Done as 011 and renumbers the planned items — regression replay 012, behavioural evidence expansion 013, community
prompt feed 014 — including the cross-reference to regression replay inside the community-feed item, with no stale
reference to a former number. Since the roadmap update of 2026-11-24 (#43) the reviewer-feedback section is gone
(its one item moved into Next features) and 013 is split: part 1 sits under Done, part 2 stays planned under its
part-2 title. A documentation check: it reads `docs/roadmap.md`, nothing else."""
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
    assert "From reviewer feedback" not in sections   # folded into Next features on 2026-11-24 (#43)
    assert "Retrieval controls" not in sections["Next features"]
    done_bullet = next(line for line in sections["Done"].splitlines() if "011 — Retrieval controls" in line)
    for phrase in ("attacker", "floor", "hit count", "embedding model", "recall@k", "memory.retrieval", "#27"):
        assert phrase in done_bullet, phrase


def test_the_planned_items_are_renumbered_with_no_stale_numbers():  # FR-019, SC-011
    # Feature 012 (Regression replay) has since shipped and moved to Done per its own FR-050
    # (test_012_is_listed_under_done_below); 013 part 1 shipped too (#39, #41), so the planned 013 entry is part 2.
    sections = _sections()
    planned = sections["Next features"]
    assert "**Feature 013 — Behavioural evidence, part 2 (tool-call log and honeypot first).**" in planned
    assert "013-part2-wip" in planned   # parked branch named in the entry
    assert "**013 — Behavioural evidence, part 1 (reply detectors)**" in sections["Done"]
    assert "**Feature 014 — Community prompt feed.**" in planned
    assert "Regression replay (012) is unaffected" in planned   # a cross-reference inside 014's own bullet
    assert "Feature 011" not in planned and "(011)" not in planned   # 0 stale references to the former numbers
    numbers = re.findall(r"\*\*Feature (\d{3}) — ", planned)
    assert sorted(numbers) == ["013", "014"]


def test_012_is_listed_under_done_and_no_longer_planned():  # 012/FR-050
    sections = _sections()
    assert "**012 — Regression replay**" in sections["Done"]
    assert "Feature 012 — Regression replay." not in sections["Next features"]
