"""Hybrid retrieval: own BM25 over rank_bm25, a vector search (Chroma or in-memory), reciprocal
rank fusion and the index-metadata guard (research.md R-04, constitution Principle IV)."""
from __future__ import annotations

import json
import math
import pickle
import re
from pathlib import Path
from typing import Any, Protocol

from rank_bm25 import BM25Okapi

from agent.config import RETRIEVAL_K, RRF_K
from agent.schemas import NomenclatureChunk

_TOKEN_RE = re.compile(r"[0-9]{4}\.[0-9]{2}|[a-z0-9]+(?:[-'][a-z0-9]+)*|[一-鿿]+")
_COMPACT_CODE = re.compile(r"^[0-9]{6}$")


def tokenize(text: str) -> list[str]:
    """Lower-case tokens; HS codes are kept in both dotted and compact forms so either matches."""
    toks: list[str] = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        toks.append(tok)
        if "." in tok and len(tok) == 7:
            toks.append(tok.replace(".", ""))
        elif _COMPACT_CODE.match(tok):
            toks.append(f"{tok[:4]}.{tok[4:]}")
        elif re.match(r"^[一-鿿]{2,}$", tok):
            toks.extend(tok[i:i + 2] for i in range(len(tok) - 1))
    return toks


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


class BM25Index:
    def __init__(self, docs: list[tuple[str, str]]) -> None:
        self.ids = [d[0] for d in docs]
        self._tokens = [tokenize(d[1]) for d in docs]
        self._bm25 = BM25Okapi(self._tokens) if self._tokens else None

    def search(self, query: str, k: int = RETRIEVAL_K) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(self.ids)), key=lambda i: -scores[i])
        return [(self.ids[i], float(scores[i])) for i in order[:k] if scores[i] > 0]

    def save(self, path: Path | str) -> None:
        with Path(path).open("wb") as f:
            pickle.dump({"ids": self.ids, "tokens": self._tokens}, f)

    @classmethod
    def load(cls, path: Path | str) -> "BM25Index":
        with Path(path).open("rb") as f:
            data = pickle.load(f)
        obj = cls.__new__(cls)
        obj.ids = data["ids"]
        obj._tokens = data["tokens"]
        obj._bm25 = BM25Okapi(obj._tokens) if obj._tokens else None
        return obj


class VectorSearch(Protocol):
    def search(self, query: str, k: int, chapter_filter: list[str] | None) -> list[tuple[str, float]]: ...
    def embed_queries(self, queries: list[str]) -> list[list[float]]: ...
    def search_by_vector(self, vector: list[float], k: int, chapter_filter: list[str] | None) -> list[tuple[str, float]]: ...


def _embed_queries(embeddings: Any, queries: list[str]) -> list[list[float]]:
    fn = getattr(embeddings, "embed_queries", None)
    if callable(fn):
        return fn(queries)
    return [embeddings.embed_query(q) for q in queries]


