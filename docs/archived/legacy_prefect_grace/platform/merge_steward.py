# ############################################################################
# AI_HEADER: merge_steward
# ROLE: Operator-approved fast-forward merge steward for accepted packet branches.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan and optionally apply operator-approved fast-forward merges for accepted packet branches.
# inputs: Target repo, branch names, evidence/review locations, remote, dry-run/apply flags.
# returns: MergeStewardResult with bounded audit and merge plan.
# side_effects: Only when apply flags are present: may perform fast-forward merge in target repo.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for unsafe conditions or Git errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergePlan
#   - dataclass: MergeStewardResult
#   - function: run_merge_steward
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


MAX_ITEMS = 25
PACKET_BRANCH_RE = re.compile(r"^agent/[^/\s]+/[^/\s]+/attempt-\d{4}$")


@dataclass
class MergePlan:
    """Merge plan with candidates and exclusions."""
    target_branch: str
    target_sha: str | None = None
    candidates_total: int = 0
    candidates_sample: list[str] = field(default_factory=list)
    excluded_total: int = 0
    excluded_sample: list[dict[str, Any]] = field(default_factory=list)
    fast_forward_eligible: bool = False
    all_candidates_accepted: bool = False

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize MergePlan to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with all fields
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MergeStewardResult:
    """Merge steward result with bounded audit."""
    status: str
    dry_run: bool
    ok: bool = False
    plan: MergePlan | None = None
    merged_count: int = 0
    merged_sample: list[str] = field(default_factory=list)
    target_branch_before_sha: str | None = None
    target_branch_after_sha: str | None = None
    blocker_reason: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize MergeStewardResult to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with all fields, plan serialized if present
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.plan:
            result["plan"] = self.plan.to_dict()
        return result


