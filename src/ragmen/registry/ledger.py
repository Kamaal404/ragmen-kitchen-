from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_chunks (
    job_id  TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    status  TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    reason  TEXT,
    PRIMARY KEY (job_id, chunk_id)
);
"""

STATUSES = ("pending", "done", "failed")


class Ledger:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def start(self, source_id: str) -> str:
        source = self._db.execute(
            "SELECT content_hash FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if source is None:
            raise KeyError(source_id)
        content_hash = source["content_hash"]
        job_id = "job_" + hashlib.sha256(f"{source_id}\x1f{content_hash}".encode("utf-8")).hexdigest()[:16]
        self._db.execute(
            "INSERT OR IGNORE INTO jobs (job_id, source_id, content_hash) VALUES (?, ?, ?)",
            (job_id, source_id, content_hash),
        )
        self._db.execute(
            "INSERT OR IGNORE INTO job_chunks (job_id, chunk_id, status) "
            "SELECT ?, chunk_id, 'pending' FROM chunks WHERE source_id = ?",
            (job_id, source_id),
        )
        self._db.commit()
        return job_id

    def pending(self, job_id: str) -> list[str]:
        return self._chunk_ids(job_id, "pending")

    def counts(self, job_id: str) -> dict[str, int]:
        result = {status: 0 for status in STATUSES}
        rows = self._db.execute(
            "SELECT status, COUNT(*) AS n FROM job_chunks WHERE job_id = ? GROUP BY status", (job_id,)
        ).fetchall()
        for row in rows:
            result[row["status"]] = row["n"]
        return result

    def mark_done(self, job_id: str, chunk_id: str) -> None:
        self._set(job_id, chunk_id, "done", None)

    def mark_failed(self, job_id: str, chunk_id: str, *, reason: str) -> None:
        self._set(job_id, chunk_id, "failed", reason)

    def retry_failed(self, job_id: str) -> int:
        cursor = self._db.execute(
            "UPDATE job_chunks SET status = 'pending', reason = NULL WHERE job_id = ? AND status = 'failed'",
            (job_id,),
        )
        self._db.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._db.close()

    def _chunk_ids(self, job_id: str, status: str) -> list[str]:
        rows = self._db.execute(
            "SELECT chunk_id FROM job_chunks WHERE job_id = ? AND status = ? ORDER BY chunk_id",
            (job_id, status),
        ).fetchall()
        return [row["chunk_id"] for row in rows]

    def _set(self, job_id: str, chunk_id: str, status: str, reason: str | None) -> None:
        cursor = self._db.execute(
            "UPDATE job_chunks SET status = ?, reason = ? WHERE job_id = ? AND chunk_id = ?",
            (status, reason, job_id, chunk_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(chunk_id)
        self._db.commit()
