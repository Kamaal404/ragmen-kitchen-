"""Entity resolver — deduplicate extracted entities against the blueprint vocabulary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    canonical_name: str
    label: str
    surface_forms: tuple[str, ...] = ()
    tier: str = "exact"
    entity_id: str = ""

    def __post_init__(self) -> None:
        if not self.entity_id:
            object.__setattr__(
                self, "entity_id",
                hashlib.sha256(f"{self.label}\0{self.canonical_name}".encode("utf-8")).hexdigest(),
            )


@dataclass(frozen=True, slots=True)
class Vocabulary:
    label: str
    entries: dict[str, list[str]]
    fuzzy_threshold: float = 0.85

    @classmethod
    def from_blueprint_ontology(cls, ontology: dict, label: str) -> Vocabulary | None:
        v = ontology.get("vocabularies", {}).get(label)
        if v is None:
            return None
        entries: dict[str, list[str]] = {}
        for entry in v.get("entries", v.get("values", [])):
            if isinstance(entry, dict):
                canon = entry.get("canonical", entry.get("name", ""))
                forms = entry.get("surface_forms", entry.get("aliases", []))
                if canon:
                    entries[canon] = forms
            elif isinstance(entry, str):
                entries[entry] = []
        threshold = v.get("fuzzy_threshold", 0.85)
        return cls(label=label, entries=entries, fuzzy_threshold=threshold)

    @classmethod
    def vocabularies_from_blueprint(cls, blueprint: dict) -> dict[str, Vocabulary]:
        ontology = blueprint.get("ontology", {})
        result: dict[str, Vocabulary] = {}
        for label in ontology.get("vocabularies", {}):
            v = cls.from_blueprint_ontology(ontology, label)
            if v is not None:
                result[label] = v
        return result


class EntityResolver:
    def __init__(self, blueprint: dict) -> None:
        self.vocabularies = Vocabulary.vocabularies_from_blueprint(blueprint)

    def resolve(
        self,
        entities: list,
        existing_entity_ids: set[str] | None = None,
    ) -> list[ResolvedEntity]:
        existing = existing_entity_ids or set()
        resolved: list[ResolvedEntity] = []
        for entity in entities:
            raw_id = self._raw_id(entity.label, entity.name)
            if raw_id in existing:
                resolved.append(ResolvedEntity(canonical_name=entity.name, label=entity.label, tier="existing", entity_id=raw_id))
                continue
            matched = self._exact_match(entity.name, entity.label)
            if matched is not None:
                resolved.append(ResolvedEntity(canonical_name=matched, label=entity.label, surface_forms=(entity.name,), tier="exact"))
                continue
            fuzzy = self._fuzzy_match(entity.name, entity.label)
            if fuzzy is not None:
                resolved.append(ResolvedEntity(canonical_name=fuzzy, label=entity.label, surface_forms=(entity.name,), tier="fuzzy"))
                continue
            resolved.append(ResolvedEntity(canonical_name=entity.name, label=entity.label, surface_forms=(entity.name,), tier="new"))
        return resolved

    def _exact_match(self, name: str, label: str) -> str | None:
        vocab = self.vocabularies.get(label)
        if vocab is None:
            return None
        name_lower = name.lower().strip()
        for canonical, forms in vocab.entries.items():
            if canonical.lower() == name_lower:
                return canonical
            for form in forms:
                if form.lower() == name_lower:
                    return canonical
        return None

    def _fuzzy_match(self, name: str, label: str) -> str | None:
        vocab = self.vocabularies.get(label)
        if vocab is None:
            return None
        try:
            from rapidfuzz import fuzz
        except ImportError:
            return None
        threshold = vocab.fuzzy_threshold
        name_s = name.strip().lower()
        best: tuple[float, str] = (0.0, "")
        for canonical, forms in vocab.entries.items():
            ratio = fuzz.ratio(name_s, canonical.lower().strip())
            if ratio > best[0]:
                best = (ratio, canonical)
            for form in forms:
                ratio = fuzz.ratio(name_s, form.lower().strip())
                if ratio > best[0]:
                    best = (ratio, canonical)
        return best[1] if best[0] >= threshold else None

    @staticmethod
    def _raw_id(label: str, name: str) -> str:
        return hashlib.sha256(f"{label}\0{name}".encode("utf-8")).hexdigest()


def resolve_batch(results: list, blueprint: dict, existing_entity_ids: set[str] | None = None) -> list[ResolvedEntity]:
    resolver = EntityResolver(blueprint)
    seen: dict[str, Any] = {}
    for result in results:
        for entity in getattr(result, "entities", []):
            eid = resolver._raw_id(entity.label, entity.name)
            if eid not in seen:
                seen[eid] = entity
    raw = list(seen.values())
    resolved = resolver.resolve(raw, existing_entity_ids)
    deduped: dict[str, ResolvedEntity] = {}
    for r in resolved:
        if r.entity_id in deduped:
            old = deduped[r.entity_id]
            deduped[r.entity_id] = ResolvedEntity(canonical_name=old.canonical_name, label=old.label, surface_forms=tuple(set(old.surface_forms + r.surface_forms)), tier=old.tier, entity_id=old.entity_id)
        else:
            deduped[r.entity_id] = r
    return list(deduped.values())


def scoped_re_resolve(old_results: list, new_results: list, blueprint: dict, existing_entity_ids: set[str] | None = None):
    old_chunk_entities: dict[str, set[str]] = {}
    for r in old_results:
        ids = set()
        for e in getattr(r, "entities", []):
            ids.add(hashlib.sha256(f"{e.label}\0{e.name}".encode("utf-8")).hexdigest())
        old_chunk_entities[getattr(r, "chunk_id", "")] = ids

    resolver = EntityResolver(blueprint)
    changed_entities = []
    changed_results = []

    for r in new_results:
        cid = getattr(r, "chunk_id", "")
        old_ids = old_chunk_entities.get(cid, set())
        new_ids = set()
        for e in getattr(r, "entities", []):
            eid = hashlib.sha256(f"{e.label}\0{e.name}".encode("utf-8")).hexdigest()
            new_ids.add(eid)
            if eid not in old_ids:
                changed_entities.append(e)
        if cid not in old_chunk_entities or new_ids != old_ids:
            changed_results.append(r)

    if not changed_entities:
        return [], changed_results
    resolved = resolver.resolve(changed_entities, existing_entity_ids)
    return resolved, changed_results