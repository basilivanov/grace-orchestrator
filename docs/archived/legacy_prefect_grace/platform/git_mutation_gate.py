# ############################################################################
# AI_HEADER: git_mutation_gate
# ROLE: Guarded Git commit, push, and merge mutation gate for packet worktrees.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan and optionally apply bounded Git mutations for one packet worktree.
# inputs: Packet path, repo/worktree paths, branch metadata, requested mutations, and approvals.
# returns: GitMutationGateResult with bounded audit and blocker details.
# side_effects: Only when apply flags are present: may git add/commit/push/ff-merge in supplied repos.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for unsafe paths, invalid evidence, or Git errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: GitMutationGateResult
#   - function: run_git_mutation_gate
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from prefect_grace.platform.artifact_validator import validate_artifact_references
from prefect_grace.platform.evidence_contract import parse_evidence_contract
from prefect_grace.platform.evidence_manifest import parse_evidence_manifest, validate_evidence_manifest
from prefect_grace.platform.packet_artifact_layout import latest_review, resolve_packet_layout
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.review_artifact_contract import read_review_artifact_status
from prefect_grace.platform.scope_guard import validate_scope


MAX_ITEMS = 25
PACKET_BRANCH_RE = re.compile(r"^agent/[^/\s]+/[^/\s]+/attempt-\d{4}$")


@dataclass
class GitMutationGateResult:
    packet_id: str
    status: str
    dry_run: bool
    ok: bool = False
    mutations: dict[str, str] = field(default_factory=dict)
    changed_files_total: int = 0
    changed_files_sample: list[str] = field(default_factory=list)
    allowed_files_sample: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    pushed_ref: str | None = None
    pushed_commit_sha: str | None = None
    merge_sha: str | None = None
    packet_branch: str = ""
    target_branch: str = ""
    remote: str = ""
    blocker_reason: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    scope_guard: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)

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


