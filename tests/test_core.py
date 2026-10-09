from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from ragmen.core.blueprint import compute_hash, load


ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "vendor" / "blueprint" / "blueprint.schema.json"
VALID_VECTORS = sorted((ROOT / "vendor/blueprint/test-vectors/valid").glob("*.yaml"))
INVALID_VECTORS = sorted((ROOT / "vendor/blueprint/test-vectors/invalid").glob("*.yaml"))


@pytest.mark.parametrize("path", VALID_VECTORS, ids=lambda path: path.stem)
def test_vendored_valid_vector_loads(path: Path) -> None:
    assert load(path, SCHEMA)["name"] == ("firecraft" if path.stem == "firecraft" else "sample")


@pytest.mark.parametrize("path", INVALID_VECTORS, ids=lambda path: path.stem)
def test_vendored_invalid_vector_fails(path: Path) -> None:
    with pytest.raises(ValueError):
        load(path, SCHEMA)


def test_hash_excludes_approval() -> None:
    value = yaml.safe_load((ROOT / "vendor/blueprint/test-vectors/valid/minimal.yaml").read_text(encoding="utf-8"))
    digest = compute_hash(value)
    value["approval"]["approved_by"] = "another-user"
    assert compute_hash(value) == digest


def test_runtime_rejects_unsupported_version(tmp_path: Path) -> None:
    value = yaml.safe_load((ROOT / "vendor/blueprint/test-vectors/valid/minimal.yaml").read_text(encoding="utf-8"))
    value["blueprint_version"] = "2.0.0"
    value["blueprint_hash"] = compute_hash(value)
    path = tmp_path / "unsupported.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(ValueError, match="supports blueprint spec v1"):
        load(path, SCHEMA)


def test_runtime_rejects_known_embedding_dimension_mismatch(tmp_path: Path) -> None:
    value = yaml.safe_load((ROOT / "vendor/blueprint/test-vectors/valid/minimal.yaml").read_text(encoding="utf-8"))
    value["embedding"] = {"model": "all-MiniLM-L6-v2", "dimensions": 128, "targets": [{}]}
    value["blueprint_hash"] = compute_hash(value)
    path = tmp_path / "wrong-dimensions.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(ValueError, match="produces 384-d vectors"):
        load(path, SCHEMA)
