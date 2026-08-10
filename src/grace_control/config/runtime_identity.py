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
# returns: Mapping with project key/name/root and target repository root.
# side_effects: Reads environment and project-local configuration.
# emitted_logs: None.
# error_behavior: Propagates malformed project configuration errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: get_runtime_identity
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from grace_control.config.project_config import get_project_config
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_identity")


# START_BLOCK_IDENTITY
# START_FUNCTION_CONTRACT
# name: get_runtime_identity
# purpose: Return the current project runtime's stable identity and readiness
#          metadata without exposing credentials or private runtime state.
# inputs: None; reads project-local config and explicit runtime root overrides.
# returns: Dict with project_key, project_name, project_root, target_repo_root,
#          and ready.
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
    return {
        "project_key": project.project.key,
        "project_name": project.project.name,
        "project_root": str(project_root),
        "target_repo_root": str(target_repo_root),
        "ready": True,
    }


# END_BLOCK_IDENTITY
