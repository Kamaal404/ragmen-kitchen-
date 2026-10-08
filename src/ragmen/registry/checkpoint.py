from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint (
    chunk_id     TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    reason       TEXT,
    PRIMARY KEY (chunk_id, profile_hash)
);
"""


class Checkpoint:
    def __init__(self, path: Path, *, profile_hash: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._profile_hash = profile_hash
        self._seen: set[str] = set()

    def plan(self, chunks: list[dict]) -> list[dict]:
        for chunk in chunks:
            self._db.execute(
                "INSERT OR IGNORE INTO checkpoint (chunk_id, profile_hash, status) VALUES (?, ?, 'pending')",
                (chunk["id"], self._profile_hash),
            )
            self._seen.add(chunk["id"])
        self._db.commit()
        done = {
            row["chunk_id"]
            for row in self._db.execute(
                "SELECT chunk_id FROM checkpoint WHERE profile_hash = ? AND status = 'done'",
                (self._profile_hash,),
            ).fetchall()
        }
        return [chunk for chunk in chunks if chunk["id"] not in done]

    def known_chunk_ids(self) -> set[str]:
        return set(self._seen)

    def mark_done(self, chunk: dict) -> None:
        self._set(chunk["id"], "done", None)

    def mark_failed(self, chunk: dict, *, reason: str) -> None:
        self._set(chunk["id"], "failed", reason)

    def close(self) -> None:
        self._db.close()

    def _set(self, chunk_id: str, status: str, reason: str | None) -> None:
        self._db.execute(
            "UPDATE checkpoint SET status = ?, reason = ? WHERE chunk_id = ? AND profile_hash = ?",
            (status, reason, chunk_id, self._profile_hash),
        )
        self._db.commit()