class InMemoryVectorSearch:
    """Cosine search over precomputed vectors; used in tests and for small demo indexes."""

    def __init__(self, docs: list[tuple[str, str, dict]], embeddings: Any) -> None:
        self.ids = [d[0] for d in docs]
        self.meta = {d[0]: d[2] for d in docs}
        self.embeddings = embeddings
        vectors = embeddings.embed_documents([d[1] for d in docs]) if docs else []
        self.vectors = [self._norm(v) for v in vectors]

    @staticmethod
    def _norm(v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return _embed_queries(self.embeddings, queries)

    def search_by_vector(self, vector: list[float], k: int, chapter_filter: list[str] | None = None) -> list[tuple[str, float]]:
        q = self._norm(vector)
        scored = []
        for doc_id, vec in zip(self.ids, self.vectors):
            if chapter_filter and self.meta.get(doc_id, {}).get("chapter") not in chapter_filter:
                continue
            scored.append((doc_id, sum(a * b for a, b in zip(q, vec))))
        scored.sort(key=lambda t: -t[1])
        return scored[:k]

    def search(self, query: str, k: int, chapter_filter: list[str] | None = None) -> list[tuple[str, float]]:
        return self.search_by_vector(self.embeddings.embed_query(query), k, chapter_filter)


class ChromaVectorSearch:
    """Persisted Chroma collection (cosine space) behind the VectorSearch protocol."""

    def __init__(self, persist_dir: Path | str, embeddings: Any, collection_name: str = "cn2026") -> None:
        from langchain_chroma import Chroma

        self.embeddings = embeddings
        self.store = Chroma(collection_name=collection_name, embedding_function=embeddings, persist_directory=str(persist_dir),
                            collection_metadata={"hnsw:space": "cosine"})

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return _embed_queries(self.embeddings, queries)

    def search_by_vector(self, vector: list[float], k: int, chapter_filter: list[str] | None = None) -> list[tuple[str, float]]:
        where = {"chapter": {"$in": list(chapter_filter)}} if chapter_filter else None
        results = self.store.similarity_search_by_vector_with_relevance_scores(embedding=vector, k=k, filter=where)
        return [((getattr(doc, "id", None) or doc.metadata.get("id")), float(score)) for doc, score in results]

    def add(self, docs: list[tuple[str, str, dict]], batch_size: int = 256) -> int:
        n = 0
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            self.store.add_texts(texts=[d[1] for d in batch], metadatas=[{**d[2], "id": d[0]} for d in batch], ids=[d[0] for d in batch])
            n += len(batch)
        return n

    def count(self) -> int:
        return self.store._collection.count()

    def search(self, query: str, k: int, chapter_filter: list[str] | None = None) -> list[tuple[str, float]]:
        where = {"chapter": {"$in": list(chapter_filter)}} if chapter_filter else None
        results = self.store.similarity_search_with_score(query, k=k, filter=where)
        out = []
        for doc, distance in results:
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id")
            out.append((doc_id, 1.0 - float(distance)))
        return out


class HybridRetriever:
    def __init__(self, bm25: BM25Index | None, vectors: VectorSearch, chunks: Any, k: int = RETRIEVAL_K, rrf_k: int = RRF_K) -> None:
        self.bm25 = bm25
        self.vectors = vectors
        self.chunks = chunks  # NomenclatureIndex or mapping id -> NomenclatureChunk
        self.k = k
        self.rrf_k = rrf_k

    def _chunk(self, doc_id: str) -> NomenclatureChunk | None:
        if hasattr(self.chunks, "get") and not isinstance(self.chunks, dict):
            code = doc_id.split(":", 1)[-1]
            return self.chunks.get(code)
        return self.chunks.get(doc_id)

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        """Embed all queries in one request so both the plain and the chapter-boosted search reuse them."""
        clean = [q for q in queries if q and q.strip()]
        return self.vectors.embed_queries(clean) if clean else []

    def search(self, queries: list[str], chapter_filter: list[str] | None = None, mode: str = "hybrid",
               k: int | None = None, query_vectors: list[list[float]] | None = None) -> tuple[list[NomenclatureChunk], dict[str, Any]]:
        k = k or self.k
        rankings: list[list[str]] = []
        vec_ranks: dict[str, int] = {}
        bm25_ranks: dict[str, int] = {}
        clean = [q for q in queries if q and q.strip()]
        vectors = query_vectors if query_vectors is not None else self.embed_queries(clean)
        for q, qvec in zip(clean, vectors):
            vhits = [d for d, _ in self.vectors.search_by_vector(qvec, k * 2, chapter_filter)]
            rankings.append(vhits)
            for r, d in enumerate(vhits, start=1):
                vec_ranks[d] = min(vec_ranks.get(d, r), r)
            if mode == "hybrid" and self.bm25 is not None:
                bhits = []
                for d, _ in self.bm25.search(q, k * 4):
                    ch = self._chunk(d)
                    if chapter_filter and (ch is None or ch.metadata.get("chapter") not in chapter_filter):
                        continue
                    bhits.append(d)
                    if len(bhits) >= k * 2:
                        break
                rankings.append(bhits)
                for r, d in enumerate(bhits, start=1):
                    bm25_ranks[d] = min(bm25_ranks.get(d, r), r)
        fused = rrf(rankings, self.rrf_k)
        out: list[NomenclatureChunk] = []
        for doc_id, _score in fused:
            ch = self._chunk(doc_id)
            if ch is None:
                continue
            ranks = {}
            if doc_id in vec_ranks:
                ranks["vector"] = vec_ranks[doc_id]
            if doc_id in bm25_ranks:
                ranks["bm25"] = bm25_ranks[doc_id]
            out.append(ch.model_copy(update={"ranks": ranks}))
            if len(out) >= k:
                break
        trace = {"mode": mode, "queries": len([q for q in queries if q and q.strip()]), "chapter_filter": chapter_filter,
                 "bm25_hits": len(bm25_ranks), "vector_hits": len(vec_ranks), "fused": len(fused), "sent_to_model": len(out)}
        return out, trace


def precedent_codes(bti_vectors: VectorSearch, bti_store: Any, query_vectors: list[list[float]], k: int = RETRIEVAL_K,
                    rrf_k: int = RRF_K, as_of: Any = None) -> list[dict[str, Any]]:
    """Precedent-driven retrieval: rank HS-6 codes by the BTI rulings whose goods match the queries.

    Each query's nearest rulings are fused with RRF; a code's score is the sum over its rulings, so a code backed by
    several similar rulings outranks one backed by a single ruling. Returns one entry per code, best first:
    {code, score, rulings, reference, member_state, excerpt}, where reference/excerpt are the best-ranked ruling.
    Rulings unknown to the store, without a code, or not valid on `as_of` are skipped.
    """
    rankings = [[d for d, _ in bti_vectors.search_by_vector(vec, k * 2, None)] for vec in query_vectors]
    by_code: dict[str, dict[str, Any]] = {}
    for ruling_id, score in rrf(rankings, rrf_k):
        rec = bti_store.get(ruling_id, as_of)
        code = (rec or {}).get("code")
        if not code:
            continue
        entry = by_code.get(code)
        if entry is None:
            excerpt = " ".join((rec.get("description") or "").split())[:200]
            entry = by_code[code] = {"code": code, "score": 0.0, "rulings": 0, "reference": rec.get("reference", ""),
                                     "member_state": rec.get("member_state", ""), "excerpt": excerpt}
        entry["score"] += score
        entry["rulings"] += 1
    return sorted(by_code.values(), key=lambda e: -e["score"])


# --------------------------------------------------------------------------- index metadata guard
class IndexMismatchError(RuntimeError):
    pass


META_NAME = "index_meta.json"


def write_index_meta(store_dir: Path | str, meta: dict[str, Any]) -> Path:
    p = Path(store_dir) / META_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return p


def load_index_meta(store_dir: Path | str) -> dict[str, Any]:
    p = Path(store_dir) / META_NAME
    if not p.exists():
        raise IndexMismatchError(f"no {META_NAME} in {store_dir} — build the knowledge base with `python -m rag.loader`")
    return json.loads(p.read_text(encoding="utf-8"))


def verify_index_meta(meta: dict[str, Any], expected_model: str, expected_dim: int | None = None) -> None:
    model = meta.get("embedding_model")
    if model != expected_model:
        raise IndexMismatchError(f"index was built with {model!r} but CARGOLINT_EMBED_MODEL is {expected_model!r}; rebuild the index")
    if expected_dim is not None and meta.get("dimension") not in (None, expected_dim):
        raise IndexMismatchError(f"index dimension {meta.get('dimension')} does not match the model's {expected_dim}")
