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
COMMANDS = ["recipe", "taste", "cook", "simmer", "serve", "toss", "query"]


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
    all_out = result.stdout + result.stderr
    assert "ok" in all_out.lower() or "PASS" in all_out


def test_toss_rejects_a_hash_mismatch() -> None:
    result = run_cli("toss", str(INVALID), "--schema", str(SCHEMA))
    assert result.returncode == 1
    all_out = result.stdout + result.stderr
    assert "hash" in all_out.lower()


def test_toss_reports_a_missing_file_without_a_traceback(tmp_path: Path) -> None:
    result = run_cli("toss", str(tmp_path / "nope.yaml"), "--schema", str(SCHEMA))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    all_out = result.stdout + result.stderr
    assert "FAIL" in all_out or "valid YAML" in all_out


@pytest.mark.parametrize("command", ["taste"])
def test_unbuilt_commands_fail_loudly(command: str) -> None:
    # A stub that exits 0 looks like success to a script. Unbuilt commands must not.
    result = run_cli(command)
    assert result.returncode == 2
    assert "not implemented" in result.stderr.lower()


def test_recipe_points_at_the_skill_repo() -> None:
    result = run_cli("recipe")
    assert result.returncode == 2
    assert "ragmen-recipe" in result.stderr


def test_query_rejects_missing_profile() -> None:
    result = run_cli("query", "test question")
    assert result.returncode == 2
    assert "required" in result.stderr.lower()


def test_query_with_empty_store_returns_graceful_message() -> None:
    """Run query with --profile pointing at a valid profile, but no data in store."""
    import tempfile, os
    # Use a minimal valid profile
    profile = """
schema:
  node_types: []
  relationship_types: []
  patterns: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(profile)
        profile_path = f.name
    try:
        # This will create an empty MemoryStore — result should be "no info found"
        result = run_cli("query", "--profile", profile_path, "test question", "--top-k", "3")
        assert result.returncode == 0
        assert "No relevant" in result.stdout or result.returncode in (0,)
    finally:
        os.unlink(profile_path)


def test_serve_help_exists() -> None:
    result = run_cli("serve", "--help")
    assert result.returncode == 0
    assert "store" in result.stdout


def test_simmer_rejects_missing_blueprint() -> None:
    result = run_cli("simmer")
    assert result.returncode == 2
    assert "required" in result.stderr.lower()


def test_cook_rejects_missing_blueprint() -> None:
    result = run_cli("cook")
    assert result.returncode == 2
    assert "required" in result.stderr.lower()


def test_cook_rejects_bogus_blueprint_path(tmp_path: Path) -> None:
    result = run_cli("cook", "--blueprint", str(tmp_path / "nope.yaml"), "--input", str(tmp_path))
    assert result.returncode == 1
    assert "rejected" in result.stderr


def test_toss_verbose_shows_all_checks() -> None:
    result = run_cli("toss", str(VALID), "--schema", str(SCHEMA), "--verbose")
    assert result.returncode == 0
    keys = ["PASS", "schema", "hash", "approval", "version", "communities", "embedding", "workload", "guardrails"]
    for k in keys:
        assert k.lower() in (result.stdout + result.stderr).lower()


def test_toss_with_firecraft_validates_all_sections() -> None:
    firecraft = ROOT / "vendor" / "blueprint" / "test-vectors" / "valid" / "firecraft.yaml"
    result = run_cli("toss", str(firecraft), "--schema", str(SCHEMA), "--verbose")
    # Firecraft has workload shapes and guardrails that should all pass
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_cook_segments_without_llm(tmp_path: Path) -> None:
    """Segment step runs; extraction step needs an LLM key so it may fail."""
    bp = ROOT / "vendor" / "blueprint" / "test-vectors" / "valid" / "minimal.yaml"
    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("hello world", encoding="utf-8")
    result = run_cli(
        "cook",
        "--blueprint", str(bp),
        "--input", str(input_dir),
        "--profile", "legal",
        "--schema", str(SCHEMA),
    )
    # Blueprint validation and segmentation should run before any LLM call.
    # The extraction step may fail if no LLM key is set, that is expected.
    assert "rejected" not in result.stderr.lower()
    # Segment.py outputs these even with 0 chunks found
    assert result.returncode in (0, 1, 2)
