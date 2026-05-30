# ############################################################################
# AI_HEADER: worktree_manager
# ROLE: Create, inspect, and clean per-packet git worktrees for safe execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Deterministic worktree management for packet execution isolation.
# inputs: Packet ID, attempt number, base ref, repo root, worktree root.
# returns: WorktreeContext, WorktreeStatus with worktree state and changed files.
# side_effects: Creates/removes git worktrees and branches under worktree_root.
# emitted_logs: None.
# error_behavior: Fail closed on invalid paths, git errors, or unsafe cleanup.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: WorktreeContext
#   - dataclass: WorktreeStatus
#   - class: WorktreeManager
#   - function: _sanitize_path_slug
#   - function: _sanitize_branch_name
#   - function: _run_git
# END_MODULE_MAP

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorktreeContext:
    """Context for a created worktree."""
    packet_id: str
    attempt: int
    repo_root: Path
    worktree_path: Path
    branch_name: str
    base_ref: str
    created: bool


@dataclass(frozen=True)
class WorktreeStatus:
    """Status of a worktree."""
    packet_id: str
    attempt: int | None
    path: Path
    branch_name: str | None
    exists: bool
    dirty: bool
    changed_files: list[str]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert WorktreeStatus to JSON-safe dictionary.
    # inputs: None (instance method).
    # returns: dict[str, Any] - JSON-safe dictionary representation.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dictionary."""
        return {
            "packet_id": self.packet_id,
            "attempt": self.attempt,
            "path": str(self.path),
            "branch_name": self.branch_name,
            "exists": self.exists,
            "dirty": self.dirty,
            "changed_files": self.changed_files,
        }


# START_FUNCTION_CONTRACT
# name: _sanitize_path_slug
# purpose: Sanitize packet ID into path-safe directory name slug.
# inputs:
#   packet_id: str - Packet ID.
# returns: str - Path-safe slug with no path separators or traversal.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if packet_id is absolute, contains traversal, or results in empty slug.
# END_FUNCTION_CONTRACT
def _sanitize_path_slug(packet_id: str) -> str:
    """
    Sanitize packet ID into path-safe directory name slug.

    Rules:
    - Reject absolute paths (starts with /)
    - Reject path traversal (..)
    - Replace path separators with -
    - Replace unsupported characters with -
    - Collapse repeated separators
    - Strip leading/trailing separators
    - Reject empty result
    """
    # Reject absolute paths
    if packet_id.startswith("/"):
        raise ValueError(f"Packet ID cannot be absolute path: {packet_id!r}")

    # Reject path traversal
    if ".." in packet_id:
        raise ValueError(f"Packet ID cannot contain path traversal: {packet_id!r}")

    # Reject empty
    if not packet_id or not packet_id.strip():
        raise ValueError(f"Packet ID cannot be empty: {packet_id!r}")

    # Replace path separators with -
    slug = packet_id.replace("/", "-").replace("\\", "-")

    # Replace unsupported characters with -
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", slug)

    # Collapse repeated separators
    slug = re.sub(r"-+", "-", slug)

    # Strip leading/trailing separators
    slug = slug.strip("-")

    # Reject empty result
    if not slug:
        raise ValueError(f"Packet ID sanitization resulted in empty slug: {packet_id!r}")

    return slug


# START_FUNCTION_CONTRACT
# name: _sanitize_branch_name
# purpose: Sanitize packet ID and project key into valid git branch name.
# inputs:
#   project_key: str - Project key.
#   packet_id: str - Packet ID.
#   attempt: int - Attempt number.
# returns: str - Sanitized branch name in format agent/<project_key>/<packet_id>/attempt-<NNNN>.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if result is empty after sanitization.
# END_FUNCTION_CONTRACT
def _sanitize_branch_name(project_key: str, packet_id: str, attempt: int) -> str:
    """
    Sanitize packet ID and project key into valid git branch name.

    Format: agent/<project_key>/<packet_id>/attempt-<NNNN>

    Rules:
    - Lowercase where safe
    - Replace unsupported characters with -
    - Collapse repeated separators
    - Keep packet ID readable
    - Reject empty result
    """
    # Sanitize project_key
    project_key_clean = re.sub(r"[^a-zA-Z0-9._/-]", "-", project_key)
    project_key_clean = re.sub(r"[-/]+", "-", project_key_clean)
    project_key_clean = project_key_clean.strip("-/")

    # Sanitize packet_id
    packet_id_clean = re.sub(r"[^a-zA-Z0-9._/-]", "-", packet_id)
    packet_id_clean = re.sub(r"[-/]+", "-", packet_id_clean)
    packet_id_clean = packet_id_clean.strip("-/")

    if not project_key_clean or not packet_id_clean:
        raise ValueError(f"Invalid branch name components: project_key={project_key!r}, packet_id={packet_id!r}")

    branch_name = f"agent/{project_key_clean}/{packet_id_clean}/attempt-{attempt:04d}"

    if not branch_name or branch_name == "agent///attempt-":
        raise ValueError(f"Branch name sanitization resulted in empty name: {branch_name!r}")

    return branch_name