def _run_git(cwd: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, args: list[str]) -> str:
    result = _run_git(cwd, args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def _current_branch(path: Path) -> str:
    return _git_output(path, ["branch", "--show-current"])


def _head_sha(path: Path) -> str:
    return _git_output(path, ["rev-parse", "HEAD"])


def _branch_exists(path: Path, branch: str) -> bool:
    result = _run_git(path, ["rev-parse", "--verify", f"refs/heads/{branch}"])
    return result.returncode == 0


def _is_fast_forward(repo: Path, target_branch: str, source_branch: str) -> bool:
    """Check if source_branch can be fast-forward merged into target_branch."""
    result = _run_git(repo, ["merge-base", "--is-ancestor", target_branch, source_branch])
    return result.returncode == 0


def _target_clean(repo: Path) -> bool:
    return _git_output(repo, ["status", "--porcelain=v1"]) == ""


def _block(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _add_blocker(result: MergeStewardResult, code: str, message: str, **extra: Any) -> None:
    result.blockers.append(_block(code, message, **extra))
    if result.blocker_reason is None:
        result.blocker_reason = code


def _add_warning(result: MergeStewardResult, code: str, message: str, **extra: Any) -> None:
    result.warnings.append(_block(code, message, **extra))


def _latest_review(packet_path: Path, *, expected_packet_id: str | None) -> tuple[bool, dict[str, Any]]:
    """Check if packet has accepted review."""
    layout = resolve_packet_layout(packet_path.parent)
    latest = latest_review(layout)
    if latest is None:
        return False, {"present": False, "accepted": False, "path": None}
    result = read_review_artifact_status(
        latest,
        expected_packet_id=expected_packet_id,
    )
    accepted = result.ok and result.status == "accepted"
    return accepted, {
        "present": True,
        "accepted": accepted,
        "path": str(result.path or latest),
        "source": result.source,
    }


def _latest_evidence(packet_path: Path, contract: Any) -> tuple[bool, dict[str, Any]]:
    """Check if packet has valid evidence."""
    evidence_root = packet_path.parent / "EVIDENCE"
    if not evidence_root.exists():
        return False, {"present": False, "valid": False, "path": None}
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
    }


def _validate_candidate(
    repo: Path,
    packet_branch: str,
    packet_path: Path | None,
) -> tuple[bool, str | None]:
    """Validate a single merge candidate.

    Returns (is_valid, reason_if_invalid).
    """
    if not PACKET_BRANCH_RE.match(packet_branch):
        return False, "invalid_branch_pattern"

    if not _branch_exists(repo, packet_branch):
        return False, "branch_not_found"

    if packet_path is None:
        return False, "packet_path_required"

    if not packet_path.exists():
        return False, "packet_not_found"

    try:
        parsed = parse_packet_markdown(packet_path)
        contract = parse_evidence_contract(parsed)
    except Exception:
        return False, "packet_parse_failed"

    review_ok, _ = _latest_review(packet_path, expected_packet_id=parsed.packet_id)
    if not review_ok:
        return False, "missing_accepted_review"

    evidence_ok, _ = _latest_evidence(packet_path, contract)
    if not evidence_ok:
        return False, "invalid_evidence"

    return True, None


def _build_merge_plan(
    repo: Path,
    target_branch: str,
    packet_branches: list[str],
    packet_paths: dict[str, Path],
) -> MergePlan:
    """Build merge plan with candidates and exclusions."""
    plan = MergePlan(target_branch=target_branch)

    try:
        plan.target_sha = _head_sha(repo)
    except Exception:
        plan.target_sha = None

    candidates = []
    excluded = []

    for branch in packet_branches:
        packet_path = packet_paths.get(branch)
        is_valid, reason = _validate_candidate(repo, branch, packet_path)

        if is_valid:
            # Check fast-forward eligibility
            try:
                if _is_fast_forward(repo, target_branch, branch):
                    candidates.append(branch)
                else:
                    excluded.append({"branch": branch, "reason": "not_fast_forward"})
            except Exception:
                excluded.append({"branch": branch, "reason": "fast_forward_check_failed"})
        else:
            excluded.append({"branch": branch, "reason": reason})

    plan.candidates_total = len(candidates)
    plan.candidates_sample = candidates[:MAX_ITEMS]
    plan.excluded_total = len(excluded)
    plan.excluded_sample = excluded[:MAX_ITEMS]
    plan.fast_forward_eligible = len(candidates) > 0
    plan.all_candidates_accepted = len(candidates) > 0 and len(excluded) == 0

    return plan


def _apply_merge(repo: Path, target_branch: str, source_branch: str) -> str:
    """Apply fast-forward merge."""
    current_branch = _current_branch(repo)
    if current_branch != target_branch:
        result = _run_git(repo, ["switch", target_branch])
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "git switch failed").strip())

    # Verify fast-forward is possible
    if not _is_fast_forward(repo, target_branch, source_branch):
        raise RuntimeError("fast-forward merge is not possible")

    # Perform fast-forward merge
    result = _run_git(repo, ["merge", "--ff-only", source_branch])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git merge failed").strip())

    return _head_sha(repo)


