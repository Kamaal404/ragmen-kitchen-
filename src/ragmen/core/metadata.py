from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseMetadata:
    blueprint_hash: str
    blueprint_version: str
    approved_by: str
    approved_at: str

    label = ":_RagmenMeta"
