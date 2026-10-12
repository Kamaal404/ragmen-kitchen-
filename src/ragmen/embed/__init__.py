"""Embedding module — vector generation with content-hash caching."""

from .embedder import Embedder, MockEmbedder, LocalEmbedder, build_embedding_targets, embed_for

__all__ = ["Embedder", "MockEmbedder", "LocalEmbedder", "build_embedding_targets", "embed_for"]