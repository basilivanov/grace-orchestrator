# ############################################################################
# AI_HEADER: project_config
# ROLE: Typed loader for `.grace/config.yaml`. Precedence is:
#           env (GRACE_*)  >  .grace/config.yaml  >  safe local defaults
#       The Pydantic `BaseSettings` class `GraceSettings` in
#       `src/grace_control/config/settings.py` is the env layer. This module
#       is the .grace/config.yaml layer. W3 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md.
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
#     methods: []
#   - class: ProjectSection
#   - class: ApiSection
#   - class: DatabaseSection
#   - class: GitSection
#   - class: ExecutionSection
#   - class: SafetySection
#   - function: _resolve_config_path
#   - function: load_project_config
#   - function: get_project_config
#   - function: reset_cache
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
    backend: str = "cli"  # "cli" | "api" | "mock" — legacy removed in W8
    state_root: str = ".grace/state"
    worktree_root: str = ".grace/worktrees"
    timeout_seconds: int = 600
    # target_repo_root: the git repository where agents write code.
    # Leave empty to use GRACE_PROJECT_ROOT / cwd (self-hosted mode).
    # Set explicitly when grace-orchestrator runs on a *different* project.
    target_repo_root: str = ""
    workspace_mode: str = "full_git_worktree"
    require_clean_target_repo: bool = True
    require_remote_sync: bool = False


class SafetySection(BaseModel):
    sandbox_mode: str = "danger-full-access"
    allow_sandbox_bypass: bool = False


class OpencodeSection(BaseModel):
    """opencode server attach settings (used by `extras:` in agent profiles)."""
    server_url: str = ""
    server_password: str = ""


class FrontendE2ESpec(BaseModel):
    """Browser E2E test configuration (TZ_FRONTEND_ACCEPTANCE P0)."""
    required: bool = True


class FrontendVisualSpec(BaseModel):
    """Visual regression configuration (TZ_FRONTEND_ACCEPTANCE P0)."""
    required: bool = False
    max_diff_pct: float = 0.001


class FrontendA11ySpec(BaseModel):
    """Accessibility check configuration via axe-core (TZ_FRONTEND_ACCEPTANCE P2)."""
    required: bool = False


class FrontendSpec(BaseModel):
    """Frontend acceptance spec (TZ_FRONTEND_ACCEPTANCE P0/P2).

    When `enabled=True`, the orchestrator runs browser E2E (T2_BROWSER)
    and/or visual regression (T3_VISUAL) stages in addition to T0/T1/T2.
    P2 adds a11y axe-core (T2_BROWSER_A11Y) and desktop viewport.
    """
    enabled: bool = False
    dev_command: str = "npm run dev"
    base_url: str = "http://localhost:3000"
    viewports: list[str] = Field(default_factory=lambda: ["android", "iphone"])
    telegram_mode: str = "mock"
    telegram_user: dict[str, Any] = Field(default_factory=dict)
    telegram_bot_token_env: str = ""
    e2e: FrontendE2ESpec = Field(default_factory=FrontendE2ESpec)
    visual: FrontendVisualSpec = Field(default_factory=FrontendVisualSpec)
    a11y: FrontendA11ySpec = Field(default_factory=FrontendA11ySpec)  # P2


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
    opencode: OpencodeSection = Field(default_factory=OpencodeSection)


# START_FUNCTION_CONTRACT
# name: _resolve_config_path
# purpose: Find `.grace/config.yaml`. Search order: GRACE_PROJECT_ROOT, then
#          cwd. A missing file is a normal condition, not an error.
# inputs: none (reads GRACE_PROJECT_ROOT).
# returns: Path — may or may not exist on disk.
# side_effects: Reads env var.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _resolve_config_path() -> Path:
    root = Path(os.environ.get("GRACE_PROJECT_ROOT", ".")).resolve()
    return root / ".grace" / "config.yaml"


# START_FUNCTION_CONTRACT
# name: load_project_config
# purpose: Load `.grace/config.yaml` and return a typed `ProjectConfig`.
# inputs: path (Path | None) — defaults to GRACE_PROJECT_ROOT/.grace/config.yaml.
# returns: ProjectConfig. Missing file → all defaults.
# side_effects: Reads filesystem.
# emitted_logs: None.
# error_behavior: Invalid YAML → raises yaml.YAMLError with the file path
#                in the message. Unknown keys → silently ignored.
# END_FUNCTION_CONTRACT
def load_project_config(path: Path | None = None) -> ProjectConfig:
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


# START_FUNCTION_CONTRACT
# name: get_project_config
# purpose: Return the cached project config, refreshing it if the file changed.
# inputs: none.
# returns: ProjectConfig.
# side_effects: Reads filesystem (once, then cached).
# emitted_logs: None.
# error_behavior: Propagates yaml.YAMLError on a malformed file.
# END_FUNCTION_CONTRACT
def get_project_config() -> ProjectConfig:
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


# START_FUNCTION_CONTRACT
# name: reset_cache
# purpose: Drop the cache. Tests use this to force a reload after writing a new config.
# inputs: none.
# returns: None.
# side_effects: Resets module-level cache.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def reset_cache() -> None:
    global _cached, _cached_mtime_ns, _cached_path
    _cached = None
    _cached_mtime_ns = None
    _cached_path = None
