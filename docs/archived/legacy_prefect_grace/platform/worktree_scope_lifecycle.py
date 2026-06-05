# ############################################################################
# AI_HEADER: worktree_scope_lifecycle
# ROLE: Lifecycle gate connecting worktree isolation and scope validation.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Evaluate packet worktree against scope guard before verifier/reviewer.
# inputs: Packet file, repo root, worktree root, packet ID, attempt, base ref.
# returns: WorktreeScopeLifecycleResult with pass/block status and scope details.
# side_effects: Creates worktree if needed, preserves on block by default.
# emitted_logs: None.
# error_behavior: Fail closed on packet parse, worktree, or scope errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: WorktreeScopeLifecycleResult
#   - function: evaluate_worktree_scope
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from prefect_grace.platform.status_model import DomainStatus
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.scope_guard import validate_scope
from prefect_grace.platform.worktree_manager import WorktreeManager


@dataclass(frozen=True)
class WorktreeScopeLifecycleResult:
    """Result of worktree scope lifecycle evaluation."""
    ok: bool
    packet_id: str
    attempt: int
    worktree_path: str
    branch_name: str
    changed_files: list[str]
    scope_guard: dict[str, Any]
    status: Literal[
        "passed",
        "scope_blocked",
        "worktree_error",
    ]
    blocker_reason: str | None = None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert WorktreeScopeLifecycleResult to JSON-safe dictionary.
    # inputs: None (instance method).
    # returns: dict[str, Any] - JSON-safe dictionary representation.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dictionary."""
        return {
            "ok": self.ok,
            "packet_id": self.packet_id,
            "attempt": self.attempt,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "changed_files": self.changed_files,
            "scope_guard": self.scope_guard,
            "status": self.status,
            "blocker_reason": self.blocker_reason,
        }


# START_FUNCTION_CONTRACT
# name: evaluate_worktree_scope
# purpose: Evaluate packet worktree against scope guard lifecycle gate.
# inputs:
#   packet_file: Path - Path to EXECUTION_PACKET.md.
#   repo_root: Path - Repository root directory.
#   worktree_root: Path - Worktree root directory.
#   project_key: str - Project key for branch naming.
#   packet_id: str - Packet ID.
#   attempt: int - Attempt number.
#   base_ref: str - Base git ref to branch from.
#   keep_on_failure: bool - If True, preserve worktree on block/error (default True).
# returns: WorktreeScopeLifecycleResult - Lifecycle evaluation result.
# side_effects: Creates worktree, may cleanup on success if keep_on_failure=False.
# emitted_logs: None.
# error_behavior: Fail closed - returns worktree_error or scope_blocked on any failure.
# END_FUNCTION_CONTRACT
def evaluate_worktree_scope(
    *,
    packet_file: Path,
    repo_root: Path,
    worktree_root: Path,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    keep_on_failure: bool = True,
) -> WorktreeScopeLifecycleResult:
    """
    Evaluate packet worktree against scope guard lifecycle gate.

    Lifecycle:
    1. Parse packet contract
    2. Create or resolve packet worktree
    3. Collect changed files from worktree
    4. Run scope guard validation
    5. Return passed/scope_blocked/worktree_error

    Fail-closed behavior:
    - Packet parse error -> worktree_error
    - Worktree creation error -> worktree_error
    - Changed file extraction error -> worktree_error
    - Scope guard violation -> scope_blocked
    - Any changed file outside allowed -> scope_blocked
    - Any changed file frozen -> scope_blocked

    Worktree preservation:
    - scope_blocked -> keep worktree (default)
    - worktree_error -> keep worktree if it exists (default)
    - passed -> may cleanup if keep_on_failure=False
    """
    # Parse packet contract
    try:
        parsed = parse_packet_markdown(packet_file, mode="legacy_warn")
    except Exception as e:
        return WorktreeScopeLifecycleResult(
            ok=False,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path="",
            branch_name="",
            changed_files=[],
            scope_guard={},
            status="worktree_error",
            blocker_reason=f"Packet parse failed: {e}",
        )

    # Create worktree manager
    manager = WorktreeManager(
        repo_root=repo_root,
        worktree_root=worktree_root,
        project_key=project_key,
    )

    # Check if worktree already exists
    status = manager.status(packet_id=packet_id, attempt=attempt)

    if status.exists:
        # Worktree already exists, use it
        from prefect_grace.platform.worktree_manager import WorktreeContext
        context = WorktreeContext(
            packet_id=packet_id,
            attempt=attempt,
            repo_root=repo_root,
            worktree_path=status.path,
            branch_name=status.branch_name,
            base_ref=base_ref,
            created=False,
        )
    else:
        # Create new worktree
        try:
            context = manager.create_packet_worktree(
                packet_id=packet_id,
                attempt=attempt,
                base_ref=base_ref,
            )
        except Exception as e:
            return WorktreeScopeLifecycleResult(
                ok=False,
                packet_id=packet_id,
                attempt=attempt,
                worktree_path="",
                branch_name="",
                changed_files=[],
                scope_guard={},
                status="worktree_error",
                blocker_reason=f"Worktree creation failed: {e}",
            )

    # Collect changed files from worktree
    try:
        changed_files = manager.get_changed_files(
            context.worktree_path,
            base_ref=base_ref,
        )
    except Exception as e:
        return WorktreeScopeLifecycleResult(
            ok=False,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path=str(context.worktree_path),
            branch_name=context.branch_name,
            changed_files=[],
            scope_guard={},
            status="worktree_error",
            blocker_reason=f"Changed file extraction failed: {e}",
        )

    # Run scope guard validation
    try:
        scope_result = validate_scope(
            changed_files=changed_files,
            allowed_scope=parsed.allowed_write_scope,
            frozen_scope=parsed.frozen_scope,
            repo_root=repo_root,
        )
    except Exception as e:
        return WorktreeScopeLifecycleResult(
            ok=False,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path=str(context.worktree_path),
            branch_name=context.branch_name,
            changed_files=changed_files,
            scope_guard={},
            status="worktree_error",
            blocker_reason=f"Scope guard validation failed: {e}",
        )

    # Determine lifecycle status
    if scope_result.ok:
        # Scope passed - may cleanup worktree if requested
        if not keep_on_failure:
            try:
                manager.cleanup_worktree(
                    packet_id=packet_id,
                    attempt=attempt,
                    keep_on_failure=False,
                )
            except Exception:
                # Cleanup failure doesn't affect passed status
                pass

        return WorktreeScopeLifecycleResult(
            ok=True,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path=str(context.worktree_path),
            branch_name=context.branch_name,
            changed_files=changed_files,
            scope_guard=scope_result.to_dict(),
            status=DomainStatus.CHECK_PASSED.value,
            blocker_reason=None,
        )
    else:
        # Scope blocked - preserve worktree for inspection
        blocker_parts = []
        if scope_result.frozen_violations:
            blocker_parts.append(f"{len(scope_result.frozen_violations)} frozen violation(s)")
        if scope_result.outside_allowed:
            blocker_parts.append(f"{len(scope_result.outside_allowed)} outside allowed")
        if scope_result.invalid_paths:
            blocker_parts.append(f"{len(scope_result.invalid_paths)} invalid path(s)")

        blocker_reason = "Scope violations: " + ", ".join(blocker_parts) if blocker_parts else "Scope validation failed"

        return WorktreeScopeLifecycleResult(
            ok=False,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path=str(context.worktree_path),
            branch_name=context.branch_name,
            changed_files=changed_files,
            scope_guard=scope_result.to_dict(),
            status=DomainStatus.SCOPE_BLOCKED.value,
            blocker_reason=blocker_reason,
        )
