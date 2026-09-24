from __future__ import annotations

import importlib
import json
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
    fixture = Path(__file__).parent / "fixtures" / "fire-graph"
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
                    print("Neo4j connectivity: RETURN 1 -> 1")
                    driver.execute_query("MATCH (n) DETACH DELETE n")
                    driver.execute_query(
                        "CREATE VECTOR INDEX fire_fixture_vector IF NOT EXISTS "
                        "FOR (n:Chunk) ON (n.embedding) "
                        "OPTIONS {indexConfig: {`vector.dimensions`: 3, `vector.similarity_function`: 'cosine'}}"
                    )
                    chunks = [
                        json.loads(line)
                        for line in (fixture / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
                    driver.execute_query(
                        "UNWIND $rows AS row CREATE (c:Chunk {id: row.id, path: row.path, text: row.text, embedding: row.embedding})",
                        rows=chunks,
                    )
                    driver.execute_query(
                        "UNWIND $rows AS row CREATE (e:Entity {id: row.id, kind: row.label, name: row.name})",
                        rows=[
                            {"id": node["id"], "label": node["label"], "name": node["properties"]["name"]}
                            for node in graph["nodes"]
                        ],
                    )
                    counts = driver.execute_query(
                        "MATCH (c:Chunk) WITH count(c) AS chunks "
                        "MATCH (e:Entity) RETURN chunks, count(e) AS entities"
                    ).records[0]
                    assert counts["chunks"] > 0
                    assert counts["entities"] > 0
                    print(f"Fire Graph fixture loaded: chunks={counts['chunks']} entities={counts['entities']}")
                    driver.execute_query(
                        "CALL db.awaitIndexes(30)"
                    )
                    results = driver.execute_query(
                        "CALL db.index.vector.queryNodes('fire_fixture_vector', 2, $embedding) "
                        "YIELD node, score RETURN node.id AS id, score ORDER BY score DESC",
                        embedding=[1.0, 0.0, 0.0],
                    ).records
                    assert len(results) > 0
                    scores = [record["score"] for record in results]
                    assert scores == sorted(scores, reverse=True)
                    print(
                        "Vector query ranked results: "
                        + ", ".join(f"{record['id']}={record['score']:.4f}" for record in results)
                    )
                return
            except Exception:
                pass
        time.sleep(2)
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "neo4j"],
        cwd=root, env=environment, capture_output=True, text=True, check=False,
    )
    pytest.fail(f"Neo4j did not accept Bolt connections: {logs.stdout[-4000:]}")
