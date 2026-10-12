"""Conflict representation — surface disagreements between sources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AssertedRelation:
    source_id: str
    source_uri: str
    relation: str
    source_label: str
    source_name: str
    target_label: str
    target_name: str
    properties: dict[str, Any] = field(default_factory=dict)
    quote: str = ""
    confidence: float = 1.0
    chunk_id: str = ""
    blueprint_hash: str = ""

    @property
    def assertion_key(self) -> str:
        raw = f"{self.source_label}\0{self.source_name}\0{self.relation}\0{self.target_label}\0{self.target_name}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    assertion_key: str
    source_label: str
    source_name: str
    relation: str
    target_label: str
    target_name: str
    assertions: tuple[AssertedRelation, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return len({a.quote for a in self.assertions if a.quote}) > 1

    @property
    def source_ids(self) -> list[str]:
        return [a.source_id for a in self.assertions]


def group_assertions(relations: list[dict], source_lookup: dict[str, str]) -> dict[str, ConflictGroup]:
    groups: dict[str, list[AssertedRelation]] = {}
    for r in relations:
        key = _ak(r["source_label"], r["source_name"], r["relation"], r["target_label"], r["target_name"])
        ar = AssertedRelation(source_id=r.get("source_id", ""), source_uri=source_lookup.get(r.get("source_id", ""), ""), relation=r["relation"], source_label=r["source_label"], source_name=r["source_name"], target_label=r["target_label"], target_name=r["target_name"], properties=r.get("properties", {}), quote=r.get("quote", ""), confidence=r.get("confidence", 1.0), chunk_id=r.get("chunk_id", ""), blueprint_hash=r.get("blueprint_hash", ""))
        groups.setdefault(key, []).append(ar)
    return {k: ConflictGroup(assertion_key=k, source_label=g[0].source_label, source_name=g[0].source_name, relation=g[0].relation, target_label=g[0].target_label, target_name=g[0].target_name, assertions=tuple(g)) for k, g in groups.items()}


def find_conflicts(relations: list[dict], source_lookup: dict[str, str]) -> list[ConflictGroup]:
    return [g for g in group_assertions(relations, source_lookup).values() if g.has_conflict]


def format_conflicts(conflicts: list[ConflictGroup]) -> str:
    if not conflicts:
        return "No conflicts detected."
    lines = [f"Conflicts found: {len(conflicts)}"]
    for cg in conflicts:
        lines.append(f"  {cg.source_label} '{cg.source_name}' --[{cg.relation}]--> {cg.target_label} '{cg.target_name}'")
        for a in cg.assertions:
            uri = a.source_uri or a.source_id
            q = f" \"{a.quote[:80]}\"" if a.quote else ""
            lines.append(f"    [{uri}] confidence={a.confidence}{q}")
    return "\n".join(lines)


def _ak(src_l: str, src_n: str, rel: str, tgt_l: str, tgt_n: str) -> str:
    return hashlib.sha256(f"{src_l}\0{src_n}\0{rel}\0{tgt_l}\0{tgt_n}".encode("utf-8")).hexdigest()