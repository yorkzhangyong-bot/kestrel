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
