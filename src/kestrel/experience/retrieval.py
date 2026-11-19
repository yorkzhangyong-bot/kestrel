"""The retrieval path (feature 011, contracts/retrieval.md): one query rule, one selection, one background provider.

`build_query` makes the search text from the attack family's label and the attacker's own last two messages — the
`attacker` role only, so a target reply (the `agent` role) never enters it, and the judge's reason and progress
notes, the memory summaries and the purpose description cannot, because they are not in the conversation at all
(FR-001, FR-002). `select_patterns` walks the store's candidates nearest first under a distance floor and a
near-identical threshold, both in the collection's own `l2` measure with the standard library (FR-003 to FR-005,
Principle X). `background_provider` is the per-turn callable both run starters hand to the graph — the API's
`start_run` and the experiment engine's `_run_rep` — so the two paths cannot drift apart; `attack/graph.py` keeps
receiving a plain callable and never imports the store. Nothing here logs text: the retrieval line carries the
settings, counts, distances and ids only (FR-013).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from kestrel import events
from kestrel.attacks.library import family_label
from kestrel.experience.hints import format_hints
from kestrel.experience.store import Candidate

QUERY_MESSAGES = 2        # attacker messages in the query (FR-001; clarified 2026-11-16) — a constant, not a setting
CANDIDATE_MULTIPLIER = 4  # candidate pool = min(k * 4, patterns in the family): room to skip up to 3k duplicates
ATTACKER_ROLE = "attacker"


@dataclass(frozen=True)
class Selection:
    """The ordered hits handed to the attacker and what the walk did (data-model.md): nearest first, at most k,
    every hit within the floor, no two within the threshold; `candidate_count` is always
    `dropped_floor + dropped_duplicate + len(selected)` (the identity the retrieval line asserts)."""
    selected: tuple[Candidate, ...]
    candidate_count: int
    dropped_floor: int
    dropped_duplicate: int

    @property
    def pattern_ids(self) -> list[str]:
        return [candidate.id for candidate in self.selected]

    @property
    def documents(self) -> list[str]:
        return [candidate.document for candidate in self.selected]

    @property
    def distances(self) -> list[float]:
        """The selected hits' query distances, 4 decimals, in selection order (for the log line)."""
        return [round(candidate.distance, 4) for candidate in self.selected]


def build_query(family: str, conversation: Sequence[tuple[str, str]]) -> tuple[str, int]:
    """The retrieval query and how many attacker messages it holds: the family label, then the last
    `QUERY_MESSAGES` messages whose role is exactly `attacker`, in conversation order (FR-001). An empty
    conversation yields the label alone (never reached in a run: the first retrieval is on turn 2, after the seed).
    Accepted residual (spec assumption): an attacker message may itself echo a fragment of a reply — that text is
    the attacker's own and is not filtered."""
    messages = [text for role, text in conversation if role == ATTACKER_ROLE][-QUERY_MESSAGES:]
    label = family_label(family)
    return " ".join([label, *messages]), len(messages)


def squared_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """The collection's `l2` measure between two stored embeddings: the squared Euclidean distance."""
    return sum((x - y) ** 2 for x, y in zip(a, b))


def select_patterns(candidates: Sequence[Candidate], *, k: int, distance_floor: float | None,
                    dedupe_threshold: float | None) -> Selection:
    """Pure. Walk the candidates nearest first and stop once k are selected. A candidate beyond the floor ends the
    walk — it and every later one count as dropped, since the list is sorted they are all farther — and a candidate
    within the threshold of an already selected hit is skipped and never spends a slot; `None` switches a control
    off. A hit at exactly the floor is kept; two at exactly the threshold are near-identical (FR-003 to FR-005).
    With both controls off the result is the k nearest (feature 004); the selection is short of k only when every
    candidate was examined (SC-003)."""
    ordered = sorted(candidates, key=lambda candidate: candidate.distance)
    selected: list[Candidate] = []
    dropped_floor = dropped_duplicate = 0
    for index, candidate in enumerate(ordered):
        if len(selected) >= k:
            break
        if distance_floor is not None and candidate.distance > distance_floor:
            dropped_floor += len(ordered) - index
            break
        if dedupe_threshold is not None and _near_identical(candidate, selected, dedupe_threshold):
            dropped_duplicate += 1
            continue
        selected.append(candidate)
    return Selection(selected=tuple(selected), candidate_count=dropped_floor + dropped_duplicate + len(selected),
                     dropped_floor=dropped_floor, dropped_duplicate=dropped_duplicate)


def _near_identical(candidate: Candidate, selected: Sequence[Candidate], threshold: float) -> bool:
    """Within the threshold of any already selected hit, by the collection's own measure over stored embeddings."""
    return any(squared_distance(candidate.embedding, hit.embedding) <= threshold for hit in selected)


def background_provider(experience: Any, *, target_id: int, purpose: str | None, family: str, settings: Any,
                        use_prior_experience: bool) -> Callable[[list], str | None]:
    """The attacker's background each turn (feature 004 FR-021, feature 011): purpose always; on a warm run with a
    usable store, this target's memory (exact id, unchanged) plus the patterns selected for the attacker-only query
    under the controls in `settings.retrieval`, with one `memory.retrieval` line per call — zero counts when nothing
    came back (`010/FR-016`). Cold, or no store: the purpose only (`004/FR-015`), no line. A store failure propagates:
    the graph treats a provider exception as best-effort (`memory.retrieval_failed`, the turn goes on without hints)."""
    def provider(conversation: list) -> str | None:
        if not use_prior_experience or experience is None:
            return format_hints(purpose=purpose, patterns=[], memory=[])   # cold: purpose only
        retrieval = settings.retrieval
        memory = experience.retrieve_memory(target_id=target_id, family=family, cap=settings.experience_memory_cap)
        query_text, used = build_query(family, conversation)
        pool = min(retrieval.k * CANDIDATE_MULTIPLIER, experience.count("pattern", family=family))
        candidates = experience.query_patterns(family=family, query_text=query_text, n=pool)
        selection = select_patterns(candidates, k=retrieval.k, distance_floor=retrieval.distance_floor,
                                    dedupe_threshold=retrieval.dedupe_threshold)
        events.memory_retrieval(pattern_ids=selection.pattern_ids, memory_count=len(memory), k=retrieval.k,
                                distance_floor=retrieval.distance_floor, dedupe_threshold=retrieval.dedupe_threshold,
                                candidate_count=selection.candidate_count, dropped_floor=selection.dropped_floor,
                                dropped_duplicate=selection.dropped_duplicate, distances=selection.distances,
                                query_messages=used)
        return format_hints(purpose=purpose, patterns=selection.documents, memory=memory)
    return provider
