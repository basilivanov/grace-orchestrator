# ############################################################################
# AI_HEADER: maintenance_service
# ROLE: Read-only disk snapshot + manual cleanup actions for the admin UI.
#       Implements TZ_RETENTION_POLICY.md Phase 3.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a maintenance snapshot (disk usage + branches + worktrees)
#          and expose manual cleanup actions for terminal-state packets.
# inputs: state_root, worktree_root, project_root (Path).
# returns: MaintenanceSnapshot dataclass; dicts for UI.
# side_effects: filesystem rm of worktree dirs; `git branch -D` for stale refs.
# emitted_logs: maintenance_cleanup_done, maintenance_cleanup_failed.
# error_behavior: Never raises. Errors collected in result.errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: BranchInfo
#   - dataclass: WorktreeEntry
#   - dataclass: MaintenanceSnapshot
#   - class: MaintenanceService
# END_MODULE_MAP

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.size_calculator import (
    DiskSnapshot,
    SizeCalculator,
    fmt_size,
)

_log = GraceLogger("maintenance_service")


# Terminal packet states (per state_machine.TERMINAL_STATES).
# REJECTED is included here for admin manual cleanup, even though it is
# technically still in the state machine flow. MERGED is handled by the
# auto-cleanup on merge; FAILED / BLOCKED_FINAL / CANCELLED are terminal.
_TERMINAL_LIKE: frozenset[str] = frozenset({
    "merged",
    "rejected",
    "failed",
    "blocked",
    "blocked_final",
    "cancelled",
})


@dataclass
class BranchInfo:
    """A git branch reference (typically an agent/* attempt branch)."""
    name: str
    is_agent_branch: bool
    is_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_agent_branch": self.is_agent_branch,
            "is_current": self.is_current,
        }


@dataclass
class WorktreeEntry:
    """A worktree dir in `.grace/worktrees/`, mapped to a packet."""
    slug: str
    path: str
    size_bytes: int
    packet_state: str | None  # None if unknown (packet not in DB)
    is_stale: bool            # True if packet is in terminal-like state

    @property
    def size_human(self) -> str:
        return fmt_size(self.size_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "packet_state": self.packet_state,
            "is_stale": self.is_stale,
        }


@dataclass
class MaintenanceSnapshot:
    """Top-level snapshot of disk + branch + worktree state."""
    disk: DiskSnapshot
    branches: list[BranchInfo] = field(default_factory=list)
    worktrees: list[WorktreeEntry] = field(default_factory=list)
    taken_at: str = ""
    git_available: bool = False
    git_root: str | None = None

    @property
    def stale_worktree_count(self) -> int:
        return sum(1 for w in self.worktrees if w.is_stale)

    @property
    def stale_worktree_total_bytes(self) -> int:
        return sum(w.size_bytes for w in self.worktrees if w.is_stale)

    @property
    def stale_worktree_total_human(self) -> str:
        return fmt_size(self.stale_worktree_total_bytes)

    @property
    def agent_branch_count(self) -> int:
        return sum(1 for b in self.branches if b.is_agent_branch)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disk": self.disk.to_dict(),
            "branches": [b.to_dict() for b in self.branches],
            "worktrees": [w.to_dict() for w in self.worktrees],
            "taken_at": self.taken_at,
            "git_available": self.git_available,
            "git_root": self.git_root,
            "stale_worktree_count": self.stale_worktree_count,
            "stale_worktree_total_bytes": self.stale_worktree_total_bytes,
            "stale_worktree_total_human": self.stale_worktree_total_human,
            "agent_branch_count": self.agent_branch_count,
        }


@dataclass
class CleanupResult:
    """Result of a manual cleanup action."""
    worktrees_removed: list[str] = field(default_factory=list)
    branches_deleted: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def bytes_freed_human(self) -> str:
        return fmt_size(self.bytes_freed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktrees_removed": self.worktrees_removed,
            "branches_deleted": self.branches_deleted,
            "bytes_freed": self.bytes_freed,
            "bytes_freed_human": self.bytes_freed_human,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "ok": not self.errors,
        }


