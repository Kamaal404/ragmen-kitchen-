from __future__ import annotations

from pathlib import Path

import pytest

from ragmen.registry.store import Registry

BLUEPRINT_A = "sha256:" + "a" * 64
BLUEPRINT_B = "sha256:" + "b" * 64


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


@pytest.fixture
def corpus_file(tmp_path: Path) -> Path:
    path = tmp_path / "book.md"
    path.write_text("# One\n\nFirst section.\n", encoding="utf-8")
    return path


def test_first_add_registers_a_source(registry: Registry, corpus_file: Path) -> None:
    result = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    assert result.action == "added"
    source = registry.get(result.source_id)
    assert source.status == "pending"
    assert source.blueprint_hash == BLUEPRINT_A
    assert source.content_hash.startswith("sha256:")


def test_readding_an_unchanged_file_is_a_noop(registry: Registry, corpus_file: Path) -> None:
    first = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    second = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    assert second.action == "unchanged"
    assert second.source_id == first.source_id
    assert second.needs_work is False
    assert len(registry.list()) == 1


def test_changed_file_keeps_source_id_and_marks_it_updated(
    registry: Registry, corpus_file: Path
) -> None:
    first = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    first_hash = registry.get(first.source_id).content_hash
    corpus_file.write_text("# One\n\nFirst section, corrected edition.\n", encoding="utf-8")
    second = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    assert second.action == "updated"
    assert second.needs_work is True
    assert second.source_id == first.source_id
    source = registry.get(first.source_id)
    assert source.previous_hash == first_hash
    assert source.content_hash != first_hash


def test_blueprint_change_invalidates_an_unchanged_source(
    registry: Registry, corpus_file: Path
) -> None:
    first = registry.add(corpus_file, blueprint_hash=BLUEPRINT_A)
    second = registry.add(corpus_file, blueprint_hash=BLUEPRINT_B)
    assert second.action == "reblueprinted"
    assert second.source_id == first.source_id
    assert registry.get(first.source_id).blueprint_hash == BLUEPRINT_B


def test_registry_survives_reopen(tmp_path: Path, corpus_file: Path) -> None:
    db = tmp_path / "registry.sqlite"
    source_id = Registry(db).add(corpus_file, blueprint_hash=BLUEPRINT_A).source_id
    reopened = Registry(db)
    assert reopened.get(source_id).blueprint_hash == BLUEPRINT_A
    assert reopened.add(corpus_file, blueprint_hash=BLUEPRINT_A).action == "unchanged"


def test_source_id_is_stable_across_paths_with_same_content(tmp_path: Path, registry: Registry) -> None:
    # Identity is the content plus its uri, so moving a file is a new source,
    # never a silent rename of an existing one.
    one = tmp_path / "a.md"
    two = tmp_path / "b.md"
    one.write_text("same", encoding="utf-8")
    two.write_text("same", encoding="utf-8")
    assert registry.add(one, blueprint_hash=BLUEPRINT_A).source_id != registry.add(
        two, blueprint_hash=BLUEPRINT_A
    ).source_id


def test_missing_file_is_rejected(registry: Registry, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        registry.add(tmp_path / "absent.md", blueprint_hash=BLUEPRINT_A)


def test_get_unknown_source_raises(registry: Registry) -> None:
    with pytest.raises(KeyError):
        registry.get("src_does_not_exist")
