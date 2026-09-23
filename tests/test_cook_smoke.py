from __future__ import annotations

import importlib
import shutil
import subprocess

import pytest


COOK_MODULES = [
    "ragmen.cook.common",
    "ragmen.cook.extract_pdf",
    "ragmen.cook.segment",
    "ragmen.cook.build_graph",
    "ragmen.cook.init_db",
    "ragmen.cook.query",
    "ragmen.cook.validate",
    "ragmen.cook.list_models",
]


def test_migrated_cook_modules_import() -> None:
    for module in COOK_MODULES:
        importlib.import_module(module)


@pytest.mark.integration
def test_fire_graph_neo4j_smoke() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is absent; Neo4j testcontainer smoke test is skipped")
    result = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.skip("Docker daemon is unavailable; Neo4j testcontainer smoke test is skipped")
    pytest.skip("Neo4j testcontainer fixture is deferred until Cook CLI ingestion is implemented")