def _run_git(cwd: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _block(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _git_output(cwd: Path, args: list[str]) -> str:
    result = _run_git(cwd, args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def _is_git_worktree(path: Path) -> bool:
    result = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _current_branch(path: Path) -> str:
    return _git_output(path, ["branch", "--show-current"])


def _head_sha(path: Path) -> str:
    return _git_output(path, ["rev-parse", "HEAD"])


def _porcelain_changed_files(path: Path) -> list[str]:
    result = _run_git(path, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git status failed").strip())
    files: list[str] = []
    entries = [entry for entry in result.stdout.split("\0") if entry]
    skip_next = False
    for entry in entries:
        if skip_next:
            skip_next = False
            continue
        if len(entry) < 4:
            continue
        status = entry[:2]
        path_part = entry[3:]
        if status[0] in {"R", "C"}:
            skip_next = True
        files.append(path_part)
    return sorted(set(files))


def _has_conflict_markers(worktree_path: Path, files: list[str]) -> list[str]:
    markers = []
    for file_name in files:
        path = worktree_path / file_name
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="ignore")
        if "<<<<<<< " in text or "=======" in text or ">>>>>>> " in text:
            markers.append(file_name)
    return markers[:MAX_ITEMS]


def _latest_review(packet_path: Path, *, expected_packet_id: str | None) -> tuple[bool, dict[str, Any]]:
    layout = resolve_packet_layout(packet_path.parent)
    latest = latest_review(layout)
    if latest is None:
        return False, {"present": False, "accepted": False, "path": None}
    review_result = read_review_artifact_status(
        latest,
        expected_packet_id=expected_packet_id,
    )
    accepted = review_result.ok and review_result.status == "accepted"
    return accepted, {
        "present": True,
        "accepted": accepted,
        "path": str(review_result.path or latest),
        "source": review_result.source,
        "errors": list(review_result.errors),
    }


def _latest_evidence(packet_path: Path, contract: Any) -> tuple[bool, dict[str, Any]]:
    evidence_root = packet_path.parent / "EVIDENCE"
    manifests = sorted(evidence_root.glob("attempt-*/evidence_manifest.json"))
    if not manifests:
        return False, {"present": False, "valid": False, "path": None}
    latest = manifests[-1]
    manifest = parse_evidence_manifest(latest)
    contract_validation = validate_evidence_manifest(manifest, contract)
    artifact_validation = validate_artifact_references(manifest, [latest.parent, packet_path.parent.parent.parent])
    valid = contract_validation.ok and artifact_validation.ok
    return valid, {
        "present": True,
        "valid": valid,
        "path": str(latest),
        "contract_ok": contract_validation.ok,
        "artifact_ok": artifact_validation.ok,
        "missing_artifacts": artifact_validation.missing_artifacts[:MAX_ITEMS],
    }


def _expected_branch(project_key: str, packet_id: str, attempt: int) -> str:
    return f"agent/{project_key}/{packet_id}/attempt-{attempt:04d}"


def _initial_result(packet_id: str, *, dry_run: bool, target_branch: str, remote: str) -> GitMutationGateResult:
    return GitMutationGateResult(
        packet_id=packet_id,
        status="planned" if dry_run else "blocked",
        dry_run=dry_run,
        mutations={
            "commit": "not_requested",
            "push": "not_requested",
            "merge": "not_requested",
        },
        target_branch=target_branch,
        remote=remote,
    )


def _add_blocker(result: GitMutationGateResult, code: str, message: str, **extra: Any) -> None:
    result.blockers.append(_block(code, message, **extra))
    if result.blocker_reason is None:
        result.blocker_reason = code


def _mark_requested(result: GitMutationGateResult, *, commit: bool, push: bool, merge: bool, value: str) -> None:
    if commit:
        result.mutations["commit"] = value
    if push:
        result.mutations["push"] = value
    if merge:
        result.mutations["merge"] = value


def _target_clean(repo_root: Path) -> bool:
    return _git_output(repo_root, ["status", "--porcelain=v1"]) == ""


def _apply_commit(worktree_path: Path, packet_id: str, allowed_files: list[str]) -> str:
    _run_git(worktree_path, ["add", "--", *allowed_files], check=True)
    message = f"{packet_id}: apply packet changes"
    result = _run_git(worktree_path, ["commit", "-m", message])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git commit failed").strip())
    return _head_sha(worktree_path)


def _apply_push(worktree_path: Path, remote: str, packet_branch: str) -> tuple[str, str]:
    sha = _head_sha(worktree_path)
    result = _run_git(worktree_path, ["push", remote, f"HEAD:refs/heads/{packet_branch}"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git push failed").strip())
    return f"{remote}/{packet_branch}", sha


def _apply_merge(repo_root: Path, packet_branch: str, target_branch: str) -> str:
    current_branch = _current_branch(repo_root)
    if current_branch != target_branch:
        result = _run_git(repo_root, ["switch", target_branch])
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "git switch failed").strip())
    ancestor = _run_git(repo_root, ["merge-base", "--is-ancestor", target_branch, packet_branch])
    if ancestor.returncode != 0:
        raise RuntimeError("fast-forward merge is not possible")
    result = _run_git(repo_root, ["merge", "--ff-only", packet_branch])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git merge failed").strip())
    return _head_sha(repo_root)


# START_FUNCTION_CONTRACT
# name: run_git_mutation_gate
# purpose: Build and optionally apply a bounded Git mutation plan for one packet worktree.
# inputs: Packet/worktree metadata, requested mutation flags, dry-run/apply flags, and merge approval flag.
# returns: GitMutationGateResult with audit fields and blockers.
# side_effects: May stage/commit/push/ff-merge only when apply and matching mutation flags are set.
# emitted_logs: None.
# error_behavior: Returns blocked result on failed preconditions or Git command errors.
# END_FUNCTION_CONTRACT
def run_git_mutation_gate(
    *,
    packet: Path | str,
    repo_root: Path | str,
    worktree_root: Path | str,
    worktree_path: Path | str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    target_branch: str,
    remote: str = "origin",
    dry_run: bool = False,
    apply: bool = False,
    commit: bool = False,
    push: bool = False,
    merge: bool = False,
    understand_merge: bool = False,
    merge_approved_env: str | None = None,
) -> GitMutationGateResult:
    del base_ref
    packet_path = Path(packet)
    repo = Path(repo_root).resolve()
    worktrees = Path(worktree_root).resolve()
    wt = Path(worktree_path).resolve()
    dry_run = bool(dry_run or not apply)
    result = _initial_result(packet_id, dry_run=dry_run, target_branch=target_branch, remote=remote)
    expected_branch = _expected_branch(project_key, packet_id, int(attempt))
    result.packet_branch = expected_branch

    if not any([commit, push, merge]):
        result.ok = True
        result.status = "planned"
        return result

    _mark_requested(result, commit=commit, push=push, merge=merge, value="planned" if dry_run else "blocked")

    try:
        parsed = parse_packet_markdown(packet_path)
        contract = parse_evidence_contract(parsed)
        if parsed.packet_id != packet_id:
            _add_blocker(result, "packet_id_mismatch", "CLI packet_id does not match EXECUTION_PACKET.md")
        if not wt.exists() or not _is_git_worktree(wt):
            _add_blocker(result, "invalid_worktree", "worktree_path is not an existing Git worktree")
        if wt == repo:
            _add_blocker(result, "main_repo_worktree_rejected", "worktree_path must not be repo_root")
        if not _is_relative_to(wt, worktrees):
            _add_blocker(result, "worktree_outside_root", "worktree_path must be under worktree_root")
        if not PACKET_BRANCH_RE.match(expected_branch):
            _add_blocker(result, "invalid_packet_branch", "Expected packet branch pattern is invalid")

        if not result.blockers:
            branch = _current_branch(wt)
            if branch != expected_branch:
                _add_blocker(result, "packet_branch_mismatch", "Current worktree branch does not match expected packet branch", current_branch=branch)

        changed_files = _porcelain_changed_files(wt) if not result.blockers else []
        result.changed_files_total = len(changed_files)
        result.changed_files_sample = changed_files[:MAX_ITEMS]
        if commit and not changed_files:
            _add_blocker(result, "empty_commit_rejected", "Commit requested but worktree has no changed files")

        scope_result = validate_scope(
            changed_files,
            parsed.allowed_write_scope,
            parsed.frozen_scope,
            repo_root=repo,
        )
        result.scope_guard = scope_result.to_dict()
        result.allowed_files_sample = scope_result.allowed_files[:MAX_ITEMS]
        if changed_files and not scope_result.ok:
            _add_blocker(result, "scope_guard_failed", "Changed files do not satisfy packet scope")

        marker_files = _has_conflict_markers(wt, changed_files)
        if marker_files:
            _add_blocker(result, "conflict_markers_found", "Changed files contain merge conflict markers", files=marker_files)

        evidence_ok, evidence_summary = _latest_evidence(packet_path, contract)
        result.evidence = evidence_summary
        if not evidence_ok:
            _add_blocker(result, "invalid_evidence_manifest", "Required verification evidence is missing or invalid")

        review_ok, review_summary = _latest_review(packet_path, expected_packet_id=parsed.packet_id)
        result.review = review_summary
        if not review_ok:
            _add_blocker(result, "missing_accepted_review", "Latest packet review is missing or not accepted")

        if push and not remote:
            _add_blocker(result, "missing_remote", "Push requested without remote")
        if merge:
            if not target_branch:
                _add_blocker(result, "missing_target_branch", "Merge requested without target branch")
            if not understand_merge:
                _add_blocker(result, "merge_requires_cli_approval", "Merge apply requires --i-understand-merge")
            if (merge_approved_env or os.environ.get("GRACE_GIT_MERGE_APPROVED")) != "1":
                _add_blocker(result, "merge_requires_env_approval", "Merge apply requires GRACE_GIT_MERGE_APPROVED=1")
            if not _target_clean(repo):
                _add_blocker(result, "dirty_target_branch", "Target repository has local changes")

        if result.blockers:
            result.ok = False
            result.status = "blocked"
            _mark_requested(result, commit=commit, push=push, merge=merge, value="blocked")
            return result

        if dry_run:
            result.ok = True
            result.status = "planned"
            _mark_requested(result, commit=commit, push=push, merge=merge, value="planned")
            return result

        if not apply:
            _add_blocker(result, "apply_required", "Mutation requested without --apply")
            result.status = "blocked"
            _mark_requested(result, commit=commit, push=push, merge=merge, value="blocked")
            return result

        if commit:
            result.commit_sha = _apply_commit(wt, packet_id, scope_result.allowed_files)
            result.mutations["commit"] = "applied"
        if push:
            pushed_ref, pushed_sha = _apply_push(wt, remote, expected_branch)
            result.pushed_ref = pushed_ref
            result.pushed_commit_sha = pushed_sha
            result.mutations["push"] = "applied"
        if merge:
            result.merge_sha = _apply_merge(repo, expected_branch, target_branch)
            result.mutations["merge"] = "applied"
        result.ok = True
        result.status = "applied"
        return result
    except Exception as exc:
        _add_blocker(result, "git_mutation_gate_failed", str(exc))
        result.ok = False
        result.status = "blocked"
        _mark_requested(result, commit=commit, push=push, merge=merge, value="blocked")
        return result
