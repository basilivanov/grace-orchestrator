# ############################################################################
# AI_HEADER: cleanup_on_state
# ROLE: Cleanup git worktree + branches when a packet reaches terminal state.
#       Implements TZ_RETENTION_POLICY.md Phase 1.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Delete git worktree directories and branch refs when a packet
#          reaches a terminal state (REJECTED, FAILED, BLOCKED, BLOCKED_*,
#          MERGED). Does NOT touch .grace/state/ (run artifacts live forever).
# inputs: project_root (Path), worktree_root (Path), packet_id (str), attempt
# returns: CleanupResult dataclass.
# side_effects: git operations in target repo, filesystem rm of worktree dirs.
# emitted_logs: terminal_cleanup_done, terminal_cleanup_failed (per error).
# error_behavior: Never raises. Collects errors in CleanupResult.errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: CleanupResult
#   - class: TerminalStateCleanup
# END_MODULE_MAP

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitService

_log = GraceLogger("terminal_cleanup")


@dataclass
class CleanupResult:
    """Outcome of a terminal-state cleanup sweep.

    Attributes:
        branches_deleted: List of branch names that were successfully deleted
                          (e.g. ['agent/pkt_xxx-attempt-0001', ...]).
        worktree_removed: True if at least one worktree directory was removed.
        errors:          List of human-readable error messages (empty on full
                          success). Best-effort cleanup collects errors but
                          continues.
    """

    branches_deleted: list[str] = field(default_factory=list)
    worktree_removed: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if no errors occurred (even if nothing was deleted)."""
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "branches_deleted": self.branches_deleted,
            "worktree_removed": self.worktree_removed,
            "errors": self.errors,
            "success": self.success,
        }


class TerminalStateCleanup:
    """Cleanup git worktree + branch refs when a packet reaches a terminal
    state. Best-effort, never raises.

    Terminal states: REJECTED, FAILED, BLOCKED, BLOCKED_RECOVERABLE,
    BLOCKED_FINAL, MERGED. (The caller decides which state to act on; this
    class does not enforce a state machine — it just cleans the resources.)

    Cleanup policy (TZ_RETENTION_POLICY.md §Retention policy):
    - Worktree directory:  removed via `git worktree remove --force` + rmtree.
    - Branch ref:          `git branch -D agent/<packet_id>-attempt-*`.
    - Run artifacts:       NOT touched. `.grace/state/.../runs/R0X/` lives on.
    - DB rows:             NOT touched. Events / PacketRun remain.
    """

    # Set of branch patterns we consider "ours" (per-packet agent branches).
    BRANCH_PREFIX = "agent/"

    def __init__(
        self,
        project_root: Path | str,
        worktree_root: Path | str,
        git: GitService | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.worktree_root = Path(worktree_root).resolve()
        self._git = git or GitService()

    def run(
        self,
        packet_id: str,
        attempt: int | None = None,
        max_attempts: int = 10,
        project_root: Path | None = None,
    ) -> CleanupResult:
        """Run cleanup for a packet that has reached a terminal state.

        Args:
            packet_id:   Packet ID (e.g. 'pkt_8YukHJdUFa').
            attempt:     Specific attempt to clean (e.g. 3). None = all
                         attempts for this packet (uses wildcard branch
                         pattern + scans worktree dirs 1..max_attempts).
            max_attempts: When `attempt` is None, scan worktree dirs for
                          attempts 1..max_attempts. Default 10.
            project_root: Optional target project root override.

        Returns:
            CleanupResult — never raises. Check `result.errors` to see if
            any step failed.
        """
        result = CleanupResult()
        pattern = self._branch_pattern(packet_id, attempt)
        repo_root = Path(project_root).resolve() if project_root else self.project_root

        # Step 1: list branches matching the pattern.
        list_result = self._git._run(
            ["branch", "--list", pattern], repo_root
        )
        if not list_result.success:
            result.errors.append(
                f"git branch --list {pattern!r} failed: {list_result.stderr[:200]}"
            )
            _log.warn(
                "terminal_cleanup_branch_list_failed",
                packet_id=packet_id,
                pattern=pattern,
                stderr=list_result.stderr[:200],
            )
        else:
            branches = self._parse_branch_list(list_result.stdout)
            for branch in branches:
                del_result = self._git._run(
                    ["branch", "-D", branch], repo_root
                )
                if del_result.success:
                    result.branches_deleted.append(branch)
                    _log.info(
                        "terminal_cleanup_branch_deleted",
                        packet_id=packet_id,
                        branch=branch,
                    )
                else:
                    msg = (
                        f"git branch -D {branch!r} failed: "
                        f"{del_result.stderr[:200]}"
                    )
                    result.errors.append(msg)
                    _log.warn(
                        "terminal_cleanup_branch_delete_failed",
                        packet_id=packet_id,
                        branch=branch,
                        stderr=del_result.stderr[:200],
                    )

        # Step 2: remove worktree dir(s).
        attempts_to_clean = (
            [attempt]
            if attempt is not None
            else list(range(1, max_attempts + 1))
        )
        for att in attempts_to_clean:
            slug = f"{packet_id}-attempt-{att:04d}"
            wt = self.worktree_root / slug
            if not wt.exists():
                continue
            removed = self._remove_worktree(wt, slug, packet_id, result, repo_root=repo_root)
            if removed:
                result.worktree_removed = True

        _log.info(
            "terminal_cleanup_done",
            packet_id=packet_id,
            attempt=attempt,
            branches_deleted=len(result.branches_deleted),
            worktree_removed=result.worktree_removed,
            errors=len(result.errors),
        )
        return result

    def _branch_pattern(self, packet_id: str, attempt: int | None) -> str:
        """Build the git branch --list pattern for this packet."""
        if attempt is None:
            return f"{self.BRANCH_PREFIX}{packet_id}-attempt-*"
        return f"{self.BRANCH_PREFIX}{packet_id}-attempt-{attempt:04d}"

    @staticmethod
    def _parse_branch_list(stdout: str) -> list[str]:
        """Parse `git branch --list` output.

        Each line may be prefixed with `* ` (current) or `  ` (other). Strip
        both, and skip empty lines.
        """
        out: list[str] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Remove leading "* " (current) or "  " marker.
            if stripped.startswith("* "):
                stripped = stripped[2:].strip()
            elif stripped.startswith("+ "):
                # check-removed branch, prefix is "+", not "current"
                stripped = stripped[2:].strip()
            if stripped:
                out.append(stripped)
        return out

    def _remove_worktree(
        self,
        wt: Path,
        slug: str,
        packet_id: str,
        result: CleanupResult,
        repo_root: Path | None = None,
    ) -> bool:
        """Best-effort: `git worktree remove` + `shutil.rmtree` fallback.

        Returns True if the worktree dir was actually removed.
        """
        removed = False
        target_repo = repo_root or self.project_root
        # First try git worktree remove (unregisters from .git/worktrees/).
        try:
            remove_result = self._git.worktree_remove(
                target_repo, wt, force=True
            )
            if not remove_result.success:
                # Not fatal — proceed with rmtree.
                _log.warn(
                    "terminal_cleanup_worktree_remove_failed",
                    packet_id=packet_id,
                    slug=slug,
                    stderr=remove_result.stderr[:200],
                )
        except Exception as e:
            result.errors.append(f"worktree_remove {slug}: {str(e)[:200]}")
            _log.warn(
                "terminal_cleanup_worktree_remove_exception",
                packet_id=packet_id,
                slug=slug,
                error=str(e)[:200],
            )

        # Always follow with rmtree as a fallback / belt-and-suspenders.
        if wt.exists():
            try:
                shutil.rmtree(wt, ignore_errors=True)
            except Exception as e:
                result.errors.append(f"rmtree {slug}: {str(e)[:200]}")
                _log.warn(
                    "terminal_cleanup_rmtree_failed",
                    packet_id=packet_id,
                    slug=slug,
                    error=str(e)[:200],
                )

        if not wt.exists():
            removed = True
            _log.info(
                "terminal_cleanup_worktree_removed",
                packet_id=packet_id,
                slug=slug,
            )
        return removed
