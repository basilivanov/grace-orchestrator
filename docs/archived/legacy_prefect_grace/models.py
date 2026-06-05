from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class FeatureStatus(str, Enum):
    DRAFT = "draft"
    ARCHITECT_READY = "architect_ready"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    ACCEPTED = "accepted"
    AWAITING_COMMIT = "awaiting_commit"
    BLOCKED = "blocked"
    PRODUCT_BLOCKED = "product_blocked"
    VERIFICATION_BLOCKED = "verification_blocked"
    PIPELINE_INVALID = "pipeline_invalid"
    ENVIRONMENT_BLOCKED = "environment_blocked"


class PacketStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    CODING = "coding"
    VERIFYING = "verifying"
    REVIEW = "review"
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    ESCALATE_TO_ARCHITECT = "escalate_to_architect"


class ReviewVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    ESCALATE_TO_ARCHITECT = "escalate_to_architect"


class ReasoningProfile(str, Enum):
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class DecisionStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class WaveVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"


class TestVerdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class ObservabilityVerdict(str, Enum):
    CLEAN = "clean"
    DEGRADED_BUT_EXPECTED = "degraded-but-expected"
    UNEXPECTED_DEGRADATION = "unexpected-degradation"
    NO_EVIDENCE_BLOCKER = "no-evidence-blocker"


class FrontendVisualVerdict(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class FeatureRecord:
    feature_id: str
    title: str
    summary: str
    status: FeatureStatus = FeatureStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    feature_dir: str = ""
    business_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status.value,
            "created_at": self.created_at,
            "feature_dir": self.feature_dir,
            "business_context": self.business_context,
        }


@dataclass(frozen=True)
class PacketRecord:
    packet_id: str
    feature_id: str
    wave_id: str
    grace_feature_ref: str
    grace_wave_ref: str
    grace_packet_ref: str
    title: str
    summary: str
    role: str
    reasoning: ReasoningProfile
    status: PacketStatus = PacketStatus.DRAFT
    packet_type: str = "execution"
    write_scope: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    reviewer_gate: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    parent_packet_id: str | None = None
    review_target_packet_id: str | None = None
    verification_profile: dict[str, Any] = field(default_factory=dict)
    execution_hints: dict[str, Any] = field(default_factory=dict)
    packet_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "feature_id": self.feature_id,
            "wave_id": self.wave_id,
            "grace_feature_ref": self.grace_feature_ref,
            "grace_wave_ref": self.grace_wave_ref,
            "grace_packet_ref": self.grace_packet_ref,
            "title": self.title,
            "summary": self.summary,
            "role": self.role,
            "reasoning": self.reasoning.value,
            "status": self.status.value,
            "packet_type": self.packet_type,
            "write_scope": self.write_scope,
            "inputs": self.inputs,
            "acceptance_criteria": self.acceptance_criteria,
            "reviewer_gate": self.reviewer_gate,
            "notes": self.notes,
            "dependencies": self.dependencies,
            "parent_packet_id": self.parent_packet_id,
            "review_target_packet_id": self.review_target_packet_id,
            "verification_profile": self.verification_profile,
            "execution_hints": self.execution_hints,
            "packet_path": self.packet_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ReviewRecord:
    packet_id: str
    verdict: ReviewVerdict
    reasons: list[str]
    feature_id: str = ""
    wave_id: str = ""
    grace_feature_ref: str = ""
    grace_wave_ref: str = ""
    grace_packet_ref: str = ""
    reviewer: str = "reviewer"
    follow_up_action: str = "none"
    review_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "feature_id": self.feature_id,
            "wave_id": self.wave_id,
            "grace_feature_ref": self.grace_feature_ref,
            "grace_wave_ref": self.grace_wave_ref,
            "grace_packet_ref": self.grace_packet_ref,
            "verdict": self.verdict.value,
            "reasons": self.reasons,
            "reviewer": self.reviewer,
            "follow_up_action": self.follow_up_action,
            "review_path": self.review_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    feature_id: str
    source_packet_id: str
    summary: str
    reasons: list[str]
    status: DecisionStatus = DecisionStatus.OPEN
    decision_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "feature_id": self.feature_id,
            "source_packet_id": self.source_packet_id,
            "summary": self.summary,
            "reasons": self.reasons,
            "status": self.status.value,
            "decision_path": self.decision_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WaveReviewRecord:
    feature_id: str
    wave_id: str
    architect_packet_id: str
    verdict: WaveVerdict
    reasons: list[str]
    reviewer: str = "architect"
    review_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "wave_id": self.wave_id,
            "architect_packet_id": self.architect_packet_id,
            "verdict": self.verdict.value,
            "reasons": self.reasons,
            "reviewer": self.reviewer,
            "review_path": self.review_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class VerificationRecord:
    packet_id: str
    test_verdict: TestVerdict
    observability_verdict: ObservabilityVerdict
    frontend_visual_verdict: FrontendVisualVerdict
    commands_run: list[str]
    evidence_paths: list[str]
    blocking_issues: list[str]
    feature_id: str = ""
    wave_id: str = ""
    grace_feature_ref: str = ""
    grace_wave_ref: str = ""
    grace_packet_ref: str = ""
    verification_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "feature_id": self.feature_id,
            "wave_id": self.wave_id,
            "grace_feature_ref": self.grace_feature_ref,
            "grace_wave_ref": self.grace_wave_ref,
            "grace_packet_ref": self.grace_packet_ref,
            "test_verdict": self.test_verdict.value,
            "observability_verdict": self.observability_verdict.value,
            "frontend_visual_verdict": self.frontend_visual_verdict.value,
            "commands_run": self.commands_run,
            "evidence_paths": self.evidence_paths,
            "blocking_issues": self.blocking_issues,
            "verification_path": self.verification_path,
            "created_at": self.created_at,
        }


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "untitled"


def project_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()
