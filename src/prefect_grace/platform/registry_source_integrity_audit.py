# ############################################################################
# AI_HEADER: registry_source_integrity_audit
# ROLE: Read-only integrity audit for accepted runtime registry packet sources.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Audit accepted runtime registry packets against source and evidence artifacts.
# inputs: Project config path, runtime registry records, packet source paths.
# returns: Bounded JSON-safe audit summary and issue list.
# side_effects: Reads registry, source packets, evidence manifests, reviews, and git index.
# emitted_logs: None.
# error_behavior: Fails closed by returning blocking issues for unreadable or invalid state.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: GitTrackingCheck
#   - class: RegistrySourceIntegrityAuditResult
#   - function: audit_registry_source_integrity
# END_MODULE_MAP

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import subprocess

from prefect_grace.platform.artifact_validator import validate_artifact_references
from prefect_grace.platform.evidence_contract import parse_evidence_contract
from prefect_grace.platform.evidence_manifest import (
    parse_evidence_manifest,
    validate_evidence_manifest,
)
from prefect_grace.platform.packet_artifact_layout import (
    latest_evidence_manifest,
    latest_review,
    resolve_packet_layout,
)
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.review_artifact_contract import read_review_status
from prefect_grace.platform.state_store import PacketRegistryStore

BLOCKING_ISSUES = {
    "source_missing",
    "source_untracked",
    "source_hash_mismatch",
    "evidence_manifest_invalid",
    "source_parse_failed",
    "git_tracking_check_failed",
}


@dataclass(frozen=True)
class GitTrackingCheck:
    tracked: bool | None
    error: str | None = None


@dataclass(frozen=True)
class RegistrySourceIntegrityAuditResult:
    ok: bool
    project_key: str
    registry_status_filter: str
    accepted_total: int
    checked_total: int
    blocking_issue_total: int
    warning_issue_total: int
    issue_counts: dict[str, int]
    issues: list[dict[str, Any]] = field(default_factory=list)
    packets: list[dict[str, Any]] = field(default_factory=list)
    max_items: int = 50
    issues_truncated: bool = False
    packets_truncated: bool = False

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert audit result to a bounded JSON-safe dictionary.
    # inputs: none.
    # returns: dict containing audit summary, bounded issues, and bounded packet summaries.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for normal dataclass values.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "registry_status_filter": self.registry_status_filter,
            "accepted_total": self.accepted_total,
            "checked_total": self.checked_total,
            "blocking_issue_total": self.blocking_issue_total,
            "warning_issue_total": self.warning_issue_total,
            "issue_counts": dict(self.issue_counts),
            "issues": list(self.issues),
            "issues_truncated": self.issues_truncated,
            "packets": list(self.packets),
            "packets_truncated": self.packets_truncated,
            "max_items": self.max_items,
        }