# START_FUNCTION_CONTRACT
# name: run_merge_steward
# purpose: Plan and optionally apply operator-approved fast-forward merges for packet branches.
# inputs: Target repo, branch names, packet paths, remote, dry-run/apply flags, approval flags.
# returns: MergeStewardResult with bounded audit and merge plan.
# side_effects: May perform fast-forward merge only when apply and all approval flags are set.
# emitted_logs: None.
# error_behavior: Returns blocked result on failed preconditions or Git command errors.
# END_FUNCTION_CONTRACT
def run_merge_steward(
    *,
    repo_root: Path | str,
    target_branch: str,
    packet_branches: list[str] | None = None,
    packet_paths: dict[str, Path] | None = None,
    remote: str = "origin",
    dry_run: bool = True,
    apply: bool = False,
    merge: bool = False,
    understand_merge: bool = False,
    merge_approved_env: str | None = None,
) -> MergeStewardResult:
    """Run merge steward to plan or apply packet branch merges.

    Args:
        repo_root: Target repository root
        target_branch: Target branch for merges
        packet_branches: List of packet branch names to merge
        packet_paths: Dict mapping branch names to packet EXECUTION_PACKET.md paths
        remote: Remote name (for validation)
        dry_run: Dry-run mode (default True)
        apply: Allow merge application
        merge: Request merge operation
        understand_merge: CLI approval flag
        merge_approved_env: Environment approval token

    Returns:
        MergeStewardResult with plan and audit
    """
    del remote  # Not used in first implementation

    repo = Path(repo_root).resolve()
    dry_run = bool(dry_run or not apply)
    result = MergeStewardResult(
        status="planned" if dry_run else "blocked",
        dry_run=dry_run,
    )

    # Validate inputs
    if not repo.exists():
        _add_blocker(result, "repo_not_found", "Repository root does not exist")
        return result

    if not target_branch:
        _add_blocker(result, "missing_target_branch", "Target branch is required")
        return result

    if packet_branches is None:
        packet_branches = []

    if packet_paths is None:
        packet_paths = {}

    if not packet_branches:
        _add_warning(result, "no_candidates", "No packet branches provided")
        result.ok = True
        result.status = "planned"
        return result

    # Build merge plan
    try:
        plan = _build_merge_plan(repo, target_branch, packet_branches, packet_paths)
        result.plan = plan
    except Exception as exc:
        _add_blocker(result, "plan_build_failed", str(exc))
        return result

    # Check if any candidates exist
    if plan.candidates_total == 0:
        _add_blocker(result, "no_valid_candidates", "No valid merge candidates found")
        result.status = "blocked"
        return result

    # If dry-run, return plan
    if dry_run:
        result.ok = True
        result.status = "planned"
        return result

    # Apply mode: check approval chain
    if not apply:
        _add_blocker(result, "apply_required", "Merge requested without --apply")
        result.status = "blocked"
        return result

    if not merge:
        _add_blocker(result, "merge_required", "Apply requested without --merge")
        result.status = "blocked"
        return result

    if not understand_merge:
        _add_blocker(result, "merge_requires_cli_approval", "Merge apply requires --i-understand-merge")
        result.status = "blocked"
        return result

    env_token = merge_approved_env or os.environ.get("GRACE_MERGE_STEWARD_APPROVED")
    if env_token != "1":
        _add_blocker(result, "merge_requires_env_approval", "Merge apply requires GRACE_MERGE_STEWARD_APPROVED=1")
        result.status = "blocked"
        return result

    if not _target_clean(repo):
        _add_blocker(result, "dirty_target_branch", "Target repository has local changes")
        result.status = "blocked"
        return result

    if not plan.fast_forward_eligible:
        _add_blocker(result, "no_fast_forward_eligible", "No fast-forward eligible candidates")
        result.status = "blocked"
        return result

    if not plan.all_candidates_accepted:
        _add_blocker(result, "not_all_candidates_accepted", "Some candidates were excluded")
        result.status = "blocked"
        return result

    # Record target branch before state
    try:
        result.target_branch_before_sha = _head_sha(repo)
    except Exception as exc:
        _add_blocker(result, "target_sha_read_failed", str(exc))
        result.status = "blocked"
        return result

    # Apply merges
    merged = []
    for branch in plan.candidates_sample:
        try:
            _apply_merge(repo, target_branch, branch)
            merged.append(branch)
        except Exception as exc:
            _add_blocker(result, "merge_failed", f"Failed to merge {branch}: {exc}")
            result.status = "blocked"
            return result

    result.merged_count = len(merged)
    result.merged_sample = merged[:MAX_ITEMS]

    # Record target branch after state
    try:
        result.target_branch_after_sha = _head_sha(repo)
    except Exception as exc:
        _add_blocker(result, "target_sha_after_read_failed", str(exc))
        result.status = "blocked"
        return result

    result.ok = True
    result.status = "applied"
    return result
