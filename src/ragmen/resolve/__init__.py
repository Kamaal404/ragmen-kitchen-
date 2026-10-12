"""Entity resolution — deduplicate extracted entities against blueprint vocabulary.

Resolution tiers (cheapest first): exact -> fuzzy -> embedding -> LLM.
Phase 3 implements exact and fuzzy. Embedding and LLM tiers are stubs.
"""

from .resolver import EntityResolver, ResolvedEntity, Vocabulary, resolve_batch, scoped_re_resolve

__all__ = ["EntityResolver", "ResolvedEntity", "Vocabulary", "resolve_batch", "scoped_re_resolve"]