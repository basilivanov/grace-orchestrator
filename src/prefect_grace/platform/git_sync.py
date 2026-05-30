# ############################################################################
# AI_HEADER: git_sync
# ROLE: High-level isolated worktree auto-branching and git-sync logic.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Manage packet auto-branching in worktrees and commit/push upon acceptance.
# inputs: Packet path, repo/worktree roots, project key, packet ID, attempt, base_ref, remote, dry-run/apply flags.
# returns: GitSyncResult with branching details and Git mutation gate outcomes.
# side_effects: Creates Git worktrees and branches, and applies commit/push mutations when accepted.
# emitted_logs: None.
# error_behavior: Fails closed returning GitSyncResult with blockers and ok=False on errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: GitSyncResult
#   - function: run_git_sync
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.git_mutation_gate import run_git_mutation_gate
from prefect_grace.platform.packet_artifact_layout import latest_review, resolve_packet_layout
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.review_artifact_contract import read_review_artifact_status
from prefect_grace.platform.worktree_manager import WorktreeManager


@dataclass
class GitSyncResult:
    """Result of the auto-branching and git-sync operation."""
    ok: bool
    packet_id: str
    status: str
    branch_name: str
    worktree_path: str
    dry_run: bool
    commit_sha: str | None = None
    pushed_ref: str | None = None
    pushed_commit_sha: str | None = None
    review_status: str = "missing"
    blocker_reason: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    git_gate_result: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert GitSyncResult to JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing bounded audit fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _add_blocker(result: GitSyncResult, code: str, message: str, **extra: Any) -> None:
    result.blockers.append(_block(code, message, **extra))
    if result.blocker_reason is None:
        result.blocker_reason = code


# START_FUNCTION_CONTRACT
# name: run_git_sync
# purpose: Isolate packet execution in worktrees, and auto-commit/push upon review acceptance.
# inputs:
#   packet: Path to EXECUTION_PACKET.md.
#   repo_root: Repository root directory.
#   worktree_root: Worktree root directory.
#   project_key: Project identifier.
#   packet_id: str.
#   attempt: int.
#   base_ref: str.
#   remote: str.
#   dry_run: bool.
#   apply: bool.
# returns: GitSyncResult.
# side_effects: Creates worktree and branch if not exists; commits and pushes accepted packets.
# emitted_logs: None.
# error_behavior: Fail-closed; returns ok=False with blockers on exceptions or git errors.
# END_FUNCTION_CONTRACT
def run_git_sync(
    *,
    packet: Path | str,
    repo_root: Path | str,
    worktree_root: Path | str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    remote: str = "origin",
    dry_run: bool = True,
    apply: bool = False,
) -> GitSyncResult:
    packet_path = Path(packet)
    repo = Path(repo_root).resolve()
    worktrees = Path(worktree_root).resolve()
    dry_run = bool(dry_run or not apply)

    result = GitSyncResult(
        ok=False,
        packet_id=packet_id,
        status="planned" if dry_run else "blocked",
        branch_name="",
        worktree_path="",
        dry_run=dry_run,
    )

    # 1. Parse packet and validate basics
    try:
        parsed = parse_packet_markdown(packet_path, mode="legacy_warn")
        if parsed.packet_id != packet_id:
            _add_blocker(result, "packet_id_mismatch", "CLI packet_id does not match EXECUTION_PACKET.md")
            return result
    except Exception as e:
        _add_blocker(result, "packet_parse_failed", f"Failed to parse packet: {e}")
        return result

    # 2. Setup Worktree & Auto-branching
    try:
        manager = WorktreeManager(repo_root=repo, worktree_root=worktrees, project_key=project_key)
        status = manager.status(packet_id=packet_id, attempt=attempt)

        if not status.exists:
            context = manager.create_packet_worktree(
                packet_id=packet_id,
                attempt=attempt,
                base_ref=base_ref,
            )
            result.worktree_path = str(context.worktree_path)
            result.branch_name = context.branch_name
        else:
            result.worktree_path = str(status.path)
            result.branch_name = str(status.branch_name or "")
    except Exception as e:
        _add_blocker(result, "worktree_setup_failed", f"Failed to setup isolated worktree: {e}")
        return result

    # 3. Resolve and read Review status
    try:
        layout = resolve_packet_layout(packet_path.parent)
        latest = latest_review(layout)
        accepted = False
        if latest is not None:
            review_result = read_review_artifact_status(latest, expected_packet_id=packet_id)
            accepted = review_result.ok and review_result.status == "accepted"
            result.review_status = "accepted" if accepted else "not_accepted"
        else:
            result.review_status = "missing"
    except Exception as e:
        _add_blocker(result, "review_read_failed", f"Failed to read review artifact: {e}")
        return result

    # If review is not accepted, we cannot commit/push changes
    if not accepted:
        _add_blocker(
            result,
            "missing_accepted_review",
            f"Sync blocked: packet requires an accepted review (current review status: {result.review_status})"
        )
        return result

    # 4. Check if we have changed files in the worktree
    try:
        changed_files = manager.get_changed_files(Path(result.worktree_path), base_ref=base_ref)
        has_changes = len(changed_files) > 0
    except Exception as e:
        _add_blocker(result, "changed_files_check_failed", f"Failed to check changed files in worktree: {e}")
        return result

    # 5. Git Mutation Gate to safely commit and push accepted changes
    try:
        gate_result = run_git_mutation_gate(
            packet=packet_path,
            repo_root=repo,
            worktree_root=worktrees,
            worktree_path=Path(result.worktree_path),
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            target_branch="",
            remote=remote,
            dry_run=dry_run,
            apply=apply and not dry_run,
            commit=has_changes,
            push=has_changes,
            merge=False,
        )

        result.git_gate_result = gate_result.to_dict()
        result.commit_sha = gate_result.commit_sha
        result.pushed_ref = gate_result.pushed_ref
        result.pushed_commit_sha = gate_result.pushed_commit_sha

        # Propagate blockers from the mutation gate
        if gate_result.blockers:
            for blocker in gate_result.blockers:
                _add_blocker(result, blocker.get("code", "git_gate_blocker"), blocker.get("message", ""))
            result.status = "blocked"
            return result

        result.ok = gate_result.ok
        result.status = gate_result.status
        return result

    except Exception as e:
        _add_blocker(result, "git_sync_failed", f"Git sync mutation gate execution failed: {e}")
        result.status = "failed"
        return result
