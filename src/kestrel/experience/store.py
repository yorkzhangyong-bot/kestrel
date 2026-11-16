"""The ChromaDB experience store: one collection of attack patterns and per-target memory (contracts/experience-store.md).

Patterns are anonymised shared knowledge (seeded from the library, added to by successes); memory is per-target,
one record per run. No method receives or stores a target URL, display name or auth value (Principle IV). This
module holds no attack text — patterns/memory are data the store holds at run time.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from kestrel import events
from kestrel.store import utc_now


@dataclass(frozen=True)
class MemoryRecord:
    """A per-target memory record as retrieved for the attacker (contracts/experience-store.md)."""
    summary: str
    family: str
    verdict: str
    succeeded: bool
    run_id: int
    created_at: str = ""


@dataclass(frozen=True)
class Candidate:
    """One family-scoped pattern hit for a retrieval query (feature 011): its id, its text, the collection's own
    `l2` distance from the query, and its stored embedding — what the selection in `retrieval.py` de-duplicates
    on, with the same squared-Euclidean measure and the standard library (research D2)."""
    id: str
    document: str
    distance: float
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class PatternWrite:
    """What a success's write-back did (feature 011): `added` a new pattern, or `merged` into the nearest
    near-identical same-family pattern by raising its hit count; `distance` is to the nearest existing same-family
    pattern — None when the family had none or de-duplication is off."""
    outcome: str          # "added" | "merged"
    pattern_id: str
    hit_count: int
    distance: float | None


COLLECTION = "kestrel_experience"
STORE_VERSION = "1"
VERSION_KEY = "kestrel_store_version"


class ExperienceStoreError(Exception):
    """The store can't be used: a mismatched persisted embedding function, or the local model couldn't load."""


_DOWNLOAD_HINTS = ("onnx", "download", "could not resolve", "connection", "timed out", "temporary failure",
                   "getaddrinfo", "ssl")


def store_error_kind(error: BaseException) -> str:
    """Why the store is unusable, as a category the log line can carry instead of the error's text (feature 010):
    `embedding_function_mismatch`, `model_download` or `other`."""
    text = str(error).lower()
    if "embedding function" in text and "not found" in text:
        return "embedding_function_mismatch"
    if any(hint in text for hint in _DOWNLOAD_HINTS):
        return "model_download"
    return "other"


def describe_store_error(error: Exception) -> str:
    """A plain, actionable one-liner for why the store is unusable (surfaced at start-up and in logs)."""
    kind = store_error_kind(error)
    if kind == "embedding_function_mismatch":
        return ("its collection was created with a different embedding function (often leftover test data). "
                "Delete the store directory and restart so it can be rebuilt with the default embeddings.")
    if kind == "model_download":
        return ("the local embedding model could not be loaded — the first run downloads it (about 80 MB), "
                "so this needs network once. Check your connection and restart.")
    return f"{type(error).__name__}: {error}"


def _and(*clauses: dict) -> dict:
    """A ChromaDB `where` filter: a single clause as-is, several joined with $and."""
    clauses = [c for c in clauses if c]
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class ExperienceStore:
    def __init__(self, path: str | Path, *, embedding_function: Any = None, store_version: str = STORE_VERSION) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path))
        # Pass the embedding function only when given; otherwise ChromaDB uses its built-in local default (R2).
        kwargs: dict[str, Any] = {} if embedding_function is None else {"embedding_function": embedding_function}
        self._collection = self._client.get_or_create_collection(
            COLLECTION, metadata={VERSION_KEY: store_version}, **kwargs)
        stored = (self._collection.metadata or {}).get(VERSION_KEY, store_version)
        self.version = str(stored)
        if self.version != store_version:
            events.emit("message", logging.WARNING, stored_version=self.version, expected_version=store_version,
                        message="The experience store's version differs from the one this Kestrel writes; "
                                "reconciling it is not handled yet.")

    def self_check(self) -> None:
        """Surface an unusable store early (bad persisted embedding function, or a failed first-use model
        download) by forcing one embedding, so the failure is a clear start-up message rather than a cryptic
        error on the first write-back mid-run. A probe record is written and removed, so it leaves no trace."""
        probe = "kestrel:self-check"
        try:
            self._collection.upsert(ids=[probe], documents=["ping"], metadatas=[{"type": "selfcheck"}])
            self._collection.delete(ids=[probe])
        except Exception as error:
            raise ExperienceStoreError(describe_store_error(error)) from error

    # ---- diagnostics ----

    def count(self, type: str | None = None, *, family: str | None = None, target_id: int | None = None) -> int:
        """Number of records, optionally filtered by type/family/target id (tests and the profile use this)."""
        if type is None and family is None and target_id is None:
            return self._collection.count()
        where = _and(*([{"type": type}] if type else []),
                     *([{"family": family}] if family else []),
                     *([{"target_id": target_id}] if target_id is not None else []))
        return len(self._collection.get(where=where, include=[])["ids"])

    # ---- seeding and writes (FR-004, FR-006, FR-009) ----

    def seed_patterns(self, library) -> int:
        """Idempotently seed one pattern per library prompt (FR-004, SC-002). Deterministic ids → re-seed is a no-op.
        Feature 011: a new seed starts with `hit_count` 1; an existing seed is upserted *without* the key, which
        ChromaDB keeps, so the hit count a merged success raised survives every start-up (research D4)."""
        if not library.prompts:
            return 0
        ids = [f"pattern:lib:{p.id}" for p in library.prompts]
        existing = set(self._collection.get(ids=ids, include=[])["ids"])
        metadatas = []
        for pattern_id, prompt in zip(ids, library.prompts):
            metadata: dict[str, Any] = {"type": "pattern", "family": prompt.family,
                                        "owasp_category": prompt.owasp_category,
                                        "source": f"library:{library.version}", "prompt_id": prompt.id}
            if pattern_id not in existing:
                metadata["hit_count"] = 1
            metadatas.append(metadata)
        self._collection.upsert(ids=ids, documents=[p.text for p in library.prompts], metadatas=metadatas)
        return len(library.prompts)

    def write_memory(self, *, run_id: int, target_id: int, summary: str, family: str, owasp_category: str,
                     verdict: str, hard_evidence: bool, turns_used: int | None, stopping_condition: str | None,
                     attacker_model: str | None) -> None:
        """One memory record per run (FR-006/7). The caller passes an already-sanitised summary; metadata is scalar."""
        self._collection.upsert(
            ids=[f"memory:run:{run_id}"],
            documents=[summary],
            metadatas=[{"type": "memory", "target_id": int(target_id), "run_id": int(run_id), "family": family,
                        "owasp_category": owasp_category, "verdict": verdict,
                        "hard_evidence": bool(hard_evidence), "succeeded": verdict == "succeeded",
                        "turns_used": int(turns_used or 0), "stopping_condition": stopping_condition or "",
                        "attacker_model": attacker_model or "", "created_at": utc_now()}])

    def write_pattern(self, *, run_id: int, document: str, family: str, owasp_category: str,
                      dedupe_threshold: float | None = None) -> PatternWrite:
        """A success becomes a shared pattern; its searchable text is the winning attacker message(s) (FR-009).
        Feature 011 (contracts/experience-store.md): with a threshold, the nearest existing pattern of the *same
        family* — library-seeded or success-derived — within it receives the hit instead (`hit_count` + 1,
        `last_hit_run_id`, the document untouched, no new record); otherwise, or with de-duplication off, a new
        pattern is added with `hit_count` 1. A store failure raises: the caller's write-back fails loudly as a whole."""
        distance: float | None = None
        if dedupe_threshold is not None and self.count("pattern", family=family) > 0:
            nearest = self._collection.query(query_texts=[document], n_results=1,
                                             where=_and({"type": "pattern"}, {"family": family}),
                                             include=["metadatas", "distances"])
            ids = (nearest.get("ids") or [[]])[0]
            if ids:
                nearest_id = str(ids[0])
                distance = float((nearest.get("distances") or [[0.0]])[0][0])
                metadata = ((nearest.get("metadatas") or [[{}]])[0][0]) or {}
                if distance <= dedupe_threshold:
                    hit_count = int(metadata.get("hit_count", 1)) + 1   # a pattern without the key counts as one
                    self._collection.update(ids=[nearest_id],
                                            metadatas=[{"hit_count": hit_count, "last_hit_run_id": int(run_id)}])
                    return PatternWrite("merged", nearest_id, hit_count, distance)
        pattern_id = f"pattern:run:{run_id}"
        self._collection.upsert(
            ids=[pattern_id],
            documents=[document],
            metadatas=[{"type": "pattern", "family": family, "owasp_category": owasp_category,
                        "source": f"run:{run_id}", "origin_run_id": int(run_id), "hit_count": 1}])
        return PatternWrite("added", pattern_id, 1, distance)

    # ---- retrieval (FR-016, FR-017, FR-018; feature 011 query_patterns) ----

    def query_patterns(self, *, family: str, query_text: str, n: int) -> list[Candidate]:
        """The up-to-n nearest patterns of this family for a query, nearest first, each with the collection's own
        `l2` distance and its stored embedding (feature 011, contracts/experience-store.md). `n` is clamped to the
        family's pattern count, so an empty family (or n <= 0) returns `[]` without querying; memory records are
        never candidates (`004/SC-014` still holds). The selection — floor and de-duplication — is `retrieval.py`'s."""
        n = max(0, min(int(n), self.count("pattern", family=family)))
        if n == 0:
            return []
        result = self._collection.query(query_texts=[query_text or ""], n_results=n,
                                        where=_and({"type": "pattern"}, {"family": family}),
                                        include=["documents", "distances", "embeddings"])
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        embeddings = result.get("embeddings")
        vectors = embeddings[0] if embeddings is not None and len(embeddings) else []
        return [Candidate(id=str(pattern_id), document=str(document), distance=float(distance),
                          embedding=tuple(float(value) for value in vector))
                for pattern_id, document, distance, vector in zip(ids, documents, distances, vectors)]

    def retrieve_patterns(self, *, family: str, query_text: str, k: int) -> list[str]:
        """Legacy (feature 004): the k nearest patterns of this family, with no floor and no de-duplication
        (FR-016/17, SC-014). Production retrieval goes through `query_patterns` and `retrieval.select_patterns`
        since feature 011; this stays for the feature-004 tests."""
        return [document for _, document in self.retrieve_patterns_with_ids(family=family, query_text=query_text,
                                                                            k=k)]

    def retrieve_patterns_with_ids(self, *, family: str, query_text: str, k: int) -> list[tuple[str, str]]:
        """Legacy (feature 004): the same k nearest patterns as `(id, document)` pairs, no floor, no
        de-duplication; the ids (`pattern:lib:<prompt_id>`, `pattern:run:<run_id>`) are what a retrieval line
        names (feature 010, FR-016) — identifiers, never the text. Not called by production code since 011."""
        if k <= 0:
            return []
        result = self._collection.query(query_texts=[query_text or ""], n_results=k,
                                        where=_and({"type": "pattern"}, {"family": family}))
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        return list(zip(ids, documents))

    def retrieve_memory(self, *, target_id: int, family: str, cap: int) -> list[MemoryRecord]:
        """This target's memory, by exact id (never semantic): recent-first to cap, keeping same-family successes."""
        got = self._collection.get(where=_and({"type": "memory"}, {"target_id": int(target_id)}))
        records = [MemoryRecord(summary=document, family=meta.get("family", ""), verdict=meta.get("verdict", ""),
                                succeeded=bool(meta.get("succeeded")), run_id=int(meta.get("run_id", 0)),
                                created_at=meta.get("created_at", ""))
                   for document, meta in zip(got["documents"], got["metadatas"])]
        records.sort(key=lambda r: r.run_id, reverse=True)
        selected = records[:cap]
        chosen = {r.run_id for r in selected}
        for record in records:  # keep an older same-family success past the recency cap (FR-016)
            if record.succeeded and record.family == family and record.run_id not in chosen:
                selected.append(record)
                chosen.add(record.run_id)
        return selected

    def delete_target_memory(self, target_id: int) -> int:
        """Delete all of a target's memory; patterns (no target identity) are untouched (FR-024/25, SC-010)."""
        before = self.count("memory", target_id=target_id)
        self._collection.delete(where=_and({"type": "memory"}, {"target_id": int(target_id)}))
        return before

    # ---- profile (FR-022, FR-023) ----

    def profile(self, target_id: int, *, recent_limit: int = 10) -> dict:
        """Summarise a target's memory: counts by family and verdict, plus the most recent summaries (secrets-free)."""
        got = self._collection.get(where=_and({"type": "memory"}, {"target_id": int(target_id)}))
        rows = list(zip(got["documents"], got["metadatas"]))
        families = Counter(meta.get("family", "") for _, meta in rows)
        verdicts = Counter(meta.get("verdict", "") for _, meta in rows)
        recent = [{"summary": document, "family": meta.get("family", ""), "verdict": meta.get("verdict", ""),
                   "created_at": meta.get("created_at", "")}
                  for document, meta in sorted(rows, key=lambda dm: int(dm[1].get("run_id", 0)), reverse=True)
                  ][:recent_limit]
        return {"target_id": int(target_id), "total_runs": len(rows),
                "by_family": [{"family": f, "count": c} for f, c in sorted(families.items())],
                "by_verdict": [{"verdict": v, "count": c} for v, c in sorted(verdicts.items())],
                "recent": recent}
