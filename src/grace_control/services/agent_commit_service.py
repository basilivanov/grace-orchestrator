# ############################################################################
# AI_HEADER: agent_commit_service
# ROLE: Encapsulate the agent-commit step (`git add -A` + `git commit` + SHA)
#       inside a worktree. W6 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run the agent-commit step the executor used to do inline. All
#          git subprocess calls live here. Returns "" on any failure.
# inputs: worktree_path, packet_id, attempt_count, timeout_seconds.
# returns: str — the new HEAD SHA, or "" on failure.
# side_effects: Creates a commit in the worktree.
# emitted_logs: agent_commit_add_failed, agent_commit_failed, agent_commit_exception.
# error_behavior: Never raises; returns "" on any failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AgentCommitService
#     methods:
#       - commit
# END_MODULE_MAP

from __future__ import annotations

import subprocess
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent_commit_service")


class AgentCommitService:
    """Encapsulates the agent-commit step: `git add -A` → `git commit` → SHA."""

    # START_FUNCTION_CONTRACT
    # name: commit
    # purpose: Run `git add -A`, then `git commit -m 'agent: ...'`, then
    #          resolve the new HEAD SHA. Logs every failure; never raises.
    # inputs: worktree_path (Path), packet_id (str), attempt_count (int),
    #         timeout_seconds (int, default 10).
    # returns: str — the new HEAD SHA, or "" on failure.
    # side_effects: Creates one commit in the worktree.
    # emitted_logs: agent_commit_add_failed, agent_commit_failed,
    #               agent_worktree_committed, agent_commit_exception.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def commit(
        self,
        worktree_path: Path,
        packet_id: str,
        attempt_count: int,
        timeout_seconds: int = 10,
    ) -> str:
        try:
            add = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(worktree_path),
                capture_output=True, timeout=timeout_seconds,
            )
            if add.returncode != 0:
                _log.warn("agent_commit_add_failed", packet_id=packet_id,
                    stderr=add.stderr.decode("utf-8", "ignore")[:200])
                return ""
            commit = subprocess.run(
                ["git", "commit", "-m",
                 f"agent: {packet_id} attempt {attempt_count}"],
                cwd=str(worktree_path),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            if commit.returncode != 0:
                _log.warn("agent_commit_failed", packet_id=packet_id,
                    stderr=commit.stderr[:200])
                return ""
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_path),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            head_sha = sha.stdout.strip() if sha.returncode == 0 else ""
            _log.debug("agent_worktree_committed", packet_id=packet_id,
                worktree=str(worktree_path), sha=head_sha[:12])
            return head_sha
        except Exception as e:
            _log.warn("agent_commit_exception", packet_id=packet_id, error=str(e)[:200])
            return ""
