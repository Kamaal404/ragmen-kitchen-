"""Lattice Serve MCP server — read-only retrieval tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ragmen.serve.retrievers import HybridRetriever


def _load_blueprint(path: str | None) -> dict:
    if path is None:
        return {"name": "unknown", "ontology": {}, "guardrails": {}}
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def create_server(store: Any, blueprint: dict | None = None) -> Server:
    bp = blueprint or {}
    retriever = HybridRetriever(store)
    app = Server("ragmen-serve")

    async def list_tools() -> list[Tool]:
        return [
            Tool(name="search", description="Hybrid search across the knowledge graph.", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 10}, "hops": {"type": "integer", "default": 1}}, "required": ["query"]}),
            Tool(name="expand", description="Explore neighbourhood of a chunk or entity.", inputSchema={"type": "object", "properties": {"node_id": {"type": "string"}, "hops": {"type": "integer", "default": 1}, "top_k": {"type": "integer", "default": 20}}, "required": ["node_id"]}),
            Tool(name="cite", description="Get verbatim text and source for a chunk.", inputSchema={"type": "object", "properties": {"chunk_id": {"type": "string"}}, "required": ["chunk_id"]}),
            Tool(name="explain_path", description="Explain how two entities connect.", inputSchema={"type": "object", "properties": {"source_label": {"type": "string"}, "source_name": {"type": "string"}, "target_label": {"type": "string"}, "target_name": {"type": "string"}, "max_depth": {"type": "integer", "default": 4}}, "required": ["source_label", "source_name", "target_label", "target_name"]}),
            Tool(name="schema", description="Get the active blueprint ontology.", inputSchema={"type": "object", "properties": {}}),
        ]

    def _fmt_result(result) -> str:
        lines = [f"Search results (total: {result.total_hits})"]
        for i, hit in enumerate(result.hits):
            lines.append(f"\n[{i+1}] score={hit.score}  chunk={hit.chunk_id[:16]}...")
            lines.append(f"    path: {hit.path}")
            if hit.page:
                lines.append(f"    page: {hit.page}")
            lines.append(f"    text: {hit.text[:200]}")
        return "\n".join(lines)

    def _fmt_cite(chunk_id: str) -> str:
        c = store.get_chunk(chunk_id)
        if c is None:
            return f"chunk not found: {chunk_id}"
        lines = [f"Chunk: {chunk_id}", f"Path: {getattr(c, 'path', '')}", f"Text: {getattr(c, 'text', '')[:500]}"]
        if hasattr(c, "page") and c.page:
            lines.append(f"Page: {c.page}")
        return "\n".join(lines)

    def _fmt_path(label_a, name_a, label_b, name_b, max_depth=4) -> str:
        if not hasattr(store, "relations"):
            return "Path explanation not available."
        adj: dict = {}
        for rel in store.relations:
            sk = f"{rel['source_label']}\0{rel['source_name']}"
            tk = f"{rel['target_label']}\0{rel['target_name']}"
            adj.setdefault(sk, []).append({"to": tk, "rel": rel["relation"], "data": rel})
            adj.setdefault(tk, []).append({"to": sk, "rel": rel["relation"], "data": rel})
        start, target = f"{label_a}\0{name_a}", f"{label_b}\0{name_b}"
        if start not in adj or target not in adj:
            return f"No path found between {name_a} and {name_b}."
        visited, queue = {start}, [[{"key": start, "rel": None}]]
        while queue:
            path = queue.pop(0)
            if path[-1]["key"] == target:
                lines = ["Path found:"]
                for i, s in enumerate(path):
                    ln = s["key"].replace("\0", " : ")
                    lines.append(f"  [{i}] {ln}{'' if s.get('rel') else ' (start)'}")
                    if s.get("rel"):
                        q = s.get("data", {}).get("quote", "")
                        lines.append(f"       \u2514\u2500 {s['rel']} \"{q[:80]}\"" if q else f"       \u2514\u2500 {s['rel']}")
                return "\n".join(lines)
            if len(path) >= max_depth:
                continue
            for edge in adj.get(path[-1]["key"], []):
                if edge["to"] not in visited:
                    visited.add(edge["to"])
                    queue.append(path + [{"key": edge["to"], "rel": edge["rel"], "data": edge["data"]}])
        return f"No path found within {max_depth} hops."

    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search":
            result = retriever.retrieve(arguments.get("query", ""), top_k=arguments.get("top_k", 10), hops=arguments.get("hops", 1))
            return [TextContent(type="text", text=_fmt_result(result))]
        if name == "expand":
            result = retriever.expand(arguments.get("node_id", ""), hops=arguments.get("hops", 1), top_k=arguments.get("top_k", 20))
            return [TextContent(type="text", text=_fmt_result(result))]
        if name == "cite":
            return [TextContent(type="text", text=_fmt_cite(arguments.get("chunk_id", "")))]
        if name == "explain_path":
            return [TextContent(type="text", text=_fmt_path(arguments.get("source_label", ""), arguments.get("source_name", ""), arguments.get("target_label", ""), arguments.get("target_name", ""), arguments.get("max_depth", 4)))]
        if name == "schema":
            return [TextContent(type="text", text=json.dumps(bp.get("ontology", {}), indent=2))]
        raise ValueError(f"Unknown tool: {name}")

    app.list_tools = list_tools
    app.call_tool = call_tool
    return app


def start_server(store_backend: str = "memory", blueprint_path: str | None = None) -> None:
    """Start the MCP server with stdio transport.

    Args:
        store_backend: "memory" or "neo4j"
        blueprint_path: Optional path to blueprint.yaml for ontology context
    """
    bp = _load_blueprint(blueprint_path)
    from ragmen.store import MemoryStore
    store = MemoryStore()

    app = create_server(store, bp)
    print(f"RAGmen Serve starting (store={store_backend})", file=sys.stderr)

    import asyncio
    from mcp.server.stdio import stdio_server
    asyncio.run(stdio_server(app))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="RAGmen Serve MCP server")
    ap.add_argument("--store", choices=["memory", "neo4j"], default="memory")
    ap.add_argument("--blueprint", "-b", help="Blueprint YAML path")
    args = ap.parse_args()
    start_server(args.store, args.blueprint)


if __name__ == "__main__":
    main()