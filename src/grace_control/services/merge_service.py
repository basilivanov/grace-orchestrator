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
#   - function: is_merge_slot_wait
#   - class: MergeService
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from grace_control.core.stage_instrumentation import stage

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketState
from grace_control.services.git_service import GitService
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseBusyError,
    MergeLeaseFencedError,
    MergeLeaseTakeoverError,
)

_log = GraceLogger("merge_service")
MERGE_SLOT_WAIT_PREFIX = "waiting_for_merge_slot:"


# START_FUNCTION_CONTRACT
# name: is_merge_slot_wait
# purpose: Identify the non-terminal merge order/lease contention result.
# inputs: error — MergeResult error text.
# returns: True only for coordinator slot/order wait reasons.
# side_effects: None.
# emitted_logs: None.
# error_behavior: False for empty or unrelated errors.
# END_FUNCTION_CONTRACT
def is_merge_slot_wait(error: str) -> bool:
    return str(error).startswith(MERGE_SLOT_WAIT_PREFIX)


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

    def __init__(
        self,
        git: GitService | None = None,
        packets=None,
        coordinator: MergeCoordinatorService | None = None,
    ):
        self._git = git or GitService()
        self._packets = packets  # lazy import to avoid cycle
        self._coordinator = coordinator or MergeCoordinatorService(git=self._git)

    # START_FUNCTION_CONTRACT
    # name: merge_packet
    # purpose: Serialize accepted packet checkout, merge, push, and MERGED
    #          transition for one target repository, including shared git
    #          worktree cleanup while the merge lease is held.
    # inputs: packet_id, target_repo_root, branch_name, target_branch, and
    #         optional worktree_path and worker_id fencing identity.
    # returns: MergeResult describing success or a typed-safe failure reason.
    # side_effects: Guarded git mutations, packet transition, and lease release.
    # emitted_logs: merge_packet_start, merge_packet_done, merge_packet_failed.
    # error_behavior: Returns unsuccessful MergeResult and never raises for
    #                 merge/coordinator failures.
    # END_FUNCTION_CONTRACT
    @stage("merge")
    async def merge_packet(
        self,
        packet_id: str,
        target_repo_root: str,
        branch_name: str,
        target_branch: str,
        worker_id: str | None = None,
        worktree_path: str | Path | None = None,
    ) -> MergeResult:
        from grace_control.services.packet_service import PacketService
        svc = self._packets or PacketService()
        repo = Path(target_repo_root).resolve()
        info = self._git.validate_repo(repo)
        holder = worker_id or f"merge:{packet_id}"

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

        sanity = self._coordinator.check_repo_sanity(repo)
        if not sanity.ok:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_repo_sanity_failed: {sanity.error}",
            )

        if not self._coordinator.can_merge_now(packet_id, target_repo_root=repo):
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error="waiting_for_merge_slot: deterministic accepted merge order",
            )

        commit_sha = ""
        try:
            lease = self._coordinator.acquire(
                target_repo_root=repo,
                packet_id=packet_id,
                worker_id=holder,
            )
        except MergeLeaseBusyError as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"waiting_for_merge_slot: {error}",
            )
        except MergeLeaseTakeoverError as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_takeover_blocked: {error}",
            )
        except Exception as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"merge lease acquisition failed: {str(error)[:200]}",
            )

        try:
            checkout = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="checkout",
                operation=lambda: self._git.checkout(repo, target_branch),
            )
            if not checkout.success:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"checkout {target_branch} failed: {checkout.stderr}")

            self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="fetch",
                operation=lambda: self._git.fetch(repo, "origin"),
            )  # best-effort: local repos may not have origin

            merge = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="merge",
                operation=lambda: self._git.merge(repo, branch_name, target_branch),
            )
            if not merge.success:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"merge failed: {merge.stderr}")

            push = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="push",
                operation=lambda: self._git.push(repo, "origin", target_branch),
            )
            if not push.success:
                # Push optional — local repos (tests, dev) may have no origin.
                if "does not appear to be a git repository" not in push.stderr:
                    return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                        error=f"push failed: {push.stderr}")

            commit_sha = self._git.current_sha(repo)
            self._coordinator.assert_current(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
            )
            await svc.transition(
                packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}",
            )

            # TZ_RETENTION_POLICY.md Phase 1: after successful merge, delete
            # all attempt branches for this packet while still holding the
            # serialized target-repository lease.
            try:
                self._coordinator.run_mutation(
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=holder,
                    step_name="branch_cleanup",
                    operation=lambda: self._cleanup_packet_branches(repo, packet_id),
                )
            except MergeLeaseFencedError:
                _log.warn("merge_branch_cleanup_skipped_fenced", packet_id=packet_id)
            except Exception as error:
                _log.warn("merge_branch_cleanup_failed",
                    packet_id=packet_id, error=str(error)[:200])

            if worktree_path:
                try:
                    cleanup_path = Path(worktree_path).resolve()
                    self._cleanup_worktree_for_merge(
                        repo,
                        cleanup_path,
                        branch_name,
                        target_repo_key=lease.target_repo_key,
                        lease_token=lease.lease_token,
                        packet_id=packet_id,
                        worker_id=holder,
                    )
                except MergeLeaseFencedError:
                    _log.warn("merge_worktree_cleanup_skipped_fenced", packet_id=packet_id)
                except Exception as error:
                    _log.warn("merge_worktree_cleanup_failed",
                        packet_id=packet_id, error=str(error)[:200])

            _log.info("merge_packet_done",
                packet_id=packet_id, commit_sha=commit_sha[:12], branch=branch_name)
            return MergeResult(True, packet_id, commit_sha, str(repo), branch_name, target_branch)
        except MergeLeaseFencedError as error:
            return MergeResult(
                False,
                packet_id,
                commit_sha,
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_lease_lost: {error}",
            )
        except Exception as error:
            _log.warn("merge_state_transition_failed",
                packet_id=packet_id, error=str(error)[:200])
            return MergeResult(
                False, packet_id, commit_sha, str(repo), branch_name, target_branch,
                error=f"state transition failed: {str(error)[:200]}",
            )
        finally:
            try:
                self._coordinator.release(
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=holder,
                )
            except MergeLeaseFencedError:
                _log.warn("merge_lease_release_skipped_fenced", packet_id=packet_id)
            except Exception as error:
                _log.warn("merge_lease_release_failed",
                    packet_id=packet_id, error=str(error)[:200])

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree
    # purpose: Best-effort cleanup for callers outside the merge orchestration.
    # inputs: worktree_path, branch, and optional target_repo_root.
    # returns: None.
    # side_effects: Git worktree metadata and filesystem cleanup.
    # emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
    #                worktree_branch_delete_failed, worktree_cleanup_failed.
    # error_behavior: Logs cleanup failures and never raises.
    # END_FUNCTION_CONTRACT
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
        4. `git branch -D` for the specific merged branch (TZ_RETENTION_POLICY Phase 1).

        If `target_repo_root` is None, falls back to legacy behaviour (rmtree
        only); callers that have a repo handle should pass it.
        """
        try:
            wt = worktree_path.resolve()
            if target_repo_root is not None:
                repo = Path(target_repo_root).resolve()
                self._cleanup_worktree_git(repo, wt, branch)
            self._remove_worktree_filesystem(wt)
        except Exception as e:
            _log.warn("worktree_cleanup_failed", worktree=str(worktree_path), error=str(e)[:200])

    def _cleanup_worktree_for_merge(
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
        """Run each shared cleanup mutation under the current merge fence."""
        remove = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_remove",
            operation=lambda: self._git.worktree_remove(repo, worktree_path, force=True),
        )
        if not remove.success:
            _log.warn("worktree_git_remove_failed",
                worktree=str(worktree_path), stderr=remove.stderr[:200])

        prune = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_prune",
            operation=lambda: self._git.worktree_prune(repo),
        )
        if not prune.success:
            _log.warn("worktree_prune_failed",
                repo=str(repo), stderr=prune.stderr[:200])

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
                _log.warn("worktree_branch_delete_failed",
                    branch=branch, stderr=del_result.stderr[:200])

        self._remove_worktree_filesystem(worktree_path)

    def _cleanup_worktree_git(self, repo: Path, worktree_path: Path, branch: str) -> None:
        remove = self._git.worktree_remove(repo, worktree_path, force=True)
        if not remove.success:
            _log.warn("worktree_git_remove_failed",
                worktree=str(worktree_path), stderr=remove.stderr[:200])
        prune = self._git.worktree_prune(repo)
        if not prune.success:
            _log.warn("worktree_prune_failed",
                repo=str(repo), stderr=prune.stderr[:200])
        # TZ_RETENTION_POLICY Phase 1: delete the merged branch. The full
        # sweep across attempt branches happens in merge_packet.
        if branch:
            del_result = self._git._run(["branch", "-D", branch], repo)
            if not del_result.success:
                _log.warn("worktree_branch_delete_failed",
                    branch=branch, stderr=del_result.stderr[:200])

    @staticmethod
    def _remove_worktree_filesystem(worktree_path: Path) -> None:
        if worktree_path.exists():
            import shutil
            shutil.rmtree(worktree_path, ignore_errors=True)

    def _cleanup_packet_branches(self, repo: Path, packet_id: str) -> None:
        """Delete ALL `agent/<packet_id>-attempt-*` branches after a successful
        merge (TZ_RETENTION_POLICY.md Phase 1).

        Best-effort: logs failures per branch, never raises. Called from
        `merge_packet` after the state transition to MERGED.
        """
        pattern = f"agent/{packet_id}-attempt-*"
        list_result = self._git._run(
            ["branch", "--list", pattern], repo
        )
        if not list_result.success:
            _log.warn("merge_branch_list_failed",
                packet_id=packet_id, pattern=pattern,
                stderr=list_result.stderr[:200])
            return
        for line in list_result.stdout.splitlines():
            branch = line.strip()
            if not branch:
                continue
            if branch.startswith("* "):
                branch = branch[2:].strip()
            if not branch:
                continue
            del_result = self._git._run(["branch", "-D", branch], repo)
            if del_result.success:
                _log.info("merge_branch_deleted",
                    packet_id=packet_id, branch=branch)
            else:
                _log.warn("merge_branch_delete_failed",
                    packet_id=packet_id, branch=branch,
                    stderr=del_result.stderr[:200])
