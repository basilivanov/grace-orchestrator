# ############################################################################
# AI_HEADER: packet_branch_push_gate
# ROLE: Narrow commit and push gate for one accepted packet branch.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan and optionally apply commit/push for one accepted packet worktree branch.
# inputs: Packet path, repo/worktree paths, branch metadata, commit/push requests, and approvals.
# returns: PacketBranchPushGateResult with bounded audit and delegated gate details.
# side_effects: Only when apply flags are present: may delegate commit/push to git_mutation_gate.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for missing approvals or delegated gate blockers.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: PacketBranchPushGateResult
#   - function: run_packet_branch_push_gate
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import subprocess
from typing import Any

from prefect_grace.platform.git_mutation_gate import run_git_mutation_gate
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.scope_guard import validate_scope


MAX_BLOCKERS = 25


@dataclass
class PacketBranchPushGateResult:
    """Bounded packet branch push gate result."""

    packet_id: str
    status: str
    dry_run: bool
    ok: bool = False
    mutations: dict[str, str] = field(default_factory=dict)
    packet_branch: str = ""
    remote: str = ""
    commit_sha: str | None = None
    pushed_ref: str | None = None
    pushed_commit_sha: str | None = None
    changed_files_total: int = 0
    changed_files_sample: list[str] = field(default_factory=list)
    committed_diff_total: int = 0
    committed_diff_sample: list[str] = field(default_factory=list)
    committed_diff_scope: dict[str, Any] = field(default_factory=dict)
    blocker_reason: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    git_gate: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert gate result to a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing bounded audit fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, args: list[str]) -> str:
    result = _run_git(cwd, args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def _initial_result(
    packet_id: str,
    *,
    dry_run: bool,
    remote: str,
    commit: bool,
    push: bool,
) -> PacketBranchPushGateResult:
    planned = "planned" if dry_run else "blocked"
    return PacketBranchPushGateResult(
        packet_id=packet_id,
        status="planned" if dry_run else "blocked",
        dry_run=dry_run,
        remote=remote,
        mutations={
            "commit": planned if commit else "not_requested",
            "push": planned if push else "not_requested",
            "merge": "not_available",
        },
    )


def _add_blocker(result: PacketBranchPushGateResult, code: str, message: str, **extra: Any) -> None:
    if len(result.blockers) < MAX_BLOCKERS:
        result.blockers.append(_block(code, message, **extra))
    if result.blocker_reason is None:
        result.blocker_reason = code


def _copy_from_git_gate(
    result: PacketBranchPushGateResult,
    gate_payload: dict[str, Any],
) -> None:
    result.status = str(gate_payload.get("status") or result.status)
    result.ok = bool(gate_payload.get("ok"))
    result.mutations = dict(gate_payload.get("mutations") or result.mutations)
    result.mutations["merge"] = "not_available"
    result.packet_branch = str(gate_payload.get("packet_branch") or "")
    result.remote = str(gate_payload.get("remote") or result.remote)
    result.commit_sha = gate_payload.get("commit_sha")
    result.pushed_ref = gate_payload.get("pushed_ref")
    result.pushed_commit_sha = gate_payload.get("pushed_commit_sha")
    result.changed_files_total = int(gate_payload.get("changed_files_total") or 0)
    result.changed_files_sample = list(gate_payload.get("changed_files_sample") or [])[:MAX_BLOCKERS]
    result.blocker_reason = gate_payload.get("blocker_reason")
    result.blockers = list(gate_payload.get("blockers") or [])[:MAX_BLOCKERS]
    result.git_gate = {
        "status": gate_payload.get("status"),
        "ok": gate_payload.get("ok"),
        "dry_run": gate_payload.get("dry_run"),
        "packet_branch": gate_payload.get("packet_branch"),
        "remote": gate_payload.get("remote"),
        "mutations": result.mutations,
        "changed_files_total": result.changed_files_total,
        "changed_files_sample": result.changed_files_sample,
        "commit_sha": result.commit_sha,
        "pushed_ref": result.pushed_ref,
        "pushed_commit_sha": result.pushed_commit_sha,
        "blocker_reason": result.blocker_reason,
        "blockers": result.blockers,
    }


def _committed_diff_files(worktree_path: Path, base_ref: str) -> list[str]:
    _git_output(worktree_path, ["merge-base", base_ref, "HEAD"])
    output = _git_output(
        worktree_path,
        ["diff", "--name-only", f"{base_ref}...HEAD", "--"],
    )
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def _validate_push_committed_diff(
    result: PacketBranchPushGateResult,
    *,
    packet: Path,
    repo_root: Path,
    worktree_path: Path,
    base_ref: str,
) -> bool:
    try:
        parsed = parse_packet_markdown(packet)
        diff_files = _committed_diff_files(worktree_path, base_ref)
    except Exception as exc:
        _add_blocker(
            result,
            "committed_diff_unavailable",
            "Push apply requires a readable committed branch diff against base_ref.",
            detail=str(exc),
        )
        return False

    result.committed_diff_total = len(diff_files)
    result.committed_diff_sample = diff_files[:MAX_BLOCKERS]
    if not diff_files:
        _add_blocker(
            result,
            "empty_committed_diff_rejected",
            "Push apply requires a non-empty committed branch diff against base_ref.",
        )
        return False

    scope_result = validate_scope(
        diff_files,
        parsed.allowed_write_scope,
        parsed.frozen_scope,
        repo_root=repo_root,
    )
    result.committed_diff_scope = scope_result.to_dict()
    if not scope_result.ok:
        _add_blocker(
            result,
            "committed_diff_scope_failed",
            "Committed branch diff does not satisfy packet scope.",
        )
        return False
    return True


def _blocked_push_result(result: PacketBranchPushGateResult) -> PacketBranchPushGateResult:
    result.ok = False
    result.status = "blocked"
    if result.mutations.get("push") != "not_requested":
        result.mutations["push"] = "blocked"
    return result


def _run_delegated_gate(
    *,
    packet: Path | str,
    repo_root: Path | str,
    worktree_root: Path | str,
    worktree_path: Path | str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    remote: str,
    dry_run: bool,
    apply: bool,
    commit: bool,
    push: bool,
) -> dict[str, Any]:
    return run_git_mutation_gate(
        packet=packet,
        repo_root=repo_root,
        worktree_root=worktree_root,
        worktree_path=worktree_path,
        project_key=project_key,
        packet_id=packet_id,
        attempt=int(attempt),
        base_ref=base_ref,
        target_branch="",
        remote=remote,
        dry_run=dry_run,
        apply=apply,
        commit=commit,
        push=push,
        merge=False,
        understand_merge=False,
    ).to_dict()


# START_FUNCTION_CONTRACT
# name: run_packet_branch_push_gate
# purpose: Plan or apply commit/push for one accepted packet branch without exposing merge.
# inputs: Packet/worktree metadata, requested commit/push flags, dry-run/apply flags, and approvals.
# returns: PacketBranchPushGateResult with bounded audit fields.
# side_effects: May commit and push only through git_mutation_gate when apply and approvals are present.
# emitted_logs: None.
# error_behavior: Returns blocked result on failed approvals, delegated preconditions, or Git errors.
# END_FUNCTION_CONTRACT
def run_packet_branch_push_gate(
    *,
    packet: Path | str,
    repo_root: Path | str,
    worktree_root: Path | str,
    worktree_path: Path | str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    remote: str = "origin",
    dry_run: bool = False,
    apply: bool = False,
    commit: bool = False,
    push: bool = False,
    approve_commit: bool = False,
    approve_push: bool = False,
) -> PacketBranchPushGateResult:
    dry_run = bool(dry_run or not apply)
    result = _initial_result(packet_id, dry_run=dry_run, remote=remote, commit=commit, push=push)

    if not commit and not push:
        result.ok = True
        return result

    if apply and commit and not approve_commit:
        _add_blocker(
            result,
            "commit_requires_approval",
            "Commit apply requires explicit packet branch commit approval.",
        )
    if apply and push and not approve_push:
        _add_blocker(
            result,
            "push_requires_approval",
            "Push apply requires explicit packet branch push approval.",
        )

    if result.blockers:
        result.ok = False
        result.status = "blocked"
        if commit:
            result.mutations["commit"] = "blocked"
        if push:
            result.mutations["push"] = "blocked"
        return result

    if not apply or not push:
        gate_payload = _run_delegated_gate(
            packet=packet,
            repo_root=repo_root,
            worktree_root=worktree_root,
            worktree_path=worktree_path,
            project_key=project_key,
            packet_id=packet_id,
            attempt=int(attempt),
            base_ref=base_ref,
            remote=remote,
            dry_run=dry_run,
            apply=apply,
            commit=commit,
            push=push,
        )
        _copy_from_git_gate(result, gate_payload)
        return result

    if commit:
        commit_payload = _run_delegated_gate(
            packet=packet,
            repo_root=repo_root,
            worktree_root=worktree_root,
            worktree_path=worktree_path,
            project_key=project_key,
            packet_id=packet_id,
            attempt=int(attempt),
            base_ref=base_ref,
            remote=remote,
            dry_run=False,
            apply=True,
            commit=True,
            push=False,
        )
        _copy_from_git_gate(result, commit_payload)
        result.mutations["push"] = "blocked"
        if not result.ok:
            return result

    if not _validate_push_committed_diff(
        result,
        packet=Path(packet),
        repo_root=Path(repo_root),
        worktree_path=Path(worktree_path),
        base_ref=base_ref,
    ):
        return _blocked_push_result(result)

    push_payload = _run_delegated_gate(
        packet=packet,
        repo_root=repo_root,
        worktree_root=worktree_root,
        worktree_path=worktree_path,
        project_key=project_key,
        packet_id=packet_id,
        attempt=int(attempt),
        base_ref=base_ref,
        remote=remote,
        dry_run=False,
        apply=True,
        commit=False,
        push=True,
    )
    commit_sha = result.commit_sha
    changed_files_total = result.changed_files_total
    changed_files_sample = list(result.changed_files_sample)
    committed_diff_total = result.committed_diff_total
    committed_diff_sample = list(result.committed_diff_sample)
    committed_diff_scope = dict(result.committed_diff_scope)
    _copy_from_git_gate(result, push_payload)
    if commit:
        result.commit_sha = commit_sha
        result.changed_files_total = changed_files_total
        result.changed_files_sample = changed_files_sample
        result.mutations["commit"] = "applied"
    result.committed_diff_total = committed_diff_total
    result.committed_diff_sample = committed_diff_sample
    result.committed_diff_scope = committed_diff_scope
    return result
