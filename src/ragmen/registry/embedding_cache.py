from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    cache_key TEXT PRIMARY KEY,
    vector    TEXT NOT NULL
);
"""


class CachedEmbedder:
    def __init__(self, inner, path: Path) -> None:
        self._inner = inner
        self._model = str(getattr(inner, "model", type(inner).__name__))
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)

    def embed_query(self, text: str) -> list[float]:
        key = self._key(text)
        row = self._db.execute("SELECT vector FROM embeddings WHERE cache_key = ?", (key,)).fetchone()
        if row is not None:
            return json.loads(row[0])
        vector = self._inner.embed_query(text)
        self._db.execute("INSERT INTO embeddings (cache_key, vector) VALUES (?, ?)", (key, json.dumps(vector)))
        self._db.commit()
        return vector

    def close(self) -> None:
        self._db.close()

    def _key(self, text: str) -> str:
        # The model is part of the key: vectors from different models live in
        # different spaces, and mixing them silently returns wrong neighbours.
        return hashlib.sha256(f"{self._model}\x1f{text}".encode("utf-8")).hexdigest()
