from __future__ import annotations

from pathlib import Path

import pytest

from ragmen.registry.store import Registry, chunk_id

BLUEPRINT = "sha256:" + "a" * 64


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


@pytest.fixture
def two_sources(tmp_path: Path, registry: Registry) -> tuple[str, str]:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("birch bark is kindling", encoding="utf-8")
    second.write_text("birch bark shelters", encoding="utf-8")
    a = registry.add(first, blueprint_hash=BLUEPRINT).source_id
    b = registry.add(second, blueprint_hash=BLUEPRINT).source_id
    registry.add_chunks(a, [("first chunk", "birch bark is kindling")])
    registry.add_chunks(b, [("second chunk", "birch bark shelters")])
    registry.assert_entity(a, "material:birch-bark")
    registry.assert_entity(b, "material:birch-bark")
    registry.assert_entity(a, "use:kindling")
    return a, b


def test_chunk_id_is_content_addressed() -> None:
    same = chunk_id("src_x", "chapter 1 / kindling", "birch bark is kindling")
    assert same == chunk_id("src_x", "chapter 1 / kindling", "birch bark is kindling")
    assert same != chunk_id("src_x", "chapter 1 / kindling", "changed text")
    assert same != chunk_id("src_y", "chapter 1 / kindling", "birch bark is kindling")


def test_retract_removes_only_that_sources_chunks(registry: Registry, two_sources: tuple[str, str]) -> None:
    a, b = two_sources
    registry.retract(a)
    assert registry.chunks_for(a) == []
    assert len(registry.chunks_for(b)) == 1


def test_shared_entity_survives_retraction(registry: Registry, two_sources: tuple[str, str]) -> None:
    a, b = two_sources
    result = registry.retract(a)
    assert "material:birch-bark" not in result.removed_entities
    assert registry.entity_exists("material:birch-bark")
    assert registry.assertions_for("material:birch-bark") == [b]


def test_entity_only_asserted_by_retracted_source_is_removed(
    registry: Registry, two_sources: tuple[str, str]
) -> None:
    a, _ = two_sources
    result = registry.retract(a)
    assert "use:kindling" in result.removed_entities
    assert not registry.entity_exists("use:kindling")


def test_retract_marks_source_retracted_and_keeps_its_row(
    registry: Registry, two_sources: tuple[str, str]
) -> None:
    a, _ = two_sources
    registry.retract(a)
    source = registry.get(a)
    assert source.status == "retracted"
    assert source.chunk_count == 0


def test_retracting_twice_is_a_noop(registry: Registry, two_sources: tuple[str, str]) -> None:
    a, _ = two_sources
    registry.retract(a)
    again = registry.retract(a)
    assert again.removed_chunks == 0
    assert again.removed_entities == []


def test_retract_unknown_source_raises(registry: Registry) -> None:
    with pytest.raises(KeyError):
        registry.retract("src_missing")


def test_readding_a_retracted_file_reactivates_it(
    tmp_path: Path, registry: Registry, two_sources: tuple[str, str]
) -> None:
    # Without this, an unchanged file re-added after retraction reports
    # "unchanged" while its chunks are gone, and nothing is ever re-ingested.
    a, _ = two_sources
    source = registry.get(a)
    registry.retract(a)
    result = registry.add(Path(source.uri), blueprint_hash=BLUEPRINT)
    assert result.action == "added"
    assert result.needs_work is True
    assert registry.get(a).status == "pending"
