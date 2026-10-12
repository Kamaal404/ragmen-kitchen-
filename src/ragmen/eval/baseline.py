"""Plain vector RAG baseline — top-k cosine similarity, no graph traversal.

This is the baseline that hybrid search must beat. If GraphRAG cannot beat
plain vector search on the same chunks and embeddings, the schema is wrong
and more graph will not fix it.
"""

from __future__ import annotations

import math
from typing import Any


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(ai * bi for ai, bi in zip(a, b))
    na = math.sqrt(sum(ai * ai for ai in a))
    nb = math.sqrt(sum(bi * bi for bi in b))
    return dot / (na * nb + 1e-10)


class BaselineVectorRetriever:
    """Plain vector search — top-k cosine similarity, no graph.

    Uses the same embeddings as the hybrid retriever so the comparison
    isolates the value of the graph traversal.
    """

    name = "baseline_vector"

    def __init__(self, store: Any) -> None:
        self.store = store

    def retrieve_chunk_ids(self, query_emb: list[float], top_k: int = 10) -> list[str]:
        scores: list[tuple[float, str]] = []
        for cid, emb in getattr(self.store, "embeddings", {}).items():
            sim = _cosine_sim(query_emb, emb)
            scores.append((sim, cid))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [cid for _, cid in scores[:top_k]]


__all__ = ["BaselineVectorRetriever"]