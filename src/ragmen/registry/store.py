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

from ragmen.registry.models import AddResult, RetractResult, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id      TEXT PRIMARY KEY,
    uri            TEXT NOT NULL UNIQUE,
    content_hash   TEXT NOT NULL,
    previous_hash  TEXT,
    blueprint_hash TEXT NOT NULL,
    status         TEXT NOT NULL,
    chunk_count    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id  TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    path      TEXT NOT NULL,
    text      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS assertions (
    entity_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (entity_id, source_id)
);
"""


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def chunk_id(source_id: str, path: str, text: str) -> str:
    # The unit separator keeps ("a", "b c") and ("a b", "c") from hashing the same.
    digest = hashlib.sha256("\x1f".join((source_id, path, text)).encode("utf-8")).hexdigest()
    return "chk_" + digest[:16]


class Registry:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

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
        if row["status"] == "retracted":
            self._db.execute(
                "UPDATE sources SET content_hash = ?, blueprint_hash = ?, status = 'pending' "
                "WHERE source_id = ?",
                (content_hash, blueprint_hash, source_id),
            )
            self._db.commit()
            return AddResult(source_id=source_id, action="added")

        if row["content_hash"] == content_hash and row["blueprint_hash"] == blueprint_hash:
            return AddResult(source_id=source_id, action="unchanged")

        if row["content_hash"] != content_hash:
            action = "updated"
            self._db.execute(
                "UPDATE sources SET content_hash = ?, previous_hash = ?, blueprint_hash = ?, "
                "status = 'pending' WHERE source_id = ?",
                (content_hash, row["content_hash"], blueprint_hash, source_id),
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

    def add_chunks(self, source_id: str, chunks: list[tuple[str, str]]) -> None:
        self.get(source_id)
        self._db.executemany(
            "INSERT OR IGNORE INTO chunks (chunk_id, source_id, path, text) VALUES (?, ?, ?, ?)",
            [(chunk_id(source_id, path, text), source_id, path, text) for path, text in chunks],
        )
        count = self._db.execute("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (source_id,)).fetchone()[0]
        self._db.execute("UPDATE sources SET chunk_count = ? WHERE source_id = ?", (count, source_id))
        self._db.commit()

    def replace_chunks(self, source_id: str, chunks: list[tuple[str, str]]) -> None:
        # Chunks are keyed by content, so anything not in the new set is stale
        # text from a previous version of the file and must go.
        self.get(source_id)
        keep = {chunk_id(source_id, path, text) for path, text in chunks}
        stale = [row["chunk_id"] for row in self._db.execute(
            "SELECT chunk_id FROM chunks WHERE source_id = ?", (source_id,)
        ).fetchall() if row["chunk_id"] not in keep]
        self._db.executemany("DELETE FROM chunks WHERE chunk_id = ?", [(c,) for c in stale])
        self._db.commit()
        self.add_chunks(source_id, chunks)

    def chunks_for(self, source_id: str) -> list[tuple[str, str, str]]:
        rows = self._db.execute(
            "SELECT chunk_id, path, text FROM chunks WHERE source_id = ? ORDER BY chunk_id",
            (source_id,),
        ).fetchall()
        return [(row["chunk_id"], row["path"], row["text"]) for row in rows]

    def assert_entity(self, source_id: str, entity_id: str) -> None:
        self.get(source_id)
        self._db.execute("INSERT OR IGNORE INTO entities (entity_id) VALUES (?)", (entity_id,))
        self._db.execute(
            "INSERT OR IGNORE INTO assertions (entity_id, source_id) VALUES (?, ?)",
            (entity_id, source_id),
        )
        self._db.commit()

    def entity_exists(self, entity_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone() is not None

    def assertions_for(self, entity_id: str) -> list[str]:
        rows = self._db.execute(
            "SELECT source_id FROM assertions WHERE entity_id = ? ORDER BY source_id", (entity_id,)
        ).fetchall()
        return [row["source_id"] for row in rows]

    def retract(self, source_id: str) -> RetractResult:
        self.get(source_id)
        candidates = [
            row["entity_id"]
            for row in self._db.execute(
                "SELECT entity_id FROM assertions WHERE source_id = ?", (source_id,)
            ).fetchall()
        ]
        removed_chunks = self._db.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,)).rowcount
        self._db.execute("DELETE FROM assertions WHERE source_id = ?", (source_id,))

        removed_entities = []
        for entity_id in candidates:
            still_asserted = self._db.execute(
                "SELECT COUNT(*) FROM assertions WHERE entity_id = ?", (entity_id,)
            ).fetchone()[0]
            if still_asserted == 0:
                self._db.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))
                removed_entities.append(entity_id)

        self._db.execute(
            "UPDATE sources SET status = 'retracted', chunk_count = 0 WHERE source_id = ?", (source_id,)
        )
        self._db.commit()
        return RetractResult(
            source_id=source_id,
            removed_chunks=removed_chunks,
            removed_entities=sorted(removed_entities),
        )

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
