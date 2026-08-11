# ############################################################################
# AI_HEADER: merge_cleanup_service — fenced post-merge worktree cleanup
# ROLE: Owns merge-specific cleanup of packet attempt branches and worktrees,
#       including the public best-effort cleanup seam used by callers.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Remove merge worktree metadata, filesystem remnants, and packet
#          attempt branches while respecting the active merge lease.
# inputs: GitService, MergeCoordinatorService, target paths, packet IDs, and
#         worktree/branch identities.
# returns: None; cleanup is best effort and never changes merge result status.
# side_effects: Fenced git worktree/branch mutations and filesystem removal.
# emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
#               worktree_branch_delete_failed, merge_branch_deleted,
#               merge_cleanup_failed.
# error_behavior: Logs failures and never raises from the public cleanup seam;
#                 fenced cleanup callers may surface lease errors to the facade.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: MergeCleanupService
#     methods:
#       - cleanup_worktree
#       - cleanup_worktree_for_merge
#       - cleanup_packet_branches
# END_MODULE_MAP

from __future__ import annotations

import shutil
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.merge_coordinator_service import MergeCoordinatorService

_log = GraceLogger("merge_service")


# START_BLOCK_MERGE_CLEANUP
class MergeCleanupService:
    """Own merge-fenced branch and worktree cleanup operations."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the existing GitService and merge lease coordinator.
    # inputs: git, coordinator — authoritative target mutation collaborators.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, git, coordinator: MergeCoordinatorService) -> None:
        self._git = git
        self._coordinator = coordinator

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree
    # purpose: Best-effort cleanup for callers outside merge orchestration.
    # inputs: worktree_path, branch, optional target_repo_root.
    # returns: None.
    # side_effects: Git worktree metadata and filesystem cleanup.
    # emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
    #                worktree_branch_delete_failed, worktree_cleanup_failed.
    # error_behavior: Logs cleanup failures and never raises.
    # END_FUNCTION_CONTRACT
    def cleanup_worktree(
        self,
        worktree_path: Path,
        branch: str,
        target_repo_root: Path | None = None,
    ) -> None:
        try:
            wt = worktree_path.resolve()
            if target_repo_root is not None:
                repo = Path(target_repo_root).resolve()
                self.cleanup_worktree_git(repo, wt, branch)
            self.remove_worktree_filesystem(wt)
        except Exception as error:
            _log.warn("worktree_cleanup_failed", worktree=str(worktree_path), error=str(error)[:200])

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree_for_merge
    # purpose: Run shared cleanup mutations under the active merge fence.
    # inputs: repo, worktree_path, branch, lease identity, packet ID, worker.
    # returns: None.
    # side_effects: Fenced worktree remove/prune/branch delete and filesystem
    #               cleanup.
    # emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
    #               worktree_branch_delete_failed.
    # error_behavior: Fencing errors propagate to the facade's compatibility
    #                 boundary; git failures are logged and cleanup continues.
    # END_FUNCTION_CONTRACT
    def cleanup_worktree_for_merge(
        self,
        repo: Path,
        worktree_path: Path,
        branch: str,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str,
    ) -> None:
        remove = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_remove",
            operation=lambda: self._git.worktree_remove(repo, worktree_path, force=True),
        )
        if not remove.success:
            _log.warn(
                "worktree_git_remove_failed",
                worktree=str(worktree_path),
                stderr=remove.stderr[:200],
            )

        prune = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_prune",
            operation=lambda: self._git.worktree_prune(repo),
        )
        if not prune.success:
            _log.warn("worktree_prune_failed", repo=str(repo), stderr=prune.stderr[:200])

        if branch:
            del_result = self._coordinator.run_mutation(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="worktree_branch_delete",
                operation=lambda: self._git._run(["branch", "-D", branch], repo),
            )
            if not del_result.success:
                _log.warn(
                    "worktree_branch_delete_failed",
                    branch=branch,
                    stderr=del_result.stderr[:200],
                )

        self.remove_worktree_filesystem(worktree_path)

    # START_FUNCTION_CONTRACT
    # name: cleanup_packet_branches
    # purpose: Delete all attempt branches for a successfully merged packet
    #          while the target-repository lease remains held.
    # inputs: repo, packet_id, merge lease identity, and worker ID.
    # returns: None.
    # side_effects: Fenced branch-list and branch-delete git mutations.
    # emitted_logs: merge_branch_list_failed, merge_branch_deleted,
    #               merge_branch_delete_failed.
    # error_behavior: Logs ordinary git failures; fencing errors propagate.
    # END_FUNCTION_CONTRACT
    def cleanup_packet_branches(
        self,
        repo: Path,
        packet_id: str,
        *,
        target_repo_key: str,
        lease_token: str,
        worker_id: str,
    ) -> None:
        pattern = f"agent/{packet_id}-attempt-*"
        list_result = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="branch_list",
            operation=lambda: self._git._run(["branch", "--list", pattern], repo),
        )
        if not list_result.success:
            _log.warn(
                "merge_branch_list_failed",
                packet_id=packet_id,
                pattern=pattern,
                stderr=list_result.stderr[:200],
            )
            return
        for line in list_result.stdout.splitlines():
            branch = line.strip()
            if not branch:
                continue
            if branch.startswith("* "):
                branch = branch[2:].strip()
            if not branch:
                continue
            del_result = self._coordinator.run_mutation(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="branch_delete",
                operation=lambda branch=branch: self._git._run(
                    ["branch", "-D", branch], repo
                ),
            )
            if del_result.success:
                _log.info("merge_branch_deleted", packet_id=packet_id, branch=branch)
            else:
                _log.warn(
                    "merge_branch_delete_failed",
                    packet_id=packet_id,
                    branch=branch,
                    stderr=del_result.stderr[:200],
                )

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree_git
    # purpose: Remove one merge worktree's git metadata and merged branch.
    # inputs: repo, worktree_path, branch.
    # returns: None.
    # side_effects: Unfenced best-effort GitService cleanup for legacy caller.
    # emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
    #               worktree_branch_delete_failed.
    # error_behavior: Logs git failures and returns.
    # END_FUNCTION_CONTRACT
    def cleanup_worktree_git(self, repo: Path, worktree_path: Path, branch: str) -> None:
        remove = self._git.worktree_remove(repo, worktree_path, force=True)
        if not remove.success:
            _log.warn(
                "worktree_git_remove_failed",
                worktree=str(worktree_path),
                stderr=remove.stderr[:200],
            )
        prune = self._git.worktree_prune(repo)
        if not prune.success:
            _log.warn("worktree_prune_failed", repo=str(repo), stderr=prune.stderr[:200])
        if branch:
            del_result = self._git._run(["branch", "-D", branch], repo)
            if not del_result.success:
                _log.warn(
                    "worktree_branch_delete_failed",
                    branch=branch,
                    stderr=del_result.stderr[:200],
                )

    # START_FUNCTION_CONTRACT
    # name: remove_worktree_filesystem
    # purpose: Remove a worktree directory left after git metadata cleanup.
    # inputs: worktree_path — filesystem path.
    # returns: None.
    # side_effects: Recursive filesystem removal when the path exists.
    # emitted_logs: None.
    # error_behavior: shutil ignores missing/individual filesystem errors.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def remove_worktree_filesystem(worktree_path: Path) -> None:
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

# END_BLOCK_MERGE_CLEANUP
