"""Tests for CLI entry points and command structure."""

import subprocess
import sys
from pathlib import Path

import pytest


def test_grace_command_help():
    """Test that grace command shows help."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0
    assert "grace" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_grace_dev_command_help():
    """Test that grace-dev command shows help."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.devtools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0
    assert "development" in result.stdout.lower() or "grace-dev" in result.stdout.lower()


def test_parser_prog_name():
    """Test that parser uses 'grace' as prog name."""
    sys.path.insert(0, "/tmp/grace-orchestrator-export/src")
    try:
        from prefect_grace.cli_commands.parser import build_parser

        parser = build_parser()
        assert parser.prog == "grace", f"Expected prog='grace', got prog='{parser.prog}'"
    finally:
        sys.path.pop(0)


def test_devtools_parser_prog_name():
    """Test that devtools parser uses 'grace-dev' as prog name."""
    sys.path.insert(0, "/tmp/grace-orchestrator-export/src")
    try:
        from prefect_grace.devtools.cli import build_devtools_parser

        parser = build_devtools_parser()
        assert parser.prog == "grace-dev", f"Expected prog='grace-dev', got prog='{parser.prog}'"
    finally:
        sys.path.pop(0)


def test_backward_compat_modules_exist():
    """Test that backward compatibility modules exist."""
    sys.path.insert(0, "/tmp/grace-orchestrator-export/src")
    try:
        from prefect_grace import cli_compat

        assert hasattr(cli_compat, "prefect_grace_main")
        assert hasattr(cli_compat, "gracectl_main")
        assert callable(cli_compat.prefect_grace_main)
        assert callable(cli_compat.gracectl_main)
    finally:
        sys.path.pop(0)


def test_grace_dev_has_smoke_commands():
    """Test that grace-dev has smoke command group."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.devtools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0
    assert "smoke" in result.stdout.lower()


def test_grace_dev_has_pilot_commands():
    """Test that grace-dev has pilot command group."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.devtools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0
    assert "pilot" in result.stdout.lower()


def test_grace_dev_has_nightly_commands():
    """Test that grace-dev has nightly command group."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.devtools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0
    assert "nightly" in result.stdout.lower()


def test_deprecated_command_wrapper_exists():
    """Test that deprecated command wrapper function exists."""
    sys.path.insert(0, "/tmp/grace-orchestrator-export/src")
    try:
        from prefect_grace.cli_commands.parser import _deprecated_command_wrapper

        assert callable(_deprecated_command_wrapper)
    finally:
        sys.path.pop(0)


def test_grace_has_production_commands():
    """Test that grace CLI has key production commands."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0

    # Check for key production commands
    stdout_lower = result.stdout.lower()
    assert "submit-packets" in stdout_lower or "submit" in stdout_lower
    assert "validate" in stdout_lower


def test_grace_does_not_have_smoke_commands():
    """Test that grace CLI does not have smoke test commands (moved to grace-dev)."""
    result = subprocess.run(
        [sys.executable, "-m", "prefect_grace.cli", "--help"],
        capture_output=True,
        text=True,
        cwd="/tmp/grace-orchestrator-export"
    )
    assert result.returncode == 0

    # Smoke commands should not appear in main grace CLI
    stdout_lower = result.stdout.lower()
    assert "registry-apply-smoke" not in stdout_lower
    assert "run-prefect-e2e-live-smoke" not in stdout_lower


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
