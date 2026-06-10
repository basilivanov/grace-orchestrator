# ############################################################################
# AI_HEADER: git_service
# ROLE: Thin wrapper around git subprocess — all git ops go through here.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Type-safe git operations. All subprocess calls return GitResult
#          dataclass. No direct subprocess.run in routers/services.
# inputs: Path, command args, timeouts.
# returns: GitResult dataclass with success, stdout, stderr, returncode.
# side_effects: Subprocess to git binary on host.
# emitted_logs: None (caller logs).
# error_behavior: Never raises — all errors in GitResult.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: GitResult
#   - dataclass: GitRepoInfo
#   - class: GitService
# END_MODULE_MAP

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int

    @classmethod
    def from_completed(cls, p: subprocess.CompletedProcess) -> "GitResult":
        return cls(
            success=p.returncode == 0,
            stdout=p.stdout or "",
            stderr=p.stderr or "",
            returncode=p.returncode,
        )


@dataclass
class GitRepoInfo:
    path: Path
    is_git: bool
    current_branch: str
    is_clean: bool


@dataclass
class PreflightResult:
    success: bool
    error: str = ""
    target_repo_root: str = ""
    is_git_repo: bool = False
    working_tree_clean: bool = False
    current_branch: str = ""
    local_head: str = ""
    remote_head: str = ""
    remote_sync: bool = False
    worktree_conflict: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "error": self.error,
            "target_repo_root": self.target_repo_root,
            "is_git_repo": self.is_git_repo,
            "working_tree_clean": self.working_tree_clean,
            "current_branch": self.current_branch,
            "local_head": self.local_head,
            "remote_head": self.remote_head,
            "remote_sync": self.remote_sync,
            "worktree_conflict": self.worktree_conflict,
        }


