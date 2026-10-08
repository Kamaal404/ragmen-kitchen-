from __future__ import annotations

from pathlib import Path

import pytest

from ragmen.registry.checkpoint import Checkpoint

PROFILE_HASH = "sha256:" + "c" * 64


def _chunk(doc: Path, chunk_id: str, text: str) -> dict:
    return {"id": chunk_id, "doc_id": str(doc), "path": "chapter 1", "text": text}


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "book.md"
    path.write_text("# Chapter 1\n\nBirch bark.\n\nOak.\n", encoding="utf-8")
    return path


@pytest.fixture
def chunks(doc: Path) -> list[dict]:
    return [_chunk(doc, "seg-1", "Birch bark."), _chunk(doc, "seg-2", "Oak.")]


def test_first_plan_returns_every_chunk(tmp_path: Path, chunks: list[dict]) -> None:
    checkpoint = Checkpoint(tmp_path / "state.sqlite", profile_hash=PROFILE_HASH)
    assert [c["id"] for c in checkpoint.plan(chunks)] == ["seg-1", "seg-2"]


def test_chunk_ids_are_the_segmentation_ids(tmp_path: Path, chunks: list[dict]) -> None:
    checkpoint = Checkpoint(tmp_path / "state.sqlite", profile_hash=PROFILE_HASH)
    checkpoint.plan(chunks)
    assert checkpoint.known_chunk_ids() == {"seg-1", "seg-2"}


def test_rerun_after_a_crash_skips_done_chunks(tmp_path: Path, chunks: list[dict]) -> None:
    db = tmp_path / "state.sqlite"
    first = Checkpoint(db, profile_hash=PROFILE_HASH)
    pending = first.plan(chunks)
    first.mark_done(pending[0])
    first.close()  # the process dies before the second chunk

    resumed = Checkpoint(db, profile_hash=PROFILE_HASH)
    assert [c["id"] for c in resumed.plan(chunks)] == ["seg-2"]


def test_completed_run_plans_nothing(tmp_path: Path, chunks: list[dict]) -> None:
    db = tmp_path / "state.sqlite"
    first = Checkpoint(db, profile_hash=PROFILE_HASH)
    for chunk in first.plan(chunks):
        first.mark_done(chunk)
    first.close()
    assert Checkpoint(db, profile_hash=PROFILE_HASH).plan(chunks) == []


def test_profile_change_replans_everything(tmp_path: Path, chunks: list[dict]) -> None:
    db = tmp_path / "state.sqlite"
    first = Checkpoint(db, profile_hash=PROFILE_HASH)
    for chunk in first.plan(chunks):
        first.mark_done(chunk)
    first.close()
    other = "sha256:" + "d" * 64
    assert [c["id"] for c in Checkpoint(db, profile_hash=other).plan(chunks)] == ["seg-1", "seg-2"]


def test_failed_chunk_is_retried_on_next_run(tmp_path: Path, chunks: list[dict]) -> None:
    db = tmp_path / "state.sqlite"
    first = Checkpoint(db, profile_hash=PROFILE_HASH)
    pending = first.plan(chunks)
    first.mark_done(pending[0])
    first.mark_failed(pending[1], reason="invalid JSON from model")
    first.close()
    assert [c["id"] for c in Checkpoint(db, profile_hash=PROFILE_HASH).plan(chunks)] == ["seg-2"]

