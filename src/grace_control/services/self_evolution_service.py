# ############################################################################
# AI_HEADER: self_evolution_service
# ROLE: Business logic for self-evolution sessions — explicit job model,
#       pipeline-based execution, approval gates, rollback metadata.
#       W11 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Own the self-evolution lifecycle — create_session, classify_risk,
#          create_rollback, check_approval. Never spawns subprocesses;
#          always delegates to the architect/packet/acceptance pipeline.
# inputs: SessionCreateRequest → creates DB session + optionally a feature/packet.
# returns: SessionCreateResponse with session_id and status.
# side_effects: DB writes.
# emitted_logs: session_created, risk_classified, approval_required,
#                rollback_recorded.
# error_behavior: Raises ValueError on invalid input; never writes partial data.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SessionCreateRequest
#   - class: SessionCreateResponse
#   - class: SelfEvolutionJob
#   - class: SelfEvolutionDecision
#   - class: SelfEvolutionApproval
#   - class: SelfEvolutionRollbackPlan
#   - class: SelfEvolutionService
# END_MODULE_MAP

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import SelfEvolutionSession

_log = GraceLogger("self_evolution_service")

# ── Risk classification ────────────────────────────────────────────────

RISK_LOW = "low"           # docs-only
RISK_MEDIUM = "medium"     # code changes (approval required)
RISK_HIGH = "high"         # config/security/execution changes (manual)

# ── DTOs ────────────────────────────────────────────────────────────────


@dataclass
class SessionCreateRequest:
    title: str
    description: str = ""
    constraints: dict | None = None
    base_branch: str = "main"
    prompt: str = ""


@dataclass
class SessionCreateResponse:
    session_id: str
    status: str  # "session_created" | "approved" | "requires_approval"
    risk_class: str
    requires_approval: bool = True
    message: str = ""


@dataclass
class SelfEvolutionJob:
    job_id: str
    session_id: str
    packet_id: str
    packet_state: str
    created_at: str = ""


@dataclass
class SelfEvolutionDecision:
    session_id: str
    decision: str  # "approved" | "blocked" | "pending"
    risk_class: str
    reason: str = ""


@dataclass
class SelfEvolutionApproval:
    session_id: str
    approved: bool = False
    approved_by: str = ""
    approved_at: str = ""


@dataclass
class SelfEvolutionRollbackPlan:
    session_id: str
    base_commit: str = ""
    changed_files: list[str] = field(default_factory=list)
    merge_commit: str = ""
    rollback_command: str = ""
    risk_class: str = ""


def _classify_risk(description: str, constraints: dict | None) -> str:
    """Classify risk based on description and constraints.

    - Low: only docs/*, *.md files
    - High: contains config/, security/, execution/ changes
    - Medium: everything else
    """
    if not constraints:
        constraints = {}
    scope = constraints.get("allowed_scope", []) or []
    frozen = constraints.get("frozen_scope", [])

    all_paths = " ".join(scope) + " " + " ".join(frozen) + " " + (description or "")
    low = ".md" in all_paths or "docs/" in all_paths
    high = any(k in all_paths for k in ("config/", "security/", "execution/"))
    if high:
        return RISK_HIGH
    if low and not scope:
        return RISK_LOW
    return RISK_MEDIUM


def _build_rollback(project_root: Path) -> SelfEvolutionRollbackPlan:
    """Build rollback metadata from the git state via WorktreeInspector."""
    from grace_control.services.worktree_inspector import WorktreeInspector
    sha = WorktreeInspector().base_sha(project_root)
    return SelfEvolutionRollbackPlan(
        session_id="",
        base_commit=sha,
        rollback_command=f"git reset --hard {sha}" if sha else "",
        risk_class="",
    )