# START_FUNCTION_CONTRACT
# name: default_git_tracking_checker
# purpose: Check whether a source packet file is tracked in git.
# inputs:
#   repo_root: repository root path.
#   source_path: source packet file path.
# returns: GitTrackingCheck with tracked true, false, or unknown error.
# side_effects: Runs git ls-files read-only subprocess.
# emitted_logs: None.
# error_behavior: Returns tracked=None with error on git failures.
# END_FUNCTION_CONTRACT
def default_git_tracking_checker(repo_root: Path, source_path: Path) -> GitTrackingCheck:
    try:
        rel = source_path.resolve().relative_to(repo_root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        return GitTrackingCheck(tracked=None, error=f"source_not_under_repo: {exc}")

    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", str(rel)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return GitTrackingCheck(tracked=None, error=str(exc))

    if completed.returncode == 0:
        return GitTrackingCheck(tracked=True)
    if completed.returncode == 1:
        return GitTrackingCheck(tracked=False)
    stderr = completed.stderr.strip() or completed.stdout.strip()
    return GitTrackingCheck(tracked=None, error=stderr or f"git exited {completed.returncode}")


# START_FUNCTION_CONTRACT
# name: audit_registry_source_integrity
# purpose: Audit accepted runtime registry packets for source and evidence integrity.
# inputs:
#   project_config: optional project.yaml path.
#   max_items: maximum issues and packet summaries to return.
#   registry_status: registry status to audit, defaults to accepted.
#   git_tracking_checker: injectable read-only git tracking helper.
# returns: RegistrySourceIntegrityAuditResult.
# side_effects: Reads registry, source packets, reviews, evidence manifests, and git index.
# emitted_logs: None.
# error_behavior: Returns blocking issues for invalid source/evidence/git states.
# END_FUNCTION_CONTRACT
def audit_registry_source_integrity(
    *,
    project_config: Path | str | None = None,
    max_items: int = 50,
    registry_status: str = "accepted",
    git_tracking_checker: Callable[[Path, Path], GitTrackingCheck] | None = None,
) -> RegistrySourceIntegrityAuditResult:
    adapter = load_project_adapter(project_config)
    repo_root = Path(adapter.repo_root).resolve()
    registry = PacketRegistryStore(Path(adapter.runtime_state_root) / "state")
    checker = git_tracking_checker or default_git_tracking_checker
    bounded_max = max(1, int(max_items))

    records = [
        record
        for record in registry.list_packets(adapter.project_key)
        if str(record.get("registry_status") or record.get("status") or "").lower() == registry_status
    ]

    all_issues: list[dict[str, Any]] = []
    packet_summaries: list[dict[str, Any]] = []

    for record in sorted(records, key=lambda item: str(item.get("packet_id") or "")):
        packet_summary, packet_issues = _audit_record(
            record=record,
            repo_root=repo_root,
            checker=checker,
        )
        packet_summaries.append(packet_summary)
        all_issues.extend(packet_issues)

    counts = Counter(str(issue.get("code")) for issue in all_issues)
    blocking_total = sum(1 for issue in all_issues if issue.get("severity") == "blocking")
    warning_total = sum(1 for issue in all_issues if issue.get("severity") == "warning")
    return RegistrySourceIntegrityAuditResult(
        ok=blocking_total == 0,
        project_key=adapter.project_key,
        registry_status_filter=registry_status,
        accepted_total=len(records),
        checked_total=len(records),
        blocking_issue_total=blocking_total,
        warning_issue_total=warning_total,
        issue_counts=dict(sorted(counts.items())),
        issues=all_issues[:bounded_max],
        packets=packet_summaries[:bounded_max],
        max_items=bounded_max,
        issues_truncated=len(all_issues) > bounded_max,
        packets_truncated=len(packet_summaries) > bounded_max,
    )


def _audit_record(
    *,
    record: dict[str, Any],
    repo_root: Path,
    checker: Callable[[Path, Path], GitTrackingCheck],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    packet_id = str(record.get("packet_id") or "")
    registry_status = str(record.get("registry_status") or record.get("status") or "")
    registry_path = str(record.get("source_path") or record.get("path") or "")
    issues: list[dict[str, Any]] = []

    source_path = _resolve_registry_path(repo_root, registry_path)
    source_file, packet_dir, source_path_error = _resolve_source_file(repo_root, source_path)
    summary: dict[str, Any] = {
        "packet_id": packet_id,
        "registry_status": registry_status,
        "path": str(record.get("path") or "") or None,
        "source_path": str(record.get("source_path") or record.get("path") or "") or None,
        "source_exists": None,
        "source_tracked_by_git": None,
        "source_hash_matches_current_source": None,
        "latest_evidence_manifest_path": None,
        "latest_evidence_manifest_valid": None,
        "latest_review_path": None,
        "latest_review_status": None,
    }

    if source_path_error:
        issues.append(_issue("source_parse_failed", "blocking", packet_id, source_path_error))
        return summary, issues

    if source_file is None or packet_dir is None or not source_file.exists():
        summary["source_exists"] = False
        issues.append(_issue("source_missing", "blocking", packet_id, f"Source packet not found: {source_path}"))
        return summary, issues

    summary["source_exists"] = True

    git_check = checker(repo_root, source_file)
    summary["source_tracked_by_git"] = git_check.tracked
    if git_check.tracked is False:
        issues.append(_issue("source_untracked", "blocking", packet_id, "Source packet is not tracked by git"))
    elif git_check.tracked is None:
        issues.append(_issue(
            "git_tracking_check_failed",
            "blocking",
            packet_id,
            git_check.error or "Git tracking check failed",
        ))

    parsed = None
    try:
        parsed = parse_packet_markdown(source_file, mode="strict")
        expected_hash = str(record.get("source_hash") or "")
        summary["source_hash_matches_current_source"] = bool(expected_hash) and expected_hash == parsed.source_hash
        if not expected_hash or expected_hash != parsed.source_hash:
            issues.append(_issue(
                "source_hash_mismatch",
                "blocking",
                packet_id,
                "Registry source_hash does not match current source packet hash",
            ))
    except Exception as exc:
        summary["source_hash_matches_current_source"] = False
        issues.append(_issue("source_parse_failed", "blocking", packet_id, str(exc)))

    layout = resolve_packet_layout(packet_dir)
    review_path = latest_review(layout)
    if review_path:
        summary["latest_review_path"] = _display_path(review_path, repo_root)
        summary["latest_review_status"] = read_review_status(
            review_path,
            expected_packet_id=packet_id,
        )

    manifest_path = latest_evidence_manifest(layout)
    if manifest_path:
        summary["latest_evidence_manifest_path"] = _display_path(manifest_path, repo_root)
        valid, message = _validate_latest_manifest(
            source_file=source_file,
            packet_dir=packet_dir,
            manifest_path=manifest_path,
            parsed_packet=parsed,
            repo_root=repo_root,
        )
        summary["latest_evidence_manifest_valid"] = valid
        if not valid:
            issues.append(_issue("evidence_manifest_invalid", "blocking", packet_id, message))
    elif layout.evidence_dir.exists():
        summary["latest_evidence_manifest_valid"] = False
        issues.append(_issue(
            "evidence_manifest_missing",
            "blocking",
            packet_id,
            "EVIDENCE directory exists but no latest attempt evidence_manifest.json was found",
        ))
    else:
        summary["latest_evidence_manifest_valid"] = False
        issues.append(_issue(
            "evidence_manifest_missing",
            "warning",
            packet_id,
            "No EVIDENCE directory exists for this accepted packet",
        ))

    return summary, issues


def _resolve_registry_path(repo_root: Path, registry_path: str) -> Path:
    if not registry_path:
        return repo_root
    candidate = Path(registry_path)
    return candidate if candidate.is_absolute() else repo_root / candidate


def _resolve_source_file(repo_root: Path, source_path: Path) -> tuple[Path | None, Path | None, str | None]:
    try:
        resolved = source_path.resolve()
        resolved.relative_to(repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, None, f"Source path is outside repo root or unreadable: {source_path} ({exc})"

    if resolved.is_dir():
        source_file = resolved / "EXECUTION_PACKET.md"
        return source_file, resolved, None
    return resolved, resolved.parent, None


def _validate_latest_manifest(
    *,
    source_file: Path,
    packet_dir: Path,
    manifest_path: Path,
    parsed_packet: Any,
    repo_root: Path,
) -> tuple[bool, str]:
    try:
        packet = parsed_packet or parse_packet_markdown(source_file, mode="strict")
        contract = parse_evidence_contract(packet)
        manifest = parse_evidence_manifest(manifest_path)
        contract_validation = validate_evidence_manifest(
            manifest,
            contract,
            artifact_roots=[manifest_path.parent, packet_dir, repo_root],
        )
        artifact_validation = validate_artifact_references(
            manifest,
            [manifest_path.parent, packet_dir, repo_root],
        )
    except Exception as exc:
        return False, str(exc)

    if contract_validation.ok and artifact_validation.ok:
        return True, "valid"

    messages = []
    for error in contract_validation.errors[:5]:
        messages.append(str(error.get("code") or error.get("message") or error))
    if artifact_validation.missing_artifacts:
        messages.append("missing_artifacts")
    return False, ", ".join(messages) or "evidence manifest validation failed"


def _issue(code: str, severity: str, packet_id: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "packet_id": packet_id,
        "message": message,
    }


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except (OSError, RuntimeError, ValueError):
        return str(path)
