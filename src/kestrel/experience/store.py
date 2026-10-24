"""The ChromaDB experience store: one collection of attack patterns and per-target memory (contracts/experience-store.md).

Patterns are anonymised shared knowledge (seeded from the library, added to by successes); memory is per-target,
one record per run. No method receives or stores a target URL, display name or auth value (Principle IV). This
module holds no attack text — patterns/memory are data the store holds at run time.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb

from kestrel.store import utc_now

log = logging.getLogger("kestrel")

COLLECTION = "kestrel_experience"
STORE_VERSION = "1"
VERSION_KEY = "kestrel_store_version"


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
            log.warning("The experience store is at version %s, but this Kestrel writes version %s; "
                        "reconciling it is not handled yet.", self.version, store_version)

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
        """Idempotently seed one pattern per library prompt (FR-004, SC-002). Deterministic ids → re-seed is a no-op."""
        if not library.prompts:
            return 0
        self._collection.upsert(
            ids=[f"pattern:lib:{p.id}" for p in library.prompts],
            documents=[p.text for p in library.prompts],
            metadatas=[{"type": "pattern", "family": p.family, "owasp_category": p.owasp_category,
                        "source": f"library:{library.version}", "prompt_id": p.id} for p in library.prompts])
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

    def write_pattern(self, *, run_id: int, document: str, family: str, owasp_category: str) -> None:
        """A success becomes a shared pattern; its searchable text is the winning attacker message(s) (FR-009)."""
        self._collection.upsert(
            ids=[f"pattern:run:{run_id}"],
            documents=[document],
            metadatas=[{"type": "pattern", "family": family, "owasp_category": owasp_category,
                        "source": f"run:{run_id}", "origin_run_id": int(run_id)}])
