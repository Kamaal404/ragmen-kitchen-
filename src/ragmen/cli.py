from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml

from ragmen.core.blueprint import KITCHEN_VERSION, load, validate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "vendor" / "blueprint" / "blueprint.schema.json"

# Exit codes: 0 success, 1 blueprint rejected, 2 usage or not yet implemented.
EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_NOT_IMPLEMENTED = 2


def _toss(args: argparse.Namespace) -> int:
    bp_path = Path(args.blueprint)
    schema_path = Path(args.schema)

    results = validate(bp_path, schema_path)

    failed = 0
    for name, ok, detail in results:
        if args.verbose or not ok:
            mark = "PASS" if ok else "FAIL"
            label = f"[{mark}] {name}"
            if detail:
                label += f"  {detail}"
            print(label)
        if not ok:
            failed += 1

    # Optional Neo4j connectivity check.
    if args.neo4j and failed == 0:
        neo4j_ok, neo4j_msg = _check_neo4j(bp_path)
        if args.verbose or not neo4j_ok:
            mark = "PASS" if neo4j_ok else "FAIL"
            print(f"[{mark}] neo4j connectivity  {neo4j_msg}")
        if not neo4j_ok:
            failed += 1

    if not args.verbose and failed == 0:
        bp_name = yaml.safe_load(bp_path.read_text(encoding="utf-8")).get("name", bp_path.name)
        print(f"ok: {bp_name} passes all {len(results)} checks")

    return EXIT_REJECTED if failed else EXIT_OK


