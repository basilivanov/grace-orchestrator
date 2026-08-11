# ############################################################################
# AI_HEADER: planning_workspace_service — manage isolated planning workspaces
# ROLE: Provides snapshot, clone/copy, mutation detection, and cleanup helpers
#       for Context Builder and Architect planning stages.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create disposable planning workspaces and detect planning mutations.
# inputs: Repository roots, planning log directories, and workspace role names.
# returns: Git snapshots, workspace paths, mutation evidence, or None when no evidence exists.
# side_effects: Runs git commands and creates/removes disposable directories.
# emitted_logs: None; callers own stage-level observability.
# error_behavior: Returns None for non-git roots; raises RuntimeError for clone/checkout failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _git_snapshot
#   - function: _remove_planning_workspace
#   - function: _prepare_planning_workspace
#   - function: _planning_workspace_mutation
# END_MODULE_MAP

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("planning_workspace")


# START_BLOCK_WORKSPACE
def _git_snapshot(repo_root: Path) -> dict | None:
    """Return a snapshot of HEAD SHA and changed files for a git repo."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        branch = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        return {
            "head": head.stdout.strip(),
            "branch": branch.stdout.strip() if branch.returncode == 0 else "",
            "status_short": status.stdout.strip(),
            "is_clean": status.stdout.strip() == "",
        }
    except Exception:
        return None


def _remove_planning_workspace(workspace: Path | None) -> None:
    """Remove a disposable planning workspace without touching its source repo."""
    if workspace is None or not workspace.exists():
        return
    shutil.rmtree(workspace, ignore_errors=True)


def _prepare_planning_workspace(repo_root: Path, log_dir: Path, role: str) -> Path:
    """Create an independent clone/copy for a read-only planning agent.

    A linked worktree is intentionally not used: exploratory planning commands
    must not share git worktree administration with live coder worktrees.
    """
    source = repo_root.resolve()
    workspace = (log_dir / f"{role}-repository").resolve()
    _remove_planning_workspace(workspace)

    snapshot = _git_snapshot(source)
    if snapshot is not None:
        cloned = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(workspace)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if cloned.returncode != 0:
            raise RuntimeError(
                f"planning workspace clone failed: {cloned.stderr.strip()[:300]}"
            )
        detached = subprocess.run(
            ["git", "checkout", "--quiet", "--detach", snapshot["head"]],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if detached.returncode != 0:
            _remove_planning_workspace(workspace)
            raise RuntimeError(
                f"planning workspace checkout failed: {detached.stderr.strip()[:300]}"
            )
        return workspace

    shutil.copytree(
        source,
        workspace,
        ignore=shutil.ignore_patterns(
            ".git", ".grace", ".venv", "node_modules", "__pycache__", ".pytest_cache"
        ),
    )
    return workspace


def _planning_workspace_mutation(
    before: dict | None,
    after: dict | None,
) -> dict | None:
    """Describe a planning workspace mutation, including branch-only changes."""
    if before is None or after is None:
        return None
    if (
        before.get("head") == after.get("head")
        and before.get("branch") == after.get("branch")
        and after.get("is_clean")
    ):
        return None
    return {
        "pre_head": before.get("head", ""),
        "post_head": after.get("head", ""),
        "pre_branch": before.get("branch", ""),
        "post_branch": after.get("branch", ""),
        "status_short": after.get("status_short", "")[:2000],
    }
# END_BLOCK_WORKSPACE
