# ############################################################################
# AI_HEADER: review_artifact_contract
# ROLE: Parses canonical YAML review artifacts with markdown fallback.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Read bounded review artifact contracts from REVIEWS/review-XXXX.yaml sidecars.
# inputs: Review artifact paths and optional expected packet id.
# returns: Structured validation result with canonical review status.
# side_effects: Reads review artifact files.
# emitted_logs: None.
# error_behavior: Fails closed with ok=False for invalid canonical YAML or unreadable files.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ReviewArtifact
#   - dataclass: ReviewArtifactValidationResult
#   - function: read_review_artifact_status
#   - function: read_review_status
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
import re

import yaml


CANONICAL_REVIEW_STATUSES = {"accepted", "blocked", "rework_required"}
_ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "artifact_type",
    "packet_id",
    "review_id",
    "status",
    "verdict",
    "reviewer",
    "generated_by",
    "reviewed_at",
    "timestamp",
    "summary",
    "notes",
    "blockers",
    "metadata",
}


@dataclass(frozen=True)
class ReviewArtifact:
    packet_id: str | None
    status: str
    reviewer: str | None
    generated_by: str | None
    reviewed_at: str
    source: str
    raw: dict[str, Any]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert review artifact to a JSON-safe dictionary.
    # inputs: none.
    # returns: dict with canonical review artifact fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for valid dataclass values.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "status": self.status,
            "reviewer": self.reviewer,
            "generated_by": self.generated_by,
            "reviewed_at": self.reviewed_at,
            "source": self.source,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True)
class ReviewArtifactValidationResult:
    ok: bool
    status: str | None = None
    artifact: ReviewArtifact | None = None
    path: Path | None = None
    source: str | None = None
    errors: tuple[str, ...] = ()

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert validation result to a JSON-safe dictionary.
    # inputs: none.
    # returns: dict with validation status, artifact path, and errors.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for valid dataclass values.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "path": str(self.path) if self.path else None,
            "source": self.source,
            "errors": list(self.errors),
            "artifact": self.artifact.to_dict() if self.artifact else None,
        }


# START_FUNCTION_CONTRACT
# name: read_review_artifact_status
# purpose: Read canonical YAML review status, falling back to legacy markdown when no YAML exists.
# inputs:
#   path: Path to review-XXXX.md, review-XXXX.yaml, or review-XXXX.yml.
#   expected_packet_id: Optional packet id required to match YAML packet_id when present.
# returns: ReviewArtifactValidationResult with ok/status or fail-closed errors.
# side_effects: Reads review artifact files.
# emitted_logs: None.
# error_behavior: Returns ok=False for missing, unreadable, or invalid artifacts.
# END_FUNCTION_CONTRACT
def read_review_artifact_status(
    path: Path | str,
    *,
    expected_packet_id: str | None = None,
) -> ReviewArtifactValidationResult:
    review_path = Path(path)
    canonical = _canonical_review_path(review_path)
    if canonical is not None:
        return _read_yaml_review(canonical, expected_packet_id=expected_packet_id)
    return _read_legacy_markdown_review(review_path)


# START_FUNCTION_CONTRACT
# name: read_review_status
# purpose: Compatibility helper returning only the parsed review status string.
# inputs:
#   path: Path to review artifact.
#   expected_packet_id: Optional packet id required for canonical YAML.
# returns: Canonical status string, unreadable, invalid, or unknown.
# side_effects: Reads review artifact files.
# emitted_logs: None.
# error_behavior: Converts structured parser failures to stable status strings.
# END_FUNCTION_CONTRACT
def read_review_status(path: Path | str, *, expected_packet_id: str | None = None) -> str:
    result = read_review_artifact_status(path, expected_packet_id=expected_packet_id)
    if result.ok and result.status:
        return result.status
    if any(error == "artifact_unreadable" for error in result.errors):
        return "unreadable"
    if any(error.startswith("missing_") or error.startswith("invalid_") for error in result.errors):
        return "invalid"
    return "unknown"


def _canonical_review_path(path: Path) -> Path | None:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return path
    if suffix == ".md":
        yaml_path = path.with_suffix(".yaml")
        if yaml_path.exists():
            return yaml_path
        yml_path = path.with_suffix(".yml")
        if yml_path.exists():
            return yml_path
    return None


