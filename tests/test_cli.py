from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "vendor" / "blueprint" / "blueprint.schema.json"
VALID = ROOT / "vendor" / "blueprint" / "test-vectors" / "valid" / "minimal.yaml"
INVALID = ROOT / "vendor" / "blueprint" / "test-vectors" / "invalid" / "blueprint_hash_mismatch.yaml"
COMMANDS = ["recipe", "taste", "cook", "simmer", "serve", "toss"]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "ragmen.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_help(command: str) -> None:
    result = run_cli(command, "--help")
    assert result.returncode == 0, result.stderr
    assert command in result.stdout


def test_top_level_help_lists_all_commands() -> None:
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    for command in COMMANDS:
        assert command in result.stdout


def test_unknown_command_is_rejected() -> None:
    result = run_cli("bogus")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_toss_accepts_a_valid_approved_blueprint() -> None:
    result = run_cli("toss", str(VALID), "--schema", str(SCHEMA))
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout.lower()


def test_toss_rejects_a_hash_mismatch() -> None:
    result = run_cli("toss", str(INVALID), "--schema", str(SCHEMA))
    assert result.returncode == 1
    assert "blueprint_hash" in result.stderr


def test_toss_reports_a_missing_file_without_a_traceback(tmp_path: Path) -> None:
    result = run_cli("toss", str(tmp_path / "nope.yaml"), "--schema", str(SCHEMA))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "rejected" in result.stderr


@pytest.mark.parametrize("command", ["cook", "serve", "taste", "simmer"])
def test_unbuilt_commands_fail_loudly(command: str) -> None:
    # A stub that exits 0 looks like success to a script. Unbuilt commands must not.
    result = run_cli(command)
    assert result.returncode == 2
    assert "not implemented" in result.stderr.lower()


def test_recipe_points_at_the_skill_repo() -> None:
    result = run_cli("recipe")
    assert result.returncode == 2
    assert "ragmen-recipe" in result.stderr
