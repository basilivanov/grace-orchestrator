# ############################################################################
# AI_HEADER: worktree_inspector
# ROLE: Read-only inspection of an agent's worktree. W6 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md. The executor
#       no longer shells out to git directly; it asks this service.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Answer the four worktree questions the executor needs: is_git,
#          has_changes, base_sha, changed_files. All git subprocess calls
#          live here.
# inputs: Path to a worktree; optional project root for base_sha; optional
#         allowed_write_scope fallback for has_changes.
# returns: Plain dicts / bools / paths. Never raises.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Swallows all git errors and returns False / "" / [].
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: WorktreeInspector
#     methods:
#       - is_git_worktree
#       - base_sha
#       - has_changes
#       - collect_changed_files
#       - inspect
# END_MODULE_MAP

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitService

_log = GraceLogger("worktree_inspector")


class WorktreeInspector:
    """Inspect a worktree after an agent run: is_git, has_changes, base_sha."""

    def __init__(self, git: GitService | None = None) -> None:
        self._git = git or GitService()

    # START_FUNCTION_CONTRACT
    # name: is_git_worktree
    # purpose: Return True iff `worktree_path` is inside a git worktree.
    # inputs: worktree_path (Path).
    # returns: bool.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Swallows all git errors; returns False.
    # END_FUNCTION_CONTRACT
    def is_git_worktree(self, worktree_path: Path) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(worktree_path),
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0 and r.stdout.strip() == "true"
        except Exception:
            return False

    # START_FUNCTION_CONTRACT
    # name: base_sha
    # purpose: Resolve `base_ref` (default HEAD) in `project_root` to a SHA.
    # inputs: project_root (Path), base_ref (str, default "HEAD").
    # returns: str — empty string on failure.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Swallows all git errors; returns "".
    # END_FUNCTION_CONTRACT
    def base_sha(self, project_root: Path, base_ref: str = "HEAD") -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", base_ref],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    # START_FUNCTION_CONTRACT
    # name: has_changes
    # purpose: Decide whether the worktree produced any changes.
    # inputs: worktree_path (Path), allowed_write_scope (list[str] | None).
    # returns: bool.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Swallows all git errors; falls through to scope check.
    # END_FUNCTION_CONTRACT
    def has_changes(
        self,
        worktree_path: Path,
        allowed_write_scope: list[str] | None = None,
    ) -> bool:
        # 1. `git status --porcelain` is the source of truth.
        try:
            sr = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_path),
                capture_output=True, text=True, timeout=5,
            )
            if sr.returncode == 0 and sr.stdout.strip():
                return True
        except Exception:
            pass

        # 2. Fallback: scope-existence check on each allowed_write_scope pattern.
        for pattern in (allowed_write_scope or []):
            scope_path = worktree_path / pattern
            if scope_path.exists() and scope_path.is_file():
                return True
            if scope_path.exists() and scope_path.is_dir():
                if list(scope_path.iterdir()):
                    return True
            if pattern.endswith("/") or pattern.endswith("/**"):
                stripped = pattern.rstrip("/").rstrip("*").rstrip("/")
                scope_dir = worktree_path / stripped
                if scope_dir.exists() and scope_dir.is_dir() and list(scope_dir.iterdir()):
                    return True
        return False

    # START_FUNCTION_CONTRACT
    # name: collect_changed_files
    # purpose: Return a de-duplicated list of paths that changed in the
    #          worktree (tracked modifications + untracked, exclude-standard).
    # inputs: worktree_root (Path).
    # returns: list[Path] — empty on failure.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Swallows all git errors; returns [].
    # END_FUNCTION_CONTRACT
    def collect_changed_files(self, worktree_root: Path) -> list[Path]:
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=str(worktree_root), capture_output=True, text=True, timeout=10,
            )
            modified = [p.strip() for p in r.stdout.splitlines() if p.strip()]
            r = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=str(worktree_root), capture_output=True, text=True, timeout=10,
            )
            untracked = [p.strip() for p in r.stdout.splitlines() if p.strip()]
            out = [worktree_root / p for p in set(modified + untracked)]
            return [p for p in out if p.exists()]
        except Exception:
            return []

    # START_FUNCTION_CONTRACT
    # name: inspect
    # purpose: One-shot aggregate of the worktree's inspectable state.
    # inputs: worktree_path (Path), project_root (Path | None), base_ref
    #         (str, default "HEAD"), allowed_write_scope (list[str] | None).
    # returns: dict with keys {exists, is_git, has_changes, base_sha, changed_files}.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def inspect(
        self,
        worktree_path: Path,
        project_root: Path | None = None,
        base_ref: str = "HEAD",
        allowed_write_scope: list[str] | None = None,
    ) -> dict[str, Any]:
        exists = worktree_path.exists()
        return {
            "exists": exists,
            "is_git": self.is_git_worktree(worktree_path) if exists else False,
            "has_changes": (
                self.has_changes(worktree_path, allowed_write_scope) if exists else False
            ),
            "base_sha": self.base_sha(project_root, base_ref) if project_root else "",
            "changed_files": [
                str(p) for p in self.collect_changed_files(worktree_path)
            ] if exists else [],
        }
