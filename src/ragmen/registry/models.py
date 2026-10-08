from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AddAction = Literal["added", "unchanged", "updated", "reblueprinted"]


@dataclass(frozen=True)
class Source:
    source_id: str
    uri: str
    content_hash: str
    previous_hash: str | None
    blueprint_hash: str
    status: str
    chunk_count: int


@dataclass(frozen=True)
class RetractResult:
    source_id: str
    removed_chunks: int
    removed_entities: list[str]


@dataclass(frozen=True)
class AddResult:
    source_id: str
    action: AddAction

    @property
    def needs_work(self) -> bool:
        # Anything other than an exact match needs (re)chunking or re-extraction.
        return self.action != "unchanged"
