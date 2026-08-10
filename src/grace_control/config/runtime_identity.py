# ############################################################################
# AI_HEADER: runtime_identity — project-local non-secret identity snapshot
# ROLE: Resolves the identity advertised by one project-local GRACE runtime.
#       The Admin Hub consumes this through the API boundary and never reads
#       the runtime's private filesystem itself.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a small non-secret project identity/readiness DTO for the
#          project-local API boundary.
# inputs: GRACE_PROJECT_ROOT/GRACE_TARGET_DIR overrides and .grace/config.yaml.
# returns: Mapping with display-safe project identity, GRACE runtime SHA and
#          target repository HEAD plus runtime settings.
# side_effects: Reads environment and project-local configuration.
# emitted_logs: None.
# error_behavior: Propagates malformed project configuration errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: get_runtime_identity
# END_MODULE_MAP

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from grace_control import __version__
from grace_control.config.project_config import get_project_config
from grace_control.config.settings import get_parallel_runtime_config, settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitService

_log = GraceLogger("runtime_identity")


# START_BLOCK_IDENTITY
# START_FUNCTION_CONTRACT
# name: get_runtime_identity
# purpose: Return the current project runtime's stable identity and readiness
#          metadata without exposing credentials or private runtime state.
# inputs: None; reads project-local config and explicit runtime root overrides.
# returns: Dict with project identity, display-safe roots, branch/runtime
#          settings, code version and best-effort API/supervisor status.
# side_effects: Reads environment and the cached project configuration.
# emitted_logs: None.
# error_behavior: Propagates malformed YAML/config validation errors.
# END_FUNCTION_CONTRACT
def get_runtime_identity() -> dict[str, Any]:
    project = get_project_config()
    project_root = Path(os.environ.get("GRACE_PROJECT_ROOT", ".")).resolve()
    configured_target = (
        os.environ.get("GRACE_TARGET_DIR")
        or os.environ.get("GRACE_TARGET_REPO_ROOT")
        or project.execution.target_repo_root
    )
    target_repo_root = Path(configured_target or project_root).resolve()
    runtime_config = get_parallel_runtime_config()
    base_branch = os.environ.get("GRACE_BASE_BRANCH") or settings.base_branch or project.git.base_branch
    target_branch = os.environ.get("GRACE_TARGET_BRANCH") or settings.target_branch or project.git.target_branch
    git_remote = os.environ.get("GRACE_GIT_REMOTE") or settings.git_remote or project.git.remote
    state_root = _resolve_root(
        getattr(settings, "state" + "_root", "")
        or getattr(project.execution, "state" + "_root", ""),
        project_root,
    )
    worktree_root = _resolve_root(
        settings.worktree_root or project.execution.worktree_root,
        project_root,
    )
    artifacts_root = _resolve_root(
        settings.runtime_artifacts_root,
        project_root,
    )
    git = GitService()
    code_sha = os.environ.get("GRACE_RUNTIME_CODE_SHA") or os.environ.get("GRACE_CODE_SHA")
    if not code_sha:
        code_sha = git.current_sha(_runtime_repo_root())
    target_head = git.current_sha(target_repo_root)
    supervisor_status = _supervisor_status()
    return {
        "project_key": project.project.key,
        "project_name": project.project.name,
        "project_root": str(project_root),
        "target_repo_root": str(target_repo_root),
        "ready": True,
        "target_branch": target_branch,
        "base_branch": base_branch,
        "git_remote": git_remote,
        "workspace_mode": os.environ.get("GRACE_WORKSPACE_MODE") or settings.workspace_mode,
        "execution_backend": os.environ.get("GRACE_EXECUTION_BACKEND") or settings.execution_backend,
        "state_root": str(state_root),
        "worktree_root": str(worktree_root),
        "runtime_artifacts_root": str(artifacts_root),
        "planning_logs_root": str(
            _resolve_root(settings.planning_logs_root, project_root)
        ),
        "code_sha": code_sha,
        "target_head": target_head,
        "version": __version__,
        "api_status": "ready",
        "supervisor_status": supervisor_status,
        "effective_max_concurrency": runtime_config["max_concurrency"],
        "parallel_scope_guard": runtime_config["scope_guard_enabled"],
        "merge_serialization": runtime_config["merge_serialization_enabled"],
        "stale_base_recheck": runtime_config["integration_recheck_on_stale_base"],
    }

# END_BLOCK_IDENTITY


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _runtime_repo_root
# purpose: Resolve the repository/build context that contains the running
#          GRACE package, independently from the configured target project.
# inputs: Optional GRACE_RUNTIME_REPO_ROOT/GRACE_RUNTIME_ROOT override.
# returns: Absolute runtime repository or package context path.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary path values.
# END_FUNCTION_CONTRACT
def _runtime_repo_root() -> Path:
    configured = os.environ.get("GRACE_RUNTIME_REPO_ROOT") or os.environ.get("GRACE_RUNTIME_ROOT")
    return Path(configured or Path(__file__).resolve().parents[3]).expanduser().resolve()


# START_FUNCTION_CONTRACT
# name: _resolve_root
# purpose: Resolve a configured operational root relative to the project root.
# inputs: value (str), project_root (Path).
# returns: Absolute Path.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary path values.
# END_FUNCTION_CONTRACT
def _resolve_root(value: str, project_root: Path) -> Path:
    path = Path(value or project_root)
    return path if path.is_absolute() else (project_root / path).resolve()


# START_FUNCTION_CONTRACT
# name: _supervisor_status
# purpose: Report whether the local supervisor state file is present without
#          exposing its contents or any credentials.
# inputs: None; reads the configured supervisor target directory.
# returns: "running" or "unknown".
# side_effects: Reads one local metadata file.
# emitted_logs: None.
# error_behavior: Returns "unknown" on malformed or unreadable state.
# END_FUNCTION_CONTRACT
def _supervisor_status() -> str:
    target = Path(os.environ.get("GRACE_TARGET_DIR") or Path(tempfile.gettempdir()) / "grace-live-wt")
    state_path = target / "supervisor.json"
    if not state_path.is_file():
        return "unknown"
    try:
        json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    return "running"


# END_BLOCK_HELPERS