def _check_neo4j(bp_path: Path) -> tuple[bool, str]:
    """Verify Neo4j is reachable and the stored blueprint hash matches."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return False, "neo4j driver not installed (pip install neo4j)"

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    if not pwd:
        return False, "NEO4J_PASSWORD not set"

    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        driver.verify_connectivity()
    except Exception as e:
        return False, f"cannot connect to {uri}: {e}"

    # Check stored blueprint metadata.
    try:
        with driver.session(database=db) as s:
            row = s.run(
                "MATCH (m:_RagmenMeta) RETURN m.blueprint_hash AS hash, m.blueprint_version AS ver LIMIT 1"
            ).single()
            if not row:
                driver.close()
                return True, f"connected to {uri}, no blueprint metadata found (empty graph)"
            bp = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
            stored_hash = row["hash"]
            blueprint_hash = bp.get("blueprint_hash", "")
            match = stored_hash == blueprint_hash
            if match:
                driver.close()
                return True, f"connected to {uri}, blueprint hash matches (:RagmenMeta v{row['ver']})"
            driver.close()
            return False, f":RagmenMeta hash {stored_hash} does not match blueprint {blueprint_hash}"
    except Exception as e:
        driver.close()
        return True, f"connected to {uri}, but metadata query failed: {e}"


def _recipe(_: argparse.Namespace) -> int:
    print(
        "ragmen recipe is a design-time skill, not a runtime command. "
        "Run it from the ragmen-recipe repository (https://github.com/Kamaal404/ragmen-recipe).",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def _cook(args: argparse.Namespace) -> int:
    blueprint = Path(args.blueprint)
    try:
        load(blueprint, Path(args.schema))
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f"rejected: {error}", file=sys.stderr)
        return EXIT_REJECTED

    inp = Path(args.input)

    old_argv = list(sys.argv)
    try:
        sys.argv = ["ragmen", "--profile", args.profile, "--input", str(inp), "--out", args.chunks]
        if args.limit:
            sys.argv.extend(["--limit", str(args.limit)])
        from ragmen.cook import segment
        segment.main()
    finally:
        sys.argv = old_argv

    try:
        sys.argv = [
            "ragmen", "--profile", args.profile, "--chunks", args.chunks,
        ]
        if args.write:
            sys.argv.extend(["--write", "--state", ".cook-checkpoint.db"])
        else:
            sys.argv.extend(["--dry-run", "--out", args.graph])
            if args.limit:
                sys.argv.extend(["--limit", str(args.limit)])
        if args.strict:
            sys.argv.append("--strict")
        from ragmen.cook.build_graph import main as build_main
        asyncio.run(build_main())
    finally:
        sys.argv = old_argv

    print(f"\ncook complete. Next: ragmen toss {args.blueprint} to re-validate")
    if not args.write:
        print(f"Inspect {args.graph}, then re-run with --write to load into Neo4j.")
    return EXIT_OK


def _query(args: argparse.Namespace) -> int:
    """One-shot cited answer from the corpus."""
    profile_path = Path(args.profile)
    if not profile_path.exists():
        from ragmen.cook.common import load_profile as _lp
        try:
            profile = _lp(args.profile)
        except SystemExit:
            print(f"profile not found: {args.profile}", file=sys.stderr)
            return EXIT_REJECTED
    else:
        import yaml as _y
        profile = _y.safe_load(profile_path.read_text(encoding="utf-8")) or {}

    from ragmen.store import MemoryStore
    from ragmen.serve.retrievers import HybridRetriever

    store = MemoryStore()
    retriever = HybridRetriever(store)
    result = retriever.retrieve(args.question, top_k=args.top_k, hops=1)

    if not result.hits:
        print("No relevant information found in the corpus.")
        return EXIT_OK

    for i, hit in enumerate(result.hits[:args.top_k]):
        print(f"[{i+1}] score={hit.score}")
        print(f"    source: {hit.source_id or 'unknown'}  path: {hit.path}")
        if hit.page:
            print(f"    page: {hit.page}")
        print(f"    {hit.text[:300]}")
        print()

    return EXIT_OK


def _serve(args: argparse.Namespace) -> int:
    """Start the read-only MCP retrieval server."""
    from ragmen.serve.mcp import start_server
    start_server(store_backend=args.store, blueprint_path=args.blueprint)
    return EXIT_OK


def _simmer(args: argparse.Namespace) -> int:
    """Re-extract after a blueprint change — incremental update."""
    from ragmen.store import MemoryStore
    store = MemoryStore()

    blueprint_path = Path(args.blueprint)
    if not blueprint_path.exists():
        print(f"blueprint not found: {blueprint_path}", file=sys.stderr)
        return EXIT_REJECTED

    import yaml
    bp = yaml.safe_load(blueprint_path.read_text(encoding="utf-8")) or {}

    print(f"simmer: blueprint={bp.get('name', 'unknown')} hash={bp.get('blueprint_hash', '')[:16]}...")
    print("  re-extraction logic: pending source re-chunking")
    return EXIT_OK


def _taste(args: argparse.Namespace) -> int:
    """Run retrieval evaluation against the golden set."""
    from ragmen.eval import run_evaluation, save_report
    from ragmen.store import MemoryStore

    store = MemoryStore()
    import yaml as _y

    profile = args.profile
    no_judge = args.no_judge

    golden_path = None
    if args.golden:
        golden_path = Path(args.golden)
        if not golden_path.exists():
            print(f"golden set not found: {golden_path}", file=sys.stderr)
            return EXIT_REJECTED

    try:
        report = run_evaluation(profile, store, no_judge=no_judge, golden_path=golden_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_REJECTED

    print(report.markdown())

    if not args.dry:
        md, js = save_report(report)
        print(f"\nresults written to:\n  {md}\n  {js}")

    # Check thresholds
    failures = 0
    for k, v in report.thresholds.items():
        for sys_name in report.systems_compared:
            if k.startswith(sys_name):
                agg = report.aggregate(sys_name)
                metric = k.replace(sys_name + "_", "")
                actual = agg.get(metric, agg.get(f"avg_{metric}", 0))
                if actual < v:
                    print(f"THRESHOLD FAIL: {k} required={v} actual={actual:.4f}")
                    failures += 1

    return EXIT_REJECTED if failures else EXIT_OK


def _not_built(name: str, _: argparse.Namespace) -> int:
    print(
        f"ragmen {name}: not implemented yet. ",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ragmen",
        description="Build and query GraphRAG knowledge graphs from approved blueprints.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    # --- recipe ---
    recipe = sub.add_parser("recipe", help="design a blueprint (runs in ragmen-recipe)")
    recipe.set_defaults(handler=_recipe)

    # --- toss ---
    toss = sub.add_parser("toss", help="validate a blueprint against the schema, hash, approval, workload, and guardrails")
    toss.add_argument("blueprint", help="path to blueprint.yaml")
    toss.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="blueprint JSON schema")
    toss.add_argument("--verbose", "-v", action="store_true", help="show every check result, not just failures")
    toss.add_argument("--neo4j", action="store_true", help="also check Neo4j connectivity and blueprint hash match")
    toss.set_defaults(handler=_toss)

    # --- cook ---
    cook = sub.add_parser("cook", help="segment a corpus and extract a knowledge graph")
    cook.add_argument("--blueprint", required=True, help="path to an approved blueprint.yaml")
    cook.add_argument("--input", required=True, help="corpus file or directory (.pdf, .txt, .md, .html)")
    cook.add_argument("--profile", default="legal", help="profile name (for the legacy extraction pipeline)")
    cook.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="blueprint JSON schema")
    cook.add_argument("--chunks", default="chunks.jsonl", help="output path for chunks")
    cook.add_argument("--graph", default="graph.jsonl", help="output path for extracted graph (dry run)")
    cook.add_argument("--write", action="store_true", help="write to Neo4j instead of dry run")
    cook.add_argument("--limit", type=int, default=0, help="stop after N chunks")
    cook.add_argument("--strict", action="store_true", help="fail on first extraction error")
    cook.set_defaults(handler=_cook)

    # --- query ---
    query = sub.add_parser("query", help="one-shot cited answer from the corpus")
    query.add_argument("--profile", required=True, help="profile name or path")
    query.add_argument("--top-k", type=int, default=5, help="number of results")
    query.add_argument("question", help="natural language question")
    query.set_defaults(handler=_query)

    # --- taste ---
    taste = sub.add_parser("taste", help="evaluate retrieval against the golden set")
    taste.add_argument("--profile", default="minimal", help="profile name (for file paths)")
    taste.add_argument("--golden", help="path to golden set JSONL (overrides default)")
    taste.add_argument("--no-judge", action="store_true", help="skip LLM judge (offline)")
    taste.add_argument("--dry", action="store_true", help="print results without saving")
    taste.set_defaults(handler=_taste)

    # --- simmer ---
    simmer = sub.add_parser("simmer", help="re-extract after a blueprint change")
    simmer.add_argument("--blueprint", required=True, help="path to updated blueprint.yaml")
    simmer.add_argument("--store", default="memory", help="store backend")
    simmer.set_defaults(handler=_simmer)

    # --- serve ---
    serve = sub.add_parser("serve", help="start the read-only MCP retrieval server")
    serve.add_argument("--store", choices=["memory", "neo4j"], default="memory")
    serve.add_argument("--blueprint", "-b", help="blueprint YAML path")
    serve.set_defaults(handler=_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
