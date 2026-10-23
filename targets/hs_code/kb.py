"""A light knowledge base so CargoLint's classifier runs with BM25-only retrieval (research R11).

`classify_lines` reads `kb.index`, `kb.retriever` and `kb.bti_vectors`. CargoLint's `rag/loader.py` builds these
from a 134 MB Chroma index and embeddings; this target uses the nomenclature JSONL, an in-memory BM25 index and a
vector search that never finds anything, so no embeddings or index build are needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag.nomenclature import NomenclatureIndex
from rag.retriever import BM25Index, HybridRetriever

NOMENCLATURE_JSONL = Path(__file__).resolve().parent / "data" / "nomenclature_2026.jsonl"


class NullVectorSearch:
    """Stands in for CargoLint's vector search: one dummy vector per query and never a hit.

    HybridRetriever runs its BM25 leg inside its loop over query vectors, so it still needs one vector per query.
    """

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return [[0.0] for _ in queries]

    def search_by_vector(self, vector: list[float], k: int, chapter_filter: list[str] | None = None,
                         **kwargs: Any) -> list[tuple[str, float]]:
        return []

    def search(self, query: str, k: int, chapter_filter: list[str] | None = None) -> list[tuple[str, float]]:
        return []


@dataclass
class LightKnowledgeBase:
    index: NomenclatureIndex
    retriever: HybridRetriever
    bti: Any = None
    bti_vectors: Any = None  # None turns the classifier's BTI precedent leg off
    shippers: list = field(default_factory=list)


def build_kb(path: Path = NOMENCLATURE_JSONL) -> LightKnowledgeBase:
    index = NomenclatureIndex.from_jsonl(path)
    # The same (id, text) pairs CargoLint's rag/loader.py uses for store/bm25.pkl.
    bm25 = BM25Index([(chunk.id, chunk.text) for chunk in index.chunks])
    return LightKnowledgeBase(index=index, retriever=HybridRetriever(bm25=bm25, vectors=NullVectorSearch(), chunks=index))
