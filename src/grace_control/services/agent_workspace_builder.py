#!/usr/bin/env python3
"""Agent workspace builder — creates minimal copy-on-write workspaces for agent runs.

START_MODULE_CONTRACT
purpose: Build a minimal git workspace from a subset of target repo files,
         preserving relative paths so acceptance/scope/patch still work.
         Creates a fresh git repo with only the files needed for a packet task.
inputs: target_root — root of the real target project
        scope_paths — list of target-relative file paths
        workspace_root — where to create the workspace directory
        slug — unique slug for the workspace directory
returns: WorkspaceResult with path, mode, copied_files, base_sha.
side_effects: Creates directories and a git repo on disk.
error_behavior: Raises if target_root doesn't exist; never leaves partial state.
END_MODULE_CONTRACT

START_MODULE_MAP
mapping:
  - class: AgentWorkspaceBuilder
    methods:
      - build_scoped_copy
      - _copy_file
      - _init_minimal_repo
END_MODULE_MAP
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceResult:
    workspace_path: Path
    workspace_mode: str = "scoped_copy"
    target_repo_root: Path | None = None
    copied_files: list[dict[str, str]] = field(default_factory=list)
    omitted_files: list[str] = field(default_factory=list)
    base_sha: str = ""
    commit_semantics: str = "workspace_only"

    def to_dict(self) -> dict:
        return {
            "workspace_path": str(self.workspace_path),
            "workspace_mode": self.workspace_mode,
            "target_repo_root": str(self.target_repo_root) if self.target_repo_root else "",
            "copied_files": self.copied_files,
            "omitted_files": self.omitted_files,
            "base_sha": self.base_sha,
            "commit_semantics": self.commit_semantics,
        }


class AgentWorkspaceBuilder:
    """Create minimal workspaces for agent execution.

    Three modes:
    - scoped_copy: copy only scope files into a fresh git repo (minimal)
    - target_repo_worktree: git worktree from target repo (full project)
    - full_git_worktree: git worktree from orchestrator root (default legacy)
    """

    def __init__(self, target_root: Path | str | None = None):
        self._target_root = Path(target_root).resolve() if target_root else Path.cwd().resolve()
        if not self._target_root.exists():
            raise ValueError(f"target_root does not exist: {target_root}")

    def build_scoped_copy(
        self,
        scope_paths: list[str],
        workspace_root: Path,
        slug: str,
        config_allowlist: list[str] | None = None,
    ) -> WorkspaceResult:
        """Create a minimal git workspace with only the scope files.

        Args:
            scope_paths: Target-relative paths to copy (e.g. ["src/app/main.py"]).
            workspace_root: Root directory for workspaces.
            slug: Unique directory name inside workspace_root.
            config_allowlist: Additional config files to include
                (e.g. ["pyproject.toml", "requirements.txt"]).

        Returns:
            WorkspaceResult with workspace path, copied files mapping, base_sha.

        Raises:
            ValueError: If no files were copied (empty workspace).
        """
        wt_path = (workspace_root / slug).resolve()
        if wt_path.exists():
            shutil.rmtree(wt_path)
        wt_path.mkdir(parents=True, exist_ok=True)

        resolved_target = self._target_root.resolve()
        copied: list[dict[str, str]] = []
        omitted: list[str] = []
        all_rel_paths: list[str] = []

        # Resolve scope paths and copy them preserving relative structure.
        # Paths outside target_root are omitted, not copied.
        for sp in scope_paths:
            src = Path(sp)
            if not src.is_absolute():
                src = resolved_target / sp
            resolved_src = src.resolve()
            try:
                rel = resolved_src.relative_to(resolved_target)
            except ValueError:
                omitted.append(f"outside_target_root:{sp}")
                continue
            if ".." in rel.parts:
                omitted.append(f"unsafe_relative_path:{sp}")
                continue
            if not resolved_src.exists():
                omitted.append(f"file_not_found:{sp}")
                continue
            dst = wt_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and dst.is_file():
                continue  # skip duplicates
            shutil.copy2(resolved_src, dst)
            copied.append({"original": str(rel), "workspace": str(rel)})
            all_rel_paths.append(str(rel))

        # Copy config allowlist files if they exist in target root
        config_files = config_allowlist or []
        for cf in config_files:
            src = resolved_target / cf
            if src.exists() and cf not in all_rel_paths:
                dst = wt_path / cf
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append({"original": cf, "workspace": cf})

        # Fail fast if no files were copied
        if not copied:
            raise ValueError(
                f"no files copied into scoped workspace — "
                f"scope_paths={scope_paths}, config_allowlist={config_allowlist}, "
                f"target_root={resolved_target}, omitted={omitted}"
            )

        # Init minimal git repo
        sha = self._init_minimal_repo(wt_path)

        return WorkspaceResult(
            workspace_path=wt_path,
            workspace_mode="scoped_copy",
            target_repo_root=resolved_target,
            copied_files=copied,
            omitted_files=omitted,
            base_sha=sha,
            commit_semantics="workspace_only",
        )

    def _init_minimal_repo(self, repo_path: Path) -> str:
        """Init a git repo and create an initial commit.

        Returns the commit SHA of the initial commit.
        """
        from grace_control.services.git_service import GitService

        git = GitService()
        git._run(["init", "-q"], repo_path)
        git._run(["config", "user.email", "agent@grace"], repo_path)
        git._run(["config", "user.name", "Grace Agent"], repo_path)
        git._run(["add", "."], repo_path)
        result = git._run(["commit", "-q", "-m", "init"], repo_path)
        # Get the initial commit SHA
        sha_result = git._run(["rev-parse", "HEAD"], repo_path)
        return sha_result.stdout.strip() or ""
