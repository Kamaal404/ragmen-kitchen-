from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="ragmen")
    parser.add_argument("command", choices=["recipe", "taste", "cook", "simmer", "serve", "toss"])
    parser.parse_args()
    print("not implemented: this RAGmen command is part of a later build step")
    return 0
