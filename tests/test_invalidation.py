from __future__ import annotations

from pathlib import Path

from ragmen.registry.ledger import Ledger
from ragmen.registry.store import Registry

BLUEPRINT_A = "sha256:" + "a" * 64
BLUEPRINT_B = "sha256:" + "b" * 64


def _setup(tmp_path: Path) -> tuple[Registry, Ledger, str, Path]:
    db = tmp_path / "registry.sqlite"
    corpus = tmp_path / "corpus.md"
    corpus.write_text("one two", encoding="utf-8")
    registry = Registry(db)
    source_id = registry.add(corpus, blueprint_hash=BLUEPRINT_A).source_id
    registry.add_chunks(source_id, [("c1", "one"), ("c2", "two")])
    return registry, Ledger(db), source_id, corpus


def test_blueprint_change_starts_a_fresh_job(tmp_path: Path) -> None:
    registry, ledger, source_id, corpus = _setup(tmp_path)
    old_job = ledger.start(source_id)
    for chunk_id in ledger.pending(old_job):
        ledger.mark_done(old_job, chunk_id)

    registry.add(corpus, blueprint_hash=BLUEPRINT_B)
    new_job = ledger.start(source_id)

    assert new_job != old_job
    assert ledger.counts(new_job) == {"pending": 2, "done": 0, "failed": 0}


def test_changed_text_purges_chunks_from_the_old_content(tmp_path: Path) -> None:
    registry, _, source_id, corpus = _setup(tmp_path)
    corpus.write_text("one two three", encoding="utf-8")
    registry.add(corpus, blueprint_hash=BLUEPRINT_A)

    registry.replace_chunks(source_id, [("c1", "one"), ("c3", "two three")])

    texts = sorted(text for _, _, text in registry.chunks_for(source_id))
    assert texts == ["one", "two three"]
    assert registry.get(source_id).chunk_count == 2


def test_replacing_chunks_with_identical_text_is_a_noop(tmp_path: Path) -> None:
    registry, _, source_id, _ = _setup(tmp_path)
    before = registry.chunks_for(source_id)
    registry.replace_chunks(source_id, [("c1", "one"), ("c2", "two")])
    assert registry.chunks_for(source_id) == before
