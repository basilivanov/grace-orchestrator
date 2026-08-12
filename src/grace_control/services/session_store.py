# ############################################################################
# AI_HEADER: session_store
# ROLE: CRUD for the agent_sessions table. Central registry of LLM sessions
#       for resume/fork across attempts.
#       Implements TZ_SESSION_RESUME.md Phase 1.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Save and query AgentSession records. Provides lookup methods for
#          session resume (find_latest, find_for_fork) and status transitions
#          (mark_completed, mark_failed).
# inputs: SQLAlchemy Session (from get_db()), AgentSession fields.
# returns: AgentSession instances or None; session_ids.
# side_effects: DB inserts and updates in agent_sessions table.
# emitted_logs: session_saved, session_mark_completed, session_mark_failed,
#               session_save_failed.
# error_behavior: Never raises. Logs errors and returns None/False on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SessionStore
#     methods:
#       - save
#       - find_latest
#       - find_for_fork
#       - mark_completed
#       - mark_failed
#       - get_sessions_for_packet
# END_MODULE_MAP

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import AgentSession

_log = GraceLogger("session_store")


def _session_run_status_usable(db: Session, external_id: str) -> bool:
    """Conservative usability check for a stored executor session.

    Returns False (skip resume) when:
    * session external_id is empty;
    * the most recent packet run referencing this session ended with
      exit_code != 0, was timed out, or had a session/auth error in stderr.

    This is intentionally conservative: when we cannot prove the session is
    healthy, we skip it. A stale session id or failed prior run must never be
    resumed blindly. External IDs are provider-owned and are not required to
    use an internal GRACE-specific prefix.

    Layout expected on PacketRun.result_json (TZ §6.5):
      {
        "legacy_result": {
          "exit_code": int | None,
          "stderr": "...",
          "stderr_tail": "...",
          "evidence": {"session_id": "provider-session-id"}
        },
        "diagnostics": {"session_id": "provider-session-id", "stderr_tail": "..."}
      }
    """
    if not external_id:
        return False
    sid = external_id.strip()
    if not sid:
        return False
    # Inspect the most recent packet run that recorded this session id.
    try:
        from grace_control.db.schema import PacketRun
        # Look back through the most recent runs. Limit is small to keep
        # this conservative and cheap; sessions older than ~20 runs are
        # already stale by definition.
        runs = (
            db.query(PacketRun)
            .order_by(PacketRun.run_number.desc())
            .limit(20)
            .all()
        )
        for r in runs:
            rj = r.result_json or {}
            if not isinstance(rj, dict):
                continue
            legacy = rj.get("legacy_result") or {}
            diagnostics = rj.get("diagnostics") or {}
            if not isinstance(legacy, dict):
                legacy = {}
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            # Some adapters store session id under different keys; the
            # actual production path puts it under legacy_result.evidence
            # or top-level diagnostics (after TZ §6.6).
            sid_candidates = [
                legacy.get("evidence", {}).get("session_id") if isinstance(legacy.get("evidence"), dict) else None,
                diagnostics.get("session_id"),
                rj.get("session_id"),
                (rj.get("evidence", {}) or {}).get("session_id") if isinstance(rj.get("evidence"), dict) else None,
            ]
            sid_candidates = [str(s).strip() for s in sid_candidates if s]
            if not sid_candidates:
                continue
            if sid not in sid_candidates:
                continue
            # Found the latest run for this session. Check health.
            if r.status in ("rejected", "failed", "timeout"):
                return False
            # PacketRun has no exit_code column — read from legacy_result.
            ec = legacy.get("exit_code")
            if ec is not None and ec != 0:
                return False
            # Check stderr / stderr_tail from legacy_result AND diagnostics
            # (TZ §6.6 may have moved tails to top-level).
            stderr = legacy.get("stderr") or ""
            stderr_tail = (
                legacy.get("stderr_tail")
                or diagnostics.get("stderr_tail")
                or ""
            )
            for blob in (stderr, stderr_tail):
                if not blob:
                    continue
                if "401" in blob or "403" in blob or "unauthorized" in blob.lower():
                    return False
            return True
        # No matching recent run found — refuse to resume conservatively.
        return False
    except Exception as e:
        _log.warn("session_usability_check_failed",
                  external_id=external_id, reason=str(e))
        return False


