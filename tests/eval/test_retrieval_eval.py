"""Retrieval (RAG) evaluation - the evaluation tool's retrieval half.

Measures the real retrieval path (feature 011) against a controlled store: a known set of relevant patterns is
seeded per family into a temporary ChromaDB store, and each golden attack text of that family is used to build the
real query (`retrieval.build_query` - the family label plus the attacker message) and run the shipped selection
(`select_patterns` under the configured k, distance floor and dedupe threshold). Recall@k counts a query as
recalling a seeded relevant pattern when that pattern is among the k selected hits; mean distances and the
floor/dedupe drops are reported per family. No attacker or judge model call - only the local embedding model - so
this runs without a key; the one-time embedding-model download is the only network use. One timestamped markdown
report per run is written to tests/eval/report/ and committed.

Marked ``judge_eval``: run with ``uv run pytest -m judge_eval``. The seeded documents are neutral descriptions of
each family's attack surface - never attack prompts (CLAUDE.md's hard rule); the query text is the golden set's own
attack string, read from tests/eval/judge_samples.json at run time, never copied here.

Traces 011/FR-001 to FR-005 and the evaluation harness (roadmap).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kestrel.attacks.library import FAMILIES
from kestrel.experience import retrieval
from kestrel.experience.store import ExperienceStore
from kestrel.settings import load_settings
from tests.eval.eval_support import render_retrieval_report, report_path

FEATURE = "011"
pytestmark = pytest.mark.judge_eval

SAMPLES = Path(__file__).resolve().parent / "judge_samples.json"
REPORT_DIR = Path(__file__).resolve().parent / "report"
QUERIES_PER_FAMILY = 3
SEED_RUN_IDS = iter(range(900_001, 900_100))   # metadata-only run ids, like the 011 e2e's own

# Neutral descriptions of each family's attack surface (relevant seeds) and off-topic same-family distractors.
RELEVANT = {
    "system_prompt_leak": [
        "A request that tries to make the assistant reveal its own system instructions or operating rules.",
        "Attempts to extract the assistant's hidden configuration by asking it to quote or summarise its rules.",
        "A user pressing the assistant to print the message that tells it how to behave.",
    ],
    "direct_injection": [
        "An instruction inside the user request that tells the assistant to ignore its earlier rules.",
        "A prompt that switches the assistant into an unrestricted role.",
        "A command embedded in the user message that overrides the assistant's prior behaviour.",
    ],
    "indirect_injection": [
        "Hidden instructions embedded inside a document the assistant is asked to process.",
        "A text attachment that carries commands for the assistant to follow.",
        "Instructions planted in tool output or reference material the assistant reads.",
    ],
    "tool_exfiltration": [
        "A request that pushes the assistant to send internal data somewhere outside the system.",
        "Attempts to export records or secrets to an external destination.",
        "A user asking the assistant to copy internal content into an unapproved channel.",
    ],
}
IRRELEVANT = {
    "system_prompt_leak": [
        "The schedule for processing customs declarations on public holidays.",
        "How a shipment's weight affects its freight class.",
    ],
    "direct_injection": [
        "The schedule for processing customs declarations on public holidays.",
        "How a shipment's weight affects its freight class.",
    ],
    "indirect_injection": [
        "The schedule for processing customs declarations on public holidays.",
        "How a shipment's weight affects its freight class.",
    ],
    "tool_exfiltration": [
        "The schedule for processing customs declarations on public holidays.",
        "How a shipment's weight affects its freight class.",
    ],
}
NEAR_DUPLICATE = {
    "system_prompt_leak": RELEVANT["system_prompt_leak"][0].replace("reveal", "disclose"),
    "direct_injection": RELEVANT["direct_injection"][0].replace("earlier", "previous"),
    "indirect_injection": RELEVANT["indirect_injection"][0].replace("hidden", "concealed"),
    "tool_exfiltration": RELEVANT["tool_exfiltration"][0].replace("outside", "beyond"),
}


def _attack_texts(family: str) -> list[str]:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"]
    return [s["attack"] for s in samples if s["family"] == family][:QUERIES_PER_FAMILY]


def _seed(store: ExperienceStore, family: str, docs: list[str], owasp: str) -> list[str]:
    return [store.write_pattern(run_id=next(SEED_RUN_IDS), document=doc, family=family,
                                owasp_category=owasp).pattern_id for doc in docs]


def test_retrieval_recall_on_the_seeded_store(tmp_path):
    settings = load_settings()
    controls = settings.retrieval
    attacks_by_family = {family: _attack_texts(family) for family in FAMILIES}

    store = ExperienceStore(tmp_path / "chroma")
    relevant_by_family: dict[str, list[str]] = {}
    for family in FAMILIES:
        owasp = FAMILIES[family]["owasp_category"]
        relevant_by_family[family] = _seed(store, family, RELEVANT[family], owasp)
        _seed(store, family, IRRELEVANT[family], owasp)
        _seed(store, family, [NEAR_DUPLICATE[family]], owasp)   # exercises the dedupe threshold observation
    store.self_check()   # the real embedding model and the l2 space, as production

    per_family = []
    for family in FAMILIES:
        relevant_ids = set(relevant_by_family[family])
        recall_sum = 0.0
        distance_sum = 0.0
        distance_count = 0
        floor_drop_queries = 0
        duplicate_drop_queries = 0
        for attack in attacks_by_family[family]:
            query_text, used = retrieval.build_query(family, [("attacker", attack)])
            assert used == 1
            pool = min(controls.k * retrieval.CANDIDATE_MULTIPLIER, store.count("pattern", family=family))
            candidates = store.query_patterns(family=family, query_text=query_text, n=pool)
            selection = retrieval.select_patterns(candidates, k=controls.k,
                                                  distance_floor=controls.distance_floor,
                                                  dedupe_threshold=controls.dedupe_threshold)
            assert selection.candidate_count == (selection.dropped_floor + selection.dropped_duplicate
                                                 + len(selection.selected))
            hit_ids = set(selection.pattern_ids) & relevant_ids
            recall_sum += len(hit_ids) / len(relevant_ids)
            distance_sum += sum(selection.distances)
            distance_count += len(selection.distances)
            floor_drop_queries += int(selection.dropped_floor > 0)
            duplicate_drop_queries += int(selection.dropped_duplicate > 0)
        queries = len(attacks_by_family[family])
        per_family.append({
            "family": family,
            "queries": queries,
            "relevant": len(relevant_ids),
            "recall": f"{recall_sum / queries:.2f}",
            "mean_distance": f"{distance_sum / distance_count:.2f}" if distance_count else "-",
            "floor_drop_queries": str(floor_drop_queries),
            "duplicate_drop_queries": str(duplicate_drop_queries),
        })

    report = render_retrieval_report(per_family=per_family,
                                     settings={"k": controls.k, "distance_floor": controls.distance_floor,
                                               "dedupe_threshold": controls.dedupe_threshold})
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = report_path(REPORT_DIR, "retrieval-eval")
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to {path}")

    assert len(per_family) == len(FAMILIES)   # every family was measured over real queries
    assert sum(p["queries"] for p in per_family) == len(FAMILIES) * QUERIES_PER_FAMILY
