# ############################################################################
# AI_HEADER: merge_service
# ROLE: Orchestrates packet merge: ACCEPTED → MERGED via GitService + PacketService.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Pure orchestration. No direct git/process calls — all go through
#          GitService. State transitions go through PacketService.
# inputs: Packet ID, target repo path, branch name, target branch.
# returns: MergeResult dataclass.
# side_effects: git operations in target repo, DB state transition, Event record.
# emitted_logs: merge_packet_start, merge_packet_done, merge_packet_failed.
# error_behavior: Returns MergeResult(success=False) on any failure; never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergeResult
#   - class: MergeService
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketState
from grace_control.services.git_service import GitService

_log = GraceLogger("merge_service")


@dataclass
class MergeResult:
    success: bool
    packet_id: str
    commit_sha: str
    target_repo: str
    branch: str
    target_branch: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "packet_id": self.packet_id,
            "commit_sha": self.commit_sha,
            "target_repo": self.target_repo,
            "branch": self.branch,
            "target_branch": self.target_branch,
            "error": self.error,
        }


class MergeService:
    """Merges accepted packet's branch into target repo's target branch."""

    def __init__(self, git: GitService | None = None, packets=None):
        self._git = git or GitService()
        self._packets = packets  # lazy import to avoid cycle

    async def merge_packet(
        self,
        packet_id: str,
        target_repo_root: str,
        branch_name: str,
        target_branch: str,
    ) -> MergeResult:
        from grace_control.services.packet_service import PacketService
        svc = self._packets or PacketService()
        repo = Path(target_repo_root).resolve()
        info = self._git.validate_repo(repo)

        _log.info("merge_packet_start",
            packet_id=packet_id, repo=str(repo), branch=branch_name, target_branch=target_branch)

        if not info.is_git:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error=f"target_repo_root is not a git repo: {repo}")
        if not info.is_clean:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error=f"target_repo is dirty: {repo}")
        if not branch_name:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error="branch_name is required")

        checkout = self._git.checkout(repo, target_branch)
        if not checkout.success:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error=f"checkout {target_branch} failed: {checkout.stderr}")

        self._git.fetch(repo, "origin")

        merge = self._git.merge(repo, branch_name, target_branch)
        if not merge.success:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error=f"merge failed: {merge.stderr}")

        push = self._git.push(repo, "origin", target_branch)
        if not push.success:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error=f"push failed: {push.stderr}")

        commit_sha = self._git.current_sha(repo)

        try:
            await svc.transition(
                packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}",
            )
        except Exception as e:
            _log.warn("merge_state_transition_failed",
                packet_id=packet_id, error=str(e)[:200])

        _log.info("merge_packet_done",
            packet_id=packet_id, commit_sha=commit_sha[:12], branch=branch_name)

        return MergeResult(True, packet_id, commit_sha, str(repo), branch_name, target_branch)

    async def cleanup_worktree(
        self,
        worktree_path: Path,
        branch: str,
        target_repo_root: Path | None = None,
    ) -> None:
        """Best-effort cleanup of worktree after merge. Logs failures, never raises.

        Order (P1#7):
        1. `git worktree remove --force` — unregister from `git worktree list`.
        2. `shutil.rmtree` — fallback if the path still exists.
        3. `git worktree prune` — drop stale admin files in `.git/worktrees/`.

        If `target_repo_root` is None, falls back to legacy behaviour (rmtree
        only); callers that have a repo handle should pass it.
        """
        try:
            wt = worktree_path.resolve()
            if target_repo_root is not None:
                repo = Path(target_repo_root).resolve()
                remove = self._git.worktree_remove(repo, wt, force=True)
                if not remove.success:
                    _log.warn("worktree_git_remove_failed",
                        worktree=str(wt), stderr=remove.stderr[:200])
                prune = self._git.worktree_prune(repo)
                if not prune.success:
                    _log.warn("worktree_prune_failed",
                        repo=str(repo), stderr=prune.stderr[:200])
            if wt.exists():
                import shutil
                shutil.rmtree(wt, ignore_errors=True)
        except Exception as e:
            _log.warn("worktree_cleanup_failed", worktree=str(worktree_path), error=str(e)[:200])
