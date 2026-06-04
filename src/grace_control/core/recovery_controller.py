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


class RecoveryController:

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._enabled = os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED", "false").lower() == "true"

    async def evaluate(self, packet_id: str, allow_apply: bool = False) -> RecoveryDecision:
        signal = self.build_signal(packet_id)
        policy = RecoveryPolicy()
        fc = classify_failure(signal)
        decision = decide_recovery(signal, policy)

        db_decision_id = self._persist_decision(packet_id, decision, signal)
        self._emit_recovery_events(packet_id, signal, decision)

        if allow_apply and self._enabled:
            await self._apply_decision(packet_id, decision)

        decision.audit_payload["decision_id"] = db_decision_id
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

            latest = runs[0]
            result = latest.result_json or {}

        legacy = result.get("legacy_result", {})
        acc = result.get("acceptance_report", {})
        ev = result.get("evidence_verifier_report", {})
        rv = result.get("reviewer_report", {})

        executor_ids = []
        prev_ids = []
        coder_count = 0
        verifier_reject = 0
        reviewer_reject = 0
        merge_count = 0
        architect_repairs = 0

        for run in runs:
            r = run.result_json or {}
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

        return FailureSignal(
            feature_id=packet.feature_id,
            packet_id=packet.id,
            packet_state=packet.state,
            domain_status=legacy.get("domain_status", ""),
            reason=result.get("reason", ""),
            acceptance_verdict=acc.get("final_verdict", ""),
            evidence_verifier_verdict=ev.get("verdict", ""),
            reviewer_verdict=rv.get("verdict", ""),
            merge_error=result.get("merge_error", ""),
            acceptance_profile=packet.acceptance_profile,
            attempt_count=packet.attempt_count,
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

    def _emit_recovery_events(self, packet_id: str, signal: FailureSignal, decision: RecoveryDecision):
        from grace_control.core.event_recorder import record_event

        record_event("recovery_classified", "packet", packet_id, {
            "failure_class": decision.failure_class.value,
            "signal": signal.model_dump(),
        })

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
        })

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
            RecoveryAction.NO_ACTION: self._apply_no_action,
        }
        method = method_map.get(decision.action, self._apply_no_action)
        if asyncio.iscoroutinefunction(method):
            await method(packet_id, decision)
        else:
            method(packet_id, decision)

    def _apply_retry_same_coder(self, packet_id: str, decision: RecoveryDecision = None):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.READY)
            packet.state = PacketState.READY.value
            db.flush()

    def _apply_switch_coder(self, packet_id: str, decision: RecoveryDecision):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.READY)
            packet.state = PacketState.READY.value

            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"requested_executor_id": decision.next_executor_hint}
            packet.spec_json = spec
            db.flush()

    def _apply_return_to_architect(self, packet_id: str, decision: RecoveryDecision):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.BLOCKED)
            packet.state = PacketState.BLOCKED.value

            spec = dict(packet.spec_json or {})
            spec["architect_repair"] = {
                "reason": decision.reason,
                "failure_class": decision.failure_class.value,
                "instruction": decision.architect_instruction,
            }
            packet.spec_json = spec
            db.flush()

    def _apply_block_feature(self, packet_id: str, decision: RecoveryDecision):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState, Feature

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.BLOCKED)
            packet.state = PacketState.BLOCKED.value

            feature = db.query(Feature).filter_by(id=packet.feature_id).first()
            if feature:
                spec = dict(packet.spec_json or {})
                spec["recovery"] = {"blocked_reason": decision.reason}
                packet.spec_json = spec
            db.flush()

    def _apply_retry_verifier(self, packet_id: str, decision: RecoveryDecision = None):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"retry_verifier": True}
            packet.spec_json = spec
            db.flush()

    def _apply_retry_reviewer(self, packet_id: str, decision: RecoveryDecision = None):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            spec = dict(packet.spec_json or {})
            spec["recovery"] = {"retry_reviewer": True}
            packet.spec_json = spec
            db.flush()

    def _apply_retry_merge(self, packet_id: str, decision: RecoveryDecision = None):
        from grace_control.db import get_db
        from grace_control.db.schema import Packet, PacketState

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                return
            sm = PacketStateMachine()
            sm.transition(PacketState(packet.state), PacketState.ACCEPTED)
            packet.state = PacketState.ACCEPTED.value
            db.flush()

    def _apply_no_action(self, packet_id: str, decision: RecoveryDecision = None):
        pass
