"""Hybrid retriever — vector + fulltext + graph traversal with RRF fusion."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    text: str
    path: str
    source_id: str | None = None
    page: int | None = None
    score: float = 0.0
    blueprint_hash: str = ""
    char_start: int = 0
    char_end: int = 0
    entity_ids: list[str] = field(default_factory=list)
    entity_labels: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)

@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    total_hits: int = 0
    retriever: str = "hybrid"


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(ai * bi for ai, bi in zip(a, b))
    na = math.sqrt(sum(ai * ai for ai in a))
    nb = math.sqrt(sum(bi * bi for bi in b))
    return dot / (na * nb + 1e-10)


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank + 1)


def _rrf_fuse(*lists: list[SearchHit], top_k: int) -> list[SearchHit]:
    scores: dict[str, tuple[float, SearchHit]] = {}
    for ranked in lists:
        for rank, hit in enumerate(ranked):
            if hit.chunk_id in scores:
                old_score, old_hit = scores[hit.chunk_id]
                scores[hit.chunk_id] = (old_score + _rrf(rank), old_hit)
            else:
                scores[hit.chunk_id] = (_rrf(rank), hit)
    result = []
    for score, hit in sorted(scores.values(), key=lambda x: x[0], reverse=True)[:top_k]:
        result.append(SearchHit(chunk_id=hit.chunk_id, text=hit.text, path=hit.path, source_id=hit.source_id, page=hit.page, score=round(score, 4), blueprint_hash=hit.blueprint_hash, char_start=hit.char_start, char_end=hit.char_end, entity_ids=list(hit.entity_ids), entity_labels=list(hit.entity_labels), entity_names=list(hit.entity_names)))
    return result


class HybridRetriever:
    name = "hybrid"

    def __init__(self, store: Any) -> None:
        self.store = store

    def _query_emb(self, query: str) -> list[float]:
        seed = hashlib.sha256(query.encode("utf-8")).digest()
        return [(0.1 if (seed[i % 32] + (i // 32)) % 2 == 0 else -0.1) for i in range(384)]

    def _vector_search(self, emb: list[float], top_k: int) -> list[SearchHit]:
        scores = [(sim, cid) for cid, emb2 in getattr(self.store, "embeddings", {}).items() if (sim := _cosine_sim(emb, emb2)) is not None]
        scores.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for sim, cid in scores[:top_k]:
            c = self.store.get_chunk(cid)
            if c is None:
                continue
            hits.append(SearchHit(chunk_id=cid, text=getattr(c, "text", "")[:500], path=getattr(c, "path", ""), source_id=getattr(c, "source_id", None), page=getattr(c, "page", None), score=round(sim, 4), blueprint_hash=getattr(c, "blueprint_hash", ""), char_start=getattr(c, "char_start", 0), char_end=getattr(c, "char_end", 0)))
        return hits

    def _fulltext_search(self, query: str, top_k: int) -> list[SearchHit]:
        terms = query.lower().split()
        scores = []
        for cid, c in getattr(self.store, "chunks", {}).items():
            text = getattr(c, "text", "").lower()
            score = sum(term in text for term in terms)
            if score > 0:
                scores.append((score, cid))
        scores.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, cid in scores[:top_k]:
            c = self.store.chunks[cid]
            hits.append(SearchHit(chunk_id=cid, text=getattr(c, "text", "")[:500], path=getattr(c, "path", ""), source_id=getattr(c, "source_id", None), page=getattr(c, "page", None), score=round(score / len(terms), 4), blueprint_hash=getattr(c, "blueprint_hash", "")))
        return hits

    def _graph_search(self, seed_ids: list[str], hops: int, top_k: int) -> list[SearchHit]:
        visited = set(seed_ids)
        current = set(seed_ids)
        for _ in range(hops):
            entities = set()
            for cid in current:
                entities.update(getattr(self.store, "entity_chunks", {}).get(cid, set()))
            neighbours = set()
            for eid in entities:
                neighbours.update(getattr(self.store, "entity_chunks", {}).get(eid, set()))
            current = neighbours - visited
            visited.update(current)
        result = list(visited - set(seed_ids))
        hits = []
        for cid in result[:top_k]:
            c = self.store.get_chunk(cid)
            if c is None:
                continue
            hits.append(SearchHit(chunk_id=cid, text=getattr(c, "text", "")[:500], path=getattr(c, "path", ""), source_id=getattr(c, "source_id", None), page=getattr(c, "page", None), score=1.0 / (1 + len(hits)), blueprint_hash=getattr(c, "blueprint_hash", "")))
        return hits

    def retrieve(self, query: str, top_k: int = 10, hops: int = 1) -> SearchResult:
        emb = self._query_emb(query)
        v = self._vector_search(emb, top_k * 2)
        f = self._fulltext_search(query, top_k * 2)
        fused = _rrf_fuse(v, f, top_k=top_k)
        seeds = [h.chunk_id for h in fused[:max(3, top_k // 2)]]
        g = self._graph_search(seeds, hops, top_k)
        final = _rrf_fuse(fused, g, top_k=top_k)
        return SearchResult(query=query, hits=final, total_hits=len(final), retriever=self.name)

    def expand(self, node_id: str, hops: int = 1, top_k: int = 20) -> SearchResult:
        c = self.store.get_chunk(node_id)
        seeds = [node_id] if c is not None else list(getattr(self.store, "entity_chunks", {}).get(node_id, [])) or [node_id]
        g = self._graph_search(seeds, hops, top_k)
        return SearchResult(query=f"expand:{node_id}", hits=g, total_hits=len(g), retriever="graph")


__all__ = ["HybridRetriever", "SearchHit", "SearchResult"]