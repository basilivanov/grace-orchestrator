# ############################################################################
# AI_HEADER: test_project_adapter
# ROLE: Test ProjectAdapter configuration loading and validation.
# ############################################################################

"""Tests for project_adapter module.

Tests cover:
- Required field validation (project_key, repo_root)
- Path validation (repo_root exists and is a directory)
- Empty/whitespace field validation
- Valid configuration loading
- Derived path computation
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from prefect_grace.platform.project_adapter import (
    load_project_adapter,
    ProjectAdapterConfig,
)


class TestProjectAdapterValidation:
    """Test validation of required fields and paths."""

    def test_missing_project_key_raises(self, tmp_path: Path) -> None:
        """Test that missing project_key raises ValueError."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="project_key is required"):
            load_project_adapter(config_file)

    def test_empty_project_key_raises(self, tmp_path: Path) -> None:
        """Test that empty/whitespace project_key raises ValueError."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "   ",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="project_key is required"):
            load_project_adapter(config_file)

    def test_missing_repo_root_raises(self, tmp_path: Path) -> None:
        """Test that missing repo_root raises ValueError."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="repo_root is required"):
            load_project_adapter(config_file)

    def test_empty_repo_root_raises(self, tmp_path: Path) -> None:
        """Test that empty/whitespace repo_root raises ValueError."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": "   ",
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="repo_root is required"):
            load_project_adapter(config_file)

    def test_nonexistent_repo_root_raises(self, tmp_path: Path) -> None:
        """Test that non-existent repo_root raises ValueError."""
        config_file = tmp_path / "project.yaml"
        nonexistent_path = tmp_path / "does-not-exist"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(nonexistent_path),
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="repo_root does not exist"):
            load_project_adapter(config_file)

    def test_repo_root_not_directory_raises(self, tmp_path: Path) -> None:
        """Test that repo_root pointing to a file raises ValueError."""
        config_file = tmp_path / "project.yaml"
        file_path = tmp_path / "not-a-directory.txt"
        file_path.write_text("test")

        config_data = {
            "project_key": "test-project",
            "repo_root": str(file_path),
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="repo_root is not a directory"):
            load_project_adapter(config_file)

    def test_missing_config_file_raises(self, tmp_path: Path) -> None:
        """Test that missing config file raises FileNotFoundError."""
        nonexistent_config = tmp_path / "does-not-exist.yaml"

        with pytest.raises(FileNotFoundError, match="Project configuration file not found"):
            load_project_adapter(nonexistent_config)


class TestProjectAdapterLoading:
    """Test successful configuration loading."""

    def test_valid_config_loads(self, tmp_path: Path) -> None:
        """Test that valid configuration loads successfully."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        assert config.project_key == "test-project"
        assert config.repo_root == str(tmp_path)
        assert config.version == 1

    def test_derived_paths_computed(self, tmp_path: Path) -> None:
        """Test that derived paths are computed correctly."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        # Check derived paths
        assert config.runtime_state_root == "/var/lib/grace-orchestrator/test-project"
        assert config.artifact_root == "/var/lib/grace-orchestrator/test-project/artifacts"
        assert config.worktree_root == "/var/lib/grace-orchestrator/test-project/worktrees"

    def test_optional_fields_have_defaults(self, tmp_path: Path) -> None:
        """Test that optional fields get default values."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        # Check defaults
        assert config.default_branch == "main"
        assert config.grace_dir == "grace"
        assert config.packets_dir == "grace/packets"
        assert config.workflow_runtime == "prefect"

    def test_explicit_optional_fields_override_defaults(self, tmp_path: Path) -> None:
        """Test that explicit optional fields override defaults."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
            "default_branch": "develop",
            "grace_dir": "custom-grace",
            "packets_dir": "custom-grace/custom-packets",
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        assert config.default_branch == "develop"
        assert config.grace_dir == "custom-grace"
        assert config.packets_dir == "custom-grace/custom-packets"

    def test_overrides_applied(self, tmp_path: Path) -> None:
        """Test that runtime overrides are applied correctly."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        overrides = {
            "default_branch": "feature-branch",
        }
        config = load_project_adapter(config_file, overrides=overrides)

        assert config.default_branch == "feature-branch"

    def test_prefect_config_defaults(self, tmp_path: Path) -> None:
        """Test that Prefect config gets correct defaults."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "my-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        assert config.prefect.work_pool == "my-project-process"
        assert config.prefect.live_queue == "my-project-live"
        assert config.prefect.monitoring_queue == "my-project-monitoring"

    def test_agent_executor_config_defaults(self, tmp_path: Path) -> None:
        """Test that agent executor config gets correct defaults."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        assert config.agent_executor.default == "codex-cli"
        assert config.agent_executor.command == "codex1"


class TestProjectAdapterWarnings:
    """Test warning behavior for missing optional directories."""

    def test_missing_grace_dir_warns(self, tmp_path: Path, caplog) -> None:
        """Test that missing grace_dir generates a warning."""
        config_file = tmp_path / "project.yaml"
        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        # grace_dir doesn't exist yet
        config = load_project_adapter(config_file)

        # Should still load successfully
        assert config.project_key == "test-project"

        # Should have logged a warning
        assert any("grace_dir does not exist" in record.message for record in caplog.records)

    def test_missing_packets_dir_warns(self, tmp_path: Path, caplog) -> None:
        """Test that missing packets_dir generates a warning."""
        config_file = tmp_path / "project.yaml"

        # Create grace_dir but not packets_dir
        grace_dir = tmp_path / "grace"
        grace_dir.mkdir()

        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        # Should still load successfully
        assert config.project_key == "test-project"

        # Should have logged a warning
        assert any("packets_dir does not exist" in record.message for record in caplog.records)

    def test_existing_directories_no_warnings(self, tmp_path: Path, caplog) -> None:
        """Test that existing directories don't generate warnings."""
        config_file = tmp_path / "project.yaml"

        # Create both directories
        grace_dir = tmp_path / "grace"
        grace_dir.mkdir()
        packets_dir = grace_dir / "packets"
        packets_dir.mkdir()

        config_data = {
            "project_key": "test-project",
            "repo_root": str(tmp_path),
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_project_adapter(config_file)

        # Should load successfully
        assert config.project_key == "test-project"

        # Should not have warnings about directories
        assert not any("grace_dir does not exist" in record.message for record in caplog.records)
        assert not any("packets_dir does not exist" in record.message for record in caplog.records)
