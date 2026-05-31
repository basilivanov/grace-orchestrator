"""Tests for runtime_config.py configuration loading and search paths."""
from __future__ import annotations

import os
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from prefect_grace.runtime_config import (
    PrefectGraceRuntimeConfig,
    load_runtime_config,
    _get_config_search_paths,
    _get_project_config_search_paths,
)


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary directory structure for config testing."""
    # Create project structure
    project_root = tmp_path / "project"
    project_root.mkdir()
    grace_dir = project_root / "grace"
    grace_dir.mkdir()

    # Create home directory structure
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    grace_home = home_dir / ".grace"
    grace_home.mkdir()

    return {
        "project_root": project_root,
        "grace_dir": grace_dir,
        "home_dir": home_dir,
        "grace_home": grace_home,
    }


@pytest.fixture
def sample_runtime_config():
    """Sample runtime configuration."""
    return {
        "api_url": "http://test-api:4200/api",
        "public_ui_url": "http://test-ui:4200",
        "work_pool_name": "test-pool",
        "live_queue_name": "test-live",
        "live_queue_limit": 2,
        "monitoring_queue_name": "test-monitoring",
        "monitoring_queue_limit": 3,
        "monitoring_interval_seconds": 600,
        "working_directory": "/test/workdir",
    }


@pytest.fixture
def sample_project_config_v2():
    """Sample project.yaml v2 configuration."""
    return {
        "version": 2,
        "project": {
            "key": "test-project",
            "root": "/test/project",
        },
        "workflow_runtime": {
            "type": "prefect",
            "api_url": "http://project-api:4200/api",
            "public_ui_url": "http://project-ui:4200",
            "work_pool": "project-pool",
            "queues": {
                "live": {
                    "name": "project-live",
                    "concurrency_limit": 5,
                },
                "monitoring": {
                    "name": "project-monitoring",
                    "concurrency_limit": 2,
                },
            },
            "monitoring_interval_seconds": 450,
        },
    }


def test_config_search_path_priority_env_var(temp_config_dir):
    """Test that GRACE_CONFIG_PATH has highest priority."""
    # Create config in custom location
    custom_config = temp_config_dir["project_root"] / "custom_runtime.yaml"
    custom_config.write_text(yaml.dump({"api_url": "http://custom:4200/api"}))

    # Create configs in other locations
    grace_config = temp_config_dir["grace_dir"] / "runtime.yaml"
    grace_config.write_text(yaml.dump({"api_url": "http://grace:4200/api"}))

    with patch.dict(os.environ, {"GRACE_CONFIG_PATH": str(custom_config)}):
        with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
            paths = _get_config_search_paths()
            assert len(paths) > 0
            assert paths[0] == custom_config


def test_config_search_path_priority_grace_dir(temp_config_dir):
    """Test that grace/runtime.yaml is checked before home directory."""
    # Create config in grace dir
    grace_config = temp_config_dir["grace_dir"] / "runtime.yaml"
    grace_config.write_text(yaml.dump({"api_url": "http://grace:4200/api"}))

    # Create config in home dir
    home_config = temp_config_dir["grace_home"] / "runtime.yaml"
    home_config.write_text(yaml.dump({"api_url": "http://home:4200/api"}))

    with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
        with patch("pathlib.Path.home", return_value=temp_config_dir["home_dir"]):
            paths = _get_config_search_paths()
            # grace_config should come before home_config
            assert grace_config in paths
            assert home_config in paths
            assert paths.index(grace_config) < paths.index(home_config)


def test_deprecation_warning_package_local(tmp_path):
    """Test that loading package-local config shows deprecation warning."""
    # Create a package-local config
    package_config = tmp_path / "runtime.yaml"
    package_config.write_text(yaml.dump({"api_url": "http://package:4200/api"}))

    with patch("prefect_grace.runtime_config.DEFAULT_CONFIG_PATH", package_config):
        with patch("pathlib.Path.cwd", return_value=tmp_path / "other"):
            with patch("pathlib.Path.home", return_value=tmp_path / "home"):
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    paths = _get_config_search_paths()

                    # Should have deprecation warning
                    assert len(w) == 1
                    assert issubclass(w[0].category, DeprecationWarning)
                    assert "deprecated" in str(w[0].message).lower()
                    assert package_config in paths


def test_grace_config_path_env_var(temp_config_dir, sample_runtime_config):
    """Test that GRACE_CONFIG_PATH environment variable works."""
    custom_config = temp_config_dir["project_root"] / "custom.yaml"
    custom_config.write_text(yaml.dump(sample_runtime_config))

    with patch.dict(os.environ, {"GRACE_CONFIG_PATH": str(custom_config)}):
        config = load_runtime_config()
        assert config.api_url == "http://test-api:4200/api"
        assert config.work_pool_name == "test-pool"


def test_default_work_pool_is_grace_process():
    """Test that default work_pool_name is 'grace-process' not 'astro-process'."""
    with patch("prefect_grace.runtime_config._get_config_search_paths", return_value=[]):
        with patch("prefect_grace.runtime_config._get_project_config_search_paths", return_value=[]):
            config = load_runtime_config()
            assert config.work_pool_name == "grace-process"


def test_project_yaml_v2_fallback(temp_config_dir, sample_project_config_v2):
    """Test that runtime config is extracted from project.yaml v2."""
    # Create project.yaml v2 in grace dir
    project_config = temp_config_dir["grace_dir"] / "project.yaml"
    project_config.write_text(yaml.dump(sample_project_config_v2))

    with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
        config = load_runtime_config()

        # Should extract from workflow_runtime section
        assert config.api_url == "http://project-api:4200/api"
        assert config.work_pool_name == "project-pool"
        assert config.live_queue_name == "project-live"
        assert config.live_queue_limit == 5
        assert config.monitoring_queue_name == "project-monitoring"
        assert config.monitoring_queue_limit == 2
        assert config.monitoring_interval_seconds == 450
        assert config.working_directory == "/test/project"


def test_config_not_found_uses_defaults():
    """Test that sensible defaults are used when no config exists."""
    with patch("prefect_grace.runtime_config._get_config_search_paths", return_value=[]):
        with patch("prefect_grace.runtime_config._get_project_config_search_paths", return_value=[]):
            config = load_runtime_config()

            # Check defaults
            assert config.api_url == "http://127.0.0.1:4200/api"
            assert config.work_pool_name == "grace-process"
            assert config.live_queue_name == "grace-live"
            assert config.monitoring_queue_name == "grace-monitoring"
            assert config.monitoring_interval_seconds == 300


def test_env_vars_override_config(temp_config_dir, sample_runtime_config):
    """Test that environment variables override file configuration."""
    config_file = temp_config_dir["grace_dir"] / "runtime.yaml"
    config_file.write_text(yaml.dump(sample_runtime_config))

    env_overrides = {
        "PREFECT_GRACE_API_URL": "http://env-api:4200/api",
        "PREFECT_GRACE_WORK_POOL": "env-pool",
        "PREFECT_GRACE_WORKDIR": "/env/workdir",
    }

    with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
        with patch.dict(os.environ, env_overrides):
            config = load_runtime_config()

            # Environment variables should override file config
            assert config.api_url == "http://env-api:4200/api"
            assert config.work_pool_name == "env-pool"
            assert config.working_directory == "/env/workdir"


def test_explicit_config_path_parameter(temp_config_dir, sample_runtime_config):
    """Test that explicit config_path parameter works."""
    custom_config = temp_config_dir["project_root"] / "explicit.yaml"
    custom_config.write_text(yaml.dump(sample_runtime_config))

    config = load_runtime_config(config_path=custom_config)
    assert config.api_url == "http://test-api:4200/api"
    assert config.work_pool_name == "test-pool"


def test_project_config_search_paths(temp_config_dir):
    """Test project.yaml search path order."""
    # Create project.yaml in multiple locations
    grace_project = temp_config_dir["grace_dir"] / "project.yaml"
    grace_project.write_text(yaml.dump({"version": 2}))

    home_project = temp_config_dir["grace_home"] / "project.yaml"
    home_project.write_text(yaml.dump({"version": 2}))

    with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
        with patch("pathlib.Path.home", return_value=temp_config_dir["home_dir"]):
            paths = _get_project_config_search_paths()

            # grace/project.yaml should come before ~/.grace/project.yaml
            assert grace_project in paths
            assert home_project in paths
            assert paths.index(grace_project) < paths.index(home_project)


def test_runtime_config_dataclass_immutable():
    """Test that PrefectGraceRuntimeConfig is immutable (frozen)."""
    config = PrefectGraceRuntimeConfig(
        api_url="http://test:4200/api",
        public_ui_url=None,
        work_pool_name="test-pool",
        live_queue_name="test-live",
        live_queue_limit=1,
        monitoring_queue_name="test-monitoring",
        monitoring_queue_limit=1,
        monitoring_interval_seconds=300,
        working_directory="/test",
    )

    # Should not be able to modify frozen dataclass
    with pytest.raises(AttributeError):
        config.api_url = "http://modified:4200/api"


def test_optional_int_normalization():
    """Test that optional integer fields handle various input formats."""
    config_data = {
        "api_url": "http://test:4200/api",
        "work_pool_name": "test-pool",
        "live_queue_name": "test-live",
        "live_queue_limit": "none",  # String "none" should become None
        "monitoring_queue_name": "test-monitoring",
        "monitoring_queue_limit": "",  # Empty string should become None
        "monitoring_interval_seconds": 300,
        "working_directory": "/test",
    }

    config_file = Path(tempfile.mktemp(suffix=".yaml"))
    try:
        config_file.write_text(yaml.dump(config_data))
        config = load_runtime_config(config_path=config_file)

        assert config.live_queue_limit is None
        assert config.monitoring_queue_limit is None
    finally:
        if config_file.exists():
            config_file.unlink()


def test_public_ui_url_optional():
    """Test that public_ui_url can be None."""
    config_data = {
        "api_url": "http://test:4200/api",
        "work_pool_name": "test-pool",
        "live_queue_name": "test-live",
        "monitoring_queue_name": "test-monitoring",
        "monitoring_interval_seconds": 300,
        "working_directory": "/test",
        # public_ui_url omitted
    }

    config_file = Path(tempfile.mktemp(suffix=".yaml"))
    try:
        config_file.write_text(yaml.dump(config_data))
        config = load_runtime_config(config_path=config_file)

        assert config.public_ui_url is None
    finally:
        if config_file.exists():
            config_file.unlink()


def test_working_directory_defaults_to_cwd():
    """Test that working_directory defaults to current working directory."""
    with patch("prefect_grace.runtime_config._get_config_search_paths", return_value=[]):
        with patch("prefect_grace.runtime_config._get_project_config_search_paths", return_value=[]):
            with patch("pathlib.Path.cwd", return_value=Path("/mock/cwd")):
                config = load_runtime_config()
                assert config.working_directory == "/mock/cwd"


def test_empty_config_file_uses_defaults(temp_config_dir):
    """Test that empty config file falls back to defaults."""
    empty_config = temp_config_dir["grace_dir"] / "runtime.yaml"
    empty_config.write_text("")  # Empty file

    with patch("pathlib.Path.cwd", return_value=temp_config_dir["project_root"]):
        config = load_runtime_config()

        # Should use defaults
        assert config.api_url == "http://127.0.0.1:4200/api"
        assert config.work_pool_name == "grace-process"


def test_config_search_skips_nonexistent_paths():
    """Test that config search gracefully skips non-existent paths."""
    with patch("pathlib.Path.cwd", return_value=Path("/nonexistent/project")):
        with patch("pathlib.Path.home", return_value=Path("/nonexistent/home")):
            with patch.dict(os.environ, {"GRACE_CONFIG_PATH": "/nonexistent/custom.yaml"}):
                paths = _get_config_search_paths()

                # Should return empty list (no paths exist)
                assert len(paths) == 0


def test_prefect_api_url_env_var_fallback():
    """Test that PREFECT_API_URL is used as fallback for PREFECT_GRACE_API_URL."""
    with patch("prefect_grace.runtime_config._get_config_search_paths", return_value=[]):
        with patch("prefect_grace.runtime_config._get_project_config_search_paths", return_value=[]):
            with patch.dict(os.environ, {"PREFECT_API_URL": "http://prefect-fallback:4200/api"}):
                config = load_runtime_config()
                assert config.api_url == "http://prefect-fallback:4200/api"


def test_env_parameter_overrides_os_environ(sample_runtime_config):
    """Test that env parameter to load_runtime_config overrides os.environ."""
    config_file = Path(tempfile.mktemp(suffix=".yaml"))
    try:
        config_file.write_text(yaml.dump(sample_runtime_config))

        # Set os.environ
        with patch.dict(os.environ, {"PREFECT_GRACE_WORK_POOL": "os-pool"}):
            # Pass different env dict
            custom_env = {"PREFECT_GRACE_WORK_POOL": "custom-pool"}
            config = load_runtime_config(config_path=config_file, env=custom_env)

            # Should use custom_env, not os.environ
            assert config.work_pool_name == "custom-pool"
    finally:
        if config_file.exists():
            config_file.unlink()
