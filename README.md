# ragmen-kitchen

Build and query runtime for approved GraphRAG blueprints.

This repository contains the `core`, `cook`, and `serve` packages under
`src/ragmen`. Cook is the build-time CLI; Serve will be the read-only MCP
server. The plugin is intentionally deferred until the runtime interfaces are
stable.

The design-time skill is maintained separately at
`Kamaal404/ragmen-recipe`. This repository and the skill are linked: the skill emits approved blueprints that this runtime consumes. Runtime refuses blueprints that are missing,
schema-invalid, incorrectly hashed, unapproved, unsupported, or incompatible
with the configured embedding dimensions.

Neo4j Community has one database per instance. Runtime stores one active
blueprint record on `(:_RagmenMeta)` with `blueprint_hash`,
`blueprint_version`, and approval fields. Ontology or embedding changes
require a new Neo4j instance or an explicit migration command; mixed graphs
are not allowed.

The migrated ingestion files under `src/ragmen/cook` originate from commit
`948b4e4` of the former `graphrag-builder` repository. The Fire Graph material
is an integration-test fixture, not a product.

```powershell
python -m pytest -q
```