class GitService:
    """All git operations for GRACE. Subprocess timeout default 60s."""

    DEFAULT_TIMEOUT = 60

    def _run(self, args: list[str], cwd: Path, timeout: int | None = None) -> GitResult:
        try:
            p = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout or self.DEFAULT_TIMEOUT,
                check=False,
            )
            return GitResult.from_completed(p)
        except subprocess.TimeoutExpired as e:
            return GitResult(False, stdout="", stderr=f"git timeout: {e}", returncode=-1)
        except Exception as e:
            return GitResult(False, stdout="", stderr=f"git error: {e}", returncode=-1)

    def validate_repo(self, path: Path) -> GitRepoInfo:
        """Return GitRepoInfo. is_git=False if not a repo."""
        path = path.resolve()
        rev = self._run(["rev-parse", "--is-inside-work-tree"], path)
        if not rev.success or rev.stdout.strip() != "true":
            return GitRepoInfo(path=path, is_git=False, current_branch="", is_clean=False)
        branch = self._run(["rev-parse", "--abbrev-ref", "HEAD"], path)
        status = self._run(["status", "--porcelain", "-uno"], path)
        is_clean = status.success and not status.stdout.strip()
        return GitRepoInfo(
            path=path,
            is_git=True,
            current_branch=branch.stdout.strip() if branch.success else "",
            is_clean=is_clean,
        )

    def run_preflight(
        self,
        target_root: Path,
        *,
        require_clean: bool = True,
        require_sync: bool = False,
        base_branch: str = "main",
        remote: str = "origin",
    ) -> PreflightResult:
        root_str = str(target_root.resolve())
        if not target_root.exists() or not target_root.is_dir():
            return PreflightResult(
                success=False,
                error=f"target_repo_root does not exist or is not a directory: {target_root}",
                target_repo_root=root_str,
            )

        # 1. Check if git repo
        rev = self._run(["rev-parse", "--is-inside-work-tree"], target_root)
        if not rev.success or rev.stdout.strip() != "true":
            return PreflightResult(
                success=False,
                error=f"target_repo_worktree requires execution.target_repo_root / GRACE_TARGET_REPO_ROOT to point to a git repo: {target_root}",
                target_repo_root=root_str,
            )

        is_git = True

        # Get current branch
        br_res = self._run(["branch", "--show-current"], target_root)
        current_branch = br_res.stdout.strip() if br_res.success else ""

        # Get local HEAD
        head_res = self._run(["rev-parse", "HEAD"], target_root)
        local_head = head_res.stdout.strip() if head_res.success else ""

        # 2. Check clean
        status_res = self._run(["status", "--porcelain"], target_root)
        if not status_res.success:
            return PreflightResult(
                success=False,
                error=f"failed to run git status: {status_res.stderr}",
                target_repo_root=root_str,
                is_git_repo=is_git,
                current_branch=current_branch,
                local_head=local_head,
            )

        is_clean = not status_res.stdout.strip()
        if require_clean and not is_clean:
            return PreflightResult(
                success=False,
                error="target repo has uncommitted changes; commit or stash before running target_repo_worktree",
                target_repo_root=root_str,
                is_git_repo=is_git,
                working_tree_clean=False,
                current_branch=current_branch,
                local_head=local_head,
            )

        # 3. Check remote sync
        remote_sync = True
        remote_head = ""
        if require_sync:
            # First, fetch to make sure remote ref is up to date
            self._run(["fetch", remote], target_root)
            remote_ref = f"{remote}/{base_branch or 'main'}"
            remote_res = self._run(["rev-parse", remote_ref], target_root)
            if remote_res.success:
                remote_head = remote_res.stdout.strip()
                if local_head != remote_head:
                    remote_sync = False
                    return PreflightResult(
                        success=False,
                        error=f"target repo local HEAD differs from {remote_ref}; sync or set explicit override before running",
                        target_repo_root=root_str,
                        is_git_repo=is_git,
                        working_tree_clean=is_clean,
                        current_branch=current_branch,
                        local_head=local_head,
                        remote_head=remote_head,
                        remote_sync=False,
                    )
            else:
                remote_sync = False
                return PreflightResult(
                    success=False,
                    error=f"failed to resolve remote ref {remote_ref}",
                    target_repo_root=root_str,
                    is_git_repo=is_git,
                    working_tree_clean=is_clean,
                    current_branch=current_branch,
                    local_head=local_head,
                    remote_sync=False,
                )

        return PreflightResult(
            success=True,
            target_repo_root=root_str,
            is_git_repo=is_git,
            working_tree_clean=is_clean,
            current_branch=current_branch,
            local_head=local_head,
            remote_head=remote_head,
            remote_sync=remote_sync,
        )

    def is_clean(self, path: Path) -> bool:
        r = self._run(["status", "--porcelain"], path)
        return r.success and not r.stdout.strip()

    def fetch(self, repo: Path, remote: str = "origin") -> GitResult:
        return self._run(["fetch", remote], repo)

    def checkout(self, repo: Path, branch: str) -> GitResult:
        return self._run(["checkout", branch], repo)

    def merge(self, repo: Path, branch: str, target_branch: str) -> GitResult:
        """Merge `branch` into current branch (assumed to be target_branch)."""
        return self._run(["merge", "--no-ff", branch, "-m", f"merge: {branch} into {target_branch}"], repo)

    def push(self, repo: Path, remote: str = "origin", branch: str | None = None) -> GitResult:
        args = ["push", remote]
        if branch:
            args.append(branch)
        return self._run(args, repo, timeout=120)

    def current_sha(self, repo: Path) -> str:
        r = self._run(["rev-parse", "HEAD"], repo)
        return r.stdout.strip() if r.success else ""

    def diff_name_only(self, repo: Path, base_ref: str) -> list[str]:
        r = self._run(["diff", "--name-only", base_ref, "HEAD"], repo)
        if not r.success:
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def worktree_add(self, repo: Path, worktree_path: Path, branch: str, base_ref: str = "HEAD") -> GitResult:
        """Create a new git worktree at `worktree_path` on a new `branch` from `base_ref`.

        `worktree_path` must NOT already exist (git refuses to overwrite).
        Returns GitResult; caller should check success.
        """
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        return self._run(
            ["worktree", "add", "-b", branch, str(worktree_path), base_ref],
            repo,
        )

    def worktree_remove(self, repo: Path, worktree_path: Path, *, force: bool = True) -> GitResult:
        """Unregister a worktree from `git worktree list` (P1#7 from post-refactor audit).

        Old code only did `shutil.rmtree()`, leaving stale entries in
        `git worktree list` that tripped later attempts. Use git removal first
        so the metadata is cleared, then filesystem cleanup as a fallback.
        """
        args = ["worktree", "remove", str(worktree_path)]
        if force:
            args.append("--force")
        return self._run(args, repo)

    def worktree_prune(self, repo: Path) -> GitResult:
        """Run `git worktree prune` — clean up stale administrative files."""
        return self._run(["worktree", "prune"], repo)