# START_FUNCTION_CONTRACT
# name: _run_git
# purpose: Run git command with explicit cwd and capture output.
# inputs:
#   args: list[str] - Git command arguments (without 'git' prefix).
#   cwd: Path - Working directory for git command.
# returns: str - Stdout from git command.
# side_effects: Executes git command.
# emitted_logs: None.
# error_behavior: Raises subprocess.CalledProcessError with command and cwd on failure.
# END_FUNCTION_CONTRACT
def _run_git(args: list[str], cwd: Path) -> str:
    """
    Run git command with explicit cwd and capture output.

    Never uses shell interpolation.
    Includes command and cwd in raised errors.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise subprocess.CalledProcessError(
            e.returncode,
            e.cmd,
            output=e.stdout,
            stderr=f"Git command failed in {cwd}:\n{e.stderr}",
        ) from e


class WorktreeManager:
    """
    Manages git worktrees for packet execution isolation.

    Worktrees are runtime sandboxes, not security boundaries.
    """

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize WorktreeManager with repo and worktree roots.
    # inputs:
    #   repo_root: Path - Repository root directory.
    #   worktree_root: Path - Root directory for worktrees.
    #   project_key: str - Project key for branch naming.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, *, repo_root: Path, worktree_root: Path, project_key: str) -> None:
        self.repo_root = repo_root.resolve()
        self.worktree_root = worktree_root.resolve()
        self.project_key = project_key

    # START_FUNCTION_CONTRACT
    # name: create_packet_worktree
    # purpose: Create a new worktree for packet execution.
    # inputs:
    #   packet_id: str - Packet ID.
    #   attempt: int - Attempt number.
    #   base_ref: str - Base git ref to branch from.
    # returns: WorktreeContext - Context for created worktree.
    # side_effects: Creates git worktree and branch.
    # emitted_logs: None.
    # error_behavior: Raises on git errors or invalid inputs.
    # END_FUNCTION_CONTRACT
    def create_packet_worktree(
        self,
        *,
        packet_id: str,
        attempt: int,
        base_ref: str,
    ) -> WorktreeContext:
        """
        Create a new worktree for packet execution.

        Creates worktree under worktree_root with deterministic branch name.
        Fails closed if packet_id would escape worktree_root.
        """
        # Sanitize packet_id for path-safe directory name
        path_slug = _sanitize_path_slug(packet_id)

        # Sanitize branch name
        branch_name = _sanitize_branch_name(self.project_key, packet_id, attempt)

        # Verify base_ref exists
        _run_git(["rev-parse", "--verify", base_ref], self.repo_root)

        # Determine worktree path using sanitized slug
        worktree_path = self.worktree_root / f"{path_slug}-attempt-{attempt:04d}"

        # Safety check: resolved path must be under worktree_root
        try:
            worktree_path.resolve().relative_to(self.worktree_root.resolve())
        except ValueError:
            raise ValueError(
                f"Worktree path {worktree_path} would escape worktree_root {self.worktree_root}. "
                f"Packet ID: {packet_id!r}"
            )

        # Ensure worktree_root exists
        self.worktree_root.mkdir(parents=True, exist_ok=True)

        # Create worktree
        _run_git(
            ["worktree", "add", "-B", branch_name, str(worktree_path), base_ref],
            self.repo_root,
        )

        return WorktreeContext(
            packet_id=packet_id,
            attempt=attempt,
            repo_root=self.repo_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
            created=True,
        )

    # START_FUNCTION_CONTRACT
    # name: get_changed_files
    # purpose: Extract all changed files in worktree vs base_ref.
    # inputs:
    #   worktree_path: Path - Path to worktree.
    #   base_ref: str - Base ref to compare against.
    # returns: list[str] - Repo-relative POSIX paths of changed files.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises on git errors.
    # END_FUNCTION_CONTRACT
    def get_changed_files(self, worktree_path: Path, *, base_ref: str) -> list[str]:
        """
        Extract all changed files in worktree vs base_ref.

        Includes:
        - Committed changes vs base_ref
        - Staged changes
        - Unstaged changes
        - Untracked files
        """
        changed_files: set[str] = set()

        # Committed changes vs base_ref
        try:
            committed = _run_git(
                ["diff", "--name-only", f"{base_ref}...HEAD"],
                worktree_path,
            )
            if committed:
                changed_files.update(committed.splitlines())
        except subprocess.CalledProcessError:
            # No commits yet or base_ref doesn't exist in worktree
            pass

        # Staged changes
        staged = _run_git(["diff", "--name-only", "--cached"], worktree_path)
        if staged:
            changed_files.update(staged.splitlines())

        # Unstaged changes
        unstaged = _run_git(["diff", "--name-only"], worktree_path)
        if unstaged:
            changed_files.update(unstaged.splitlines())

        # Untracked files
        untracked = _run_git(["ls-files", "--others", "--exclude-standard"], worktree_path)
        if untracked:
            changed_files.update(untracked.splitlines())

        # Return sorted, deduplicated list
        return sorted(changed_files)

    # START_FUNCTION_CONTRACT
    # name: status
    # purpose: Get status of a worktree.
    # inputs:
    #   packet_id: str - Packet ID.
    #   attempt: int - Attempt number.
    # returns: WorktreeStatus - Status of worktree.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns exists=False if worktree doesn't exist.
    # END_FUNCTION_CONTRACT
    def status(self, *, packet_id: str, attempt: int) -> WorktreeStatus:
        """Get status of a worktree."""
        path_slug = _sanitize_path_slug(packet_id)
        worktree_path = self.worktree_root / f"{path_slug}-attempt-{attempt:04d}"
        branch_name = _sanitize_branch_name(self.project_key, packet_id, attempt)

        if not worktree_path.exists():
            return WorktreeStatus(
                packet_id=packet_id,
                attempt=attempt,
                path=worktree_path,
                branch_name=branch_name,
                exists=False,
                dirty=False,
                changed_files=[],
            )

        # Check if dirty
        try:
            status_output = _run_git(["status", "--porcelain"], worktree_path)
            dirty = bool(status_output)
            changed_files = [line.split(maxsplit=1)[1] for line in status_output.splitlines() if line]
        except subprocess.CalledProcessError:
            dirty = False
            changed_files = []

        return WorktreeStatus(
            packet_id=packet_id,
            attempt=attempt,
            path=worktree_path,
            branch_name=branch_name,
            exists=True,
            dirty=dirty,
            changed_files=sorted(changed_files),
        )

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree
    # purpose: Remove worktree and branch.
    # inputs:
    #   packet_id: str - Packet ID.
    #   attempt: int - Attempt number.
    #   keep_on_failure: bool - If True, preserve worktree on failure.
    # returns: WorktreeStatus - Final status after cleanup.
    # side_effects: Removes worktree and deletes branch.
    # emitted_logs: None.
    # error_behavior: Fails closed if path is outside worktree_root.
    # END_FUNCTION_CONTRACT
    def cleanup_worktree(
        self,
        *,
        packet_id: str,
        attempt: int,
        keep_on_failure: bool,
    ) -> WorktreeStatus:
        """
        Remove worktree and branch.

        Safety:
        - Fails closed if path is outside worktree_root
        - Respects keep_on_failure flag
        - Only deletes branches matching manager prefix
        """
        path_slug = _sanitize_path_slug(packet_id)
        worktree_path = self.worktree_root / f"{path_slug}-attempt-{attempt:04d}"
        branch_name = _sanitize_branch_name(self.project_key, packet_id, attempt)

        # Safety check: path must be under worktree_root
        try:
            worktree_path.resolve().relative_to(self.worktree_root.resolve())
        except ValueError:
            raise ValueError(f"Worktree path {worktree_path} is outside worktree_root {self.worktree_root}")

        if not worktree_path.exists():
            return WorktreeStatus(
                packet_id=packet_id,
                attempt=attempt,
                path=worktree_path,
                branch_name=branch_name,
                exists=False,
                dirty=False,
                changed_files=[],
            )

        # Check if worktree has changes
        status_before = self.status(packet_id=packet_id, attempt=attempt)

        if keep_on_failure and (status_before.dirty or status_before.changed_files):
            # Keep worktree
            return status_before

        # Remove worktree
        try:
            _run_git(["worktree", "remove", str(worktree_path)], self.repo_root)
        except subprocess.CalledProcessError as e:
            if keep_on_failure:
                return status_before
            raise

        # Delete branch (only if it matches our prefix)
        if branch_name.startswith("agent/"):
            try:
                _run_git(["branch", "-D", branch_name], self.repo_root)
            except subprocess.CalledProcessError:
                # Branch might not exist or already deleted
                pass

        return WorktreeStatus(
            packet_id=packet_id,
            attempt=attempt,
            path=worktree_path,
            branch_name=branch_name,
            exists=False,
            dirty=False,
            changed_files=[],
        )

    # START_FUNCTION_CONTRACT
    # name: list_active_worktrees
    # purpose: List all active worktrees managed by this manager.
    # inputs: None.
    # returns: list[WorktreeStatus] - List of active worktree statuses.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns empty list on git errors.
    # END_FUNCTION_CONTRACT
    def list_active_worktrees(self) -> list[WorktreeStatus]:
        """List all active worktrees managed by this manager."""
        try:
            output = _run_git(["worktree", "list", "--porcelain"], self.repo_root)
        except subprocess.CalledProcessError:
            return []

        worktrees: list[WorktreeStatus] = []
        current_worktree: dict[str, str] = {}

        for line in output.splitlines():
            if line.startswith("worktree "):
                if current_worktree:
                    # Process previous worktree
                    path = Path(current_worktree.get("worktree", ""))
                    branch = current_worktree.get("branch", "")

                    # Only include worktrees under our worktree_root
                    try:
                        path.resolve().relative_to(self.worktree_root)
                        # Extract packet_id and attempt from path
                        # Format: {packet_id}-attempt-{NNNN}
                        name = path.name
                        if "-attempt-" in name:
                            packet_id = name.rsplit("-attempt-", 1)[0]
                            attempt_str = name.rsplit("-attempt-", 1)[1]
                            try:
                                attempt = int(attempt_str)
                            except ValueError:
                                attempt = None
                        else:
                            packet_id = name
                            attempt = None

                        worktrees.append(WorktreeStatus(
                            packet_id=packet_id,
                            attempt=attempt,
                            path=path,
                            branch_name=branch if branch else None,
                            exists=True,
                            dirty=False,  # Would need to check each worktree
                            changed_files=[],
                        ))
                    except ValueError:
                        # Not under our worktree_root, skip
                        pass

                current_worktree = {"worktree": line.split(maxsplit=1)[1]}
            elif line.startswith("branch "):
                current_worktree["branch"] = line.split(maxsplit=1)[1]

        # Process last worktree
        if current_worktree:
            path = Path(current_worktree.get("worktree", ""))
            branch = current_worktree.get("branch", "")

            try:
                path.resolve().relative_to(self.worktree_root)
                name = path.name
                if "-attempt-" in name:
                    packet_id = name.rsplit("-attempt-", 1)[0]
                    attempt_str = name.rsplit("-attempt-", 1)[1]
                    try:
                        attempt = int(attempt_str)
                    except ValueError:
                        attempt = None
                else:
                    packet_id = name
                    attempt = None

                worktrees.append(WorktreeStatus(
                    packet_id=packet_id,
                    attempt=attempt,
                    path=path,
                    branch_name=branch if branch else None,
                    exists=True,
                    dirty=False,
                    changed_files=[],
                ))
            except ValueError:
                pass

        return worktrees
