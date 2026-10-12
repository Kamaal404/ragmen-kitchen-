"""Drift report — metrics that surface when the ontology is going stale."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class UnmappedMention:
    chunk_id: str
    text: str

@dataclass(frozen=True, slots=True)
class PatternViolation:
    chunk_id: str
    relation: str
    source_label: str
    target_label: str
    reason: str

@dataclass(frozen=True, slots=True)
class VocabMiss:
    entity_id: str
    label: str
    surface_form: str
    tier: str

@dataclass(frozen=True, slots=True)
class HubCandidate:
    entity_id: str
    label: str
    name: str
    degree: int
    threshold: int

@dataclass(frozen=True, slots=True)
class DriftReport:
    blueprint_name: str
    blueprint_hash: str
    source_id: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    unmapped_mention_rate: float = 0.0
    unmapped_mentions: tuple[UnmappedMention, ...] = ()
    pattern_violation_rate: float = 0.0
    pattern_violations: tuple[PatternViolation, ...] = ()
    vocab_miss_rate: float = 0.0
    vocab_misses: tuple[VocabMiss, ...] = ()
    hub_candidates: tuple[HubCandidate, ...] = ()
    total_chunks: int = 0
    total_entities: int = 0
    total_relations: int = 0
    total_unmapped: int = 0
    total_violations: int = 0
    total_vocab_misses: int = 0
    max_unmapped_mention_rate: float = 0.15
    max_vocab_miss_rate: float = 0.10
    max_degree: int = 200

    @property
    def thresholds_exceeded(self) -> list[str]:
        exceeded = []
        if self.unmapped_mention_rate > self.max_unmapped_mention_rate:
            exceeded.append(f"unmapped_mention_rate ({self.unmapped_mention_rate:.1%} > {self.max_unmapped_mention_rate:.1%})")
        if self.vocab_miss_rate > self.max_vocab_miss_rate:
            exceeded.append(f"vocab_miss_rate ({self.vocab_miss_rate:.1%} > {self.max_vocab_miss_rate:.1%})")
        n_over = sum(1 for h in self.hub_candidates if h.degree >= self.max_degree)
        if n_over:
            exceeded.append(f"{n_over} hub(s) with degree >= {self.max_degree}")
        return exceeded


def build_drift_report(blueprint: dict, source_id: str, results: list, resolved_entities: list | None = None, hub_threshold: int = 50) -> DriftReport:
    ontology = blueprint.get("ontology", {})
    drift_cfg = blueprint.get("drift", {})
    patterns = {tuple(p) for p in ontology.get("patterns", [])}
    resolved = resolved_entities or []

    unmapped = []
    for r in results:
        for mention in getattr(r, "unmapped_mentions", []):
            unmapped.append(UnmappedMention(chunk_id=getattr(r, "chunk_id", ""), text=mention))

    total_entities = sum(len(getattr(r, "entities", [])) for r in results)
    total_unmapped = len(unmapped)
    unmapped_rate = total_unmapped / max(1, total_unmapped + total_entities)

    violations = []
    for r in results:
        for rel in getattr(r, "relations", []):
            key = (rel.source_label, rel.relation, rel.target_label)
            if key not in patterns:
                violations.append(PatternViolation(chunk_id=getattr(r, "chunk_id", ""), relation=rel.relation, source_label=rel.source_label, target_label=rel.target_label, reason=f"Pattern not declared"))

    total_relations = sum(len(getattr(r, "relations", [])) for r in results)
    violation_rate = len(violations) / max(1, total_relations)

    misses = [VocabMiss(entity_id=re_entity.entity_id, label=re_entity.label, surface_form=re_entity.surface_forms[0] if re_entity.surface_forms else re_entity.canonical_name, tier=re_entity.tier) for re_entity in resolved if re_entity.tier in ("embedding", "llm")]
    vocab_miss_rate = len(misses) / max(1, len(resolved))

    entity_counts: dict[str, int] = {}
    for r in results:
        seen = set()
        for e in getattr(r, "entities", []):
            eid = hashlib.sha256(f"{e.label}\0{e.name}".encode("utf-8")).hexdigest()
            if eid not in seen:
                seen.add(eid)
                entity_counts[eid] = entity_counts.get(eid, 0) + 1

    entity_info: dict[str, tuple[str, str]] = {}
    for re_entity in resolved:
        entity_info[re_entity.entity_id] = (re_entity.label, re_entity.canonical_name)
    for r in results:
        for e in getattr(r, "entities", []):
            eid = hashlib.sha256(f"{e.label}\0{e.name}".encode("utf-8")).hexdigest()
            if eid not in entity_info:
                entity_info[eid] = (e.label, e.name)

    hubs = []
    seen_hub_ids = set()
    for eid, degree in entity_counts.items():
        if degree >= hub_threshold and eid not in seen_hub_ids:
            seen_hub_ids.add(eid)
            label, name = entity_info.get(eid, ("Entity", "unknown"))
            hubs.append(HubCandidate(entity_id=eid, label=label, name=name, degree=degree, threshold=hub_threshold))
    hubs.sort(key=lambda h: h.degree, reverse=True)

    return DriftReport(
        blueprint_name=blueprint.get("name", "unknown"),
        blueprint_hash=blueprint.get("blueprint_hash", ""),
        source_id=source_id,
        unmapped_mention_rate=round(unmapped_rate, 4),
        unmapped_mentions=tuple(unmapped),
        pattern_violation_rate=round(violation_rate, 4),
        pattern_violations=tuple(violations),
        vocab_miss_rate=round(vocab_miss_rate, 4),
        vocab_misses=tuple(misses),
        hub_candidates=tuple(hubs),
        total_chunks=len(results),
        total_entities=total_entities,
        total_relations=total_relations,
        total_unmapped=total_unmapped,
        total_violations=len(violations),
        total_vocab_misses=len(misses),
        max_unmapped_mention_rate=drift_cfg.get("max_unmapped_mention_rate", 0.15),
        max_vocab_miss_rate=drift_cfg.get("max_vocabulary_miss_rate", 0.10),
        max_degree=drift_cfg.get("max_degree", 200),
    )


def print_report(report: DriftReport) -> str:
    lines = [
        f"Drift Report: {report.blueprint_name}",
        f"  source: {report.source_id}  hash: {report.blueprint_hash[:20]}...",
        f"  Chunks: {report.total_chunks}  Entities: {report.total_entities}  Relations: {report.total_relations}",
        f"  Unmapped mentions: {report.total_unmapped} ({report.unmapped_mention_rate:.1%})",
        f"  Pattern violations: {report.total_violations} ({report.pattern_violation_rate:.1%})",
        f"  Vocabulary misses: {report.total_vocab_misses} ({report.vocab_miss_rate:.1%})",
        f"  Hub candidates: {len(report.hub_candidates)}",
    ]
    if report.hub_candidates:
        for h in sorted(report.hub_candidates, key=lambda x: x.degree, reverse=True)[:5]:
            lines.append(f"    {h.name} ({h.label}) degree={h.degree}")
    if report.thresholds_exceeded:
        lines.append("")
        for msg in report.thresholds_exceeded:
            lines.append(f"  \u26a0 {msg}")
    return "\n".join(lines)