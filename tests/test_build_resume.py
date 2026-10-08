from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ragmen.cook.build_graph as build_graph


def _write_chunks(path: Path, count: int) -> None:
    lines = [
        json.dumps({
            "id": f"seg-{i}", "doc_id": "doc", "path": "p", "text": f"text {i}",
            "char_start": i, "char_end": i + 1,
        })
        for i in range(count)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakePipeline:
    def __init__(self, fail_on: set[str], calls: list[str]) -> None:
        self._fail_on = fail_on
        self._calls = calls

    async def run_async(self, *, text: str, document_metadata: dict) -> None:
        self._calls.append(document_metadata["chunk_id"])
        if document_metadata["chunk_id"] in self._fail_on:
            raise RuntimeError("model returned invalid JSON")


def _patch_heavy_dependencies(monkeypatch: pytest.MonkeyPatch, fail_on: set[str], calls: list[str]) -> None:
    monkeypatch.setattr(build_graph, "load_profile", lambda name: {"name": name, "schema": {}})
    monkeypatch.setattr(build_graph, "graph_schema", lambda profile: {})
    monkeypatch.setattr(build_graph, "check_embedder_dims", lambda profile: None)
    monkeypatch.setattr(build_graph, "build_llm", lambda: None)
    monkeypatch.setattr(build_graph, "build_embedder", lambda: None)
    monkeypatch.setattr(build_graph, "get_driver", lambda: object())
    monkeypatch.setattr(build_graph, "database", lambda profile: "neo4j")
    monkeypatch.setattr(build_graph, "build_prompt_template", lambda profile: "")
    monkeypatch.setattr(build_graph, "write_deterministic_edges", lambda *a, **k: None)

    async def _resolve(driver, profile) -> None:
        return None

    monkeypatch.setattr(build_graph, "resolve_entities", _resolve)
    import neo4j_graphrag.experimental.pipeline.kg_builder as kg

    monkeypatch.setattr(
        kg, "SimpleKGPipeline", lambda **kwargs: _FakePipeline(fail_on, calls), raising=True
    )


def _args(chunks: Path, state: Path | None) -> SimpleNamespace:
    return SimpleNamespace(
        profile="firecraft",
        chunks=str(chunks),
        dry_run=False,
        write=True,
        out="unused.jsonl",
        limit=0,
        strict=False,
        state=str(state) if state else None,
    )


def test_resume_after_a_failed_run_only_reprocesses_failed_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tmp_path / "chunks.jsonl"
    _write_chunks(chunks, 4)
    state = tmp_path / "state.sqlite"

    first_calls: list[str] = []
    _patch_heavy_dependencies(monkeypatch, fail_on={"seg-2"}, calls=first_calls)
    asyncio.run(build_graph.build(_args(chunks, state)))
    assert first_calls == ["seg-0", "seg-1", "seg-2", "seg-3"]

    second_calls: list[str] = []
    _patch_heavy_dependencies(monkeypatch, fail_on=set(), calls=second_calls)
    asyncio.run(build_graph.build(_args(chunks, state)))
    assert second_calls == ["seg-2"]


def test_without_state_every_chunk_runs_each_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tmp_path / "chunks.jsonl"
    _write_chunks(chunks, 3)

    for _ in range(2):
        calls: list[str] = []
        _patch_heavy_dependencies(monkeypatch, fail_on=set(), calls=calls)
        asyncio.run(build_graph.build(_args(chunks, None)))
        assert calls == ["seg-0", "seg-1", "seg-2"]
