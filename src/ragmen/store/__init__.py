"""Store module — abstract GraphStore + Memory adapter."""

from .interface import GraphStore
from .memory import MemoryStore


def store_for(backend: str = "memory", **kwargs):
    if backend == "memory":
        return MemoryStore(**kwargs)
    raise ValueError(f"Unknown store backend: {backend!r}")


__all__ = ["GraphStore", "MemoryStore", "store_for"]