from __future__ import annotations

import argparse
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

NOT_BUILT_YET = {
    "taste": "evaluate retrieval against a golden set",
    "cook": "chunk, extract, embed and load a corpus into Neo4j",
    "simmer": "re-run a built graph after a blueprint change",
    "serve": "start the read-only MCP retrieval server",
}


def _toss(args: argparse.Namespace) -> int:
    try:
        load(Path(args.blueprint), Path(args.schema))
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f"rejected: {error}", file=sys.stderr)
        return EXIT_REJECTED
    print(f"ok: {args.blueprint} is a valid, approved blueprint")
    return EXIT_OK


def _not_built(name: str) -> int:
    print(f"ragmen {name}: not implemented yet ({NOT_BUILT_YET[name]})", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def _recipe(_: argparse.Namespace) -> int:
    print(
        "ragmen recipe is a design-time skill, not a runtime command. "
        "Run it from the ragmen-recipe repository (https://github.com/Kamaal404/ragmen-recipe).",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ragmen",
        description="Build and query GraphRAG knowledge graphs from approved blueprints.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    recipe = sub.add_parser("recipe", help="design a blueprint (runs in ragmen-recipe)")
    recipe.set_defaults(handler=_recipe)

    toss = sub.add_parser("toss", help="validate a blueprint against the schema, hash and approval")
    toss.add_argument("blueprint", help="path to blueprint.yaml")
    toss.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="blueprint JSON schema")
    toss.set_defaults(handler=_toss)

    for name, summary in [
        ("cook", "build the graph from a corpus (not yet built)"),
        ("taste", "evaluate retrieval on the golden set (not yet built)"),
        ("simmer", "re-run after a blueprint change (not yet built)"),
        ("serve", "start the read-only MCP server (not yet built)"),
    ]:
        command = sub.add_parser(name, help=summary)
        command.set_defaults(handler=lambda _args, name=name: _not_built(name))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
