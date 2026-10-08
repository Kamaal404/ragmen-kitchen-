from __future__ import annotations

from pathlib import Path

import pytest

from ragmen.registry.ledger import Ledger
from ragmen.registry.store import Registry

BLUEPRINT = "sha256:" + "a" * 64
CHUNKS = [("c1", "one"), ("c2", "two"), ("c3", "three"), ("c4", "four")]


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, str]:
    file = tmp_path / "corpus.md"
    file.write_text("one two three four", encoding="utf-8")
    registry = Registry(tmp_path / "registry.sqlite")
    source_id = registry.add(file, blueprint_hash=BLUEPRINT).source_id
    registry.add_chunks(source_id, CHUNKS)
    registry.close()
    return tmp_path, source_id


def test_new_job_marks_every_chunk_pending(source: tuple[Path, str]) -> None:
    tmp_path, source_id = source
    ledger = Ledger(tmp_path / "registry.sqlite")
    job_id = ledger.start(source_id)
    assert ledger.counts(job_id) == {"pending": 4, "done": 0, "failed": 0}


def test_a_killed_run_resumes_at_the_first_unfinished_chunk(source: tuple[Path, str]) -> None:
    tmp_path, source_id = source
    db = tmp_path / "registry.sqlite"

    ledger = Ledger(db)
    job_id = ledger.start(source_id)
    chunk_ids = [chunk for chunk, _, _ in Registry(db).chunks_for(source_id)]
    ledger.mark_done(job_id, chunk_ids[0])
    ledger.mark_done(job_id, chunk_ids[1])
    ledger.close()  # simulates the process dying mid-run

    resumed = Ledger(db)
    again = resumed.start(source_id)
    assert again == job_id
    assert resumed.pending(job_id) == chunk_ids[2:]
    assert resumed.counts(job_id) == {"pending": 2, "done": 2, "failed": 0}


def test_completed_chunks_are_never_reprocessed(source: tuple[Path, str]) -> None:
    tmp_path, source_id = source
    db = tmp_path / "registry.sqlite"
    ledger = Ledger(db)
    job_id = ledger.start(source_id)
    for chunk_id in ledger.pending(job_id):
        ledger.mark_done(job_id, chunk_id)
    ledger.close()

    reopened = Ledger(db)
    assert reopened.pending(job_id) == []
    assert reopened.start(source_id) == job_id
    assert reopened.counts(job_id)["done"] == 4


def test_failed_chunk_stays_retryable(source: tuple[Path, str]) -> None:
    tmp_path, source_id = source
    ledger = Ledger(tmp_path / "registry.sqlite")
    job_id = ledger.start(source_id)
    chunk_id = ledger.pending(job_id)[0]
    ledger.mark_failed(job_id, chunk_id, reason="LLM returned invalid JSON")
    assert chunk_id not in ledger.pending(job_id)
    assert ledger.counts(job_id)["failed"] == 1
    assert ledger.retry_failed(job_id) == 1
    assert chunk_id in ledger.pending(job_id)


def test_marking_an_unknown_chunk_is_rejected(source: tuple[Path, str]) -> None:
    tmp_path, source_id = source
    ledger = Ledger(tmp_path / "registry.sqlite")
    job_id = ledger.start(source_id)
    with pytest.raises(KeyError):
        ledger.mark_done(job_id, "chk_not_in_this_source")


def test_source_change_starts_a_new_job(source: tuple[Path, str], tmp_path: Path) -> None:
    db = tmp_path / "registry.sqlite"
    ledger = Ledger(db)
    first_job = ledger.start(source[1])
    for chunk_id in ledger.pending(first_job):
        ledger.mark_done(first_job, chunk_id)

    registry = Registry(db)
    corpus = Path(registry.get(source[1]).uri)
    corpus.write_text("one two three four, corrected", encoding="utf-8")
    registry.add(corpus, blueprint_hash=BLUEPRINT)
    registry.close()

    second_job = ledger.start(source[1])
    assert second_job != first_job
    assert ledger.counts(second_job) == {"pending": 4, "done": 0, "failed": 0}
