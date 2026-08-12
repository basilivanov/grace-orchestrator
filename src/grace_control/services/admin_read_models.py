# ############################################################################
# AI_HEADER: admin_read_models — bounded typed read models for Admin surfaces
# ROLE: Defines the small, stable value objects that cross Admin service read
#       boundaries. The models are infrastructure-free and serialize explicitly
#       back to the existing JSON-safe dictionaries.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide immutable typed models for stable Admin read contracts.
# inputs: Explicit scalar values from Admin read services.
# returns: Frozen slotted dataclasses and their exact legacy dictionary shapes.
# side_effects: None; serialization does not perform I/O or mutate state.
# emitted_logs: None.
# error_behavior: Dataclass construction follows normal Python type semantics;
#                 to_dict returns a new dictionary for every model.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CrossProjectCoverage
#     methods:
#       - to_dict
#   - class: AttentionItem
#     methods:
#       - to_dict
#   - class: ProjectHealthSnapshot
#     methods:
#       - to_dict
#   - class: WorkerSnapshot
#     methods:
#       - to_dict
#   - class: PacketRunSummary
#     methods:
#       - to_dict
#   - class: PipelineStageView
#     methods:
#       - to_dict
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_read_models")


# START_BLOCK_READ_MODELS
@dataclass(frozen=True, slots=True)
class CrossProjectCoverage:
    """The complete coverage shape used by Admin overview diagnostics."""

    projects_total: int
    projects_responded: int
    projects_failed: int
    projects_disabled: int
    projects_partial: int
    partial: bool

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the complete six-field project coverage contract.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe coverage dictionary with exactly six keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "projects_total": self.projects_total,
            "projects_responded": self.projects_responded,
            "projects_failed": self.projects_failed,
            "projects_disabled": self.projects_disabled,
            "projects_partial": self.projects_partial,
            "partial": self.partial,
        }


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One normalized operator-attention row."""

    severity: str
    project_key: str
    project_name: str
    kind: str
    entity_type: str | None
    entity_id: Any | None
    title: str
    reason: str
    timestamp: Any | None
    detail_url: str

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the normalized ten-field attention-row contract.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe attention dictionary with exactly ten keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "project_key": self.project_key,
            "project_name": self.project_name,
            "kind": self.kind,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "title": self.title,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "detail_url": self.detail_url,
        }


@dataclass(frozen=True, slots=True)
class ProjectHealthSnapshot:
    """The Admin system-health snapshot, distinct from lifecycle health."""

    supervisor_alive: bool
    api_alive: bool
    workers_alive: int
    db_ok: bool
    code_sha: str
    version: str

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the existing Admin system-health response shape.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe health dictionary with exactly six keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "supervisor_alive": self.supervisor_alive,
            "api_alive": self.api_alive,
            "workers_alive": self.workers_alive,
            "db_ok": self.db_ok,
            "code_sha": self.code_sha,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class WorkerSnapshot:
    """The six-field Admin overview worker row."""

    id: str
    status: str
    current_packet_id: str | None
    last_heartbeat: str | None
    started_at: str | None
    current_elapsed: int | None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the Admin worker-list response row.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe worker dictionary with exactly six keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "current_packet_id": self.current_packet_id,
            "last_heartbeat": self.last_heartbeat,
            "started_at": self.started_at,
            "current_elapsed": self.current_elapsed,
        }


@dataclass(frozen=True, slots=True)
class PacketRunSummary:
    """The rich run row returned by the Admin packet-runs endpoint."""

    run_id: str
    run_number: int
    worker_id: str
    executor_id: str
    model: str
    status: str
    duration_ms: int
    started_at: str | None
    finished_at: str | None
    elapsed_seconds: int | None
    is_running: bool
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    base_sha: str | None
    integration_base_sha: str | None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the exact rich packet-run summary contract.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe run dictionary with exactly sixteen keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_number": self.run_number,
            "worker_id": self.worker_id,
            "executor_id": self.executor_id,
            "model": self.model,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "is_running": self.is_running,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "base_sha": self.base_sha,
            "integration_base_sha": self.integration_base_sha,
        }


@dataclass(frozen=True, slots=True)
class PipelineStageView:
    """The canonical eight-field operator pipeline stage card."""

    key: str
    label: str
    status: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    meta: str
    target_tab: str

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the canonical pipeline stage-card contract.
    # inputs: None; uses the immutable model fields.
    # returns: A new JSON-safe stage dictionary with exactly eight keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a constructed model.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
            "target_tab": self.target_tab,
        }


# END_BLOCK_READ_MODELS