class SelfEvolutionService:
    """Self-evolution session lifecycle — no subprocess spawning."""

    # START_FUNCTION_CONTRACT
    # name: create_session
    # purpose: Create a SelfEvolutionSession DB row, classify risk, build
    #          rollback plan metadata. Does NOT spawn a worker.
    # inputs: request (SessionCreateRequest), project_root (Path|None).
    # returns: SessionCreateResponse.
    # side_effects: Writes SelfEvolutionSession to DB.
    # emitted_logs: session_created, risk_classified, approval_required.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def create_session(
        self,
        request: SessionCreateRequest,
        project_root: Path | None = None,
    ) -> SessionCreateResponse:
        session_id = f"se-{uuid.uuid4().hex[:12]}"
        risk = _classify_risk(request.description, request.constraints)
        requires_approval = risk != RISK_LOW
        pr = project_root or Path(".")

        rollback = _build_rollback(pr)

        with get_db() as db:
            session = SelfEvolutionSession(
                id=session_id,
                title=request.title,
                description=request.description,
                constraints_json=request.constraints or {},
                status="created",
                risk_class=risk,
                base_branch=request.base_branch,
                requires_approval=requires_approval,
                rollback_plan={
                    "base_commit": rollback.base_commit,
                    "rollback_command": rollback.rollback_command,
                },
                prompt=request.prompt or "",
                created_at=datetime.now(timezone.utc),
            )
            db.add(session)

        _log.info("session_created", session_id=session_id, risk=risk)
        if requires_approval:
            _log.info("approval_required", session_id=session_id, risk=risk)
        else:
            _log.info("risk_classified", session_id=session_id, risk=risk)

        return SessionCreateResponse(
            session_id=session_id,
            status="session_created",
            risk_class=risk,
            requires_approval=requires_approval,
            message=f"Session {session_id} created (risk={risk})",
        )

    # START_FUNCTION_CONTRACT
    # name: commit_after_merge
    # purpose: Record merge commit and changed files in the session rollback plan.
    # inputs: session_id, merge_commit, changed_files.
    # returns: None.
    # side_effects: Updates SelfEvolutionSession row.
    # emitted_logs: rollback_recorded.
    # error_behavior: Never raises; logs warning on missing session.
    # END_FUNCTION_CONTRACT
    def commit_after_merge(
        self,
        session_id: str,
        merge_commit: str,
        changed_files: list[str],
    ) -> None:
        with get_db() as db:
            session = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if not session:
                _log.warn("session_not_found", session_id=session_id)
                return
            rp = dict(session.rollback_plan or {})
            rp["merge_commit"] = merge_commit
            rp["changed_files"] = list(changed_files)
            if merge_commit:
                rp["rollback_command"] = f"git revert --no-commit {merge_commit}"
            session.rollback_plan = rp
            session.status = "merged"
        _log.info("rollback_recorded", session_id=session_id, merge_commit=merge_commit[:12] if merge_commit else "")

    # START_FUNCTION_CONTRACT
    # name: get_rollback
    # purpose: Return the stored rollback plan for a session.
    # inputs: session_id (str).
    # returns: SelfEvolutionRollbackPlan | None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises; returns None if not found.
    # END_FUNCTION_CONTRACT
    def get_rollback(self, session_id: str) -> SelfEvolutionRollbackPlan | None:
        with get_db() as db:
            session = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if not session:
                return None
            rp = session.rollback_plan or {}
            return SelfEvolutionRollbackPlan(
                session_id=session_id,
                base_commit=rp.get("base_commit", ""),
                changed_files=list(rp.get("changed_files") or []),
                merge_commit=rp.get("merge_commit", ""),
                rollback_command=rp.get("rollback_command", ""),
                risk_class=session.risk_class or "",
            )

    # START_FUNCTION_CONTRACT
    # name: classify
    # purpose: Determine if a session is low/medium/high risk.
    # inputs: session_id, description, constraints.
    # returns: str ("low" | "medium" | "high").
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def classify(
        self,
        description: str,
        constraints: dict | None = None,
    ) -> str:
        return _classify_risk(description, constraints)

    # START_FUNCTION_CONTRACT
    # name: list_sessions
    # purpose: List sessions with pagination. Owns the DB query.
    # inputs: limit (int), offset (int).
    # returns: list[dict].
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with get_db() as db:
            sessions = (db.query(SelfEvolutionSession)
                         .order_by(SelfEvolutionSession.created_at.desc())
                         .offset(offset).limit(limit).all())
            return [
                {
                    "id": s.id, "title": s.title, "status": s.status,
                    "risk_class": s.risk_class or "",
                    "requires_approval": s.requires_approval,
                    "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
                }
                for s in sessions
            ]

    # START_FUNCTION_CONTRACT
    # name: get_session
    # purpose: Return full session dict including rollback_plan.
    # inputs: session_id (str).
    # returns: dict | None — None if not found.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_session(self, session_id: str) -> dict | None:
        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if not s:
                return None
            return {
                "id": s.id, "title": s.title, "description": s.description,
                "status": s.status, "risk_class": s.risk_class or "",
                "requires_approval": s.requires_approval,
                "base_branch": s.base_branch or "main",
                "constraints": s.constraints_json or {},
                "rollback_plan": s.rollback_plan or {},
                "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
            }

    # START_FUNCTION_CONTRACT
    # name: cancel_session
    # purpose: Cancel a pending session. Owns the DB mutation.
    # inputs: session_id (str).
    # returns: bool — True if cancelled, raises ValueError if not found or merged.
    # side_effects: Sets session.status = "cancelled".
    # emitted_logs: session_cancelled.
    # error_behavior: Raises ValueError if not found or already merged.
    # END_FUNCTION_CONTRACT
    def cancel_session(self, session_id: str) -> bool:
        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if not s:
                raise ValueError("session not found")
            if s.status == "merged":
                raise ValueError("cannot cancel merged session")
            s.status = "cancelled"
        _log.info("session_cancelled", session_id=session_id)
        return True
