"""Embedding providers — local sentence-transformers and mock for testing."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Embedder(ABC):
    model: str = ""
    dimensions: int = 384

    @abstractmethod
    def embed(self, text: str, key: str | None = None) -> list[float]: ...

    @abstractmethod
    def embed_batch(self, texts: list[str], keys: list[str | None] | None = None) -> list[list[float]]: ...


class MockEmbedder(Embedder):
    model = "mock"
    dimensions: int

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, text: str, key: str | None = None) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        return [(0.1 if (seed[i % 32] + (i // 32)) % 2 == 0 else -0.1) for i in range(self.dimensions)]

    def embed_batch(self, texts: list[str], keys: list[str | None] | None = None) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class LocalEmbedder(Embedder):
    _CACHE_FILE = "embedding_cache.json"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", cache_dir: str | Path | None = None) -> None:
        self.model_name = model_name
        self.model = model_name
        self.dimensions = 384
        self._model: Any = None
        self._cache: dict[str, list[float]] = {}
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._dirty = False
        if self._cache_dir:
            cp = self._cache_dir / self._CACHE_FILE
            if cp.exists():
                try:
                    self._cache = {k: [float(v) for v in vec] for k, vec in json.loads(cp.read_text("utf-8")).items()}
                except (json.JSONDecodeError, ValueError):
                    self._cache = {}

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        except ImportError:
            raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")

    def _persist(self) -> None:
        if not self._cache_dir or not self._dirty:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / self._CACHE_FILE).write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")

    def _content_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed(self, text: str, key: str | None = None) -> list[float]:
        ck = key or self._content_key(text)
        if ck in self._cache:
            return self._cache[ck]
        self._load_model()
        vec = self._model.encode(text, normalize_embeddings=True).tolist()
        self._cache[ck] = vec
        self._dirty = True
        self._persist()
        return vec

    def embed_batch(self, texts: list[str], keys: list[str | None] | None = None) -> list[list[float]]:
        results, uncached_i, uncached_t = [], [], []
        for i, text in enumerate(texts):
            ck = (keys[i] if keys else None) or self._content_key(text)
            if ck in self._cache:
                results.append(self._cache[ck])
            else:
                results.append([])
                uncached_i.append(i)
                uncached_t.append(text)
        if uncached_t:
            self._load_model()
            embeddings = self._model.encode(uncached_t, normalize_embeddings=True).tolist()
            for idx, vec in zip(uncached_i, embeddings):
                ck = (keys[idx] if keys else None) or self._content_key(texts[idx])
                self._cache[ck] = vec
                results[idx] = vec
            self._dirty = True
            self._persist()
        return results


def embed_for(backend: str = "local", **kwargs: Any) -> Embedder:
    if backend == "mock":
        return MockEmbedder(**kwargs)
    if backend == "local":
        return LocalEmbedder(**kwargs)
    raise ValueError(f"Unknown embedder backend: {backend!r}")


def build_embedding_targets(blueprint: dict, chunks: list[dict], resolved_entities: list | None = None) -> list[tuple[str, str, str]]:
    targets: list[tuple[str, str, str]] = []
    for tdef in blueprint.get("embedding", {}).get("targets", []):
        of_types = tdef.get("of", [])
        if isinstance(of_types, str):
            of_types = [of_types]
        template = tdef.get("text", "{text}")
        if "Chunk" in of_types:
            for chunk in chunks:
                rendered = template.format(path=chunk.get("path", ""), text=chunk.get("text", ""))
                targets.append((tdef.get("name", "chunk"), rendered, f"chunk:{chunk.get('chunk_id', '')}"))
        if resolved_entities and any(t not in ("Chunk",) for t in of_types):
            for re_entity in resolved_entities:
                rendered = template.format(name=re_entity.canonical_name)
                targets.append((tdef.get("name", "entity"), rendered, f"entity:{re_entity.entity_id}"))
    return targets