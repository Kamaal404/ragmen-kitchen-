from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import yaml


KITCHEN_VERSION = "0.1.0"
"""Semver of ragmen-kitchen itself. Used to check blueprint.compatibility."""


def canonical_payload(blueprint: dict) -> bytes:
    payload = {key: value for key, value in blueprint.items() if key not in {"blueprint_hash", "approval"}}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hash(blueprint: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(blueprint)).hexdigest()


# ---------------------------------------------------------------------------
# Individual checks. Each returns (name, passed, detail).
# passed=False means the blueprint is rejected. detail explains what went wrong.
# ---------------------------------------------------------------------------


def _check_yaml(path: Path) -> tuple[str, bool, str]:
    try:
        bp = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(bp, dict):
            return "valid YAML", False, "not a mapping at top level"
        return "valid YAML", True, ""
    except (OSError, yaml.YAMLError) as e:
        return "valid YAML", False, str(e)


def _check_schema(blueprint: dict, schema_path: Path) -> tuple[str, bool, str]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(blueprint))
        if errors:
            msgs = "; ".join(error.message for error in errors)
            return "schema validation", False, msgs
        return "schema validation", True, ""
    except (OSError, json.JSONDecodeError) as e:
        return "schema validation", False, str(e)


def _check_hash(blueprint: dict) -> tuple[str, bool, str]:
    stored = blueprint.get("blueprint_hash", "")
    computed = compute_hash(blueprint)
    if not stored:
        return "blueprint hash", False, "blueprint_hash field is missing"
    if stored != computed:
        return "blueprint hash", False, f"expected {computed}, got {stored}"
    return "blueprint hash", True, f"sha256:{computed[7:]}"


def _check_approval(blueprint: dict) -> tuple[str, bool, str]:
    approval = blueprint.get("approval")
    if not approval:
        return "approval", False, "approval field is missing or empty"
    if not isinstance(approval, dict):
        return "approval", False, "approval must be a mapping"
    if not approval.get("approved_by"):
        return "approval", False, "approval.approved_by is missing"
    if not approval.get("approved_at"):
        return "approval", False, "approval.approved_at is missing"
    return "approval", True, f"by {approval['approved_by']} at {approval['approved_at']}"


def _check_version(blueprint: dict) -> tuple[str, bool, str]:
    ver = blueprint.get("blueprint_version", "")
    if not ver:
        return "blueprint version", False, "blueprint_version is missing"
    major = ver.split(".")[0]
    # Kitchen v0.1.0 supports blueprint spec v1.x. These are separate version axes.
    if major != "1":
        return "blueprint version", False, f"kitchen supports blueprint spec v1.x, blueprint is v{ver}"
    return "blueprint version", True, f"blueprint spec v{ver} (kitchen v{KITCHEN_VERSION})"


def _check_communities(blueprint: dict) -> tuple[str, bool, str]:
    communities = blueprint.get("communities")
    if not communities:
        return "communities", False, "missing"
    max_lv = communities.get("max_levels", 0)
    sum_lv = communities.get("summarize_levels", [])
    bad = [str(l) for l in sum_lv if l >= max_lv]
    if bad:
        return "communities", False, f"summarize_levels {', '.join(bad)} >= max_levels {max_lv}"
    return "communities", True, f"leiden, {max_lv} levels, {len(sum_lv)} summarize levels"


def _check_embedding(blueprint: dict) -> tuple[str, bool, str]:
    emb = blueprint.get("embedding", {})
    model = emb.get("model", "")
    declared_dims = emb.get("dimensions", 0)

    known = {
        "all-MiniLM-L6-v2": 384, "bge-small-en-v1.5": 384,
        "bge-base-en-v1.5": 768, "all-mpnet-base-v2": 768,
        "text-embedding-3-small": 1536, "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536, "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
    }
    expected = known.get(model) or known.get(model.split("/")[-1])
    if expected and expected != declared_dims:
        return "embedding dimensions", False, f"{model} produces {expected}-d vectors but blueprint declares {declared_dims}"
    return "embedding dimensions", True, f"{model}, {declared_dims}d"


