from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import yaml


def canonical_payload(blueprint: dict) -> bytes:
    payload = {key: value for key, value in blueprint.items() if key not in {"blueprint_hash", "approval"}}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hash(blueprint: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(blueprint)).hexdigest()


def load(path: Path, schema_path: Path) -> dict:
    blueprint = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(blueprint))
    if errors:
        raise ValueError("blueprint schema validation failed: " + "; ".join(error.message for error in errors))
    if blueprint.get("blueprint_hash") != compute_hash(blueprint):
        raise ValueError("blueprint_hash does not match canonical blueprint content")
    if not blueprint.get("approval"):
        raise ValueError("approved blueprint is required")
    if not blueprint["blueprint_version"].startswith("1."):
        raise ValueError("unsupported blueprint version")
    communities = blueprint["communities"]
    if any(level >= communities["max_levels"] for level in communities["summarize_levels"]):
        raise ValueError("communities.summarize_levels must be within max_levels")
    model_dimensions = {"all-MiniLM-L6-v2": 384, "bge-small-en-v1.5": 384}
    model = blueprint["embedding"]["model"].split("/")[-1]
    expected_dimensions = model_dimensions.get(model)
    if expected_dimensions is not None and blueprint["embedding"]["dimensions"] != expected_dimensions:
        raise ValueError("embedding dimension mismatch")
    return blueprint