class MaintenanceService:
    """Read-only snapshot + manual cleanup for the maintenance tab.

    All cleanup actions are best-effort and never raise. Errors are
    collected in CleanupResult.errors and logged.

    The service does NOT auto-clean anything (TZ_RETENTION_POLICY.md).
    The admin must click "Clean up" buttons to free disk space.
    """

    def __init__(self, state_root: Path | str | None = None,
                 worktree_root: Path | str | None = None,
                 project_root: Path | str | None = None):
        self.state_root = Path(state_root) if state_root else None
        self.worktree_root = Path(worktree_root) if worktree_root else None
        self.project_root = Path(project_root) if project_root else None
        self.size_calculator = SizeCalculator(
            state_root=state_root, worktree_root=worktree_root,
        )

    # ── snapshot ────────────────────────────────────────────────────────

    def snapshot(self, packet_states: dict[str, str] | None = None) -> MaintenanceSnapshot:
        """Build a full snapshot of disk + git state.

        Args:
            packet_states: Optional mapping of packet_id → state string.
                          Used to determine which worktrees are stale.
                          If a worktree slug has no entry in this map,
                          the worktree is treated as unknown (not stale).
        """
        disk = self.size_calculator.disk_snapshot()
        branches = self._list_branches()
        worktrees = self._list_worktrees(packet_states or {})
        git_root = self._find_git_root()
        return MaintenanceSnapshot(
            disk=disk,
            branches=branches,
            worktrees=worktrees,
            taken_at=datetime.now(timezone.utc).isoformat(),
            git_available=git_root is not None,
            git_root=str(git_root) if git_root else None,
        )

    def _list_branches(self) -> list[BranchInfo]:
        """List all git branches in the project root (best-effort)."""
        if not self.project_root:
            return []
        try:
            result = subprocess.run(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            _log.warn("maintenance_branches_list_failed", reason=str(e))
            return []

        if result.returncode != 0:
            return []
        branches: list[BranchInfo] = []
        current = ""
        try:
            cur = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            )
            if cur.returncode == 0:
                current = cur.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        for line in result.stdout.splitlines():
            name = line.strip().lstrip("* ").strip()
            if not name:
                continue
            branches.append(BranchInfo(
                name=name,
                is_agent_branch=name.startswith("agent/"),
                is_current=(name == current),
            ))
        return branches

    def _list_worktrees(self, packet_states: dict[str, str]) -> list[WorktreeEntry]:
        """List all worktree dirs with size + state info."""
        if not self.worktree_root or not self.worktree_root.exists():
            return []
        entries: list[WorktreeEntry] = []
        for path in sorted(self.worktree_root.iterdir()):
            if not path.is_dir():
                continue
            slug = path.name
            size = self.size_calculator.du(path)
            # Worktree slugs are "<pkt_id>-attempt-NNNN" but packet_states
            # uses "<pkt_id>" as the key. Extract the packet_id for lookup.
            packet_id = slug.rsplit("-attempt-", 1)[0] if "-attempt-" in slug else slug
            state = packet_states.get(packet_id)
            is_stale = state in _TERMINAL_LIKE
            entries.append(WorktreeEntry(
                slug=slug,
                path=str(path.resolve()),
                size_bytes=size,
                packet_state=state,
                is_stale=is_stale,
            ))
        return entries

    def _find_git_root(self) -> Path | None:
        """Find the git repo root via `git rev-parse --show-toplevel`."""
        if not self.project_root:
            return None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    # ── cleanup actions ────────────────────────────────────────────────

    def cleanup_worktree(self, slug: str, dry_run: bool = False) -> CleanupResult:
        """Remove a worktree dir + its git branch (if any)."""
        result = CleanupResult(dry_run=dry_run)
        if not self.worktree_root:
            result.errors.append("worktree_root not configured")
            return result
        path = self.worktree_root / slug
        if not path.exists():
            result.errors.append(f"worktree not found: {slug}")
            return result
        size_before = self.size_calculator.du(path)
        if dry_run:
            result.worktrees_removed.append(slug)
            result.bytes_freed = size_before
            return result
        # Use git worktree remove first, then prune stale metadata
        from grace_control.services.git_service import GitService
        git = GitService()
        repo_root = self._find_git_root() or self.project_root
        if repo_root:
            rm_result = git.worktree_remove(repo_root, path, force=True)
            if not rm_result.success:
                # Fallback to filesystem removal if git fails
                try:
                    shutil.rmtree(path)
                except OSError as e:
                    result.errors.append(f"rmtree {slug}: {e}")
                    return result
            # Prune stale git worktree metadata
            git.worktree_prune(repo_root)
        else:
            try:
                shutil.rmtree(path)
            except OSError as e:
                result.errors.append(f"rmtree {slug}: {e}")
                return result
        result.worktrees_removed.append(slug)
        result.bytes_freed = size_before
        # Also delete the matching agent branch, if any
        branch = f"agent/{slug}"
        if self._branch_exists(branch):
            ok, err = self._delete_branch(branch)
            if ok:
                result.branches_deleted.append(branch)
            else:
                result.errors.append(f"branch -D {branch}: {err}")
        _log.info("maintenance_worktree_removed",
                  slug=slug, size_freed=size_before, dry_run=dry_run)
        return result

    def cleanup_branch(self, branch_name: str, dry_run: bool = False) -> CleanupResult:
        """Delete a single git branch."""
        result = CleanupResult(dry_run=dry_run)
        if not self._branch_exists(branch_name):
            result.errors.append(f"branch not found: {branch_name}")
            return result
        if dry_run:
            result.branches_deleted.append(branch_name)
            return result
        ok, err = self._delete_branch(branch_name)
        if ok:
            result.branches_deleted.append(branch_name)
        else:
            result.errors.append(f"branch -D {branch_name}: {err}")
        return result

    def cleanup_stale_worktrees(self, packet_states: dict[str, str] | None = None,
                                dry_run: bool = False) -> CleanupResult:
        """Remove worktrees for all terminal-like-state packets."""
        result = CleanupResult(dry_run=dry_run)
        snapshot = self.snapshot(packet_states=packet_states or {})
        for w in snapshot.worktrees:
            if not w.is_stale:
                continue
            sub = self.cleanup_worktree(w.slug, dry_run=dry_run)
            result.worktrees_removed.extend(sub.worktrees_removed)
            result.branches_deleted.extend(sub.branches_deleted)
            result.bytes_freed += sub.bytes_freed
            result.errors.extend(sub.errors)
        return result

    def cleanup_stale_branches(self, keep_for_slugs: set[str] | None = None,
                                dry_run: bool = False) -> CleanupResult:
        """Delete agent/* branches that have no live worktree.

        Args:
            keep_for_slugs: Set of packet slugs whose worktree still exists
                           (i.e. branches to KEEP). Any agent/<slug> branch
                           whose slug is not in this set will be deleted.
            dry_run: If True, only report what would be deleted.
        """
        result = CleanupResult(dry_run=dry_run)
        keep_for_slugs = keep_for_slugs or set()
        snapshot = self.snapshot()
        live_slugs = {w.slug for w in snapshot.worktrees}
        for b in snapshot.branches:
            if not b.is_agent_branch:
                continue
            if b.is_current:
                continue
            # Extract slug from "agent/<slug>-attempt-NNNN" or "agent/<slug>"
            slug = b.name[len("agent/"):]
            # Strip attempt suffix if present
            if "-attempt-" in slug:
                slug = slug.rsplit("-attempt-", 1)[0]
            if slug in live_slugs and slug in keep_for_slugs:
                continue
            sub = self.cleanup_branch(b.name, dry_run=dry_run)
            result.branches_deleted.extend(sub.branches_deleted)
            result.errors.extend(sub.errors)
        return result

    # ── git helpers ─────────────────────────────────────────────────────

    def _branch_exists(self, branch_name: str) -> bool:
        if not self.project_root:
            return False
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def _delete_branch(self, branch_name: str) -> tuple[bool, str]:
        if not self.project_root:
            return False, "no project_root"
        try:
            r = subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                return True, ""
            return False, r.stderr.strip() or f"exit {r.returncode}"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            return False, str(e)
