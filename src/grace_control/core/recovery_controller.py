# ############################################################################
# AI_HEADER: recovery_controller
# ROLE: Live RecoveryController — builds FailureSignal from DB, classifies,
#       decides, persists, applies safe actions, emits events.
# Phase 3 of TZ-017 escalation policy.
# ############################################################################

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grace_control.core.feature_recovery import (
    FailureClass,
    FailureSignal,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    classify_failure,
    decide_recovery,
)
from grace_control.core.state_machine import PacketStateMachine
from grace_control.core.structured_logger import GraceLogger, get_trace_id

_log = GraceLogger("recovery_controller")


class RecoveryController:

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._enabled = os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED", "false").lower() == "true"

    async def evaluate(self, packet_id: str, allow_apply: bool = False, trace_id: str | None = None) -> RecoveryDecision:
        _log.info("evaluate_start",
            packet_id=packet_id,
            allow_apply=allow_apply,
            trace_id=trace_id,
        )
        signal = self.build_signal(packet_id)
        policy = RecoveryPolicy()
        fc = classify_failure(signal)
        decision = decide_recovery(signal, policy)

        db_decision_id = self._persist_decision(packet_id, decision, signal)
        self._emit_recovery_events(packet_id, signal, decision, trace_id=trace_id)

        if allow_apply and self._enabled:
            await self._apply_decision(packet_id, decision)

        decision.audit_payload["decision_id"] = db_decision_id

        _log.info("recovery_decision_applied",
            packet_id=packet_id,
            action=decision.action.value,
            failure_class=decision.failure_class.value,
            reason=decision.reason or "",
            next_executor_hint=decision.next_executor_hint or "",
            allow_apply=allow_apply,
        )
        return decision

    def build_signal(self, packet_id: str) -> FailureSignal:
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketRun

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet not found: {packet_id}")

            runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
                PacketRun.run_number.desc()
            ).limit(10).all()

            if not runs:
                raise ValueError(f"No runs for packet: {packet_id}")

            # Eagerly read all needed fields inside the session
            p_feature_id = packet.feature_id
            p_id = packet.id
            p_state = packet.state
            p_profile = packet.acceptance_profile
            p_attempt = packet.attempt_count

            latest = runs[0]
            result = dict(latest.result_json or {})

            legacy = result.get("legacy_result", {})
            if isinstance(legacy, dict):
                legacy = dict(legacy)
            else:
                legacy = {}
            acc = result.get("acceptance_report", {})
            if isinstance(acc, dict):
                acc = dict(acc)
            else:
                acc = {}
            ev = result.get("evidence_verifier_report", {})
            if isinstance(ev, dict):
                ev = dict(ev)
            else:
                ev = {}
            rv = result.get("reviewer_report", {})
            if isinstance(rv, dict):
                rv = dict(rv)
            else:
                rv = {}

            executor_ids = []
            prev_ids = []
            coder_count = 0
            verifier_reject = 0
            reviewer_reject = 0
            merge_count = 0
            architect_repairs = 0

            for run in runs:
                r = dict(run.result_json or {})
                exec_id = r.get("executor_id", "")
                if exec_id and exec_id not in executor_ids:
                    executor_ids.append(exec_id)
                prev_ids.append(exec_id)
                if run.status in ("rejected", "failed"):
                    coder_count += 1
                if "verifier" in (r.get("domain_status") or ""):
                    verifier_reject += 1
                if "reviewer" in (r.get("domain_status") or ""):
                    reviewer_reject += 1
                if "merge" in (r.get("domain_status") or ""):
                    merge_count += 1
                if "architect" in (r.get("domain_status") or ""):
                    architect_repairs += 1

        _log.info("build_signal",
            packet_id=packet_id,
            runs_count=len(runs),
            coder_attempt_count=coder_count,
            executor_ids=executor_ids,
            verifier_rejects=verifier_reject,
            acceptance_verdict=acc.get("final_verdict", ""),
        )

        return FailureSignal(
            feature_id=p_feature_id,
            packet_id=p_id,
            packet_state=p_state,
            domain_status=legacy.get("domain_status", ""),
            reason=result.get("reason", ""),
            acceptance_verdict=acc.get("final_verdict", ""),
            evidence_verifier_verdict=ev.get("verdict", ""),
            reviewer_verdict=rv.get("verdict", ""),
            merge_error=result.get("merge_error", ""),
            acceptance_profile=p_profile,
            attempt_count=p_attempt,
            coder_attempt_count=coder_count,
            architect_repair_count=architect_repairs,
            verifier_reject_count=verifier_reject,
            reviewer_reject_count=reviewer_reject,
            merge_attempt_count=merge_count,
            current_executor_id=prev_ids[-1] if prev_ids else None,
            previous_executor_ids=prev_ids,
        )

    def _persist_decision(self, packet_id: str, decision: RecoveryDecision, signal: FailureSignal) -> str:
        import uuid
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketRun

        decision_id = f"recd-{uuid.uuid4().hex[:12]}"
        decision_dict = decision.model_dump()
        decision_dict["decision_id"] = decision_id

        with get_db() as db:
            runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
                PacketRun.run_number.desc()
            ).limit(5).all()
            for run in runs:
                rj = run.result_json or {}
                rj["recovery"] = decision_dict
                run.result_json = rj
            db.flush()
        return decision_id

    def _emit_recovery_events(self, packet_id: str, signal: FailureSignal, decision: RecoveryDecision,
                                trace_id: str | None = None):
        from grace_control.core.event_recorder import record_event

        record_event("recovery_classified", "packet", packet_id, {
            "failure_class": decision.failure_class.value,
            "signal": signal.model_dump(),
        }, trace_id=trace_id)

        action_event_map = {
            RecoveryAction.RETRY_SAME_CODER: "recovery_retry_same_coder",
            RecoveryAction.SWITCH_CODER: "recovery_switch_coder",
            RecoveryAction.RETURN_TO_ARCHITECT: "recovery_return_to_architect",
            RecoveryAction.ESCALATE_ARCHITECT: "recovery_escalate_architect",
            RecoveryAction.RETRY_VERIFIER: "recovery_retry_verifier",
            RecoveryAction.RETRY_REVIEWER: "recovery_retry_reviewer",
            RecoveryAction.RETRY_MERGE: "recovery_retry_merge",
            RecoveryAction.BLOCK_FEATURE: "recovery_block_feature",
            RecoveryAction.NO_ACTION: "recovery_no_action",
        }
        event_type = action_event_map.get(decision.action, "recovery_no_action")
        record_event(event_type, "packet", packet_id, {
            "action": decision.action.value,
            "reason": decision.reason,
            "next_executor_hint": decision.next_executor_hint,
        }, trace_id=trace_id)

        # Create StageRun and emit stage_returned for recovery loops
        from_stage = "verifier"
        if signal.reviewer_verdict in ("REWORK_TO_CODER", "RETURN_TO_ARCHITECT", "rework_required") or (
            decision.action == RecoveryAction.RETRY_REVIEWER
        ):
            from_stage = "reviewer"
        elif decision.action == RecoveryAction.RETRY_MERGE:
            from_stage = "merge"

        to_stage = None
        if decision.action in (RecoveryAction.RETRY_SAME_CODER, RecoveryAction.SWITCH_CODER):
            to_stage = "coder"
        elif decision.action == RecoveryAction.RETURN_TO_ARCHITECT:
            to_stage = "architect"
        elif decision.action == RecoveryAction.RETRY_VERIFIER:
            to_stage = "verifier"
        elif decision.action == RecoveryAction.RETRY_REVIEWER:
            to_stage = "reviewer"
        elif decision.action == RecoveryAction.RETRY_MERGE:
            to_stage = "merge"

        if to_stage:
            from grace_control.core.stage_instrumentation import create_for_return
            create_for_return(
                packet_id=packet_id,
                from_stage=from_stage,
                to_stage=to_stage,
                reason=decision.reason or "",
                trace_id=trace_id,
            )

    async def _apply_decision(self, packet_id: str, decision: RecoveryDecision):
        method_map = {
            RecoveryAction.RETRY_SAME_CODER: self._apply_retry_same_coder,
            RecoveryAction.SWITCH_CODER: self._apply_switch_coder,
            RecoveryAction.RETURN_TO_ARCHITECT: self._apply_return_to_architect,
            RecoveryAction.ESCALATE_ARCHITECT: self._apply_block_feature,
            RecoveryAction.RETRY_VERIFIER: self._apply_retry_verifier,
            RecoveryAction.RETRY_REVIEWER: self._apply_retry_reviewer,
            RecoveryAction.RETRY_MERGE: self._apply_retry_merge,
            RecoveryAction.BLOCK_FEATURE: self._apply_block_feature,
            RecoveryAction.NEW_ARCHITECT: self._apply_new_architect,
            RecoveryAction.NO_ACTION: self._apply_no_action,
        }
        method = method_map.get(decision.action, self._apply_no_action)
        if asyncio.iscoroutinefunction(method):
            await method(packet_id, decision)
        else:
            method(packet_id, decision)

    def _apply_retry_same_coder(self, packet_id: str, decision: RecoveryDecision = None):
        _log.info("apply_retry_same_coder_start", packet_id=packet_id)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_retry_same_coder_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.READY)
            packet.state = PacketState.READY.value
            db.flush()
        _log.info("apply_retry_same_coder_done", packet_id=packet_id, new_state="ready")

    def _apply_switch_coder(self, packet_id: str, decision: RecoveryDecision):
        _log.info("apply_switch_coder_start", packet_id=packet_id,
            requested_executor=decision.next_executor_hint)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_switch_coder_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.READY)
            packet.state = PacketState.READY.value

            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"requested_executor_id": decision.next_executor_hint}
            packet.spec_json = spec
            db.flush()
        _log.info("apply_switch_coder_done", packet_id=packet_id,
            new_state="ready", requested_executor=decision.next_executor_hint)

    def _apply_return_to_architect(self, packet_id: str, decision: RecoveryDecision):
        _log.info("apply_return_to_architect_start", packet_id=packet_id,
            reason=decision.reason[:100] if decision.reason else "")
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_return_to_architect_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.BLOCKED_FINAL)
            packet.state = PacketState.BLOCKED_FINAL.value

            spec = dict(packet.spec_json or {})
            spec["architect_repair"] = {
                "reason": decision.reason,
                "failure_class": decision.failure_class.value,
                "instruction": decision.architect_instruction,
            }
            packet.spec_json = spec
            db.flush()
        _log.info("apply_return_to_architect_done", packet_id=packet_id, new_state="blocked")

    def _apply_block_feature(self, packet_id: str, decision: RecoveryDecision):
        _log.info("apply_block_feature_start", packet_id=packet_id,
            reason=decision.reason[:100] if decision.reason else "")
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState, Feature

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_block_feature_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.BLOCKED_FINAL)
            packet.state = PacketState.BLOCKED_FINAL.value

            feature = db.query(Feature).filter_by(id=packet.feature_id).first()
            if feature:
                spec = dict(packet.spec_json or {})
                spec["recovery"] = {"blocked_reason": decision.reason}
                packet.spec_json = spec
            db.flush()
        _log.info("apply_block_feature_done", packet_id=packet_id, new_state="blocked")

    def _apply_retry_verifier(self, packet_id: str, decision: RecoveryDecision = None):
        _log.info("apply_retry_verifier_start", packet_id=packet_id)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_retry_verifier_skip", packet_id=packet_id, reason="packet_not_found")
                return
            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"retry_verifier": True}
            packet.spec_json = spec
            db.flush()
        _log.info("apply_retry_verifier_done", packet_id=packet_id)

    def _apply_retry_reviewer(self, packet_id: str, decision: RecoveryDecision = None):
        _log.info("apply_retry_reviewer_start", packet_id=packet_id)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_retry_reviewer_skip", packet_id=packet_id, reason="packet_not_found")
                return
            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"retry_reviewer": True}
            packet.spec_json = spec
            db.flush()
        _log.info("apply_retry_reviewer_done", packet_id=packet_id)

    def _apply_retry_merge(self, packet_id: str, decision: RecoveryDecision = None):
        _log.info("apply_retry_merge_start", packet_id=packet_id)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_retry_merge_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.ACCEPTED)
            packet.state = PacketState.ACCEPTED.value
            db.flush()
        _log.info("apply_retry_merge_done", packet_id=packet_id, new_state="accepted")

    def _apply_no_action(self, packet_id: str, decision: RecoveryDecision = None):
        _log.info("apply_no_action", packet_id=packet_id)

    def _build_architect_context(self, packet, db) -> dict:
        from grace_control.db.schema import PacketRun

        runs = db.query(PacketRun).filter_by(packet_id=packet.id).order_by(
            PacketRun.run_number.desc()
        ).limit(20).all()

        context = {
            "original_spec": packet.spec_json or {},
            "attempts": [],
            "acceptance_reports": [],
            "verifier_reports": [],
            "executor_ids": [],
            "changed_files": [],
        }
        for run in runs:
            rj = run.result_json or {}
            context["attempts"].append({"run_number": run.run_number, "status": run.status})
            acc = rj.get("acceptance_report")
            if acc:
                context["acceptance_reports"].append(acc)
            ev = rj.get("evidence_verifier_report")
            if ev:
                context["verifier_reports"].append(ev)
            eid = rj.get("executor_id", "")
            if eid and eid not in context["executor_ids"]:
                context["executor_ids"].append(eid)

        context["summary"] = (
            f"{len(runs)} attempts, "
            f"{len(context['executor_ids'])} coders, "
            f"{len(context['acceptance_reports'])} acceptance reports"
        )
        return context

    def _apply_new_architect(self, packet_id: str, decision: RecoveryDecision):
        _log.info("apply_new_architect_start", packet_id=packet_id)
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                _log.warn("apply_new_architect_skip", packet_id=packet_id, reason="packet_not_found")
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.BLOCKED_FINAL)
            packet.state = PacketState.BLOCKED_FINAL.value

            architect_ctx = self._build_architect_context(packet, db)
            spec = dict(packet.spec_json or {})
            spec["recovery"] = spec.get("recovery", {})
            spec["recovery"]["new_architect"] = architect_ctx
            packet.spec_json = spec
            db.flush()
        _log.info("apply_new_architect_done", packet_id=packet_id, new_state="blocked")
