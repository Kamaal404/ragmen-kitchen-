from __future__ import annotations

from pathlib import Path

from ragmen.registry.embedding_cache import CachedEmbedder


class _CountingEmbedder:
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self.model = model
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [float(len(text)), 1.0]


def test_identical_text_is_embedded_once(tmp_path: Path) -> None:
    inner = _CountingEmbedder()
    cached = CachedEmbedder(inner, tmp_path / "embeddings.sqlite")
    first = cached.embed_query("birch bark")
    second = cached.embed_query("birch bark")
    assert first == second
    assert inner.calls == ["birch bark"]


def test_different_text_is_embedded_separately(tmp_path: Path) -> None:
    inner = _CountingEmbedder()
    cached = CachedEmbedder(inner, tmp_path / "embeddings.sqlite")
    cached.embed_query("birch bark")
    cached.embed_query("oak")
    assert inner.calls == ["birch bark", "oak"]


def test_cache_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "embeddings.sqlite"
    CachedEmbedder(_CountingEmbedder(), db).embed_query("birch bark")

    inner = _CountingEmbedder()
    reopened = CachedEmbedder(inner, db)
    assert reopened.embed_query("birch bark") == [10.0, 1.0]
    assert inner.calls == []


def test_changing_the_model_does_not_reuse_vectors(tmp_path: Path) -> None:
    db = tmp_path / "embeddings.sqlite"
    CachedEmbedder(_CountingEmbedder("all-MiniLM-L6-v2"), db).embed_query("birch bark")

    other = _CountingEmbedder("text-embedding-3-small")
    CachedEmbedder(other, db).embed_query("birch bark")
    assert other.calls == ["birch bark"]
