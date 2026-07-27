# ############################################################################
# AI_HEADER: rerun_contracts — Pydantic models & enums for rerun pipeline
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define pure-data contracts for rerun context, pipeline, and persistence.
# inputs: None (defines types only)
# outputs: RerunStage, RerunContext, RerunResult
# invariants:
#   - RerunContext.acceptance_report must have final_verdict key
#   - None fields mean "not applicable" not "missing"
# side_effects: none
# error_behavior: standard Pydantic validation
# observability: none
# non_goals:
#   - Does not import or call adapter/service implementation
#   - Does not query DB
#   - Does not persist anything
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: RerunStage (VERIFIER, REVIEWER)
#   - model: RerunContext
#   - model: RerunResult
# END_MODULE_MAP

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class RerunStage(str, Enum):
    VERIFIER = "verifier"
    REVIEWER = "reviewer"


class RerunContext(BaseModel):
    """Validated context from the previous terminal PacketRun."""

    packet_id: str
    current_run_id: str
    source_run_id: str
    source_run_number: int

    source_worktree_path: str
    source_run_dir: str
    branch_name: str
    commit_sha: str

    acceptance_report: dict
    evidence_verifier_report: dict | None = None
    reviewer_report: dict | None = None


class RerunResult(BaseModel):
    """Single terminal result produced by a rerun pipeline invocation."""

    accepted: bool
    domain_status: str
    reason: str
    duration_ms: int = 0

    source_run_id: str = ""
    worktree_path: str = ""
    branch_name: str = ""
    commit_sha: str = ""

    evidence: dict = {}
    acceptance_report: dict = {}
    evidence_verifier_report: dict | None = None
    reviewer_report: dict | None = None