def _check_model_available(blueprint: dict) -> tuple[str, bool, str]:
    """Warn if the embedding model may not be installable. Never blocks validation."""
    model = (blueprint.get("embedding") or {}).get("model", "")
    provider = (blueprint.get("embedding") or {}).get("provider", "local")
    msg = f"{model} (provider: {provider})"
    if provider in ("local", "sentence-transformers"):
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
        except ImportError:
            return "embedding model installed", True, msg + " -- sentence-transformers not installed, will fail at runtime"
    return "embedding model installed", True, msg


def _check_workload(blueprint: dict) -> tuple[str, bool, str]:
    workload = blueprint.get("workload", {})
    ontology = blueprint.get("ontology", {})
    declared_rels = {r.get("label", r) if isinstance(r, dict) else r for r in ontology.get("relationship_types", [])}
    declared_nodes = {n.get("label", n) if isinstance(n, dict) else n for n in ontology.get("node_types", [])}

    shapes = workload.get("shapes", [])
    if not shapes:
        return "workload shapes", True, "none declared (valid but minimal)"

    issues = []
    for s in shapes:
        for rel in s.get("must_traverse", []):
            if rel not in declared_rels:
                issues.append(f"shape '{s.get('id', '?')}' references undeclared relationship '{rel}'")
        for node in s.get("must_return", []):
            if node not in declared_nodes:
                issues.append(f"shape '{s.get('id', '?')}' references undeclared node type '{node}'")

    if issues:
        return "workload shapes", False, "; ".join(issues)
    return "workload shapes", True, f"{len(shapes)} shape(s) declared, all reference valid ontology types"


def _check_guardrails(blueprint: dict) -> tuple[str, bool, str]:
    guardrails = blueprint.get("guardrails", {})
    if not guardrails:
        return "guardrails", True, "none declared"

    ontology = blueprint.get("ontology", {})
    declared_nodes = {n.get("label", n) if isinstance(n, dict) else n for n in ontology.get("node_types", [])}
    issues = []

    hf = guardrails.get("hard_filters", [])
    for f in hf:
        for label in f.get("labels", []):
            if label not in declared_nodes:
                issues.append(f"hard_filter '{f.get('name', '?')}' references undeclared node '{label}'")
        if f.get("mode") == "restrict" and not f.get("cypher"):
            issues.append(f"hard_filter '{f.get('name', '?')}' in restrict mode has no cypher clause")
        if f.get("cypher"):
            try:
                import re
                if not re.search(r"RETURN\s", f["cypher"], re.IGNORECASE) and not re.search(r"WHERE\s", f["cypher"], re.IGNORECASE):
                    pass  # minimal structural check
            except (re.error, Exception):
                issues.append(f"hard_filter '{f.get('name', '?')}' has invalid cypher pattern")

    if issues:
        return "guardrails", False, "; ".join(issues)
    n_hf = len(hf)
    return "guardrails", True, f"{n_hf} hard filter(s), conflict_policy: {guardrails.get('conflict_policy', 'surface_both')}"


ALL_CHECKS = [
    _check_yaml,
    _check_schema,
    _check_hash,
    _check_approval,
    _check_version,
    _check_communities,
    _check_embedding,
    _check_model_available,
    _check_workload,
    _check_guardrails,
]


def validate(path: Path, schema_path: Path) -> list[tuple[str, bool, str]]:
    """Run every check and return (name, passed, detail) tuples."""
    results: list[tuple[str, bool, str]] = []

    yaml_name, yaml_ok, yaml_detail = _check_yaml(path)
    results.append((yaml_name, yaml_ok, yaml_detail))
    if not yaml_ok:
        return results

    blueprint = yaml.safe_load(path.read_text(encoding="utf-8"))

    for check in ALL_CHECKS[1:]:
        if check is _check_schema:
            result = check(blueprint, schema_path)
        elif check is _check_yaml:
            continue
        else:
            result = check(blueprint)
        results.append(result)

    return results


def load(path: Path, schema_path: Path) -> dict:
    """Legacy: load, validate all checks, raise on first failure. Kept for backward compat."""
    results = validate(path, schema_path)
    for name, ok, detail in results:
        if not ok:
            raise ValueError(f"{name}: {detail}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))