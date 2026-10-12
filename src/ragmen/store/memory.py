"""In-memory GraphStore for offline testing."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .interface import GraphStore


class MemoryStore(GraphStore):
    def __init__(self) -> None:
        self.chunks: dict[str, Any] = {}
        self.sources: dict[str, Any] = {}
        self.chunks_by_source: dict[str, set[str]] = defaultdict(set)
        self.entities: dict[str, dict] = {}
        self.relations: list[dict] = []
        self.embeddings: dict[str, list[float]] = {}
        self.entity_refs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.entity_chunks: dict[str, set[str]] = defaultdict(set)
        self.active_blueprint_hash: str | None = None

    def write_chunk(self, chunk, source):
        assert source is not None
        cid = getattr(chunk, "chunk_id", str(id(chunk)))
        sid = getattr(source, "source_id", str(id(source)))
        self.chunks[cid] = chunk
        self.sources[sid] = source
        self.chunks_by_source[sid].add(cid)

    def write_entity(self, entity, chunk_id, source_id, blueprint_hash):
        eid = f"{entity.label}\0{entity.name}"
        if eid not in self.entities:
            self.entities[eid] = {"label": entity.label, "name": entity.name, "blueprint_hash": blueprint_hash}
        self.entity_chunks[eid].add(chunk_id)
        self.entity_refs[eid][source_id] += 1

    def write_relation(self, relation, chunk_id, blueprint_hash):
        self.relations.append({"source_label": relation.source_label, "source_name": relation.source_name, "relation": relation.relation, "target_label": relation.target_label, "target_name": relation.target_name, "quote": getattr(relation, "quote", ""), "char_start": getattr(relation, "char_start", 0), "char_end": getattr(relation, "char_end", 0), "confidence": getattr(relation, "confidence", 1.0), "chunk_id": chunk_id, "blueprint_hash": blueprint_hash, "source_id": "", "properties": {p.name: p.value for p in getattr(relation, "properties", [])}})

    def write_embedding(self, node_id, label, embedding, blueprint_hash):
        self.embeddings[node_id] = embedding

    def create_indexes(self):
        pass

    def set_blueprint_active(self, blueprint_hash):
        self.active_blueprint_hash = blueprint_hash

    def get_relations(self) -> list[dict]:
        return list(self.relations)

    def get_source_uri(self, source_id: str) -> str:
        s = self.sources.get(source_id)
        return getattr(s, "uri", "") if s else ""

    def get_all_source_uris(self) -> dict[str, str]:
        return {sid: getattr(s, "uri", "") for sid, s in self.sources.items()}

    def get_chunks_by_blueprint(self, blueprint_hash: str) -> list:
        return [c for c in self.chunks.values() if getattr(c, "blueprint_hash", "") == blueprint_hash]

    def get_entity_ids(self) -> set[str]:
        return set(self.entities.keys())

    def get_chunk(self, chunk_id: str):
        return self.chunks.get(chunk_id)

    def get_source(self, source_id: str):
        return self.sources.get(source_id)

    def get_entity(self, name: str, label: str):
        return self.entities.get(f"{label}\0{name}")

    def retract_source(self, source_id: str):
        source_chunks = self.chunks_by_source.get(source_id, set())
        orphan_entities = {eid for eid, refs in self.entity_refs.items() if source_id in refs and len(refs) == 1}
        self.relations = [r for r in self.relations if r.get("chunk_id", "") not in source_chunks]
        for eid in orphan_entities:
            self.entities.pop(eid, None)
            self.embeddings.pop(eid, None)
            self.entity_chunks.pop(eid, None)
        for eid in list(self.entity_refs.keys()):
            if source_id in self.entity_refs[eid]:
                del self.entity_refs[eid][source_id]
                if not self.entity_refs[eid]:
                    del self.entity_refs[eid]
        for cid in source_chunks:
            self.chunks.pop(cid, None)
            self.embeddings.pop(cid, None)
        self.chunks_by_source.pop(source_id, None)
        if source_id in self.sources:
            self.sources.pop(source_id)

    def entity_count(self) -> int:
        return len(self.entities)

    def relation_count(self) -> int:
        return len(self.relations)

    def close(self) -> None:
        self.chunks.clear()
        self.sources.clear()
        self.entities.clear()
        self.relations.clear()
        self.embeddings.clear()
        self.entity_refs.clear()
        self.entity_chunks.clear()