class SessionStore:
    """CRUD for the agent_sessions table.

    All methods are idempotent and safe to call on missing DB/table.
    The TZ_SESSION_RESUME.md specifies that callers should detect
    table_missing via sqlite_master before querying.
    """

    def _check_table(self, db: Session) -> bool:
        """Return True if the agent_sessions table exists in the DB.

        Uses a direct query on the current session's connection so it never
        interferes with pending session state (inspect/engine.connect can
        steal the connection from SingletonThreadPool and corrupt the
        session's implicit transaction on in-memory SQLite).
        """
        try:
            from sqlalchemy import text as _text
            db.execute(_text("SELECT 1 FROM agent_sessions LIMIT 0"))
            return True
        except Exception:
            return False

    def save(self, db: Session, *,
             packet_id: str,
             run_id: str | None,
             role: str,
             executor_id: str | None,
             backend: str,
             attempt_number: int,
             external_id: str | None,
             parent_session_id: str | None = None,
             status: str = "active") -> str | None:
        """Persist a session record. Returns the internal session ID.

        All kwargs are passed to AgentSession().
        """
        try:
            ses_id = f"ses_{uuid.uuid4().hex[:12]}"
            record = AgentSession(
                id=ses_id,
                external_id=external_id,
                packet_id=packet_id,
                run_id=run_id,
                role=role,
                executor_id=executor_id,
                backend=backend,
                attempt_number=attempt_number,
                status=status,
                parent_session_id=parent_session_id,
            )
            db.add(record)
            db.flush()
            _log.info("session_saved",
                      session_id=ses_id,
                      packet_id=packet_id,
                      role=role,
                      attempt=attempt_number)
            return ses_id
        except Exception as e:
            _log.warn("session_save_failed",
                      packet_id=packet_id,
                      role=role,
                      reason=str(e))
            return None

    def find_latest(self, db: Session, packet_id: str, role: str,
                    executor_id: str | None = None) -> Optional[AgentSession]:
        """Find the most recent active/completed session for resume.

        Args:
            packet_id: The packet to query.
            role: Agent role ("coder", "architect", etc.).
            executor_id: Optional — if given, only return sessions from
                         the same executor profile (for RETRY_SAME_CODER).
        """
        try:
            q = (
                db.query(AgentSession)
                .filter(
                    AgentSession.packet_id == packet_id,
                    AgentSession.role == role,
                    AgentSession.status.in_(["active", "completed"]),
                )
            )
            if executor_id:
                q = q.filter(AgentSession.executor_id == executor_id)
            q = q.order_by(AgentSession.created_at.desc())
            # Filter out sessions whose latest run failed/timed-out (TZ §6.5).
            # Conservative: if we cannot determine status, skip the session.
            for s in q.all():
                if not _session_run_status_usable(db, s.external_id):
                    _log.info("session_resume_skipped_invalid",
                              packet_id=packet_id,
                              role=role,
                              session_id=s.external_id,
                              reason="latest_run_failed_or_timeout")
                    continue
                return s
            return None
        except Exception as e:
            _log.warn("session_find_latest_failed",
                      packet_id=packet_id,
                      role=role,
                      reason=str(e))
            return None

    def find_for_fork(self, db: Session, packet_id: str,
                      role: str) -> Optional[AgentSession]:
        """Find any completed session for fork (can be different executor_id).

        Used for SWITCH_CODER — the new coder forks a readonly copy
        of the previous coder's session.

        TZ §6.5: skip sessions whose latest run failed/timed-out, same as
        find_latest(). Forking a stale session can cascade the same error
        into the new executor.
        """
        try:
            q = (
                db.query(AgentSession)
                .filter(
                    AgentSession.packet_id == packet_id,
                    AgentSession.role == role,
                    AgentSession.status.in_(["active", "completed"]),
                )
                .order_by(AgentSession.created_at.desc())
            )
            for s in q.all():
                if not _session_run_status_usable(db, s.external_id):
                    _log.info("session_fork_skipped_invalid",
                              packet_id=packet_id,
                              role=role,
                              session_id=s.external_id,
                              reason="latest_run_failed_or_timeout")
                    continue
                return s
            return None
        except Exception as e:
            _log.warn("session_find_for_fork_failed",
                      packet_id=packet_id,
                      role=role,
                      reason=str(e))
            return None

    def mark_completed(self, db: Session, session_id: str) -> bool:
        """Mark a session as completed."""
        try:
            row = db.query(AgentSession).filter(
                AgentSession.id == session_id
            ).first()
            if row is None:
                return False
            row.status = "completed"
            row.finished_at = datetime.now(timezone.utc)
            db.flush()
            _log.info("session_mark_completed", session_id=session_id)
            return True
        except Exception as e:
            _log.warn("session_mark_completed_failed",
                      session_id=session_id,
                      reason=str(e))
            return False

    def mark_failed(self, db: Session, session_id: str) -> bool:
        """Mark a session as failed."""
        try:
            row = db.query(AgentSession).filter(
                AgentSession.id == session_id
            ).first()
            if row is None:
                return False
            row.status = "failed"
            row.finished_at = datetime.now(timezone.utc)
            db.flush()
            _log.info("session_mark_failed", session_id=session_id)
            return True
        except Exception as e:
            _log.warn("session_mark_failed_failed",
                      session_id=session_id,
                      reason=str(e))
            return False

    def get_sessions_for_packet(self, db: Session,
                                packet_id: str) -> dict:
        """Return sessions for a packet with reason.

        Returns dict with keys: sessions (list), reason ("ok" | "table_missing").
        If the agent_sessions table doesn't exist, returns empty list with
        reason="table_missing" (forward-compat for DBs before migration).

        Each session dict: id, external_id, role, executor_id, attempt_number,
        status, parent_session_id, created_at, finished_at, duration_seconds,
        fork_of.
        """
        try:
            if not self._check_table(db):
                return {"sessions": [], "reason": "table_missing"}
            rows = (
                db.query(AgentSession)
                .filter(AgentSession.packet_id == packet_id)
                .order_by(AgentSession.created_at.asc(),
                          AgentSession.attempt_number.asc())
                .all()
            )
            result: list[dict] = []
            for r in rows:
                dur = None
                if r.created_at and r.finished_at:
                    dur = (r.finished_at - r.created_at).total_seconds()
                result.append({
                    "id": r.id,
                    "external_id": r.external_id,
                    "role": r.role,
                    "executor_id": r.executor_id,
                    "attempt_number": r.attempt_number,
                    "status": r.status,
                    "parent_session_id": r.parent_session_id,
                    "fork_of": r.parent_session_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "duration_seconds": dur,
                })
            return {"sessions": result, "reason": "ok"}
        except Exception as e:
            _log.warn("session_get_for_packet_failed",
                      packet_id=packet_id,
                      reason=str(e))
            return {"sessions": [], "reason": f"error: {e}"}