def _read_yaml_review(path: Path, *, expected_packet_id: str | None) -> ReviewArtifactValidationResult:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return ReviewArtifactValidationResult(
            ok=False,
            path=path,
            source="yaml",
            errors=("artifact_unreadable",),
        )

    artifact, errors = _validate_yaml_review(data, expected_packet_id=expected_packet_id)
    if errors or artifact is None:
        return ReviewArtifactValidationResult(
            ok=False,
            path=path,
            source="yaml",
            errors=tuple(errors),
        )
    return ReviewArtifactValidationResult(
        ok=True,
        status=artifact.status,
        artifact=artifact,
        path=path,
        source="yaml",
    )


def _validate_yaml_review(
    data: Any,
    *,
    expected_packet_id: str | None,
) -> tuple[ReviewArtifact | None, list[str]]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["invalid_yaml_document"]

    data = _normalize_yaml_review_scalars(data)

    unknown = sorted(str(key) for key in data if str(key) not in _ALLOWED_TOP_LEVEL_KEYS)
    if unknown:
        errors.append("invalid_unknown_fields")

    if not _json_safe(data):
        errors.append("invalid_non_json_safe_value")

    packet_id = _optional_string(data.get("packet_id"))
    if packet_id and expected_packet_id and packet_id != expected_packet_id:
        errors.append("invalid_packet_id_mismatch")

    status = _normalize_status(data.get("status") if "status" in data else data.get("verdict"))
    if status is None:
        errors.append("missing_or_invalid_verdict")

    reviewer = _optional_string(data.get("reviewer"))
    generated_by = _optional_string(data.get("generated_by"))
    if not reviewer and not generated_by:
        errors.append("missing_reviewer_or_generated_by")

    reviewed_at = _optional_string(data.get("reviewed_at") if "reviewed_at" in data else data.get("timestamp"))
    if not reviewed_at:
        errors.append("missing_reviewed_at_or_timestamp")

    if errors or status is None or reviewed_at is None:
        return None, errors

    artifact = ReviewArtifact(
        packet_id=packet_id,
        status=status,
        reviewer=reviewer,
        generated_by=generated_by,
        reviewed_at=reviewed_at,
        source="yaml",
        raw=dict(data),
    )
    return artifact, []


def _read_legacy_markdown_review(path: Path) -> ReviewArtifactValidationResult:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ReviewArtifactValidationResult(
            ok=False,
            path=path,
            source="markdown",
            errors=("artifact_unreadable",),
        )

    status = _legacy_markdown_status(text)
    if status is None:
        return ReviewArtifactValidationResult(
            ok=False,
            path=path,
            source="markdown",
            errors=("missing_or_invalid_verdict",),
        )

    artifact = ReviewArtifact(
        packet_id=None,
        status=status,
        reviewer=None,
        generated_by="legacy_markdown_fallback",
        reviewed_at="legacy_unknown",
        source="markdown",
        raw={"status": status},
    )
    return ReviewArtifactValidationResult(
        ok=True,
        status=status,
        artifact=artifact,
        path=path,
        source="markdown",
    )


def _legacy_markdown_status(content: str) -> str | None:
    label_match = re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(status|verdict)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+?)\s*$",
        content,
    )
    if label_match:
        status = _normalize_status(label_match.group(2))
        if status:
            return status

    lines = content.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+verdict\b", line.strip(), re.IGNORECASE):
            for candidate in lines[index + 1:index + 8]:
                stripped = candidate.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                return _normalize_status(stripped)
    return None


def _normalize_status(value: Any) -> str | None:
    token = str(value or "").strip().lower()
    token = token.strip("`'\". ")
    token = token.replace("-", "_")
    token = re.sub(r"^[^a-z0-9_]+", "", token)
    if token in {"accepted", "accept"}:
        return "accepted"
    if token in {"blocked", "scope_blocked", "failed"}:
        return "blocked"
    if token in {"rework_required", "rework"}:
        return "rework_required"
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _normalize_yaml_review_scalars(data: dict[Any, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        normalized_key = str(key)
        if normalized_key in {"reviewed_at", "timestamp"}:
            normalized[normalized_key] = _normalize_yaml_timestamp(value)
        else:
            normalized[normalized_key] = value
    return normalized


def _normalize_yaml_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _json_safe(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_safe(item) for key, item in value.items())
    return False
