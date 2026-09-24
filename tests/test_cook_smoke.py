from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import time
from pathlib import Path

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
    assert shutil.which("docker") is not None, "Docker is required for the Neo4j smoke test"
    root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment.setdefault("NEO4J_PASSWORD", "ragmen-smoke-password")
    started = subprocess.run(
        ["docker", "compose", "up", "-d", "neo4j"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr or started.stdout

    deadline = time.monotonic() + 120
    password = environment["NEO4J_PASSWORD"]
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    from neo4j import GraphDatabase

    while time.monotonic() < deadline:
        state = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "graphrag-neo4j"],
            capture_output=True, text=True, check=False,
        )
        if state.stdout.strip().lower() == "true":
            try:
                with GraphDatabase.driver(uri, auth=(user, password)) as driver:
                    driver.verify_connectivity()
                    record = driver.execute_query("RETURN 1 AS ok").records[0]
                    assert record["ok"] == 1
                return
            except Exception:
                pass
        time.sleep(2)
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "neo4j"],
        cwd=root, env=environment, capture_output=True, text=True, check=False,
    )
    pytest.fail(f"Neo4j did not accept Bolt connections: {logs.stdout[-4000:]}")
