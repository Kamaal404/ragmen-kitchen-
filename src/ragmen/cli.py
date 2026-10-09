from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from ragmen.core.blueprint import load

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "vendor" / "blueprint" / "blueprint.schema.json"

# Exit codes: 0 success, 1 blueprint rejected, 2 usage or not yet implemented.
EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_NOT_IMPLEMENTED = 2


def _toss(args: argparse.Namespace) -> int:
    try:
        load(Path(args.blueprint), Path(args.schema))
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f"rejected: {error}", file=sys.stderr)
        return EXIT_REJECTED
    print(f"ok: {args.blueprint} is a valid, approved blueprint")
    return EXIT_OK


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
    toss = sub.add_parser("toss", help="validate a blueprint against the schema, hash and approval")
    toss.add_argument("blueprint", help="path to blueprint.yaml")
    toss.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="blueprint JSON schema")
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

    # --- taste ---
    taste = sub.add_parser("taste", help="evaluate retrieval against the golden set (not yet built)")
    taste.set_defaults(handler=lambda a: _not_built("taste", a))

    # --- simmer ---
    simmer = sub.add_parser("simmer", help="re-extract after a blueprint change (not yet built)")
    simmer.set_defaults(handler=lambda a: _not_built("simmer", a))

    # --- serve ---
    serve = sub.add_parser("serve", help="start the read-only MCP retrieval server (not yet built)")
    serve.set_defaults(handler=lambda a: _not_built("serve", a))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
