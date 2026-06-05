# ############################################################################
# AI_HEADER: project_config
# ROLE: Typed loader for `.grace/config.yaml` — the project-level config file
#       described in `docs/grace/CONFIGURATION.md`. Precedence is:
#
#           env (.env / GRACE_* env vars)  >  .grace/config.yaml  >  defaults
#
#       The Pydantic `BaseSettings` class `GraceSettings` in
#       `src/grace_control/config/settings.py` is the env layer. This module
#       is the .grace/config.yaml layer. It is OPTIONAL — if the file does
#       not exist, it returns safe local defaults; nothing breaks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Load `.grace/config.yaml` from the project root (or GRACE_PROJECT_ROOT)
#          and surface its typed fields to the rest of the runtime.
# inputs: Optional env var GRACE_PROJECT_ROOT (defaults to cwd).
# returns: A `ProjectConfig` instance (Pydantic). All fields are optional;
#          the loader never raises on a missing file.
# side_effects: Reads filesystem; reads GRACE_PROJECT_ROOT env var.
# emitted_logs: None.
# error_behavior: YAML parse error → clear exception. Missing file → defaults.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ProjectConfig
#   - function: load_project_config
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ProjectSection(BaseModel):
    name: str = "grace-orchestrator"
    key: str = "default"


class ApiSection(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8042


class DatabaseSection(BaseModel):
    url: str = "sqlite:///./grace.db"


class GitSection(BaseModel):
    remote: str = "origin"
    base_branch: str = "main"
    target_branch: str = "main"


class ExecutionSection(BaseModel):
    backend: str = "legacy"  # "legacy" | "api" | "mock" — see grace_control.agent.select_backend
    state_root: str = ".grace/state"
    worktree_root: str = ".grace/worktrees"
    timeout_seconds: int = 600


class SafetySection(BaseModel):
    sandbox_mode: str = "danger-full-access"
    allow_sandbox_bypass: bool = False


class ProjectConfig(BaseModel):
    """Typed mirror of `.grace/config.yaml`.

    All fields are optional. A missing file is treated as an empty config
    and the defaults below take effect. The file is loaded lazily on first
    access and cached for the lifetime of the process.
    """

    project: ProjectSection = Field(default_factory=ProjectSection)
    api: ApiSection = Field(default_factory=ApiSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    git: GitSection = Field(default_factory=GitSection)
    execution: ExecutionSection = Field(default_factory=ExecutionSection)
    safety: SafetySection = Field(default_factory=SafetySection)


def _resolve_config_path() -> Path:
    """Find `.grace/config.yaml`. Search order: GRACE_PROJECT_ROOT, then cwd.

    The lookup is deliberately permissive — a missing file is a normal
    condition, not an error. We do not raise here.
    """
    root = Path(os.environ.get("GRACE_PROJECT_ROOT", ".")).resolve()
    return root / ".grace" / "config.yaml"


def load_project_config(path: Path | None = None) -> ProjectConfig:
    """Load `.grace/config.yaml` and return a typed `ProjectConfig`.

    - `path` defaults to `<GRACE_PROJECT_ROOT>/.grace/config.yaml`.
    - Missing file → all-defaults `ProjectConfig`.
    - Invalid YAML → raises `yaml.YAMLError` with the file path in the message.
    - Unknown keys → silently ignored (Pydantic default).
    """
    cfg_path = path or _resolve_config_path()
    if not cfg_path.exists():
        return ProjectConfig()
    try:
        raw: dict[str, Any] = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError as e:
        raise yaml.YAMLError(
            f"Failed to parse {cfg_path}: {e}"
        ) from e
    if not isinstance(raw, dict):
        return ProjectConfig()
    return ProjectConfig(**raw)


# Module-level cached instance. Recomputed only if the file's mtime changes.
_cached: ProjectConfig | None = None
_cached_mtime_ns: int | None = None
_cached_path: Path | None = None


def get_project_config() -> ProjectConfig:
    """Return the cached project config, refreshing it if the file changed."""
    global _cached, _cached_mtime_ns, _cached_path
    cfg_path = _resolve_config_path()
    try:
        mtime = cfg_path.stat().st_mtime_ns if cfg_path.exists() else -1
    except OSError:
        mtime = -1
    if _cached is None or _cached_path != cfg_path or mtime != _cached_mtime_ns:
        _cached = load_project_config(cfg_path)
        _cached_mtime_ns = mtime
        _cached_path = cfg_path
    return _cached


def reset_cache() -> None:
    """Drop the cache. Tests use this to force a reload after writing a new config."""
    global _cached, _cached_mtime_ns, _cached_path
    _cached = None
    _cached_mtime_ns = None
    _cached_path = None
