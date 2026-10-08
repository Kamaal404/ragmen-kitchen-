"""SQLite-backed source registry.

Identity is the resolved file path. Content changes update the same source
rather than creating a new one, so retraction and re-chunking can address a
stable id. Moving a file creates a new source: a rename is never silently
treated as the same document.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ragmen.registry.models import AddResult, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id     TEXT PRIMARY KEY,
    uri           TEXT NOT NULL UNIQUE,
    content_hash  TEXT NOT NULL,
    previous_hash TEXT,
    blueprint_hash TEXT NOT NULL,
    status        TEXT NOT NULL,
    chunk_count   INTEGER NOT NULL DEFAULT 0
)
"""


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Registry:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)
        self._db.commit()

    def add(self, file: Path, *, blueprint_hash: str) -> AddResult:
        if not file.is_file():
            raise FileNotFoundError(f"no such source file: {file}")
        uri = str(file.resolve())
        content_hash = _hash_bytes(file.read_bytes())
        row = self._db.execute("SELECT * FROM sources WHERE uri = ?", (uri,)).fetchone()

        if row is None:
            source_id = "src_" + hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]
            self._db.execute(
                "INSERT INTO sources (source_id, uri, content_hash, previous_hash, "
                "blueprint_hash, status, chunk_count) VALUES (?, ?, ?, NULL, ?, 'pending', 0)",
                (source_id, uri, content_hash, blueprint_hash),
            )
            self._db.commit()
            return AddResult(source_id=source_id, action="added")

        source_id = row["source_id"]
        if row["content_hash"] == content_hash and row["blueprint_hash"] == blueprint_hash:
            return AddResult(source_id=source_id, action="unchanged")

        if row["content_hash"] != content_hash:
            action = "updated"
            previous = row["content_hash"]
            self._db.execute(
                "UPDATE sources SET content_hash = ?, previous_hash = ?, blueprint_hash = ?, "
                "status = 'pending' WHERE source_id = ?",
                (content_hash, previous, blueprint_hash, source_id),
            )
        else:
            action = "reblueprinted"
            self._db.execute(
                "UPDATE sources SET blueprint_hash = ?, status = 'pending' WHERE source_id = ?",
                (blueprint_hash, source_id),
            )
        self._db.commit()
        return AddResult(source_id=source_id, action=action)

    def get(self, source_id: str) -> Source:
        row = self._db.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        return _to_source(row)

    def list(self) -> list[Source]:
        rows = self._db.execute("SELECT * FROM sources ORDER BY uri").fetchall()
        return [_to_source(row) for row in rows]

    def close(self) -> None:
        self._db.close()


def _to_source(row: sqlite3.Row) -> Source:
    return Source(
        source_id=row["source_id"],
        uri=row["uri"],
        content_hash=row["content_hash"],
        previous_hash=row["previous_hash"],
        blueprint_hash=row["blueprint_hash"],
        status=row["status"],
        chunk_count=row["chunk_count"],
    )
