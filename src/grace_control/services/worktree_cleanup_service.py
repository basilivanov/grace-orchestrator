# ############################################################################
# AI_HEADER: worktree_cleanup_service
# ROLE: Thin service — clean up stale git worktrees/branches before agent runs.
#       Exists so packet_executor does not import subprocess directly.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prune/remove stale git worktrees and delete leftover branches before
#          a new agent attempt. The only file in services/ allowed to use
#          subprocess for git cleanup operations.
# inputs: project_root (Path), slug (str) — e.g. "pkt_001-attempt-0001".
# returns: None.
# side_effects: Deletes worktree directory, prunes git worktree list, deletes branch.
# emitted_logs: worktree_cleanup_failed (best-effort, never raises).
# error_behavior: Never raises; logs and swallows all exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: WorktreeCleanupService
# END_MODULE_MAP

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("worktree_cleanup")


class WorktreeCleanupService:
    """Clean up stale git worktrees and branches before an agent run attempt."""

    # START_FUNCTION_CONTRACT
    # name: cleanup_attempt
    # purpose: Run `git worktree prune`, remove any leftover worktree for
    #          this slug, delete the corresponding branch. Best-effort.
    # inputs: project_root (Path), slug (str).
    # returns: None.
    # side_effects: Deletes worktree dir + branch.
    # emitted_logs: worktree_cleanup_failed (on non-fatal errors).
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def cleanup_attempt(self, project_root: Path, slug: str,
                        worktree_root: Path | None = None) -> None:
        """Clean up worktree and branch for a given attempt slug.

        Args:
            project_root: Root of the git repo (used for git -C).
            slug:         Attempt slug, e.g. "pkt_001-attempt-0001".
            worktree_root: Directory where worktrees live. Defaults to
                           project_root/.grace/worktrees (canonical). The old
                           code used project_root / slug which was incorrect.
        """
        wt_base = worktree_root if worktree_root is not None else (project_root / ".grace" / "worktrees")
        wt = wt_base / slug
        branch = f"agent/{slug}"
        try:
            # Prune stale git worktree metadata first.
            subprocess.run(
                ["git", "-C", str(project_root), "worktree", "prune"],
                capture_output=True, timeout=10,
            )
            if wt.exists():
                subprocess.run(
                    ["git", "-C", str(project_root), "worktree", "remove", str(wt), "--force"],
                    capture_output=True, timeout=10,
                )
                shutil.rmtree(wt, ignore_errors=True)
            # Delete the branch unconditionally — it may exist even if the
            # worktree directory was already removed.
            subprocess.run(
                ["git", "-C", str(project_root), "branch", "-D", branch],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            _log.warn("worktree_cleanup_failed", slug=slug, error=str(e)[:200])
