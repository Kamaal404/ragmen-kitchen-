from __future__ import annotations

import asyncio
from pathlib import Path

from ragmen.registry.checkpoint import Checkpoint, run_pending

PROFILE_HASH = "sha256:" + "c" * 64
CHUNKS = [{"id": f"seg-{i}", "text": f"text {i}"} for i in range(1, 5)]


def _run(coro):
    return asyncio.run(coro)


def test_processes_only_pending_and_counts_outcomes(tmp_path: Path) -> None:
    checkpoint = Checkpoint(tmp_path / "state.sqlite", profile_hash=PROFILE_HASH)
    seen: list[str] = []

    async def process(chunk: dict) -> None:
        seen.append(chunk["id"])
        if chunk["id"] == "seg-3":
            raise ValueError("model returned invalid JSON")

    outcome = _run(run_pending(checkpoint, CHUNKS, process))

    assert seen == ["seg-1", "seg-2", "seg-3", "seg-4"]
    assert outcome == {"ok": 3, "failed": 1}


def test_failed_chunk_is_not_marked_done(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    checkpoint = Checkpoint(db, profile_hash=PROFILE_HASH)

    async def process(chunk: dict) -> None:
        if chunk["id"] == "seg-2":
            raise ValueError("boom")

    _run(run_pending(checkpoint, CHUNKS, process))
    checkpoint.close()

    resumed = Checkpoint(db, profile_hash=PROFILE_HASH)
    replayed: list[str] = []

    async def record(chunk: dict) -> None:
        replayed.append(chunk["id"])

    _run(run_pending(resumed, CHUNKS, record))
    assert replayed == ["seg-2"]


def test_a_rerun_after_success_does_no_work(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"

    async def process(chunk: dict) -> None:
        return None

    _run(run_pending(Checkpoint(db, profile_hash=PROFILE_HASH), CHUNKS, process))

    calls: list[str] = []

    async def must_not_run(chunk: dict) -> None:
        calls.append(chunk["id"])

    outcome = _run(run_pending(Checkpoint(db, profile_hash=PROFILE_HASH), CHUNKS, must_not_run))
    assert calls == []
    assert outcome == {"ok": 0, "failed": 0}
