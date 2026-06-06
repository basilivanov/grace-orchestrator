# ############################################################################
# AI_HEADER: git_context
# ROLE: Canonical git execution context — target repo, state root, worktree root.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define GitExecutionContext with target repo / state / worktree / base ref.
#          resolve_git_execution_context() builds from env vars or defaults.
# inputs: Optional overrides for each path.
# returns: GitExecutionContext.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises; falls back to sensible defaults.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: GitExecutionContext
#   - function: resolve_git_execution_context
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class GitExecutionContext(BaseModel):
    control_plane_root: Path
    target_repo_root: Path
    runtime_state_root: Path
    worktree_root: Path
    base_ref: str = "HEAD"


def resolve_git_execution_context(
    *,
    control_plane_root: Path | None = None,
    target_repo_root: Path | None = None,
    runtime_state_root: Path | None = None,
    worktree_root: Path | None = None,
    base_ref: str | None = None,
) -> GitExecutionContext:
    cwd = Path.cwd().resolve()
    ctrl = control_plane_root or cwd
    target = target_repo_root or Path(os.environ.get("GRACE_TARGET_REPO_ROOT", str(ctrl)))
    state = runtime_state_root or Path(os.environ.get("GRACE_STATE_ROOT", str(target / ".grace" / "state")))
    wt = worktree_root or Path(os.environ.get("GRACE_WORKTREE_ROOT", str(target / ".grace" / "worktrees")))
    ref = base_ref or os.environ.get("GRACE_BASE_REF", "HEAD")
    return GitExecutionContext(
        control_plane_root=ctrl.resolve(),
        target_repo_root=target.resolve(),
        runtime_state_root=state.resolve(),
        worktree_root=wt.resolve(),
        base_ref=ref,
    )
